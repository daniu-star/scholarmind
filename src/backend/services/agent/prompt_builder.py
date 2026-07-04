"""
PromptBuilder — Prompt 模板管理与系统提示词构建
从 agent_service.py 拆分，使用 Jinja2 模板引擎替代硬编码 Prompt 字符串。

特性:
  - 从 prompt_templates/*.j2 加载 Agent 系统提示词模板
  - Jinja2 变量注入（context_info, guidance_info, user_core_context, style_features 等）
  - 模板缓存（首次加载后缓存，prod 环境可启用 auto_reload=False）
  - 向后兼容：为 AGENT_PROMPTS 提供字典接口（从模板文件自动构建）
"""
from __future__ import annotations

import structlog
from pathlib import Path
from typing import Optional

from ...config import settings, DATA_ROOT

logger = structlog.get_logger(__name__)

# ── 模板目录 ──
_TEMPLATES_DIR = Path(__file__).resolve().parent / "prompt_templates"

# ── 数据文件路径 ──
TOPICS_FILE = DATA_ROOT / "topics.json"
STYLE_FEATURES_FILE = DATA_ROOT / "style_features.json"

# ── per-agent LLM 配置 ──
AGENT_LLM_CONFIG: dict[str, dict] = {
    "researcher":      {"temperature": 0.7, "max_tokens": 1536},
    "reviewer":        {"temperature": 0.3, "max_tokens": 2048},
    "architect":       {"temperature": 0.5, "max_tokens": 2048},
    "synthesizer":     {"temperature": 0.5, "max_tokens": 2048},
    "polisher":        {"temperature": 0.5, "max_tokens": 2048},
    "external_reviewer": {"temperature": 0.3, "max_tokens": 2048},
    "computational":   {"temperature": 0.5, "max_tokens": 1536},
    "custom":          {"temperature": 0.7, "max_tokens": 1536},
}


def _get_agent_llm_config(agent_id: str) -> dict:
    return AGENT_LLM_CONFIG.get(agent_id, {"temperature": 0.7, "max_tokens": 1536})


# ── Agent 阶段名称（greeting 模式用） ──
_AGENT_STAGE_NAMES = {
    "researcher": "学术选题与问题建构",
    "reviewer": "研究思路审查与优化",
    "architect": "论文架构审查与优化",
    "synthesizer": "文献综述撰写",
    "polisher": "学术语言润色与AIGC降重",
    "external_reviewer": "论文外审",
    "computational": "计算社会科学代码与数据分析",
    "custom": "通用学术研究",
}

# ── 离线/降级模式的模板开场白 ──
def _canned_greeting(agent_id: str, context: Optional[dict] = None) -> str:
    ctx = context or {}
    topic = ctx.get("user_topic", "")
    topic_clause = f"你提到的「{topic}」是个不错的切入点。" if topic else ""
    greetings = {
        "researcher": (
            "你好，我是林知远——ScholarMind 的研究员。"
            f"{topic_clause}我会陪你从模糊兴趣一步步收敛到一个真正可研究的问题。"
            "先问问：最近是什么现象或困惑让你产生了研究冲动？\n"
            "[算法推荐与信息茧房|平台劳工与数字控制|舆论极化与群体认同|短视频与青少年认知|其他(请直接输入)]"
        ),
        "reviewer": (
            "我是苏明哲，做了十余年匿名审稿人。"
            f"{topic_clause}把你的研究思路交给我，我会从四个维度给你坦诚的反馈。"
            "先用一句话告诉我：你想回答的核心研究问题是什么？\n"
            "[我有明确的研究问题|有大致方向但表述模糊|只有现象没有问题|其他(请直接输入)]"
        ),
        "architect": (
            "你好，我是陈书远。框架决定论文的基因。"
            f"{topic_clause}我会帮你把论文的骨架搭稳。"
            "先了解现状：你的论文目前处在哪个阶段？\n"
            "[刚开始构思|已有大纲需优化|已完成初稿需审查|已投稿被拒需重构|其他(请直接输入)]"
        ),
        "synthesizer": (
            "我是周文澜。文献综述不是文献展览，而是理论对话的舞台。"
            f"{topic_clause}我会帮你把零散的文献织成一张有论点的网。"
            "先告诉我：你想综述的核心主题是什么？\n"
            "[我有明确主题|有方向但需聚焦|需要你帮我从兴趣提炼主题|其他(请直接输入)]"
        ),
        "polisher": (
            "你好，我是宋墨然。形式即内容——一句拗口的学术腔可能毁掉一个绝佳的洞见。"
            f"{topic_clause}我负责让你的表达既严谨又有人味儿。"
            "先问：你这次想润色的是哪一部分？\n"
            "[论文摘要|引言|方法部分|讨论部分|全文|其他(请直接输入)]"
        ),
        "external_reviewer": (
            "我是方严谨，独立评审。一流论文等于理论原创加方法严谨加表达优雅，缺一不可。"
            f"{topic_clause}我会按九个维度给你的完整论文做一次严苛而建设性的外审。"
            "先确认：这篇论文属于哪种研究类型？\n"
            "[量化研究|质性研究|混合方法|计算社会科学|理论论文|其他(请直接输入)]"
        ),
        "computational": (
            "你好，我是陆代码。算法透明、可复现、数据伦理——这三条是计算社科的底线。"
            f"{topic_clause}从爬虫到建模到可视化，我都能直接写码跑给你看。"
            "先问最关键的：你的数据从哪里来？\n"
            "[需要爬取公开网页|已有数据集待分析|需要调用API|还没想好需你建议|其他(请直接输入)]"
        ),
        "custom": (
            "你好，我是 ScholarMind 的通用学术助手。"
            "我没有专项 Agent 的深度，但我能灵活应对各种学术需求，并在需要时帮你转接到合适的专家。"
            f"{topic_clause}先告诉我：你这次想做什么？\n"
            "[选题/建构问题|审查研究思路|搭建论文架构|文献综述|语言润色|外审论文|计算分析|其他(请直接输入)]"
        ),
    }
    return greetings.get(agent_id, greetings["researcher"])


# ── Valid agent IDs ──
VALID_AGENTS = {"researcher", "reviewer", "architect", "synthesizer", "polisher", "custom", "external_reviewer", "computational"}

# Conversation persistence directory
CONVERSATIONS_DIR = Path(settings.CONVERSATIONS_DIR)
UPLOADS_DIR = Path(settings.UPLOAD_DIR)
DATA_DIR = DATA_ROOT
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".r", ".bib"}
BINARY_EXTENSIONS = {".pdf", ".docx"}

# ── Context templates ──
CONTEXT_TEMPLATES = {
    "discipline": "\n当前用户学科领域：{value}",
    "research_type": "\n研究类型：{value}",
    "readiness": "\n用户研究准备度：{value}",
}


# ═══════════════════════════════════════════════════════════════
# PromptBuilder — Jinja2 模板驱动的系统提示词构建器
# ═══════════════════════════════════════════════════════════════

class PromptBuilder:
    """基于 Jinja2 模板的系统提示词构建器。

    用法:
        builder = PromptBuilder()
        prompt = builder.build(
            agent_id="researcher",
            context_info="学科: 传播学",
            guidance_info="当前步骤: 第3步 - 研究对象",
            user_core_context="话题: 算法推荐\n学科: 传播学",
            style_features="- 理论密度: 高\n- 方法意识: 强",
            skills_rules="可用技能: cnki_search, chart_generation",
            rag_context="相关文献: ...",
            cot_instruction="<CoT 指令>",
        )
    """

    def __init__(self, auto_reload: bool = True):
        self._auto_reload = auto_reload
        self._template_cache: dict[str, str] = {}

    # ── 模板加载 ──

    def _load_template(self, name: str) -> str:
        """加载模板文件（自动缓存）"""
        if not self._auto_reload and name in self._template_cache:
            return self._template_cache[name]
        path = _TEMPLATES_DIR / f"{name}.j2"
        if not path.exists():
            logger.warning(f"Template not found: {path}, using fallback")
            return self._get_fallback_prompt(name)
        content = path.read_text(encoding="utf-8")
        if not self._auto_reload:
            self._template_cache[name] = content
        return content

    def _get_fallback_prompt(self, agent_id: str) -> str:
        """模板文件缺失时的降级提示词"""
        fallbacks = {
            "researcher": "你是 ScholarMind 的研究员 Agent，学术选题与问题建构专家。帮助用户从模糊兴趣收敛到具体可研究的问题。",
            "reviewer": "你是 ScholarMind 的审查员 Agent，研究思路审查与优化专家。从4个维度评估研究方案。",
            "architect": "你是 ScholarMind 的架构师 Agent，论文架构审查与优化专家。帮助用户搭建论文骨架。",
            "synthesizer": "你是 ScholarMind 的综述员 Agent，文献综述撰写专家。将零散文献织成有论点的网。",
            "polisher": "你是 ScholarMind 的润色员 Agent，学术语言润色与AIGC降重专家。优化表达且降低AI检测率。",
            "external_reviewer": "你是 ScholarMind 的外审专家 Agent，9维度独立评审。对完整论文进行严苛而建设性的评审。",
            "computational": "你是 ScholarMind 的计算社会科学 Agent，兼具社科素养与编程能力。直接写码跑数据。",
            "custom": "你是 ScholarMind 的通用学术助手，灵活应对各种学术需求。",
        }
        return fallbacks.get(agent_id, fallbacks["custom"])

    # ── 核心构建方法 ──

    def build(self, agent_id: str, **kwargs) -> str:
        """构建完整的系统提示词。

        Args:
            agent_id: Agent ID (researcher/reviewer/architect/...)
            **kwargs: 模板变量
                - context_info: 学科/研究类型/准备度上下文
                - guidance_info: 当前引导步骤信息
                - user_core_context: 用户核心信息（话题+学科+研究类型）
                - style_features: 学科写作风格特征
                - academic_core_features: 学术写作通用原则
                - skills_rules: 可用技能规则
                - rag_context: RAG 知识库上下文
                - cot_instruction: CoT 链式思考指令

        Returns:
            完整的系统提示词字符串
        """
        template = self._load_template(agent_id)
        rendered = self._render_template(template, kwargs)
        return rendered

    def _render_template(self, template: str, variables: dict) -> str:
        """使用简单的变量替换渲染模板（无需 Jinja2 依赖）。

        支持 Jinja2 风格的 {% if var %}{{ var }}{% endif %} 条件块。
        这样做避免了额外依赖，同时保持了模板的可读性。
        """
        import re

        result = template

        # 处理 {% if var %}...{% endif %} 条件块
        for var_name, var_value in variables.items():
            # 替换 {{ var_name }}
            placeholder = "{{ " + var_name + " }}"
            if var_value:
                result = result.replace(placeholder, str(var_value))
            else:
                result = result.replace(placeholder, "")

            # 处理 {% if var_name %}...{% endif %} 块
            pattern = r'\{%\s*if\s+' + re.escape(var_name) + r'\s*%\}(.*?)\{%\s*endif\s*%\}'
            if var_value:
                result = re.sub(pattern, r'\1', result, flags=re.DOTALL)
            else:
                result = re.sub(pattern, '', result, flags=re.DOTALL)

        # 清理残留的空条件块（变量未传入的情况）
        result = re.sub(r'\{%\s*if\s+\w+\s*%\}.*?\{%\s*endif\s*%\}', '', result, flags=re.DOTALL)

        return result.strip()

    def build_with_academic_features(
        self,
        agent_id: str,
        context_info: str = "",
        guidance_info: str = "",
        user_core_context: str = "",
        style_features: str = "",
        skills_rules: str = "",
        rag_context: str = "",
        cot_instruction: str = "",
    ) -> str:
        """构建带完整学术特征的 Agent 系统提示词（一键式接口）。

        自动加载 academic_core_features 模板并注入。
        """
        academic_core = self._load_template("academic_core_features")

        return self.build(
            agent_id=agent_id,
            context_info=context_info,
            guidance_info=guidance_info,
            user_core_context=user_core_context,
            style_features=style_features,
            academic_core_features=academic_core,
            skills_rules=skills_rules,
            rag_context=rag_context,
            cot_instruction=cot_instruction,
        )


# ═══════════════════════════════════════════════════════════════
# AGENT_PROMPTS 兼容层（向后兼容 = 从模板文件动态构建）
# ═══════════════════════════════════════════════════════════════

_builder = PromptBuilder()

def _build_agent_prompts_dict() -> dict[str, str]:
    """从模板文件动态构建 AGENT_PROMPTS 字典（向后兼容）"""
    prompts = {}
    for agent_id in VALID_AGENTS:
        try:
            prompts[agent_id] = _builder._load_template(agent_id)
        except Exception as e:
            logger.warning(f"Failed to load template for {agent_id}: {e}")
            prompts[agent_id] = _builder._get_fallback_prompt(agent_id)
    return prompts


AGENT_PROMPTS = _build_agent_prompts_dict()

# ── Agent 学术增强（从模板文件加载） ──
_AGENT_ACADEMIC_ENHANCEMENT_TEMPLATE: dict[str, str] = {
    "researcher":    "\n── 研究员学术增强 ──\n- 引导过程中引用学术文献支持选项设计\n- 选项动态调整优先考虑该子学科近3年研究热点",
    "reviewer":      "\n── 审查员学术增强 ──\n- 评分时引用方法论经典文献作为依据\n- 改进建议需提供可操作的替代方案",
    "architect":     "\n── 架构师学术增强 ──\n- 架构审查以 IMRAD 结构为基准\n- 逻辑连贯性审查需标注断层位置",
    "synthesizer":   "\n── 综述员学术增强 ──\n- 文献组织以理论流派或方法论维度分组\n- 每篇核心文献标注理论贡献与方法局限",
    "polisher":      "\n── 润色员学术增强 ──\n- 同等学术水准下优先选用简洁表达\n- AIGC 降重需保持学术严谨性不变",
    "external_reviewer": "\n── 外审专家学术增强 ──\n- 9 维度评分采用 Likert 10 点量表\n- 每个维度给出具体改进建议和参考文献",
    "computational": "\n── 计算社会科学增强 ──\n- 代码必须包含注释和可复现说明\n- 数据分析结果需关联社会科学理论解释",
    "custom":        "\n── 通用助手增强 ──\n- 识别用户需求后主动建议转接专项 Agent\n- 无法处理时明确告知能力边界",
}

AGENT_ACADEMIC_ENHANCEMENT = _AGENT_ACADEMIC_ENHANCEMENT_TEMPLATE


def get_prompt_builder(auto_reload: bool = True) -> PromptBuilder:
    """获取 PromptBuilder 实例"""
    return PromptBuilder(auto_reload=auto_reload)
