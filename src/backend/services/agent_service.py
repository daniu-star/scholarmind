from __future__ import annotations

from openai import AsyncOpenAI
from typing import Optional, Any, TYPE_CHECKING
import json
import logging
import re
import uuid
from pathlib import Path
from datetime import datetime

from ..services.skills_service import SkillsService
from ..services import chart_service
from ..config import settings
from ..utils.circuit_breaker import deepseek_circuit_breaker
from ..core.exceptions import AgentChatFailedError
from .interfaces import IAgentService

if TYPE_CHECKING:
    from ..db.repository.conversation import ConversationRepository
    from ..db.repository.chart import ChartRepository
    from ..services.cnki_service import CNKIService

logger = logging.getLogger(__name__)

# Agent system prompts
AGENT_PROMPTS = {
    "researcher": """你是ScholarMind的「研究员」Agent，一位学术选题与问题建构专家。
你的职责是通过循循善诱的对话，帮助用户：
1. 明确研究方向和选题
2. 建构问题边界
3. 发现研究空白
4. 初步确定研究框架

对话规则：
- 每次回复提供2-4个选项按钮供用户选择，格式为【选项A】选项文字
- 用学术但易懂的语言
- 适时建议使用CNKI检索相关文献
- 当用户提到数据时，建议生成学术图表
- 回复末尾用单独一行列出所有选项，格式：[选项A|选项B|选项C]""",

    "reviewer": """你是ScholarMind的「审查员」Agent，一位研究思路审查与优化专家。
你的职责是：
1. 审查用户的研究思路文档
2. 评估研究问题的明确性、理论框架适配度、方法论可行性、创新性
3. 给出具体的改进建议

对话规则：
- 审查时从4个维度评估：研究问题明确性、理论框架适配度、方法论可行性、创新性
- 每个维度给出1-10评分和改进建议
- 支持用户上传附件进行审查
- 回复末尾用单独一行列出后续操作选项，格式：[选项A|选项B|选项C]""",

    "architect": """你是ScholarMind的「架构师」Agent，一位论文架构审查与优化专家。
你的职责是：
1. 审查论文架构的完整性与逻辑性
2. 评估逻辑连贯性、章节完整性、论证链路
3. 优化论文结构

对话规则：
- 用树状结构展示论文架构
- 对每个章节给出颜色标记：✅完整 / ⚠️待完善 / ❌缺失
- 计算架构完整度评分（0-100）
- 回复末尾用单独一行列出后续操作选项，格式：[选项A|选项B|选项C]""",

    "synthesizer": """你是ScholarMind的「综述员」Agent，一位文献综述撰写专家。
你的职责是：
1. 辅助文献检索与筛选
2. 帮助撰写系统文献综述
3. 组织文献之间的逻辑关系

对话规则：
- 建议使用CNKI检索文献
- 按主题/方法/时间线组织文献
- 生成文献综述大纲
- 回复末尾用单独一行列出后续操作选项，格式：[选项A|选项B|选项C]""",

    "polisher": """你是ScholarMind的「润色员」Agent，一位学术语言润色与AIGC降重专家。
你的职责是：
1. 学术语言润色
2. 降低AIGC检测率
3. 确保学术写作规范

对话规则：
- 保持原文核心意思不变
- 使用学术化表达
- 调整句式结构降低AI检测率
- 具体策略：变换句式结构、使用同义替换、增加过渡词、调整段落逻辑
- 回复末尾用单独一行列出后续操作选项，格式：[选项A|选项B|选项C]"""
}

# Context templates that get appended to system prompts based on user profile
CONTEXT_TEMPLATES = {
    "discipline": "\n当前用户学科领域：{value}",
    "research_type": "\n研究类型：{value}",
    "readiness": "\n用户研究准备度：{value}",
}

# Valid agent IDs
VALID_AGENTS = set(AGENT_PROMPTS.keys())

# Conversation persistence directory
CONVERSATIONS_DIR = Path("data/conversations")

# Upload directory base
UPLOADS_DIR = Path("data/uploads")

# Supported file extensions for text extraction
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".r", ".bib"}
BINARY_EXTENSIONS = {".pdf", ".docx"}


class AgentService(IAgentService):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        conversation_repo: ConversationRepository | None = None,
        skills_service: SkillsService | None = None,
        cnki_service: CNKIService | None = None,
        chart_repo: ChartRepository | None = None,
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url) if api_key else None
        self.model = model
        self.conversation_repo = conversation_repo
        self.skills_service = skills_service or SkillsService()
        self.cnki_service = cnki_service
        self.chart_repo = chart_repo

        # 文件模式回退：当无 repository 时使用内存字典 + 文件存储
        self.conversations: dict[str, list[dict]] = {}
        self._use_db = conversation_repo is not None

        # RAG service for knowledge base injection
        self.rag_service = None
        try:
            from .rag_service import get_rag_service
            self.rag_service = get_rag_service()
        except Exception as e:
            logger.warning(f"RAG service not available: {e}")

        # 只在文件模式下加载持久化的对话
        if not self._use_db:
            self._load_all_conversations()

    # ── Conversation persistence ──────────────────────────

    def _load_all_conversations(self) -> None:
        """Load all persisted conversations from data/conversations/"""
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
        for fp in CONVERSATIONS_DIR.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                session_id = fp.stem
                self.conversations[session_id] = data.get("messages", [])
            except Exception as e:
                logger.warning(f"Failed to load conversation {fp.name}: {e}")

    def _save_conversation(self, session_id: str) -> None:
        """Persist a single conversation to data/conversations/{session_id}.json"""
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = CONVERSATIONS_DIR / f"{session_id}.json"
        try:
            payload = {
                "session_id": session_id,
                "updated_at": datetime.now().isoformat(),
                "messages": self.conversations.get(session_id, []),
            }
            filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save conversation {session_id}: {e}")

    # ── Main chat method ──────────────────────────────────

    async def chat(
        self,
        message: str,
        agent_id: str,
        session_id: str,
        context: Optional[dict] = None,
    ) -> dict:
        """Send message to agent and get response

        Returns:
            dict with keys: reply, options, skills_used, chart_info, cnki_results, skill_hint
        """
        if agent_id not in VALID_AGENTS:
            return {
                "reply": f"未知的Agent类型：{agent_id}。可用的Agent有：{', '.join(VALID_AGENTS)}",
                "options": [],
                "skills_used": [],
                "chart_info": None,
                "cnki_results": None,
                "skill_hint": None,
            }

        if not settings.DEEPSEEK_API_KEY:
            raise AgentChatFailedError("DeepSeek API key not configured")

        # Get or create conversation history
        if self._use_db:
            db_history = await self.conversation_repo.get_by_session(session_id)
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in db_history
            ]
        else:
            if session_id not in self.conversations:
                self.conversations[session_id] = []
            history = self.conversations[session_id]

        # Build system prompt (with skills injection)
        if context is None:
            context = {}
        context["last_message"] = message
        system_prompt = self._build_system_prompt(agent_id, context)

        # Load file upload context and append to user message
        upload_context = self._load_upload_context(session_id)
        user_content = message
        if upload_context:
            user_content = f"{message}\n\n---\n📎 用户上传的文件内容摘要：\n{upload_context}"

        # Build messages list for API call
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        # Call DeepSeek API (async client) with circuit breaker
        try:
            async with deepseek_circuit_breaker:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                    stream=False,
                )
            reply = response.choices[0].message.content
        except Exception as e:
            logger.error(f"DeepSeek API call failed: {e}")
            raise AgentChatFailedError(f"AI服务调用失败: {str(e)}")

        # Update conversation history
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})

        if self._use_db:
            # 使用 repository 持久化
            await self.conversation_repo.add_message(session_id, agent_id, "user", message)
            await self.conversation_repo.add_message(session_id, agent_id, "assistant", reply)
        else:
            # Keep conversation history within reasonable limits (last 20 turns)
            max_history_messages = 40  # 20 turns * 2 messages
            if len(history) > max_history_messages:
                self.conversations[session_id] = history[-max_history_messages:]
            # Persist conversation to disk
            self._save_conversation(session_id)

        # Parse options from reply
        options = self._parse_options(reply)

        # Detect skills that could be used based on reply content
        skills_used = self._detect_skills(reply, message)

        # Execute chart generation skill if detected
        chart_info = None
        if "chart_generation" in skills_used:
            chart_info = await self._execute_chart_skill(message, reply, session_id)

        # Execute CNKI search skill if detected
        cnki_results = None
        if "cnki_search" in skills_used:
            cnki_results = await self._execute_cnki_skill(message, session_id)

        # Detect skill hint for unmatched needs
        skill_hint = self._detect_skill_hint(reply, message, skills_used)

        return {
            "reply": reply,
            "options": options,
            "skills_used": skills_used,
            "chart_info": chart_info,
            "cnki_results": cnki_results,
            "skill_hint": skill_hint,
        }

    # ── Stream chat method (WebSocket) ───────────────────

    async def stream_chat(
        self,
        message: str,
        agent_id: str,
        session_id: str,
        context: Optional[dict] = None,
    ):
        """流式对话：逐token生成回复，通过 async generator 返回

        Yields:
            dict with keys: type, content, index, skills_used, options, chart_info, cnki_results
        """
        if agent_id not in VALID_AGENTS:
            yield {
                "type": "error",
                "message": f"未知的Agent类型：{agent_id}。可用的Agent有：{', '.join(VALID_AGENTS)}",
            }
            return

        if not settings.DEEPSEEK_API_KEY:
            yield {
                "type": "error",
                "message": "DeepSeek API key not configured",
            }
            return

        # Get or create conversation history (stream)
        if self._use_db:
            db_history = await self.conversation_repo.get_by_session(session_id)
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in db_history
            ]
        else:
            if session_id not in self.conversations:
                self.conversations[session_id] = []
            history = self.conversations[session_id]

        # Build system prompt
        if context is None:
            context = {}
        context["last_message"] = message
        system_prompt = self._build_system_prompt(agent_id, context)

        # Load file upload context
        upload_context = self._load_upload_context(session_id)
        user_content = message
        if upload_context:
            user_content = f"{message}\n\n---\n📎 用户上传的文件内容摘要：\n{upload_context}"

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        # Stream from DeepSeek API with circuit breaker
        full_reply = ""
        try:
            async with deepseek_circuit_breaker:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                    stream=True,
                )

                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        full_reply += delta.content
                        yield {"type": "token", "content": delta.content}

        except Exception as e:
            logger.error(f"DeepSeek stream API failed: {e}")
            yield {"type": "error", "message": f"AI服务调用失败: {str(e)}"}
            return

        # Update conversation history
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": full_reply})

        if self._use_db:
            await self.conversation_repo.add_message(session_id, agent_id, "user", message)
            await self.conversation_repo.add_message(session_id, agent_id, "assistant", full_reply)
        else:
            max_history_messages = 40
            if len(history) > max_history_messages:
                self.conversations[session_id] = history[-max_history_messages:]
            self._save_conversation(session_id)

        # Parse options, detect skills
        options = self._parse_options(full_reply)
        skills_used = self._detect_skills(full_reply, message)
        skill_hint = self._detect_skill_hint(full_reply, message, skills_used)

        # Execute chart/cnki skills asynchronously
        chart_info = None
        cnki_results = None

        if "chart_generation" in skills_used:
            chart_info = await self._execute_chart_skill(message, full_reply, session_id)

        if "cnki_search" in skills_used:
            cnki_results = await self._execute_cnki_skill(message, session_id)

        yield {
            "type": "done",
            "skills_used": skills_used,
            "options": options,
            "chart_info": chart_info,
            "cnki_results": cnki_results,
            "skill_hint": skill_hint,
        }

    # ── System prompt building with skills injection ──────

    def _build_system_prompt(
        self, agent_id: str, context: Optional[dict] = None
    ) -> str:
        """Build system prompt for the agent, including enabled skills rules and RAG context"""
        prompt = AGENT_PROMPTS[agent_id]

        if context:
            for key, template in CONTEXT_TEMPLATES.items():
                value = context.get(key)
                if value:
                    prompt += template.format(value=value)

        # Inject enabled skills associated with this agent
        skills_rules = self._load_skills_for_agent(agent_id)
        if skills_rules:
            prompt += "\n\n── 已启用的技能规则 ──\n"
            for skill in skills_rules:
                prompt += f"\n【技能：{skill['display_name']}】\n"
                if skill.get("rules"):
                    prompt += skill["rules"] + "\n"

        # Inject RAG knowledge base context
        if self.rag_service and context and context.get("last_message"):
            try:
                rag_context = self.rag_service.build_context(
                    query=context["last_message"],
                    agent_id=agent_id,
                    top_k=settings.RAG_TOP_K,
                )
                if rag_context:
                    prompt += "\n\n── 相关学术资源（来自知识库） ──\n"
                    prompt += rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed: {e}")

        return prompt

    def _load_skills_for_agent(self, agent_id: str) -> list[dict]:
        """Load enabled skills associated with the given agent_id"""
        all_skills = self.skills_service.list_all()
        matched = []
        for skill in all_skills:
            if not skill.get("enabled", False):
                continue
            agents = skill.get("agents", [])
            if agent_id in agents:
                matched.append(skill)
        return matched

    # ── File upload context ───────────────────────────────

    def _load_upload_context(self, session_id: str) -> str:
        """Read uploaded files for the session and return a summary string"""
        upload_dir = UPLOADS_DIR / session_id
        if not upload_dir.exists():
            return ""

        summaries = []
        for fp in sorted(upload_dir.iterdir()):
            if fp.is_file():
                try:
                    content = self._extract_file_content(fp)
                    if content:
                        # Truncate to avoid overwhelming the context
                        max_chars = 2000
                        if len(content) > max_chars:
                            content = content[:max_chars] + "\n...（内容已截断）"
                        summaries.append(f"文件：{fp.name}\n{content}")
                except Exception as e:
                    logger.warning(f"Failed to extract content from {fp.name}: {e}")
                    summaries.append(f"文件：{fp.name}（无法读取内容：{e}）")

        if not summaries:
            return ""

        return "\n\n".join(summaries)

    def _extract_file_content(self, fp: Path) -> str:
        """Extract text content from a supported file"""
        ext = fp.suffix.lower()

        if ext in TEXT_EXTENSIONS:
            return fp.read_text(encoding="utf-8", errors="replace")

        if ext == ".pdf":
            return self._extract_pdf(fp)

        if ext == ".docx":
            return self._extract_docx(fp)

        return ""

    def _extract_pdf(self, fp: Path) -> str:
        """Extract text from PDF using pypdf"""
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(fp))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n".join(pages)
        except ImportError:
            logger.warning("pypdf not installed, cannot extract PDF content")
            return ""
        except Exception as e:
            logger.warning(f"Failed to extract PDF {fp.name}: {e}")
            return ""

    def _extract_docx(self, fp: Path) -> str:
        """Extract text from DOCX using python-docx"""
        try:
            from docx import Document
            doc = Document(str(fp))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)
        except ImportError:
            logger.warning("python-docx not installed, cannot extract DOCX content")
            return ""
        except Exception as e:
            logger.warning(f"Failed to extract DOCX {fp.name}: {e}")
            return ""

    # ── Chart generation skill ────────────────────────────

    async def _execute_chart_skill(
        self, message: str, reply: str, session_id: str
    ) -> Optional[dict]:
        """When chart_generation skill is detected, use DeepSeek to recommend chart type
        and generate the chart via chart_service."""
        try:
            # Ask DeepSeek to analyze the conversation and recommend a chart type
            chart_types_desc = "\n".join(
                f"- {k}: {chart_service.CHART_NAMES.get(k, k)} — {chart_service.CHART_DESCRIPTIONS.get(k, '')}"
                for k in chart_service.CHART_FUNCTIONS
            )

            analysis_prompt = f"""根据以下用户消息和AI回复，分析用户需要什么类型的学术图表，并推荐最合适的图表类型。

用户消息：{message}
AI回复：{reply}

可选图表类型：
{chart_types_desc}

请仅返回一个JSON对象，格式如下：
{{"chart_type": "图表类型key", "title": "图表标题", "x_label": "X轴标签", "y_label": "Y轴标签", "data_description": "数据格式说明"}}
"""

            analysis_response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": analysis_prompt}],
                temperature=0.3,
                max_tokens=512,
                stream=False,
            )
            analysis_text = analysis_response.choices[0].message.content.strip()

            # Parse the JSON from the analysis
            # Try to extract JSON from the response (may be wrapped in markdown code block)
            json_match = re.search(r'\{[\s\S]*\}', analysis_text)
            if not json_match:
                logger.warning("Failed to parse chart analysis response as JSON")
                return None

            json_str = json_match.group()
            try:
                chart_config = json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode chart analysis JSON: {json_str[:200]}")
                return None
            chart_type = chart_config.get("chart_type", "")
            title = chart_config.get("title", "学术研究图表")
            x_label = chart_config.get("x_label", "")
            y_label = chart_config.get("y_label", "")

            if chart_type not in chart_service.CHART_FUNCTIONS:
                logger.warning(f"Invalid chart type recommended: {chart_type}")
                return None

            # Generate sample/demonstration data for the chart
            # In a real scenario, the user would provide data; here we generate placeholder data
            sample_data = self._generate_sample_data(chart_type)

            # Generate chart
            chart_bytes = chart_service.generate_chart(
                chart_type=chart_type,
                data=sample_data,
                title=title,
                x_label=x_label,
                y_label=y_label,
            )

            # Save chart to file
            chart_id = str(uuid.uuid4())
            charts_dir = Path("data/charts")
            charts_dir.mkdir(parents=True, exist_ok=True)
            chart_filename = f"{chart_id}.png"
            chart_filepath = charts_dir / chart_filename
            chart_filepath.write_bytes(chart_bytes)

            chart_url = f"/api/v1/charts/{chart_filename}"

            # 持久化图表记录到数据库
            if self.chart_repo is not None:
                try:
                    await self.chart_repo.save_record(
                        chart_id=chart_id,
                        chart_type=chart_type,
                        title=title,
                        filepath=str(chart_filepath),
                        session_id=session_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist chart record to DB: {e}")

            return {
                "chart_id": chart_id,
                "chart_url": chart_url,
                "chart_type": chart_type,
                "chart_name": chart_service.CHART_NAMES.get(chart_type, chart_type),
                "title": title,
            }

        except Exception as e:
            logger.error(f"Chart generation failed: {e}")
            return None

    def _generate_sample_data(self, chart_type: str) -> Any:
        """Generate sample demonstration data for a given chart type"""
        import numpy as np

        if chart_type in ("ribbon",):
            x = list(range(10))
            return [(x, [i * 2 + j for j in range(3)]) for i in range(3)]

        if chart_type in ("violin", "swarm"):
            return {
                "组A": list(np.random.normal(50, 10, 30)),
                "组B": list(np.random.normal(60, 12, 30)),
                "组C": list(np.random.normal(45, 8, 30)),
            }

        if chart_type in ("alluvial", "chord"):
            return [
                ("类别A", "类别X", 30),
                ("类别A", "类别Y", 20),
                ("类别B", "类别X", 15),
                ("类别B", "类别Z", 25),
                ("类别C", "类别Y", 10),
            ]

        if chart_type in ("bubble_kde",):
            return [(x, x * 2 + np.random.randn() * 5, abs(np.random.randn()) * 30 + 10)
                    for x in np.linspace(0, 50, 30)]

        if chart_type in ("gradient_area",):
            x = list(np.linspace(0, 10, 50))
            y = list(np.sin(x) * 10 + 20 + np.random.randn(50) * 2)
            return list(zip(x, y))

        if chart_type in ("surface3d", "contour"):
            return np.random.rand(10, 10).tolist()

        if chart_type in ("parallel",):
            return {
                "class": ["A"] * 5 + ["B"] * 5,
                "特征1": list(np.random.rand(10) * 100),
                "特征2": list(np.random.rand(10) * 100),
                "特征3": list(np.random.rand(10) * 100),
            }

        if chart_type in ("scatter_density",):
            return [(np.random.randn(), np.random.randn()) for _ in range(200)]

        if chart_type in ("heatmap_dendro",):
            return np.random.rand(8, 8).tolist()

        # Default fallback
        return [(i, i * 2) for i in range(10)]

    # ── CNKI search skill ─────────────────────────────────

    async def _execute_cnki_skill(
        self, message: str, session_id: str
    ) -> Optional[list]:
        """When cnki_search skill is detected, extract keywords and search CNKI"""
        try:
            # Extract search keywords from the message using DeepSeek
            keyword_prompt = f"""从以下用户消息中提取学术文献检索关键词，返回一个JSON对象。

用户消息：{message}

返回格式：{{"keywords": "检索关键词", "year_filter": ""}}

year_filter格式示例："2020-2024" 或 "2024" 或 ""（不限年份）
仅返回JSON，不要其他内容。"""

            keyword_response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": keyword_prompt}],
                temperature=0.2,
                max_tokens=256,
                stream=False,
            )
            keyword_text = keyword_response.choices[0].message.content.strip()

            # Parse JSON
            json_match = re.search(r'\{[\s\S]*\}', keyword_text)
            if not json_match:
                logger.warning("Failed to parse keyword extraction response")
                return None

            json_str = json_match.group()
            try:
                keyword_config = json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode keyword JSON: {json_str[:200]}")
                return None
            keywords = keyword_config.get("keywords", "")
            year_filter = keyword_config.get("year_filter", "")

            if not keywords:
                return None

            # Execute CNKI search using injected service (with cache + circuit breaker)
            if self.cnki_service is not None:
                results = await self.cnki_service.search(query=keywords, year_filter=year_filter, count=10)
            else:
                # Fallback: create standalone instance (no cache/circuit breaker)
                from ..services.cnki_service import CNKIService
                cnki = CNKIService()
                results = await cnki.search(query=keywords, year_filter=year_filter, count=10)
                await cnki.close()

            # Convert results to dict list
            return [r.to_dict() for r in results]

        except Exception as e:
            logger.error(f"CNKI search failed: {e}")
            return None

    # ── Skill hint detection ──────────────────────────────

    def _detect_skill_hint(
        self, reply: str, user_message: str, skills_used: list[str]
    ) -> Optional[str]:
        """When a need is detected that doesn't match existing skills,
        suggest the user create a custom skill."""
        # Keywords that indicate a need but don't map to existing skills
        unmatched_keywords = {
            "翻译": "学术翻译",
            "格式": "论文格式化",
            "投稿": "投稿指导",
            "答辩": "答辩准备",
            "实验设计": "实验设计",
            "问卷": "问卷设计",
            "量表": "量表开发",
            "编码": "质性编码",
            "扎根理论": "扎根理论分析",
            "元分析": "元分析/Meta分析",
            "案例研究": "案例研究方法",
            "田野调查": "田野调查方法",
        }

        combined = reply + user_message
        for keyword, skill_name in unmatched_keywords.items():
            if keyword in combined:
                # Check if this need is already covered by detected skills
                if not any(s in skills_used for s in ["cnki_search", "chart_generation", "polish", "literature_review", "architecture"]):
                    return f"检测到您可能需要「{skill_name}」相关功能，当前暂无对应技能。您可以在技能管理中创建自定义技能来满足此需求。"

        return None

    # ── Option parsing (unchanged) ────────────────────────

    def _parse_options(self, reply: str) -> list[str]:
        """Extract option buttons from agent reply"""
        options: list[str] = []

        bracket_match = self._extract_bracket_options(reply)
        if bracket_match:
            return bracket_match

        inline_matches = self._extract_inline_options(reply)
        if inline_matches:
            return inline_matches

        numbered_matches = self._extract_numbered_options(reply)
        if numbered_matches:
            return numbered_matches

        return options

    def _extract_bracket_options(self, reply: str) -> list[str]:
        """Extract options from [A|B|C] pattern"""
        matches = re.findall(r'\[([^\]]+)\]', reply)
        if not matches:
            return []

        last_match = matches[-1]
        if '|' in last_match:
            options = [opt.strip() for opt in last_match.split('|') if opt.strip()]
            if 2 <= len(options) <= 6:
                return options

        return []

    def _extract_inline_options(self, reply: str) -> list[str]:
        """Extract options from 【option】 pattern"""
        matches = re.findall(r'【([^】]+)】', reply)
        if len(matches) >= 2:
            return matches
        return []

    def _extract_numbered_options(self, reply: str) -> list[str]:
        """Extract options from numbered list pattern"""
        matches = re.findall(r'(?:\d[.、]|①|②|③|④|⑤|⑥)\s*(.+?)(?:\n|$)', reply)
        if len(matches) >= 2:
            return [m.strip() for m in matches]
        return []

    # ── Skill detection (unchanged) ───────────────────────

    def _detect_skills(self, reply: str, user_message: str) -> list[str]:
        """Detect which skills/tools the agent suggests using"""
        skills: list[str] = []
        combined = reply + user_message

        if any(kw in combined for kw in ["CNKI", "知网", "检索", "文献搜索", "查找文献"]):
            skills.append("cnki_search")

        if any(kw in combined for kw in ["图表", "可视化", "画图", "数据图", "统计图"]):
            skills.append("chart_generation")

        if any(kw in combined for kw in ["润色", "降重", "AIGC", "查重", "改写"]):
            skills.append("polish")

        if any(kw in combined for kw in ["综述", "文献综述", "系统综述"]):
            skills.append("literature_review")

        if any(kw in combined for kw in ["架构", "论文结构", "大纲", "目录"]):
            skills.append("architecture")

        return skills

    # ── Conversation management (unchanged) ───────────────

    async def clear_conversation(self, session_id: str) -> bool:
        """Clear conversation history for a session

        Returns True if session existed and was cleared, False otherwise
        """
        if self._use_db:
            deleted = await self.conversation_repo.clear_session(session_id)
            return deleted > 0
        else:
            if session_id in self.conversations:
                del self.conversations[session_id]
                # Also remove persisted file
                filepath = CONVERSATIONS_DIR / f"{session_id}.json"
                if filepath.exists():
                    try:
                        filepath.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to delete conversation file {session_id}: {e}")
                return True
            return False

    async def get_conversation_history(self, session_id: str) -> list[dict]:
        """Get conversation history for a session"""
        if self._use_db:
            db_history = await self.conversation_repo.get_by_session(session_id)
            return [
                {"role": msg.role, "content": msg.content}
                for msg in db_history
            ]
        else:
            return self.conversations.get(session_id, [])

    def list_agents(self) -> list[dict]:
        """List all available agents with their descriptions"""
        agent_info = {
            "researcher": {
                "id": "researcher",
                "name": "研究员",
                "description": "学术选题与问题建构专家，帮助明确研究方向、建构问题边界、发现研究空白",
                "icon": "🔬",
            },
            "reviewer": {
                "id": "reviewer",
                "name": "审查员",
                "description": "研究思路审查与优化专家，从4个维度评估研究方案并给出改进建议",
                "icon": "📋",
            },
            "architect": {
                "id": "architect",
                "name": "架构师",
                "description": "论文架构审查与优化专家，评估逻辑连贯性、章节完整性、论证链路",
                "icon": "🏗️",
            },
            "synthesizer": {
                "id": "synthesizer",
                "name": "综述员",
                "description": "文献综述撰写专家，辅助文献检索、筛选与综述撰写",
                "icon": "📚",
            },
            "polisher": {
                "id": "polisher",
                "name": "润色员",
                "description": "学术语言润色与AIGC降重专家，确保学术写作规范",
                "icon": "✨",
            },
        }
        return list(agent_info.values())
