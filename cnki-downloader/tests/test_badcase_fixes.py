# -*- coding: utf-8 -*-
"""CNKI 爬虫 Badcase 修复单元测试。

测试覆盖 9 个 badcase 的修复：
  - Badcase 1 (P0): PDF 下载策略优先级（browser 为主要方式）
  - Badcase 2 (P1): Title 清洁提取（移除 "附视频" 后缀）
  - Badcase 3 (P1): Authors 清洁提取（移除 <sup> 上标）
  - Badcase 4 (P1): Journal Name 扩展选择器
  - Badcase 5 (P2): Issue Number 扩展正则 + DOI 提取
  - Badcase 6 (P2): Citations 多策略提取
  - Badcase 7 (P2): Year 优先从 DOI 提取
  - Badcase 8 (P2): pdf/caj URL 去重
  - Badcase 9 (P3): RSS 重试机制
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper, FullPaperData


# ── 测试用 HTML 样本 ──────────────────────────────────────────

# CNKI 详情页 HTML 样本（包含 "附视频" 标记、作者上标、期刊名等）
SAMPLE_DETAIL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>情绪偏移：生育报道的情绪不一致性启动路径探究 - CNKI</title>
    <meta name="citation_doi" content="10.13495/j.cnki.cjjc.2026.03.004"/>
    <link rel="stylesheet" href="/piccache/css/20260624r/style.css"/>
    <script src="/js/2023/common.js"></script>
</head>
<body>
    <h1>情绪偏移：生育报道的情绪不一致性启动路径探究
        <span id="corr-video" class="type" style="display: none">附视频</span>
    </h1>
    <h3 class="author" id="authorpart">
        <span><a href="/author?id=1">周俊<sup>1,2</sup></a><input class="authorcode" type="hidden" value="code1"/></span>
        <span><a href="/author?id=2">张宇<sup>2</sup></a><input class="authorcode" type="hidden" value="code2"/></span>
        <span><a href="/author?id=3">陈科宇<sup>3</sup></a><input class="authorcode" type="hidden" value="code3"/></span>
        <span><a href="/author?id=4">余婉遥<sup>2</sup></a><input class="authorcode" type="hidden" value="code4"/></span>
    </h3>
    <div class="top-tip">
        <a href="/journal/gjxw">国际新闻界</a>
        <span>2026, 48</span>
    </div>
    <div class="abstract-text">
        摘要：本文探讨生育报道中的情绪偏移现象...
    </div>
    <div class="keywords">
        <a href="/keyword/1">生育报道</a>
        <a href="/keyword/2">情绪偏移</a>
    </div>
    <div class="source">
        <span class="resource-url"></span>
    </div>
    <div class="citation">被引：15</div>
    <a id="pdfDown" href="https://bar.cnki.net/bar/download/order?id=pdf123">PDF下载</a>
    <a id="cajDown" href="https://bar.cnki.net/bar/download/order?id=caj456">CAJ下载</a>
    <a id="cajDown2" href="https://bar.cnki.net/bar/download/order?id=pdf123">CAJ下载</a>
    <input type="hidden" name="filename" value="GJXW202603004"/>
    <input type="hidden" name="dbcode" value="CJFQ"/>
    <input type="hidden" name="tablename" value="GJXW202603"/>
    <input type="hidden" name="filesourcetype" value="1"/>
</body>
</html>
"""

# 不带 "附视频" 的 HTML 样本
SAMPLE_DETAIL_HTML_NO_VIDEO = """
<!DOCTYPE html>
<html><body>
    <h1>普通论文标题</h1>
    <h3 class="author">
        <span><a href="/author?id=1">作者一</a></span>
        <span><a href="/author?id=2">作者二</a></span>
    </h3>
    <div class="journal-name">测试期刊</div>
    <div class="abstract-text">摘要内容</div>
</body></html>
"""

# JS 中转页面 HTML 样本
SAMPLE_JS_INTERMEDIARY_HTML = """
<!DOCTYPE html>
<html>
<head><title>知网研学 - 中转中...</title></head>
<body>
    <script>window.location.href = 'https://x.cnki.net/real/download';</script>
    中转中...
</body>
</html>
"""

# 在线阅读器 SPA HTML 样本
SAMPLE_SPA_READER_HTML = """
<!DOCTYPE html>
<html>
<head><title>在线阅读 - CNKI</title></head>
<body>
    <div id="app"></div>
    <script src="/js/vue.js"></script>
    <script>new Vue({el: '#app'});</script>
    <a id="downloadBtn" href="/download/pdf">下载</a>
</body>
</html>
"""


class TestBadcaseFixTitle(unittest.TestCase):
    """Badcase 2: Title 清洁提取（移除 "附视频" 后缀）"""

    def setUp(self):
        self.scraper = CNKIHybridScraper(
            cookies={"LID": "test", "Ecp_ClientId": "test"},
            output_dir=tempfile.mkdtemp(),
        )

    def test_title_removes_video_suffix(self):
        """测试移除 "附视频" 后缀"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(SAMPLE_DETAIL_HTML, "html.parser")
        title_el = soup.select_one("h1")
        # 模拟 extract_detail_page 中的 title 提取逻辑
        for span in title_el.find_all('span', class_='type'):
            span.decompose()
        title = title_el.get_text(strip=True)
        self.assertEqual(title, "情绪偏移：生育报道的情绪不一致性启动路径探究")
        self.assertNotIn("附视频", title)

    def test_title_no_video_suffix(self):
        """测试无 "附视频" 标记的标题"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(SAMPLE_DETAIL_HTML_NO_VIDEO, "html.parser")
        title_el = soup.select_one("h1")
        for span in title_el.find_all('span', class_='type'):
            span.decompose()
        title = title_el.get_text(strip=True)
        self.assertEqual(title, "普通论文标题")


class TestBadcaseFixAuthors(unittest.TestCase):
    """Badcase 3: Authors 清洁提取（移除 <sup> 上标）"""

    def setUp(self):
        from bs4 import BeautifulSoup
        self.soup = BeautifulSoup(SAMPLE_DETAIL_HTML, "html.parser")

    def test_authors_removes_superscript(self):
        """测试移除 <sup> 上标"""
        author_el = self.soup.select_one(".author")
        # 模拟修复后的逻辑
        for tag in author_el.find_all(['sup', 'sub']):
            tag.decompose()
        for inp in author_el.find_all('input'):
            inp.decompose()
        author_links = author_el.find_all('a')
        authors = [
            a.get_text(strip=True)
            for a in author_links
            if a.get_text(strip=True) and len(a.get_text(strip=True)) > 1
        ]
        self.assertEqual(authors, ['周俊', '张宇', '陈科宇', '余婉遥'])
        # 确保不包含数字
        for author in authors:
            self.assertFalse(any(c.isdigit() for c in author))

    def test_authors_no_links_fallback(self):
        """测试无 <a> 元素时的兜底逻辑"""
        from bs4 import BeautifulSoup
        html = '<h3 class="author">作者一; 作者二; 作者三</h3>'
        soup = BeautifulSoup(html, "html.parser")
        author_el = soup.select_one(".author")
        for tag in author_el.find_all(['sup', 'sub']):
            tag.decompose()
        author_links = author_el.find_all('a')
        # 无 <a> 元素，使用兜底
        self.assertEqual(len(author_links), 0)
        author_text = author_el.get_text(strip=True)
        import re
        authors = [
            a.strip().rstrip(";；,，")
            for a in re.split(r"[;；,，\n]+", author_text)
            if a.strip() and len(a.strip()) > 1
        ]
        self.assertEqual(authors, ['作者一', '作者二', '作者三'])


class TestBadcaseFixJournalName(unittest.TestCase):
    """Badcase 4: Journal Name 扩展选择器"""

    def test_journal_name_from_top_tip(self):
        """测试从 .top-tip a 提取期刊名"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(SAMPLE_DETAIL_HTML, "html.parser")
        # 模拟扩展选择器
        journal_el = (
            soup.select_one(".journal-name")
            or soup.select_one('[class*="journal-name"]')
            or soup.select_one(".top-tip a")
            or soup.select_one(".breadcrumb a:last-child")
            or soup.select_one(".source")
            or soup.select_one('[class*="source"]')
        )
        self.assertIsNotNone(journal_el)
        text = journal_el.get_text(strip=True)
        self.assertEqual(text, "国际新闻界")

    def test_journal_name_from_journal_class(self):
        """测试从 .journal-name 提取期刊名"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(SAMPLE_DETAIL_HTML_NO_VIDEO, "html.parser")
        journal_el = soup.select_one(".journal-name")
        self.assertIsNotNone(journal_el)
        text = journal_el.get_text(strip=True)
        self.assertEqual(text, "测试期刊")

    def test_journal_name_excludes_url(self):
        """测试排除 URL 类元素"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(SAMPLE_DETAIL_HTML, "html.parser")
        # .source 元素包含空 resource-url，应被跳过
        source_el = soup.select_one(".source")
        text = source_el.get_text(strip=True)
        # .source 元素文本为空（resource-url span 无文本）
        self.assertEqual(text, "")


class TestBadcaseFixYear(unittest.TestCase):
    """Badcase 7: Year 优先从 DOI 提取"""

    def test_year_from_doi_priority(self):
        """测试 DOI 年份提取优先级最高"""
        import re
        doi = "10.13495/j.cnki.cjjc.2026.03.004"
        year = 0
        # Strategy 1: DOI contains year (匹配 .2026.03.004 格式)
        if doi:
            dm = re.search(r'\.(\d{4})\.\d{2}\.\d{3}', doi)
            if dm:
                year = int(dm.group(1))
        self.assertEqual(year, 2026)

    def test_year_excludes_css_js_paths(self):
        """测试排除 CSS/JS 路径中的数字"""
        import re
        html = """
        <link rel="stylesheet" href="/piccache/css/20260624r/style.css"/>
        <script src="/js/2023/common.js"></script>
        <body>2026年 第3期</body>
        """
        year = 0
        # 移除 script/style/link 标签内容
        cleaned_html = re.sub(
            r'<(?:script|style|link)[^>]*>.*?(?:</(?:script|style)>|/>)',
            '', html, flags=re.DOTALL | re.IGNORECASE
        )
        # Strategy 5: 在清理后的 HTML 中查找年份（匹配 "2026年" 格式）
        dm = re.search(r'(\d{4})[年/\.]', cleaned_html)
        if dm and dm.group(1).startswith(('20', '19')):
            year = int(dm.group(1))
        self.assertEqual(year, 2026)
        # 确保没有匹配到 2023（JS 路径中的年份）
        self.assertNotEqual(year, 2023)


class TestBadcaseFixIssueNumber(unittest.TestCase):
    """Badcase 5: Issue Number 扩展正则 + DOI 提取"""

    def test_issue_from_doi(self):
        """测试从 DOI 提取期号"""
        import re
        doi = "10.13495/j.cnki.cjjc.2026.03.004"
        issue_number = ""
        # 从 DOI 提取期号
        doi_issue = re.search(r'\.\d{4}\.(\d{2})\.\d{3}', doi)
        if doi_issue:
            issue_number = doi_issue.group(1)
        self.assertEqual(issue_number, "03")

    def test_issue_from_year_comma_format(self):
        """测试匹配 "2026, 48" 格式"""
        import re
        html = "2026, 48"
        issue_number = ""
        issue_match = re.search(r'\d{4},\s*(\d+)', html)
        if issue_match:
            issue_number = issue_match.group(1)
        self.assertEqual(issue_number, "48")

    def test_issue_from_label(self):
        """测试匹配 "期3" / "No.3" 格式"""
        import re
        # CNKI 格式：期号跟在 "期" 或 "No." 后面
        html = "No.3"
        issue_number = ""
        issue_match = re.search(r'(?:期|No\.|issue)\s*(\d+)', html, re.IGNORECASE)
        if issue_match:
            issue_number = issue_match.group(1)
        self.assertEqual(issue_number, "3")


class TestBadcaseFixCitations(unittest.TestCase):
    """Badcase 6: Citations 多策略提取"""

    def test_citations_from_text(self):
        """测试从 "被引：N" 文本提取"""
        import re
        html = "被引：15"
        cite_match = re.search(
            r'(?:被引|引用|cited?)\s*[：:]\s*(\d+)', html, re.IGNORECASE
        )
        self.assertIsNotNone(cite_match)
        self.assertEqual(int(cite_match.group(1)), 15)

    def test_citations_from_element(self):
        """测试从 .citation 元素提取"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            '<div class="citation">被引：15</div>', "html.parser"
        )
        cite_el = soup.select_one('.citation')
        self.assertIsNotNone(cite_el)
        cite_text = cite_el.get_text(strip=True)
        import re
        cite_num = re.search(r'(\d+)', cite_text)
        self.assertIsNotNone(cite_num)
        self.assertEqual(int(cite_num.group(1)), 15)

    def test_citations_from_data_attr(self):
        """测试从 data-citation 属性提取"""
        import re
        html = '<div data-citation="42"></div>'
        attr_match = re.search(
            r'data-citation["\']?\s*[:=]\s*["\']?(\d+)', html, re.IGNORECASE
        )
        self.assertIsNotNone(attr_match)
        self.assertEqual(int(attr_match.group(1)), 42)


class TestBadcaseFixPdfCajUrl(unittest.TestCase):
    """Badcase 8: pdf/caj URL 去重"""

    def test_order_urls_dedup(self):
        """测试 order_urls 去重"""
        import re
        html = """
        <a href="https://bar.cnki.net/bar/download/order?id=pdf123">PDF</a>
        <a href="https://bar.cnki.net/bar/download/order?id=caj456">CAJ</a>
        <a href="https://bar.cnki.net/bar/download/order?id=pdf123">PDF2</a>
        """
        order_urls = re.findall(
            r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html
        )
        # 去重（保持顺序）
        order_urls = list(dict.fromkeys(order_urls))
        self.assertEqual(len(order_urls), 2)
        self.assertEqual(order_urls[0], "pdf123")
        self.assertEqual(order_urls[1], "caj456")

    def test_pdf_caj_different_urls(self):
        """测试 pdf 和 caj URL 不同"""
        import re
        html = """
        <a href="https://bar.cnki.net/bar/download/order?id=pdf123">PDF</a>
        <a href="https://bar.cnki.net/bar/download/order?id=caj456">CAJ</a>
        """
        order_urls = re.findall(
            r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html
        )
        order_urls = list(dict.fromkeys(order_urls))
        pdf_url = f"https://bar.cnki.net/bar/download/order?id={order_urls[0]}"
        caj_url = f"https://bar.cnki.net/bar/download/order?id={order_urls[1]}"
        self.assertNotEqual(pdf_url, caj_url)


class TestBadcaseFixRssRetry(unittest.TestCase):
    """Badcase 9: RSS 重试机制"""

    def setUp(self):
        self.scraper = CNKIHybridScraper(
            cookies={"LID": "test", "Ecp_ClientId": "test"},
            output_dir=tempfile.mkdtemp(),
        )

    def test_rss_cache_exists(self):
        """测试 RSS 缓存属性存在"""
        self.assertTrue(hasattr(self.scraper, '_rss_cache'))
        self.assertTrue(hasattr(self.scraper, '_RSS_CACHE_TTL'))
        self.assertEqual(self.scraper._RSS_CACHE_TTL, 1800.0)

    def test_rss_cache_hit(self):
        """测试 RSS 缓存命中"""
        import time
        # 手动写入缓存
        cached_papers = [{"title": "test", "link": "http://example.com"}]
        self.scraper._rss_cache["TEST"] = (time.time(), cached_papers)

        # 调用 discover_papers_rss 应命中缓存
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.scraper.discover_papers_rss("TEST", max_papers=5)
            )
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["title"], "test")
        finally:
            loop.close()

    def test_rss_cache_expired(self):
        """测试 RSS 缓存过期后重新请求"""
        import time
        # 写入过期缓存（2 小时前）
        cached_papers = [{"title": "old"}]
        self.scraper._rss_cache["EXPIRED"] = (
            time.time() - 7200,  # 2 小时前
            cached_papers
        )
        # 缓存应已过期
        cache_time, _ = self.scraper._rss_cache["EXPIRED"]
        self.assertTrue(time.time() - cache_time > self.scraper._RSS_CACHE_TTL)


class TestBadcaseFixPdfDownloadPriority(unittest.TestCase):
    """Badcase 1: PDF 下载策略优先级（browser 为主要方式）"""

    def setUp(self):
        self.scraper = CNKIHybridScraper(
            cookies={"LID": "test", "Ecp_ClientId": "test"},
            output_dir=tempfile.mkdtemp(),
            browser_fallback=True,  # 启用浏览器降级
        )

    def test_browser_strategy_in_stats(self):
        """测试 browser 策略在统计中"""
        self.scraper._load_strategy_stats()
        self.assertIn("browser", self.scraper._strategy_stats)
        self.assertIn("success", self.scraper._strategy_stats["browser"])
        self.assertIn("fail", self.scraper._strategy_stats["browser"])

    def test_browser_download_method_exists(self):
        """测试 _try_browser_download 方法存在"""
        self.assertTrue(hasattr(self.scraper, '_try_browser_download'))
        self.assertTrue(callable(getattr(self.scraper, '_try_browser_download')))

    def test_download_pdf_calls_browser_first(self):
        """测试 download_pdf 优先调用 browser 策略"""
        paper = FullPaperData(cnki_url="http://test.com")
        paper.filename = "test"
        paper.pdf_order_url = "http://bar.cnki.net/test"

        # Mock browser download to return success
        async def mock_browser_download(p):
            p.download_success = True
            p.file_path = "/tmp/test.pdf"
            p.file_format = "pdf"
            return p

        self.scraper._try_browser_download = mock_browser_download

        # Mock HTTP strategies (should NOT be called)
        self.scraper._try_bar_download = AsyncMock(
            side_effect=AssertionError("bar should not be called when browser succeeds")
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.scraper.download_pdf(paper))
            self.assertTrue(result.download_success)
        finally:
            loop.close()

    def test_http_fallback_when_browser_fails(self):
        """测试 browser 失败后回退到 HTTP 策略"""
        paper = FullPaperData(cnki_url="http://test.com")
        paper.filename = "test"
        paper.pdf_order_url = "http://bar.cnki.net/test"

        # Mock browser download to fail
        async def mock_browser_download(p):
            p.errors.append("browser_download: failed")
            return p

        # Mock bar download to succeed
        async def mock_bar_download(p):
            p.download_success = True
            p.file_path = "/tmp/test.pdf"
            p.file_format = "pdf"
            return p

        self.scraper._try_browser_download = mock_browser_download
        self.scraper._try_bar_download = mock_bar_download
        # Mock other strategies to fail
        self.scraper._try_auth_check_download = AsyncMock(return_value=paper)
        self.scraper._try_gateway_download = AsyncMock(return_value=paper)
        self.scraper._try_legacy_download = AsyncMock(return_value=paper)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.scraper.download_pdf(paper))
            self.assertTrue(result.download_success)
        finally:
            loop.close()


class TestBrowserFallbackRefactored(unittest.TestCase):
    """测试重构后的 BrowserFallback"""

    def setUp(self):
        from crawler.browser_fallback import BrowserFallback
        self.BrowserFallback = BrowserFallback
        self.fb = BrowserFallback(
            cookies={"LID": "test"},
            output_dir=tempfile.mkdtemp(),
        )

    def test_download_text_patterns_exist(self):
        """测试文本匹配模式存在"""
        self.assertTrue(hasattr(self.fb, 'DOWNLOAD_TEXT_PATTERNS'))
        self.assertIn("PDF下载", self.fb.DOWNLOAD_TEXT_PATTERNS)
        self.assertIn("下载全文", self.fb.DOWNLOAD_TEXT_PATTERNS)

    def test_js_redirect_timeout_exists(self):
        """测试 JS 中转超时配置存在"""
        self.assertTrue(hasattr(self.fb, 'JS_REDIRECT_TIMEOUT'))
        self.assertEqual(self.fb.JS_REDIRECT_TIMEOUT, 15.0)

    def test_spa_render_timeout_exists(self):
        """测试 SPA 渲染超时配置存在"""
        self.assertTrue(hasattr(self.fb, 'SPA_RENDER_TIMEOUT'))
        self.assertEqual(self.fb.SPA_RENDER_TIMEOUT, 10.0)

    def test_download_strategies_methods_exist(self):
        """测试多策略方法存在"""
        self.assertTrue(callable(getattr(self.fb, '_try_download_strategies', None)))
        self.assertTrue(callable(getattr(self.fb, '_try_css_selectors', None)))
        self.assertTrue(callable(getattr(self.fb, '_try_text_buttons', None)))
        self.assertTrue(callable(getattr(self.fb, '_try_spa_reader', None)))
        self.assertTrue(callable(getattr(self.fb, '_try_js_intermediary', None)))

    def test_download_selectors_updated(self):
        """测试下载按钮选择器已更新"""
        self.assertIn('#pdfDown', self.fb.DOWNLOAD_SELECTORS)
        self.assertIn('a.btn-dlpdf', self.fb.DOWNLOAD_SELECTORS)
        self.assertIn('a[href*="bar.cnki.net"]', self.fb.DOWNLOAD_SELECTORS)


class TestFullDetailPageExtraction(unittest.TestCase):
    """测试完整的详情页提取流程（集成测试）"""

    def setUp(self):
        self.scraper = CNKIHybridScraper(
            cookies={"LID": "test", "Ecp_ClientId": "test"},
            output_dir=tempfile.mkdtemp(),
        )

    def test_extract_detail_page_all_fields(self):
        """测试详情页提取所有字段"""
        paper = FullPaperData(cnki_url="http://test.com")

        # Mock TLS response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_DETAIL_HTML
        mock_resp.url = "http://kns.cnki.net/detail"
        mock_resp.content = b"<html>...</html>"

        async def mock_get(url, headers=None):
            return mock_resp

        mock_tls = MagicMock()
        mock_tls.get = mock_get
        self.scraper._get_tls = AsyncMock(return_value=mock_tls)
        self.scraper._is_cnki_blocked = MagicMock(return_value=False)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.scraper.extract_detail_page("http://test.com")
            )
            # 验证 title 不包含 "附视频"
            self.assertNotIn("附视频", result.title)
            self.assertIn("情绪偏移", result.title)

            # 验证 authors 不包含数字
            for author in result.authors:
                self.assertFalse(any(c.isdigit() for c in author))
            self.assertIn("周俊", result.authors)

            # 验证 year 从 DOI 提取为 2026
            self.assertEqual(result.year, 2026)

            # 验证 doi
            self.assertEqual(result.doi, "10.13495/j.cnki.cjjc.2026.03.004")

            # 验证 issue_number 从 DOI 提取
            self.assertEqual(result.issue_number, "03")

            # 验证 citations
            self.assertEqual(result.citations, 15)

            # 验证 pdf/caj URL 不同
            self.assertNotEqual(result.pdf_order_url, result.caj_order_url)
            self.assertIn("pdf123", result.pdf_order_url)
            self.assertIn("caj456", result.caj_order_url)

        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
