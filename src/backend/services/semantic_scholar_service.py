"""
Semantic Scholar 学术搜索服务

通过 Semantic Scholar Graph API 检索英文学术文献，
作为多源学术聚合中的一个数据源。单源失败不应阻塞整体流程，
因此所有错误均被捕获并返回空列表。
"""
from __future__ import annotations

import asyncio
import structlog
import time
from dataclasses import dataclass, asdict
from typing import Optional, Any

import httpx

logger = structlog.get_logger(__name__)


@dataclass
class AcademicPaper:
    """统一的学术文献数据结构"""

    title: str
    authors: list[str]
    year: Optional[int]
    abstract: Optional[str]
    citation_count: int
    url: str
    source: str = "semantic_scholar"  # 固定为 "semantic_scholar"
    doi: Optional[str] = None
    pdf_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class SemanticScholarService:
    """Semantic Scholar 学术搜索服务

    使用 Semantic Scholar Graph API 进行文献检索：
    - 支持可选的 API Key（通过 x-api-key header），无 key 时使用免费 tier（有速率限制）
    - 中文关键词可借助 DeepSeek 翻译为英文以提升检索效果
    - 内存缓存，TTL 30 分钟
    - 单源失败不抛异常，返回空列表
    """

    # Semantic Scholar Graph API 端点
    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    # 请求字段
    FIELDS = "title,authors,year,abstract,citationCount,url,externalIds"
    # 请求超时（秒）
    TIMEOUT = 15.0
    # 缓存 TTL（30 分钟）
    CACHE_TTL = 1800

    def __init__(
        self,
        api_key: Optional[str] = None,
        deepseek_api_key: Optional[str] = None,
        deepseek_base_url: str = "https://api.deepseek.com",
        deepseek_model: str = "deepseek-chat",
    ) -> None:
        """初始化 Semantic Scholar 服务

        Args:
            api_key: Semantic Scholar API Key（可选，无则使用免费 tier）
            deepseek_api_key: DeepSeek API Key（可选，用于中文关键词翻译）
            deepseek_base_url: DeepSeek API 基础 URL
            deepseek_model: DeepSeek 模型名称
        """
        self.api_key = api_key
        self.deepseek_api_key = deepseek_api_key
        self.deepseek_base_url = deepseek_base_url.rstrip("/")
        self.deepseek_model = deepseek_model

        # 内存缓存：key -> (results, timestamp)
        self._cache: dict[str, tuple[list[AcademicPaper], float]] = {}

        # 复用 httpx 异步客户端
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取（或创建）复用的 httpx 异步客户端"""
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {
                "Accept": "application/json",
                "User-Agent": "ScholarMind/1.0 (academic-research-agent)",
            }
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.TIMEOUT),
                headers=headers,
            )
        return self._client

    # ── 缓存相关 ────────────────────────────────────────────

    def _cache_key(self, query: str, limit: int) -> str:
        """生成缓存键：查询词 + limit"""
        return f"semantic_scholar:{query}|{limit}"

    def _get_cached(self, key: str) -> Optional[list[AcademicPaper]]:
        """获取缓存结果，过期则清除"""
        if key not in self._cache:
            return None
        results, ts = self._cache[key]
        if time.time() - ts < self.CACHE_TTL:
            return results
        del self._cache[key]
        return None

    def _set_cached(self, key: str, results: list[AcademicPaper]) -> None:
        """设置缓存并清理过期项"""
        self._cache[key] = (results, time.time())
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > self.CACHE_TTL]
        for k in expired:
            del self._cache[k]

    # ── 中文关键词翻译 ──────────────────────────────────────

    async def _translate_to_english(self, query: str) -> str:
        """将中文检索词翻译为适合学术检索的英文关键词

        如果有 DeepSeek API key，调用 DeepSeek 进行翻译；
        如果没有 API key 或翻译失败，直接返回原关键词
        （Semantic Scholar 对中文关键词也有一定支持）。

        Args:
            query: 用户输入的检索词（可能为中文）

        Returns:
            翻译后的英文关键词，或原关键词
        """
        if not self.deepseek_api_key:
            return query

        prompt = (
            f"将以下中文检索词翻译为适合学术检索的英文关键词"
            f"（只返回关键词，不要其他内容）：{query}"
        )
        payload = {
            "model": self.deepseek_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.deepseek_api_key}",
        }
        url = f"{self.deepseek_base_url}/v1/chat/completions"

        try:
            client = await self._get_client()
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    f"DeepSeek 翻译请求失败，状态码 {resp.status_code}，使用原关键词"
                )
                return query
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                logger.warning("DeepSeek 翻译返回空 choices，使用原关键词")
                return query
            content = choices[0].get("message", {}).get("content", "")
            translated = content.strip()
            if not translated:
                logger.warning("DeepSeek 翻译返回空内容，使用原关键词")
                return query
            logger.info(f"DeepSeek 翻译：{query!r} -> {translated!r}")
            return translated
        except Exception as e:
            logger.warning(f"DeepSeek 翻译异常，使用原关键词：{e}")
            return query

    # ── 结果解析 ────────────────────────────────────────────

    def _parse_paper(self, item: dict[str, Any]) -> Optional[AcademicPaper]:
        """将 Semantic Scholar 单条结果解析为 AcademicPaper

        Args:
            item: Semantic Scholar API 返回的单条 paper 字典

        Returns:
            AcademicPaper 实例；若关键字段缺失则返回 None
        """
        title = item.get("title") or ""
        if not title:
            return None

        # 作者列表
        authors_raw = item.get("authors") or []
        authors: list[str] = []
        for a in authors_raw:
            name = a.get("name") if isinstance(a, dict) else None
            if name:
                authors.append(name)

        # 年份
        year_raw = item.get("year")
        year: Optional[int] = None
        if isinstance(year_raw, int):
            year = year_raw

        # 摘要
        abstract = item.get("abstract")

        # 引用数
        citation_count = int(item.get("citationCount") or 0)

        # URL
        url = item.get("url") or ""

        # externalIds 中的 DOI
        external_ids = item.get("externalIds") or {}
        doi = external_ids.get("DOI") if isinstance(external_ids, dict) else None

        # pdf_url：Semantic Scholar 在 externalIds 中可能不直接提供 PDF 链接，
        # 这里尝试从 openAccessPdf 字段获取（若 API 返回），否则为 None
        pdf_url = None
        open_access = item.get("openAccessPdf")
        if isinstance(open_access, dict):
            pdf_url = open_access.get("url")

        return AcademicPaper(
            title=title,
            authors=authors,
            year=year,
            abstract=abstract,
            citation_count=citation_count,
            url=url,
            source="semantic_scholar",
            doi=doi,
            pdf_url=pdf_url,
        )

    def _parse_results(self, data: dict[str, Any]) -> list[AcademicPaper]:
        """解析 Semantic Scholar 搜索响应

        Args:
            data: Semantic Scholar API 返回的 JSON 字典

        Returns:
            解析后的 AcademicPaper 列表
        """
        results: list[AcademicPaper] = []
        items = data.get("data") or []
        if not isinstance(items, list):
            return results

        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                paper = self._parse_paper(item)
                if paper is not None:
                    results.append(paper)
            except Exception as e:
                logger.warning(f"解析 Semantic Scholar 单条结果失败：{e}")
                continue

        return results

    # ── 核心搜索 ────────────────────────────────────────────

    async def _do_search(
        self, query: str, limit: int
    ) -> list[AcademicPaper]:
        """执行一次 Semantic Scholar API 请求

        Args:
            query: 检索关键词（通常为英文）
            limit: 返回数量上限

        Returns:
            AcademicPaper 列表

        Raises:
            httpx.HTTPStatusError: 当返回 429 等可重试状态码时由调用方处理
        """
        client = await self._get_client()
        params = {
            "query": query,
            "limit": limit,
            "fields": self.FIELDS,
        }

        resp = await client.get(self.BASE_URL, params=params)

        # 限流：交给上层处理重试
        if resp.status_code == 429:
            raise httpx.HTTPStatusError(
                "Semantic Scholar API 限流 (429)",
                request=resp.request,
                response=resp,
            )

        if resp.status_code != 200:
            logger.warning(
                f"Semantic Scholar API 返回状态码 {resp.status_code}："
                f"{resp.text[:200]}"
            )
            return []

        try:
            data = resp.json()
        except Exception as e:
            logger.warning(f"Semantic Scholar 响应 JSON 解析失败：{e}")
            return []

        return self._parse_results(data)

    async def search(self, query: str, count: int = 10) -> list[AcademicPaper]:
        """检索 Semantic Scholar

        Args:
            query: 检索关键词（可为中文，会尝试翻译为英文）
            count: 返回结果数量上限，默认 10

        Returns:
            AcademicPaper 列表；失败时返回空列表（不抛异常）
        """
        if not query or not query.strip():
            return []

        query = query.strip()
        # 限制 limit 在 Semantic Scholar 允许的范围内（1-100）
        limit = max(1, min(int(count), 100))

        # 检查缓存
        cache_key = self._cache_key(query, limit)
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.info(f"Semantic Scholar 缓存命中：{query!r}")
            return cached[:limit]

        # 翻译关键词（若有 DeepSeek API key）
        try:
            search_query = await self._translate_to_english(query)
        except Exception as e:
            logger.warning(f"关键词翻译异常，使用原关键词：{e}")
            search_query = query

        # 执行检索（含 429 限流重试一次）
        try:
            try:
                results = await self._do_search(search_query, limit)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning(
                        "Semantic Scholar API 限流 (429)，等待 1 秒后重试一次"
                    )
                    await asyncio.sleep(1.0)
                    results = await self._do_search(search_query, limit)
                else:
                    raise
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"Semantic Scholar 检索失败（HTTP {e.response.status_code}），返回空列表"
            )
            return []
        except httpx.RequestError as e:
            logger.warning(f"Semantic Scholar 网络错误：{e}，返回空列表")
            return []
        except Exception as e:
            logger.warning(f"Semantic Scholar 检索异常：{e}，返回空列表")
            return []

        if results:
            self._set_cached(cache_key, results)
            logger.info(
                f"Semantic Scholar 检索 {query!r} 返回 {len(results)} 条结果"
            )
        else:
            logger.info(f"Semantic Scholar 检索 {query!r} 无结果")

        return results[:limit]

    # ── 资源清理 ────────────────────────────────────────────

    async def close(self) -> None:
        """关闭底层 httpx 客户端"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
