"""
SkillRouter — 技能检测、工具执行与选项解析
从 agent_service.py 拆分，负责技能匹配、图表生成、CNKI 检索、选项提取。
"""
from __future__ import annotations

import json
import structlog
from typing import Any, Optional, TYPE_CHECKING

from ...services import chart_service
from ...core.exceptions import AgentChatFailedError

if TYPE_CHECKING:
    from ...services.cnki_service import CNKIService
    from ...services.skills_service import SkillsService

logger = structlog.get_logger(__name__)

# 内置技能关键词映射（Function Calling 注册前的过渡方案）
_BUILTIN_SKILL_KEYWORDS: dict[str, list[str]] = {
    'cnki_search': ['检索', '搜索', '查找文献', '知网', 'CNKI', '文献检索', '找论文', '查一下'],
    'chart_generation': ['图表', '柱状图', '折线图', '饼图', '散点图', '热力图', '生成图', '可视化', 'chart', 'plot'],
    'polish': ['润色', '降重', '改写', '润饰', 'polish'],
    'literature_review': ['综述', '文献回顾', '研究现状', '梳理文献'],
    'architecture': ['架构', '框架', '大纲', '结构', '章节', 'outline'],
}


class SkillRouter:
    """技能路由器：检测 + 执行 + 选项解析"""

    def __init__(self, skills_service=None, cnki_service=None, chart_repo=None):
        self.skills_service = skills_service
        self.cnki_service = cnki_service
        self.chart_repo = chart_repo

    # ── 技能检测 ──
    def detect_skills(self, reply: str, user_message: str, enabled_skills: list = None) -> list[str]:
        """检测回复中触发的技能"""
        matched = set()
        combined = (reply + ' ' + user_message).lower()

        # 1. 自定义技能触发器
        if enabled_skills:
            for skill in enabled_skills:
                triggers = skill.get('triggers', []) if isinstance(skill, dict) else getattr(skill, 'triggers', [])
                for trigger in triggers:
                    if trigger.lower() in combined:
                        matched.add(skill.get('id', '') if isinstance(skill, dict) else getattr(skill, 'skill_id', ''))
                        break

        # 2. 内置关键词回退
        for skill_id, keywords in _BUILTIN_SKILL_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in combined:
                    matched.add(skill_id)
                    break

        return list(matched)

    def detect_skill_hint(self, reply: str, user_message: str) -> Optional[str]:
        """检测未满足的需求，返回提示建议"""
        combined = (reply + ' ' + user_message).lower()
        hints = {
            'cnki_search': '需要检索学术文献吗？我可以帮你在知网、Semantic Scholar 等数据库中搜索。',
            'chart_generation': '需要可视化呈现吗？我可以生成柱状图、折线图、饼图等学术图表。',
            'polish': '需要润色文本吗？我可以帮你优化语言表达并降低 AIGC 检测率。',
        }
        for skill_id, hint in hints.items():
            if skill_id not in self.detect_skills(reply, user_message):
                # 检测弱信号：提到数据但未触发图表
                if skill_id == 'chart_generation' and any(w in combined for w in ['数据', '统计', '比例', '趋势']):
                    return hint
                if skill_id == 'cnki_search' and any(w in combined for w in ['参考', '引用', '文献']):
                    return hint
        return None

    # ── 选项解析 ──
    def parse_options(self, reply: str) -> list[str]:
        """从 LLM 回复中提取选项"""
        options = self._extract_bracket_options(reply)
        if not options:
            options = self._extract_numbered_options(reply)
        return options

    def _extract_bracket_options(self, reply: str) -> list[str]:
        import re
        matches = re.findall(r'\[([^\]]+)\]', reply)
        options = []
        for m in matches:
            parts = [p.strip() for p in m.split('|')]
            options.extend([p for p in parts if p and len(p) < 100])
        return options[:8]

    def _extract_numbered_options(self, reply: str) -> list[str]:
        import re
        lines = reply.split('\n')
        options = []
        for line in lines:
            m = re.match(r'^\s*\d+[\).、]\s*(.+)', line)
            if m:
                opt = m.group(1).strip()
                if len(opt) < 100:
                    options.append(opt)
        return options[:8]

    # ── 图表技能执行 ──
    async def execute_chart_skill(self, reply: str, user_message: str, session_id: str = '') -> Optional[dict]:
        """执行图表生成技能"""
        try:
            from ...utils.llm_client import llm_client
            prompt = f'根据以下对话内容，推荐最合适的图表类型。只返回 JSON：{{"chart_type": "类型", "title": "标题"}}\n\n用户: {user_message}\nAI: {reply[:500]}'
            result = await llm_client.chat_json(
                system='你是数据可视化专家，只返回 JSON。chart_type 可选: bar/line/pie/scatter/heatmap/radar/box/histogram/area/bubble/waterfall/funnel',
                user=prompt, temperature=0.3, max_tokens=200
            )
            chart_type = result.get('chart_type', 'bar') if isinstance(result, dict) else 'bar'
            title = result.get('title', '学术图表') if isinstance(result, dict) else '学术图表'
            chart_path = chart_service.generate_chart(
                chart_type=chart_type, title=title, session_id=session_id
            )
            if self.chart_repo:
                import uuid
                await self.chart_repo.save_record(
                    chart_id=uuid.uuid4().hex, chart_type=chart_type,
                    title=title, filepath=chart_path, session_id=session_id
                )
            return {'chart_type': chart_type, 'title': title, 'filepath': chart_path}
        except Exception as e:
            logger.warning(f'Chart generation failed: {e}')
            return None

    # ── CNKI 检索技能执行 ──
    async def execute_cnki_skill(self, reply: str, user_message: str) -> Optional[dict]:
        """执行 CNKI 学术检索技能"""
        if not self.cnki_service:
            return None
        try:
            from ...utils.llm_client import llm_client
            prompt = f'从以下对话提取学术检索关键词。只返回 JSON：{{"keywords": ["关键词1", "关键词2"]}}\n\n用户: {user_message}\nAI: {reply[:300]}'
            result = await llm_client.chat_json(
                system='你是信息检索专家，只返回 JSON 格式。',
                user=prompt, temperature=0.3, max_tokens=200
            )
            keywords = result.get('keywords', []) if isinstance(result, dict) else []
            if not keywords:
                return None
            search_results = await self.cnki_service.search(keywords[:3], count=5)
            return {'keywords': keywords, 'results': search_results}
        except Exception as e:
            logger.warning(f'CNKI search failed: {e}')
            return None
