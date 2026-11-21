"""私有全文检索（FR-05；T03）。

检索边界
========
- 一切入口先走 ``ownership.require_version``（统一 404），再在``owner_id``/
  ``version_id`` 受限的范围内取块，绝不跨用户、跨版本命中。
- 分块索引按版本惰性建立：``ensure_index`` 写 ``DocumentChunk``（含 owner/project/
  version/block 关联与码点偏移），重复调用幂等。
- 向量后端可用时用注入的 embedding provider 在**同一范围**内算余弦；不可用、
  抛错或返回畸形时降级为词法打分，并在每条结果上标注 ``retrieval_method``
  （``vector`` / ``lexical``）与 ``degraded``，绝不把词法结果伪装成向量结果。
- 全文诊断必须 ``iter_chunks`` 取回**全部**分块，禁止 top-k 代替全量。
- embedding provider 由调用方显式注入（模块级，不导入期加载模型、不耦合全局
  单例）；默认未注入 → 诚实降级。
"""
from __future__ import annotations

import math
import re
from typing import Callable, Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import Actor, new_id, normalize_text, utcnow
from .document_parser import ParsedBlock, build_chunks
from .errors import not_found
from .models import Document, DocumentBlock, DocumentChunk
from .ownership import require_version

EmbeddingProvider = Callable[[Sequence[str]], Sequence[Sequence[float]]]

_PROVIDER: Optional[EmbeddingProvider] = None
# 是否已尝试按 settings 自动装配（只尝试一次，避免每次检索都重复加载失败）
_AUTO_PROVIDER_TRIED = False

_TERM_RE = re.compile(r"[0-9a-zA-Z_]+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_INDEX_BATCH = 500


# ---------------------------------------------------------------------------
# 可选的向量后端（默认不使用）
# ---------------------------------------------------------------------------
def configure_embedding_provider(provider: Optional[EmbeddingProvider]) -> None:
    """注入向量化实现；传 ``None`` 表示回到纯词法模式。"""

    global _PROVIDER, _AUTO_PROVIDER_TRIED
    if provider is not None and not callable(provider):
        raise TypeError("embedding provider 必须可调用")
    _PROVIDER = provider
    _AUTO_PROVIDER_TRIED = True


def reset_embedding_provider() -> None:
    """回到「未注入」状态；下次检索时会重新按 settings 装配。"""

    global _PROVIDER, _AUTO_PROVIDER_TRIED
    _PROVIDER = None
    _AUTO_PROVIDER_TRIED = False


def configure_from_settings() -> Optional[EmbeddingProvider]:
    """按 ``RESEARCH_EMBEDDING_MODEL`` 装配本地 embedding provider。

    * 未配置模型 → 返回 ``None``（保持词法检索，这是默认路径）。
    * 配置了模型 → 装配惰性 provider（首次调用才加载模型；加载失败会抛
      ``EmbeddingUnavailable``，由检索路径降级并记录原因）。
    * 任何异常都不外抛：应用启动不因检索后端缺失而失败。
    """

    global _PROVIDER, _AUTO_PROVIDER_TRIED
    _AUTO_PROVIDER_TRIED = True
    try:
        from .embeddings import build_provider_from_settings

        provider = build_provider_from_settings()
    except Exception:  # pragma: no cover - 装配失败退化为词法
        _PROVIDER = None
        return None
    _PROVIDER = provider
    return provider


def _ensure_provider() -> Optional[EmbeddingProvider]:
    """惰性自动装配：脚本/测试未显式注入时按 settings 尝试一次。"""

    global _AUTO_PROVIDER_TRIED
    if _PROVIDER is not None or _AUTO_PROVIDER_TRIED:
        return _PROVIDER
    return configure_from_settings()


def embedding_available() -> bool:
    return _PROVIDER is not None


def _is_blank(text: object) -> bool:
    return not str(text or "").strip()


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------
async def _version_and_document(
    db: AsyncSession, actor: Actor, version_id: str
):
    version = await require_version(db, actor, version_id)
    document = await db.get(Document, version.document_id)
    if document is None or document.owner_id != actor.user_id:
        raise not_found("文档版本")
    return version, document


async def _block_rows(db: AsyncSession, version_id: str) -> list[DocumentBlock]:
    result = await db.execute(
        select(DocumentBlock)
        .where(DocumentBlock.version_id == version_id)
        .order_by(DocumentBlock.ordinal.asc())
    )
    return list(result.scalars().all())


async def _chunk_count(db: AsyncSession, version_id: str) -> int:
    result = await db.execute(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.version_id == version_id
        )
    )
    return int(result.scalar_one() or 0)


async def ensure_index(db: AsyncSession, actor: Actor, version_id: str) -> int:
    """确保该版本的块已切分为 ``DocumentChunk``；返回当前分块总数。"""

    version, document = await _version_and_document(db, actor, version_id)
    existing = await _chunk_count(db, version.id)
    if existing:
        return existing

    blocks = await _block_rows(db, version.id)
    if not blocks:
        return 0

    specs = build_chunks(
        [
            ParsedBlock(
                ordinal=block.ordinal,
                kind=block.kind,
                text=block.text,
                start=block.start,
                end=block.end,
                section_path=block.section_path,
                eligible=bool(block.eligible),
            )
            for block in blocks
        ]
    )
    if not specs:
        return 0

    block_ids = {block.ordinal: block.id for block in blocks}
    now = utcnow()
    created = 0
    for spec in specs:
        block_id = block_ids.get(spec.block_ordinal)
        if block_id is None:
            continue
        db.add(
            DocumentChunk(
                id=new_id("rchk"),
                version_id=version.id,
                block_id=block_id,
                project_id=document.project_id,
                owner_id=document.owner_id,
                ordinal=spec.ordinal,
                text=spec.text,
                start=spec.start,
                end=spec.end,
                created_at=now,
            )
        )
        created += 1
        if created % _INDEX_BATCH == 0:
            await db.flush()
    await db.flush()
    return created


async def iter_chunks(db: AsyncSession, actor: Actor, version_id: str) -> list[DocumentChunk]:
    """返回该版本**全部**分块（按 ordinal），供全文诊断遍历。"""

    version = await require_version(db, actor, version_id)
    await ensure_index(db, actor, version.id)
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.version_id == version.id)
        .order_by(DocumentChunk.ordinal.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------
def _query_terms(query: str) -> list[str]:
    normalized = normalize_text(query).casefold()
    terms: list[str] = []
    for match in _TERM_RE.finditer(normalized):
        token = match.group(0)
        if len(token) >= 2:
            terms.append(token)
    for segment in _CJK_RE.findall(normalized):
        if len(segment) == 1:
            terms.append(segment)
            continue
        terms.extend(segment[i : i + 2] for i in range(len(segment) - 1))
    # 去重但保序
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    return unique


def _lexical_score(text: str, terms: Sequence[str]) -> float:
    haystack = text.casefold()
    score = 0.0
    for term in terms:
        hits = haystack.count(term)
        if hits:
            score += hits * (1.0 + math.log2(1.0 + len(term)))
    if score <= 0:
        return 0.0
    # 长度归一化：避免超长块因词频堆积霸榜
    return score / math.sqrt(1.0 + len(text) / 400.0)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def _result_payload(
    chunk: DocumentChunk,
    score: float,
    *,
    method: str,
    degraded: bool,
    reason: Optional[str],
) -> dict:
    return {
        "chunk_id": chunk.id,
        "version_id": chunk.version_id,
        "block_id": chunk.block_id,
        "ordinal": int(chunk.ordinal),
        "text": chunk.text,
        "start": int(chunk.start),
        "end": int(chunk.end),
        "score": round(float(score), 6),
        "retrieval_method": method,
        "degraded": degraded,
        "degraded_reason": reason,
    }


def _vector_results(
    query: str, chunks: Sequence[DocumentChunk]
) -> tuple[Optional[list[tuple[DocumentChunk, float]]], Optional[str]]:
    """返回 (结果, 降级原因)。结果 ``None`` 表示不可用，必须降级词法。"""

    provider = _ensure_provider()
    if provider is None:
        return None, "vector_backend_unavailable"
    try:
        vectors = provider([query] + [chunk.text for chunk in chunks])
    except Exception as exc:  # provider 任何异常都不得变成 500
        reason = getattr(exc, "reason", None)
        if isinstance(reason, str) and reason:
            # embeddings.EmbeddingUnavailable：模型缺失/加载失败等可解释原因
            return None, f"vector_backend_unavailable:{reason}"
        return None, f"vector_provider_failed:{type(exc).__name__}"
    try:
        vectors = [list(map(float, vector)) for vector in vectors]
    except (TypeError, ValueError):
        return None, "vector_provider_failed:malformed_response"
    if len(vectors) != len(chunks) + 1 or not vectors[0]:
        return None, "vector_provider_failed:malformed_response"
    query_vector = vectors[0]
    scored = [
        (chunk, _cosine(query_vector, vector))
        for chunk, vector in zip(chunks, vectors[1:])
    ]
    return scored, None


def _rank(
    scored: Iterable[tuple[DocumentChunk, float]],
    *,
    method: str,
    degraded: bool,
    reason: Optional[str],
    limit: int,
) -> list[dict]:
    ranked = sorted(
        scored,
        key=lambda item: (-item[1], int(item[0].ordinal)),
    )
    return [
        _result_payload(
            chunk,
            score,
            method=method,
            degraded=degraded,
            reason=reason,
        )
        for chunk, score in ranked
        if score > 0
    ][:limit]


async def search(
    db: AsyncSession,
    actor: Actor,
    version_id: str,
    query: str,
    *,
    limit: int = 8,
) -> list[dict]:
    """在单个版本（已授权）内检索；向量不可用时降级词法并诚实标注。"""

    if _is_blank(query):
        return []
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 8

    version = await require_version(db, actor, version_id)
    await ensure_index(db, actor, version.id)
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.version_id == version.id)
        .order_by(DocumentChunk.ordinal.asc())
    )
    chunks = list(result.scalars().all())
    if not chunks:
        return []

    vector_scored, reason = _vector_results(normalize_text(query), chunks)
    if vector_scored is not None:
        ranked = _rank(
            vector_scored, method="vector", degraded=False, reason=None, limit=limit
        )
        if ranked:
            return ranked
        # 向量分数全 0（如 provider 退化为常量向量）时仍诚实降级词法
        reason = "vector_returned_no_match"

    terms = _query_terms(query)
    if not terms:
        return []
    lexical_scored = [
        (chunk, _lexical_score(chunk.text, terms)) for chunk in chunks
    ]
    return _rank(
        lexical_scored,
        method="lexical",
        degraded=True,
        reason=reason or "vector_backend_unavailable",
        limit=limit,
    )


__all__ = [
    "configure_embedding_provider",
    "configure_from_settings",
    "embedding_available",
    "ensure_index",
    "iter_chunks",
    "reset_embedding_provider",
    "search",
]
