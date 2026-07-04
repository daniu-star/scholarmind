"""CNKI REST API 客户端 — 使用 restApiToken 和 restApiClientId 直接调用官方 API。

CNKI 搜索页面包含隐藏字段 restApiToken 和 restApiClientId，
这些凭据可用于调用 CNKI 的 REST API，直接获取 JSON 格式的搜索结果，
绕过 HTML 解析，更稳定可靠。

使用流程：
  1. 从 CNKI 搜索页提取 restApiToken 和 restApiClientId
  2. 使用 QueryJson 结构化查询调用 /kns8s/rest/QueryHandler
  3. 获取搜索结果列表
  4. 可选：调用 /kns8s/brief/grid 获取详细字段

参考：
  - cnki_search_debug.html 中的隐藏字段
  - test_cnki_rest_api.py 的测试代码
  - CNKI 搜索 API 的 QueryJson 结构
"""
from __future__ import annotations

import asyncio
import json
import re
import logging
from typing import Optional
from urllib.parse import quote, urlencode

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

# CNKI 搜索字段映射
FIELD_MAPPING = {
    "subject": "SU",      # 主题
    "title": "TI",        # 标题
    "author": "AU",       # 作者
    "keyword": "KY",      # 关键词
    "abstract": "AB",     # 摘要
    "source": "LY",       # 文献来源（期刊名）
    "institution": "AF",  # 作者单位
    "fund": "FN",         # 基金项目
    "year": "PY",         # 出版年份
}

# 跨库代码（默认搜索的数据库列表）
DEFAULT_KUAKU_CODE = (
    "YSTT4HG0,LSTPFY1C,JUP3MUPD,MPMFIG1A,WQ0UVIAA,"
    "BLZOG7CK,EMRPGLPA,PWFIRAGL,NLBO1Z6R,NN3FJMUV"
)


class CNKIRestAPI:
    """CNKI 官方 REST API 客户端。

    通过提取 CNKI 搜索页的 restApiToken 和 restApiClientId，
    调用 CNKI 的 REST API 直接获取 JSON 格式的搜索结果。

    优势：
      - 绕过 HTML 解析，直接获取结构化数据
      - 更稳定，不受页面结构变化影响
      - 支持高级查询语法（QueryJson）
    """

    def __init__(
        self,
        cookies: dict[str, str],
        impersonate: str = "chrome124",
        proxy_url: Optional[str] = None,
    ):
        self.cookies = cookies
        self.impersonate = impersonate
        self.proxy_url = proxy_url
        self._tls: Optional[AsyncSession] = None
        self._rest_api_token: Optional[str] = None
        self._rest_api_client_id: Optional[str] = None
        self._search_token: Optional[str] = None  # 搜索后获取的 token

    @property
    def default_headers(self) -> dict:
        """完整的浏览器请求头"""
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,application/signed-exchange;v=b3;q=0.8"
            ),
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://kns.cnki.net/",
        }

    async def _get_tls(self) -> AsyncSession:
        """获取或创建 TLS 会话"""
        if self._tls is None:
            self._tls = AsyncSession(
                impersonate=self.impersonate,
                timeout=30,
                verify=False,
                proxy=self.proxy_url,
            )
            # 显式设置多个域
            for domain in [".cnki.net", ".bar.cnki.net", ".kns.cnki.net", "cnki.net"]:
                for name, value in self.cookies.items():
                    if value:
                        self._tls.cookies.set(name, value, domain=domain)
        return self._tls

    async def warmup_and_extract_credentials(self) -> bool:
        """预热会话并提取 REST API 凭据。

        访问 CNKI 搜索页，提取隐藏字段 restApiToken 和 restApiClientId。
        这些凭据用于后续的 REST API 调用。

        Returns:
            True 如果成功提取凭据，False 否则
        """
        tls = await self._get_tls()

        try:
            # Step 1: 访问首页
            resp = await tls.get("https://www.cnki.net/", headers=self.default_headers)
            if resp.status_code != 200:
                logger.error(f"访问首页失败: HTTP {resp.status_code}")
                return False

            # Step 2: 访问搜索页
            resp = await tls.get(
                "https://kns.cnki.net/kns8s/", headers=self.default_headers
            )
            if resp.status_code != 200:
                logger.error(f"访问搜索页失败: HTTP {resp.status_code}")
                return False

            html = resp.text

            # 提取 restApiToken
            token_match = re.search(
                r'id="restApiToken"[^>]*value="([^"]+)"', html
            )
            client_id_match = re.search(
                r'id="restApiClientId"[^>]*value="([^"]+)"', html
            )

            if token_match and client_id_match:
                self._rest_api_token = token_match.group(1)
                self._rest_api_client_id = client_id_match.group(1)
                logger.info(
                    f"成功提取 REST API 凭据: "
                    f"token={self._rest_api_token[:8]}..., "
                    f"client_id={self._rest_api_client_id[:8]}..."
                )
                return True

            logger.warning("未能从搜索页提取 REST API 凭据")
            return False

        except Exception as e:
            logger.error(f"提取 REST API 凭据失败: {e}")
            return False

    def _build_query_json(
        self,
        query: str,
        field: str = "SU",
        search_type: int = 1,
    ) -> dict:
        """构建 QueryJson 结构化查询条件。

        Args:
            query: 搜索关键词
            field: 搜索字段（SU=主题, TI=标题, AU=作者, KY=关键词等）
            search_type: 搜索类型（1=高级检索）

        Returns:
            QueryJson 字典
        """
        return {
            "Platform": "",
            "Resource": "CROSSDB",
            "Classid": "WD0FTY92",
            "Products": "",
            "QNode": {
                "QGroup": [
                    {
                        "Key": "Subject",
                        "Title": "",
                        "Logic": 0,
                        "Items": [],
                        "ChildItems": [
                            {
                                "Key": "input[data-tipid=gradetxt-1]",
                                "Title": "主题",
                                "Logic": 0,
                                "Items": [
                                    {
                                        "Key": "input[data-tipid=gradetxt-1]",
                                        "Title": "主题",
                                        "Logic": 0,
                                        "Field": field,
                                        "Operator": "DEFAULT",
                                        "Value": query,
                                        "Value2": "",
                                    }
                                ],
                                "ChildItems": [],
                            }
                        ],
                    },
                    {
                        "Key": "ControlGroup",
                        "Title": "",
                        "Logic": 0,
                        "Items": [],
                        "ChildItems": [],
                    },
                ]
            },
            "ExScope": "0",
            "SearchType": search_type,
            "Rlang": "CHINESE",
            "KuaKuCode": DEFAULT_KUAKU_CODE,
        }

    async def search(
        self,
        query: str,
        field: str = "SU",
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        """使用 REST API 搜索论文。

        Args:
            query: 搜索关键词
            field: 搜索字段（SU=主题, TI=标题, AU=作者, KY=关键词等）
            page: 页码（从1开始）
            page_size: 每页结果数

        Returns:
            论文列表，每个论文是包含 title/url 等字段的字典
        """
        # 确保已提取凭据
        if not self._rest_api_token:
            success = await self.warmup_and_extract_credentials()
            if not success:
                logger.error("无法提取 REST API 凭据，搜索失败")
                return []

        tls = await self._get_tls()

        # 构建 QueryJson
        query_json = self._build_query_json(query, field)

        # 构建请求参数
        params = {
            "boolSearch": "true",
            "QueryJson": json.dumps(query_json, ensure_ascii=False),
            "pageNum": str(page),
            "pageSize": str(page_size),
            "dstyle": "listmode",
            "boolSortSearch": "false",
            "sentenceSearch": "false",
            "productStr": DEFAULT_KUAKU_CODE + ",",
            "aside": f"（主题：{query}）",
            "searchFrom": "资源范围：总库;时间范围：更新时间：不限;",
            "CurPage": str(page),
        }

        # 构建请求 URL
        url = "https://kns.cnki.net/kns8s/rest/QueryHandler"

        headers = {
            **self.default_headers,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://kns.cnki.net/kns8s/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            # 发送搜索请求
            resp = await tls.post(url, data=params, headers=headers)

            if resp.status_code != 200:
                logger.error(f"搜索请求失败: HTTP {resp.status_code}")
                return []

            # 解析响应
            result = resp.json()
            logger.info(f"搜索返回结果: {result}")

            # 提取搜索结果
            return self._parse_search_results(result, query)

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    def _parse_search_results(self, result: dict, query: str) -> list[dict]:
        """解析搜索结果。

        Args:
            result: API 返回的 JSON 数据
            query: 原始搜索关键词

        Returns:
            论文列表
        """
        papers = []

        # CNKI REST API 返回格式可能不同，需要适配
        # 常见格式：{"data": [...], "total": N}
        # 或：{"result": [...], "count": N}
        items = (
            result.get("data")
            or result.get("result")
            or result.get("results")
            or result.get("items")
            or []
        )

        if not items and isinstance(result, list):
            items = result

        for item in items:
            if not isinstance(item, dict):
                continue

            paper = {
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                "source": item.get("source", item.get("journal", "")),
                "year": item.get("year", ""),
                "doi": item.get("doi", ""),
                "abstract": item.get("abstract", ""),
                "url": item.get("url", item.get("link", "")),
                "citations": item.get("citations", 0),
                "is_core": item.get("is_core", False),
            }

            if paper["title"]:
                papers.append(paper)

        return papers

    async def search_via_brief_grid(
        self,
        query: str,
        field: str = "SU",
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        """使用 brief/grid 接口搜索（备选方案）。

        如果 QueryHandler 接口不工作，可以尝试 brief/grid 接口。
        """
        tls = await self._get_tls()

        # 先执行搜索
        await self.search(query, field, page, page_size)

        # 然后获取结果列表
        url = "https://kns.cnki.net/kns8s/brief/grid"
        params = {
            "pageno": str(page),
            "pagesize": str(page_size),
            "sorttype": "",
            "sortfield": "",
        }

        headers = {
            **self.default_headers,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://kns.cnki.net/kns8s/",
        }

        try:
            resp = await tls.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return []

            # 解析 HTML 或 JSON
            content_type = resp.headers.get("content-type", "")
            if "json" in content_type or resp.text.strip().startswith("{"):
                result = resp.json()
                return self._parse_search_results(result, query)
            else:
                # HTML 格式，使用正则解析
                return self._parse_html_results(resp.text)

        except Exception as e:
            logger.error(f"brief/grid 搜索失败: {e}")
            return []

    def _parse_html_results(self, html: str) -> list[dict]:
        """解析 HTML 格式的搜索结果（备选方案）"""
        from bs4 import BeautifulSoup

        papers = []
        soup = BeautifulSoup(html, "html.parser")

        # 查找结果表格行
        rows = soup.select("tr.result-table-list") or soup.select(
            'tr[class*="result"]'
        )

        for row in rows:
            paper = {}

            # 标题
            title_el = row.select_one("a.fz14") or row.select_one("a")
            if title_el:
                paper["title"] = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href:
                    paper["url"] = (
                        href if href.startswith("http")
                        else f"https://kns.cnki.net{href}"
                    )

            # 作者
            author_el = row.select_one('td[class*="author"]')
            if author_el:
                paper["author"] = author_el.get_text(strip=True)

            # 来源
            source_el = row.select_one('td[class*="source"]')
            if source_el:
                paper["source"] = source_el.get_text(strip=True)

            # 日期
            date_el = row.select_one('td[class*="date"]')
            if date_el:
                date_text = date_el.get_text(strip=True)
                yr_match = re.search(r"\d{4}", date_text)
                if yr_match:
                    paper["year"] = yr_match.group()

            # 被引
            cite_el = row.select_one('td[class*="cite"]')
            if cite_el:
                cite_text = cite_el.get_text(strip=True)
                try:
                    paper["citations"] = int(cite_text)
                except ValueError:
                    paper["citations"] = 0

            if paper.get("title"):
                papers.append(paper)

        return papers

    async def close(self) -> None:
        """关闭会话"""
        if self._tls:
            try:
                await self._tls.close()
            except Exception:
                pass
            self._tls = None


# ── 测试入口 ──────────────────────────────────────────────────

async def test_rest_api():
    """测试 REST API 客户端"""
    import sys
    from pathlib import Path

    # 添加父目录到路径，以便导入 hybrid_scraper
    sys.path.insert(0, str(Path(__file__).parent))

    from hybrid_scraper import CNKIHybridScraper

    print("=" * 70)
    print("CNKI REST API 客户端测试")
    print("=" * 70)

    # 加载 cookies
    try:
        cookies = CNKIHybridScraper.load_cookies_from_file(
            str(Path(__file__).parent.parent / "cookies.json")
        )
        print(f"[0] 加载 {len(cookies)} 个 cookies")
    except Exception as e:
        print(f"[0] 加载 cookies 失败: {e}")
        return

    # 创建 REST API 客户端
    api = CNKIRestAPI(cookies=cookies)

    try:
        # Step 1: 提取凭据
        print("\n[1] 提取 REST API 凭据...")
        success = await api.warmup_and_extract_credentials()
        if not success:
            print("    提取凭据失败！")
            return

        print(f"    Token: {api._rest_api_token}")
        print(f"    Client ID: {api._rest_api_client_id}")

        # Step 2: 搜索
        print("\n[2] 搜索论文: '大语言模型'...")
        papers = await api.search("大语言模型", field="SU", page=1, page_size=10)

        print(f"\n[3] 找到 {len(papers)} 篇论文:")
        for i, paper in enumerate(papers[:5], 1):
            print(f"\n  --- Paper {i} ---")
            print(f"  标题: {paper.get('title', 'N/A')}")
            print(f"  作者: {paper.get('author', 'N/A')}")
            print(f"  来源: {paper.get('source', 'N/A')}")
            print(f"  年份: {paper.get('year', 'N/A')}")

    finally:
        await api.close()

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_rest_api())
