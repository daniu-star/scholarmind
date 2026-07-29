from __future__ import annotations

import asyncio
import structlog
import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from ..models.dto.scholar import AcademicPaper
from ..utils.cache import CacheManager

logger = structlog.get_logger(__name__)

# arXiv Atom XML 命名空间
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class ArxivService:
    """arXiv 学术搜索服务

    通过 arXiv API 检索预印本论文，解析 Atom XML 响应并统一为
    AcademicPaper 数据结构。内置内存缓存与速率限制控制。
    """

    BASE_URL = "https://export.arxiv.org/api/query"
    TIMEOUT = 15  # 请求超时（秒）
    RATE_LIMIT_INTERVAL = 3.0  # arXiv API 要求请求间隔至少 3 秒
    CACHE_TTL = 1800  # 缓存 TTL：30 分钟

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._last_request_time: float = 0.0
        self._cache = CacheManager(default_ttl=self.CACHE_TTL)

    @staticmethod
    def _cache_key(query: str, count: int) -> str:
        return f"arxiv:{query}|{count}"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.TIMEOUT,
                headers={
                    "User-Agent": "ScholarMind/1.0 (academic research tool)",
                    "Accept": "application/atom+xml",
                },
            )
        return self._client

    async def _enforce_rate_limit(self) -> None:
        """速率限制：确保请求间隔至少 3 秒"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_INTERVAL:
            await asyncio.sleep(self.RATE_LIMIT_INTERVAL - elapsed)
        self._last_request_time = time.time()

    async def search(self, query: str, count: int = 10) -> list[AcademicPaper]:
        """检索 arXiv"""
        # 检查缓存
        cache_key = self._cache_key(query, count)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info(f"arXiv cache hit for query: {query}")
            return cached

        # 构造检索参数：全字段检索
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": count,
        }

        # 发起 HTTP 请求
        try:
            await self._enforce_rate_limit()
            client = await self._get_client()
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"arXiv 请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"arXiv 请求发生未知错误: {e}")
            return []

        # 解析 XML 响应
        try:
            papers = self._parse_atom_xml(response.text)
        except ET.ParseError as e:
            logger.error(f"arXiv XML 解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"arXiv 结果解析发生未知错误: {e}")
            return []

        # 写入缓存
        self._cache.set(cache_key, papers)
        logger.info(f"arXiv 检索返回 {len(papers)} 条结果（query={query}）")
        return papers

    def _parse_atom_xml(self, xml_text: str) -> list[AcademicPaper]:
        """解析 arXiv Atom XML 响应"""
        root = ET.fromstring(xml_text)
        papers: list[AcademicPaper] = []

        for entry in root.findall(f"{_ATOM_NS}entry"):
            try:
                paper = self._parse_entry(entry)
                if paper is not None:
                    papers.append(paper)
            except Exception as e:
                logger.warning(f"解析 arXiv entry 失败: {e}")
                continue

        return papers

    def _parse_entry(self, entry: ET.Element) -> Optional[AcademicPaper]:
        """解析单个 entry 元素为 AcademicPaper"""
        # 标题：entry/title
        title = ""
        title_elem = entry.find(f"{_ATOM_NS}title")
        if title_elem is not None and title_elem.text:
            # arXiv 标题常含换行/多余空白，需规整
            title = " ".join(title_elem.text.split())

        # 作者列表：entry/author/name（可能有多个）
        authors: list[str] = []
        for author_elem in entry.findall(f"{_ATOM_NS}author"):
            name_elem = author_elem.find(f"{_ATOM_NS}name")
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        # 发表年份：从 entry/published 提取年份
        year: Optional[int] = None
        published_elem = entry.find(f"{_ATOM_NS}published")
        if published_elem is not None and published_elem.text:
            year_str = published_elem.text.strip()[:4]
            if year_str.isdigit():
                year = int(year_str)

        # 摘要：entry/summary
        abstract: Optional[str] = None
        summary_elem = entry.find(f"{_ATOM_NS}summary")
        if summary_elem is not None and summary_elem.text:
            abstract = " ".join(summary_elem.text.split())

        # arXiv ID：entry/id（URL 末尾部分）
        arxiv_id = ""
        id_elem = entry.find(f"{_ATOM_NS}id")
        if id_elem is not None and id_elem.text:
            arxiv_id = id_elem.text.strip().rsplit("/", 1)[-1]

        # 摘要页 URL
        url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""

        # PDF URL：entry/link 中 title="pdf" 的 href 属性
        pdf_url: Optional[str] = None
        for link_elem in entry.findall(f"{_ATOM_NS}link"):
            if link_elem.get("title") == "pdf":
                pdf_url = link_elem.get("href")
                break

        # DOI：entry/arxiv:doi（如果有）
        doi: Optional[str] = None
        doi_elem = entry.find(f"{_ARXIV_NS}doi")
        if doi_elem is not None and doi_elem.text:
            doi = doi_elem.text.strip()

        # 缺少标题与 ID 视为无效条目
        if not title and not arxiv_id:
            return None

        return AcademicPaper(
            title=title,
            authors=authors,
            year=year,
            abstract=abstract,
            citation_count=0,
            url=url,
            source="arxiv",
            doi=doi,
            pdf_url=pdf_url,
        )

    async def close(self) -> None:
        """关闭 httpx 客户端，释放资源"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
