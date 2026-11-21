"""R2：窗口正文与引用偏移一致性回归。

背景（2026-11-20 真实语料审计）：检索分块允许 ≤100 码点重叠，若把同一块的多个
chunk 文本直接拼起来，重叠部分会被重复写入窗口正文，导致窗口文本比块长；随后
``_locate_quote`` 用「块起点 + 块内下标」换算全文偏移，就会落错位置（审计在
1965 条诊断中发现 12 条 locator 与引用不一致）。本文件锁住修复后的行为。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.research.pipelines.base import ReviewWindow
from backend.research.pipelines.review.pipeline import ReviewPipeline
from backend.research.review_workflow import _build_review_blocks, _chunk_text_for_block


@dataclass
class _FakeBlock:
    id: str
    ordinal: int
    text: str
    start: int
    end: int
    section_path: str = "1 引言"
    kind: str = "paragraph"


@dataclass
class _FakeChunk:
    ordinal: int
    text: str
    start: int
    end: int
    block_id: Optional[str] = None


BODY = "第一段文字用于测试重叠分块。" * 6  # 90 码点，足够容纳重叠
BLOCK_START = 1000
BLOCK_END = BLOCK_START + len(BODY)


def _block() -> _FakeBlock:
    return _FakeBlock(
        id="rblk_1",
        ordinal=3,
        text=BODY,
        start=BLOCK_START,
        end=BLOCK_END,
    )


def _chunks() -> list[_FakeChunk]:
    """造三个分块：第 1、2 块重叠 20 码点，第 3 块接续到最后。"""
    first = (BLOCK_START, BLOCK_START + 40)
    second = (BLOCK_START + 20, BLOCK_START + 70)
    third = (BLOCK_START + 70, BLOCK_END)
    return [
        _FakeChunk(0, BODY[first[0] - BLOCK_START : first[1] - BLOCK_START], *first),
        _FakeChunk(1, BODY[second[0] - BLOCK_START : second[1] - BLOCK_START], *second),
        _FakeChunk(2, BODY[third[0] - BLOCK_START : third[1] - BLOCK_START], *third),
    ]


def test_chunk_text_deduplicates_overlap() -> None:
    text = _chunk_text_for_block(_block(), _chunks())
    assert text is not None
    # 修复前：三段直接拼接 → 长度 120（多出 20 个重叠码点）
    assert len(text) == len(BODY) == BLOCK_END - BLOCK_START
    assert text == BODY


def test_chunk_text_falls_back_when_block_text_disagrees_with_offsets() -> None:
    block = _block()
    block.text = BODY[:-1]  # 正文与偏移不一致：不得猜偏移
    assert _chunk_text_for_block(block, _chunks()) is None


def test_locator_offsets_slice_back_to_quote() -> None:
    blocks = [_block()]
    review_blocks, _warnings = _build_review_blocks(blocks, {"rblk_1": _chunks()})
    assert len(review_blocks) == 1
    window = ReviewWindow(label="窗口 块3", text=review_blocks[0].text, blocks=tuple(review_blocks))
    quote = BODY[25:45]
    located = ReviewPipeline._locate_quote(quote, window)
    assert located is not None
    _block_ref, start, end = located
    assert end - start == len(quote)
    assert 0 <= start - BLOCK_START < len(BODY)
    # 关键断言：用返回的全文偏移回切块正文，必须逐字等于引用
    assert BODY[start - BLOCK_START : end - BLOCK_START] == quote


def test_locator_skips_quote_outside_window() -> None:
    blocks = [_block()]
    review_blocks, _warnings = _build_review_blocks(blocks, {"rblk_1": _chunks()})
    window = ReviewWindow(label="窗口 块3", text=review_blocks[0].text, blocks=tuple(review_blocks))
    assert ReviewPipeline._locate_quote("这段文字不在原文中", window) is None
