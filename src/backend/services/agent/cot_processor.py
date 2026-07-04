"""
CoTProcessor — Chain-of-Thought 链式思考处理
从 agent_service.py 拆分，负责 CoT 指令注入、响应解析、流式状态机。
"""
from __future__ import annotations

import re
import structlog
from typing import Optional

logger = structlog.get_logger(__name__)

# 启用 CoT 的 Agent
_COT_ENABLED_AGENTS: set[str] = {'external_reviewer', 'writer', 'reviewer', 'researcher'}

_COT_INSTRUCTION = """

── 链式思考（Chain-of-Thought）指令 ──
在回答用户之前，请先用 <thought>...</thought> 标签包裹你的逐步思考过程。
思考过程应包含：
1. 拆解用户问题（核心诉求是什么？）
2. 识别关键约束与已知信息
3. 列出可能的解决方案或回答路径
4. 评估各方案的权衡
5. 选定最终方案并说明理由

思考完成后，在 </thought> 标签之外给出对用户的正式回复。
正式回复不得重复思考过程，应直接呈现结论与可执行建议。
"""

_COT_PATTERN = re.compile(r'<thought>(.*?)</thought>', re.IGNORECASE | re.DOTALL)
_COT_OPEN_TAG = '<thought>'
_COT_CLOSE_TAG = '</thought>'


def is_cot_enabled(agent_id: str) -> bool:
    return agent_id in _COT_ENABLED_AGENTS


def get_cot_instruction() -> str:
    return _COT_INSTRUCTION


def parse_cot_response(content: str) -> tuple[str, Optional[str]]:
    """从 LLM 响应中提取 <thought>...</thought> 思考块
    Returns: (clean_content, thought)
    """
    if not content:
        return content, None
    match = _COT_PATTERN.search(content)
    if not match:
        return content, None
    thought = match.group(1).strip()
    clean = _COT_PATTERN.sub('', content)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()
    return clean, (thought or None)


def match_partial_tag_suffix(text: str, tag: str) -> str:
    """检查 text 末尾是否匹配 tag 的前缀（处理标签跨 chunk 分裂）"""
    max_check = min(len(text), len(tag) - 1)
    for i in range(max_check, 0, -1):
        if text[-i:] == tag[:i]:
            return text[-i:]
    return ''


class CoTStreamState:
    """流式 CoT 处理状态机
    
    状态: 'detecting' → 'thought' → 'content'
    处理 <thought> / </thought> 标签跨 chunk 分裂。
    """
    __slots__ = ('state', 'buffer')

    def __init__(self):
        self.state = 'detecting'
        self.buffer = ''

    def reset(self):
        self.state = 'detecting'
        self.buffer = ''

    def process_chunk(self, chunk: str) -> list[dict]:
        """处理一个文本 chunk，返回事件列表 [{type:'thought'|'token', content:str}]"""
        events = []
        if self.state == 'detecting':
            idx = chunk.find(_COT_OPEN_TAG)
            if idx >= 0:
                before = chunk[:idx]
                if before.strip():
                    events.append({'type': 'token', 'content': before})
                self.state = 'thought'
                after_open = chunk[idx + len(_COT_OPEN_TAG):]
                close_idx = after_open.find(_COT_CLOSE_TAG)
                if close_idx >= 0:
                    thought_content = after_open[:close_idx]
                    if thought_content.strip():
                        events.append({'type': 'thought', 'content': thought_content})
                    rest = after_open[close_idx + len(_COT_CLOSE_TAG):]
                    self.state = 'content'
                    if rest:
                        events.append({'type': 'token', 'content': rest})
                else:
                    self.buffer = after_open
            else:
                suffix = match_partial_tag_suffix(chunk, _COT_OPEN_TAG)
                if suffix:
                    before = chunk[:-len(suffix)]
                    if before.strip():
                        events.append({'type': 'token', 'content': before})
                    self.buffer = suffix
                    self.state = 'thought'
                elif chunk.strip():
                    events.append({'type': 'token', 'content': chunk})
        elif self.state == 'thought':
            combined = self.buffer + chunk
            close_idx = combined.find(_COT_CLOSE_TAG)
            if close_idx >= 0:
                thought_content = combined[:close_idx]
                if thought_content.strip():
                    events.append({'type': 'thought', 'content': thought_content})
                rest = combined[close_idx + len(_COT_CLOSE_TAG):]
                self.state = 'content'
                self.buffer = ''
                if rest:
                    events.append({'type': 'token', 'content': rest})
            else:
                self.buffer = combined
        else:  # content
            if chunk:
                events.append({'type': 'token', 'content': chunk})
        return events
