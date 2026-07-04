"""CNKI Hybrid Scraper — Full paper data + body text extraction.

Uses curl_cffi (Chrome 124 TLS impersonation) + real university cookies
to bypass CNKI's anti-bot detection at the TLS/HTTP layer.

Architecture:
  1. RSS feeds → paper discovery (URL + basic info)
  2. curl_cffi → detail page HTML → full metadata extraction
  3. curl_cffi → PDF download → full-text extraction via pypdf
  4. Comprehensive error logging to markdown

No browser automation needed — works purely at the HTTP layer.
"""
import asyncio
import re
import json
import hashlib
import time
import random
import traceback
import contextlib
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
from xml.etree import ElementTree as ET
from io import BytesIO

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession, Response

from config.settings import settings
from crawler.proxy_pool import ProxyPool
from crawler.cooldown_scheduler import CooldownScheduler
from crawler.block_tracker import CNKIBlockTracker

# ── 跨平台文件锁 ──────────────────────────────────────────────
if sys.platform == "win32":
    import msvcrt

    @contextlib.contextmanager
    def _file_lock(lock_path: Path):
        """Windows 兼容的文件锁。"""
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as f:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                yield
            finally:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
else:
    import fcntl

    @contextlib.contextmanager
    def _file_lock(lock_path: Path):
        """Unix 兼容的文件锁。"""
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass

# ── TLS 指纹轮换池 ────────────────────────────────────────────
# 统一使用 config/settings.py 中的 settings.TLS_FINGERPRINT_POOL（Task 3.6 已完成）
#
# Task 4.1 评估结论：未让 hybrid_scraper 直接复用 anti_anti_crawl/tls_client.py 的
# TLSClient，原因如下（保持最小改动，避免过度重构）：
#   1. verify 差异：本模块使用 verify=False（代理链路需要），TLSClient 默认 verify=True
#   2. Cookie 管理：本模块需在 .cnki.net/.bar.cnki.net/.kns.cnki.net/cnki.net 多域
#      显式设置 cookies，TLSClient 不支持多域 cookie 管理
#   3. 指纹策略：本模块 _pick_fingerprint() 使用历史窗口（避免最近 3 次重复），
#      比 TLSClient.rotate_impersonate() 的纯随机策略更精细
#   4. 影响面：TLSClient 被其他模块引用，修改其默认行为风险较高
# 配置统一已通过 settings.TLS_FINGERPRINT_POOL 完成，无需进一步合并。
# 指纹历史保留窗口（避免短时间内重复使用同一指纹）
_FINGERPRINT_HISTORY_WINDOW: int = 3

# ── Data Models ────────────────────────────────────────────────


class ErrorType(Enum):
    """错误分类枚举 — 用于诊断报告与统计。"""

    HTTP_418 = "反爬虫拦截"
    HTTP_403 = "权限不足"
    HTTP_302_LOGIN = "登录重定向"
    HTML_RESPONSE = "HTML响应非PDF"
    NETWORK_ERROR = "网络异常"
    INVALID_PDF = "文件魔数错误"
    OTHER = "其他"


@dataclass
class FullPaperData:
    """Complete paper data including body text."""
    # Basic metadata
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    journal_name: str = ""
    discipline: str = ""
    issue_number: str = ""

    # Content
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    body_text: str = ""  # <-- Full text extracted from PDF
    body_text_length: int = 0

    # Identifiers
    doi: str = ""
    cnki_url: str = ""

    # Download info
    filename: str = ""
    dbcode: str = ""
    tablename: str = ""
    filesourcetype: str = ""
    pdf_order_url: str = ""
    caj_order_url: str = ""
    auth_check_url: str = ""
    download_success: bool = False
    file_path: str = ""
    file_format: str = ""
    file_size: int = 0
    file_checksum: str = ""

    # Core journal flag
    is_core: bool = False
    citations: int = 0

    # Error tracking
    errors: list[str] = field(default_factory=list)
    extraction_time: float = 0.0


# ── Main Hybrid Scraper ───────────────────────────────────────

class CNKIHybridScraper:
    """Complete CNKI paper acquisition with TLS impersonation + full-text extraction."""

    def __init__(
        self,
        cookies: dict[str, str],
        output_dir: str = "../数据库/cnki/hybrid",
        impersonate: str = "chrome124",
        proxy_url: Optional[str] = None,
        proxy_pool_path: Optional[str] = None,
        strategy_stats_path: Optional[str] = None,
        browser_fallback: bool = False,
        block_tracker_path: Optional[str] = None,
    ):
        self.cookies = cookies
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.impersonate = impersonate
        self.proxy_url = proxy_url
        self._tls: Optional[AsyncSession] = None

        # ── Task 9: 浏览器自动化降级 ──
        # 默认关闭，用户可启用；首次使用时创建 BrowserFallback 实例（延迟导入）
        self._browser_fallback_enabled: bool = browser_fallback
        self._browser_fallback = None

        # ── Task 2: 代理池 ──
        # 当前生效的代理 URL（switch_proxy 切换时更新）
        self._current_proxy: Optional[str] = proxy_url
        self._proxy_pool: Optional[ProxyPool] = None
        if proxy_pool_path:
            self._proxy_pool = ProxyPool()
            loaded = self._proxy_pool.load(proxy_pool_path)
            # 代理池非空时，优先用池中第一个可用代理
            if loaded > 0:
                pooled = self._proxy_pool.next()
                if pooled:
                    self._current_proxy = pooled

        # ── CNKI 418 封锁追踪器 ──
        # 追踪被 CNKI EdgeOne CDN 封锁的代理 IP，24 小时自动过期
        tracker_path = block_tracker_path or str(self.output_dir / "cnki_block_status.json")
        self._block_tracker: CNKIBlockTracker = CNKIBlockTracker(state_path=tracker_path)

        # ── Task 3: TLS 指纹历史 ──
        # close() 后不清空，避免重启后立即重复
        self._fingerprint_history: list[str] = []

        # ── Task 4: 418 冷却调度器 ──
        self._cooldown = CooldownScheduler()

        # ── Task 6: 断点续传 ──
        self._progress_path: Path = self.output_dir / "progress.json"

        # ── Task 7: 策略统计 ──
        self._strategy_stats_path: Optional[Path] = None
        self._strategy_stats: dict[str, dict[str, int]] = {}
        if strategy_stats_path:
            self._strategy_stats_path = Path(strategy_stats_path)
            self._load_strategy_stats()

        # ── Task 8: 请求模式随机化 ──
        self._request_count: int = 0

        # Error log collection
        self.error_log: list[dict] = []
        self._stats = {
            "total_attempted": 0,
            "detail_success": 0,
            "detail_failed": 0,
            "pdf_success": 0,
            "pdf_failed": 0,
            "body_text_success": 0,
            "body_text_failed": 0,
            "cnki_blocks_detected": 0,
            "proxy_switches": 0,
        }

    def _pick_fingerprint(self) -> str:
        """从 settings.TLS_FINGERPRINT_POOL 中随机选取一个未在最近 3 次使用过的指纹。

        若所有指纹都在历史窗口内，则随机选一个（避免阻塞）。
        """
        fingerprint_pool = settings.TLS_FINGERPRINT_POOL
        recent = set(self._fingerprint_history[-_FINGERPRINT_HISTORY_WINDOW:])
        candidates = [fp for fp in fingerprint_pool if fp not in recent]
        if not candidates:
            candidates = list(fingerprint_pool)
        chosen = random.choice(candidates)
        self._fingerprint_history.append(chosen)
        return chosen

    async def _get_tls(self) -> AsyncSession:
        if self._tls is None:
            # Task 3: 随机选取指纹（保留历史避免重复）
            fingerprint = self._pick_fingerprint()
            # Task 2: 使用 self._current_proxy 支持代理切换
            self._tls = AsyncSession(
                impersonate=fingerprint,
                timeout=30,
                verify=False,
                proxy=self._current_proxy,
            )
            # 显式设置多个域，确保 bar.cnki.net 等子域能继承 cookies
            for domain in [".cnki.net", ".bar.cnki.net", ".kns.cnki.net", "cnki.net"]:
                for name, value in self.cookies.items():
                    if value:  # 跳过空值
                        self._tls.cookies.set(name, value, domain=domain)
        return self._tls

    async def switch_proxy(self) -> bool:
        """切换到代理池中的下一个代理。

        关闭当前会话，从代理池取下一个可用代理，重建会话。
        若代理池为空或无可用代理，返回 False。

        Returns:
            True 表示切换成功，False 表示无可用代理
        """
        if self._proxy_pool is None:
            return False

        # 标记当前代理失败
        if self._current_proxy:
            self._proxy_pool.mark_failed(self._current_proxy)

        # 关闭旧会话
        await self.close()

        # 取下一个可用代理
        next_proxy = self._proxy_pool.next()
        if not next_proxy:
            self._current_proxy = None
            return False

        self._current_proxy = next_proxy
        # close() 已将 _tls 置为 None，下次 _get_tls() 会用新代理重建
        return True

    # ── CNKI 418 自动检测与代理切换 ─────────────────────────────

    def _is_cnki_blocked(self, response: Response) -> bool:
        """检测响应是否被 CNKI 反爬虫拦截（HTTP 418）。

        CNKI 使用腾讯 EdgeOne CDN 进行 IP 级封锁，检测条件：
          1. 响应状态码为 418
          2. 响应头包含 server: TencentEdgeOne 且 body 为空
          3. 响应为 HTML 但 body 极短（< 50 字节）且状态码为 418

        Args:
            response: curl_cffi 的 Response 对象

        Returns:
            True 表示检测到 CNKI 418 拦截
        """
        # 条件 1: 状态码为 418
        if response.status_code == 418:
            self._log_cnki_block(response)
            return True

        # 条件 2: server 头为 TencentEdgeOne 且 body 为空
        server_header = ""
        try:
            # curl_cffi 的 headers 是 Headers 对象，不区分大小写
            server_header = response.headers.get("server", "") or response.headers.get("Server", "")
        except Exception:
            pass
        if server_header and "tencentedgeone" in server_header.lower():
            try:
                body_len = len(response.content)
            except Exception:
                body_len = 0
            if body_len == 0:
                self._log_cnki_block(response)
                return True

        # 条件 3: HTML 响应但 body 极短（< 50 字节）且状态码 418
        # （状态码 418 已在条件 1 处理，这里补充 body 长度判断）
        if response.status_code == 418:
            try:
                body_len = len(response.content)
            except Exception:
                body_len = 0
            if body_len < 50:
                self._log_cnki_block(response)
                return True

        return False

    def _log_cnki_block(self, response: Response) -> None:
        """记录 CNKI 418 拦截事件到错误日志。

        Args:
            response: 触发 418 的 Response 对象
        """
        self._stats["cnki_blocks_detected"] += 1
        server_header = ""
        try:
            server_header = response.headers.get("server", "") or response.headers.get("Server", "")
        except Exception:
            pass
        body_len = 0
        try:
            body_len = len(response.content)
        except Exception:
            pass
        self._log_error(
            "cnki_418_block",
            f"HTTP 418 — CNKI EdgeOne CDN IP 封锁 "
            f"(server={server_header}, body_len={body_len}, proxy={self._current_proxy})",
            error_type=ErrorType.HTTP_418,
            status_code=response.status_code,
            server=server_header,
            body_length=body_len,
            proxy=self._current_proxy or "direct",
        )
        print(
            f"[418] CNKI EdgeOne CDN 拦截 — "
            f"proxy={self._current_proxy or 'direct'}, "
            f"server={server_header}, body_len={body_len}"
        )

    async def _switch_proxy_for_cnki(self) -> bool:
        """CNKI 418 专用代理切换：标记封锁 + 切换到未封锁代理。

        流程：
          1. 标记当前代理为 CNKI 封锁（block_tracker.mark_blocked + proxy_pool.mark_cnki_blocked）
          2. 标记代理失败计数（proxy_pool.mark_failed）
          3. 关闭旧会话
          4. 从代理池取下一个未被 CNKI 封锁的代理（next_for_cnki）
          5. 若无可用代理返回 False

        Returns:
            True 表示切换成功，False 表示所有代理均被封锁或代理池为空
        """
        if self._proxy_pool is None:
            return False

        # 标记当前代理被 CNKI 封锁
        if self._current_proxy:
            # 同时更新 CNKIBlockTracker（持久化）和 proxy_pool 内部状态
            self._block_tracker.mark_blocked(self._current_proxy)
            self._proxy_pool.mark_cnki_blocked(self._current_proxy)
            self._proxy_pool.mark_failed(self._current_proxy)
            print(f"[418] 代理 {self._current_proxy} 已标记为 CNKI 封锁（24h 冷却）")

        # 关闭旧会话
        await self.close()

        # 取下一个未被 CNKI 封锁的代理
        # next_for_cnki() 内部会跳过 cnki_status="cnki_blocked" 的代理
        next_proxy = self._proxy_pool.next_for_cnki()
        if not next_proxy:
            self._current_proxy = None
            print("[418] 所有代理均被 CNKI 封锁或不可用")
            return False

        self._current_proxy = next_proxy
        self._stats["proxy_switches"] += 1
        remaining = self._block_tracker.cooldown_remaining(next_proxy)
        print(f"[418] 已切换到未封锁代理 → {next_proxy} (剩余冷却: {remaining:.0f}s)")
        return True

    async def _request_with_cnki_retry(
        self,
        url: str,
        *,
        headers: Optional[dict] = None,
        max_retries: int = 3,
        method: str = "GET",
    ) -> tuple[Optional[Response], bool]:
        """带 CNKI 418 自动检测与代理切换的请求封装。

        检测到 418 时：
          1. 标记当前代理为 CNKI 封锁
          2. 切换到下一个未封锁代理
          3. 重试请求（最多 max_retries 次）
          4. 所有代理均封锁时返回 (None, True) 表示需浏览器降级

        Args:
            url: 请求 URL
            headers: 请求头，为 None 时使用 default_headers
            max_retries: 最大重试次数（每次切换代理后重试一次）
            method: HTTP 方法，目前仅支持 GET

        Returns:
            (response, all_blocked) 元组：
              - response: 成功时的 Response 对象，失败时为 None
              - all_blocked: True 表示所有代理均被 CNKI 封锁，需浏览器降级
        """
        req_headers = headers if headers is not None else self.default_headers

        for attempt in range(max_retries):
            # 检查当前代理是否已被 CNKI 封锁（启动时可能从持久化状态恢复）
            if self._current_proxy and self._block_tracker.is_blocked(self._current_proxy):
                print(f"[418] 当前代理 {self._current_proxy} 已被封锁，尝试切换...")
                if not await self._switch_proxy_for_cnki():
                    # 所有代理均被封锁
                    return None, True

            try:
                tls = await self._get_tls()
                if method.upper() == "GET":
                    resp = await tls.get(url, headers=req_headers)
                else:
                    resp = await tls.request(method, url, headers=req_headers)

                # 检测 CNKI 418 拦截
                if self._is_cnki_blocked(resp):
                    print(f"[418] 检测到拦截 (attempt {attempt + 1}/{max_retries})，切换代理...")
                    if await self._switch_proxy_for_cnki():
                        # 切换成功，重试
                        continue
                    else:
                        # 所有代理均被封锁
                        return None, True

                # 非 418 响应，返回给调用方处理
                return resp, False

            except Exception as e:
                self._log_error(
                    "cnki_request_exception",
                    f"请求异常: {e}",
                    url=url[:120],
                    proxy=self._current_proxy or "direct",
                    attempt=attempt,
                )
                # 网络异常也尝试切换代理
                if attempt < max_retries - 1:
                    if await self._switch_proxy_for_cnki():
                        continue
                    return None, True
                return None, False

        # 重试次数耗尽
        return None, True

    async def warmup_session(self) -> bool:
        """预热会话：访问首页 → 搜索页，建立 CNKI 会话。

        CNKI 需要先建立会话才能访问受保护资源（如 PDF 下载）。
        直接请求详情页可能导致认证失败。

        检测到 418 时使用 _switch_proxy_for_cnki() 切换到未封锁代理；
        所有代理均被封锁时返回 False。

        Returns:
            True 如果会话预热成功，False 如果被 418 拦截或失败
        """
        tls = await self._get_tls()

        # Step 1: 访问首页
        try:
            resp = await tls.get("https://www.cnki.net/", headers=self.default_headers)
            if self._is_cnki_blocked(resp):
                self._log_error("warmup_home", "HTTP 418 — CNKI 反爬虫拦截")
                print("[warmup] HTTP 418 — CNKI EdgeOne CDN 拦截，尝试切换代理...")
                # CNKI 418 专用切换：标记封锁 + 取未封锁代理
                if await self._switch_proxy_for_cnki():
                    print(f"[warmup] 已切换代理 → {self._current_proxy}")
                    return await self.warmup_session()
                print("[warmup] 所有代理均被 CNKI 封锁，无法切换")
                return False
            if resp.status_code != 200:
                self._log_error("warmup_home", f"HTTP {resp.status_code}")
                return False
        except Exception as e:
            self._log_error("warmup_home", str(e))
            return False

        # Step 2: 访问搜索页
        try:
            resp = await tls.get("https://kns.cnki.net/kns8s/", headers=self.default_headers)
            if self._is_cnki_blocked(resp):
                self._log_error("warmup_search", "HTTP 418 — CNKI 反爬虫拦截")
                print("[warmup] HTTP 418 — CNKI EdgeOne CDN 拦截，尝试切换代理...")
                # CNKI 418 专用切换：标记封锁 + 取未封锁代理
                if await self._switch_proxy_for_cnki():
                    print(f"[warmup] 已切换代理 → {self._current_proxy}")
                    return await self.warmup_session()
                print("[warmup] 所有代理均被 CNKI 封锁，无法切换")
                return False
            if resp.status_code != 200:
                self._log_error("warmup_search", f"HTTP {resp.status_code}")
                return False
        except Exception as e:
            self._log_error("warmup_search", str(e))
            return False

        # 验证登录状态（可选，校园网 IP 认证可能不显示登录标识）
        if "dx0741" in resp.text or "中央民族大学" in resp.text:
            return True
        return True  # 即使没检测到登录标识也继续，因为校园网 IP 认证可能不显示

    async def close(self):
        if self._tls:
            await self._tls.close()
            self._tls = None
        # Task 3: 不清空 _fingerprint_history，避免重启后立即重复使用同一指纹

    @property
    def default_headers(self) -> dict:
        """完整的浏览器请求头，模拟 Chrome 124 真实请求。

        包含 Sec-CH-UA 和 Sec-Fetch-* 等浏览器安全头，
        这些头是 CNKI 反爬虫系统检测的关键字段。
        """
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,application/signed-exchange;v=b3;q=0.8",
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

    # ── Task 8: 请求模式随机化 ─────────────────────────────────

    async def _human_delay(self) -> None:
        """模拟人类浏览间隔：随机等待 5~15 秒。

        替代固定延迟，降低被 CNKI 反爬虫识别为机器人的概率。
        """
        await asyncio.sleep(random.uniform(5.0, 15.0))

    async def _browse_behavior(self) -> None:
        """模拟浏览行为：每 10 次请求后访问首页或搜索页。

        在请求计数达到 10 的倍数时触发，模拟真实用户在站点内浏览。
        """
        self._request_count += 1
        if self._request_count % 10 != 0:
            return
        try:
            tls = await self._get_tls()
            # 随机选择访问首页或搜索页
            target = random.choice([
                "https://www.cnki.net/",
                "https://kns.cnki.net/kns8s/",
            ])
            await tls.get(target, headers=self.default_headers)
        except Exception:
            # 浏览行为失败不影响主流程
            pass

    # ── RSS Discovery ──────────────────────────────────────────

    # RSS 缓存：避免短时间内重复请求同一期刊（key=journal_code, value=(timestamp, papers)）
    _rss_cache: dict[str, tuple[float, list[dict]]] = {}
    # RSS 缓存有效期（秒）：30 分钟内复用缓存结果
    _RSS_CACHE_TTL: float = 1800.0

    async def discover_papers_rss(
        self, journal_code: str, max_papers: int = 20
    ) -> list[dict]:
        """Discover papers from a journal's RSS feed.

        增强稳定性：
          - 30 分钟缓存：避免短时间内重复请求同一期刊
          - 非 418 错误也重试（最多 3 次，指数退避）
          - 418 拦截：切换代理后重试
        """
        # 检查缓存：30 分钟内复用结果
        cached = self._rss_cache.get(journal_code)
        if cached:
            cache_time, cached_papers = cached
            if time.time() - cache_time < self._RSS_CACHE_TTL:
                print(f"[rss] 命中缓存（{len(cached_papers)} 篇，"
                      f"缓存于 {time.ctime(cache_time)}）")
                return cached_papers[:max_papers] if max_papers < len(cached_papers) else cached_papers

        url = f"https://rss.cnki.net/knavi/rss/{journal_code}?pcode=CJFD,CCJD"
        max_retries = 3

        for attempt in range(max_retries):
            tls = await self._get_tls()
            try:
                resp = await tls.get(url, headers=self.default_headers)

                # CNKI 418 自动检测：检测到拦截时切换代理并重试
                if self._is_cnki_blocked(resp):
                    self._log_error("rss_fetch", "HTTP 418 — CNKI 拦截", url=url)
                    if await self._switch_proxy_for_cnki():
                        print(f"[rss] 418 拦截，已切换代理 → {self._current_proxy}，重试中...")
                        continue  # 切换代理后重试
                    else:
                        print("[rss] 418 拦截，所有代理均被封锁")
                        return []

                if resp.status_code != 200:
                    self._log_error("rss_fetch", f"Status {resp.status_code}", url=url)
                    # 非 418 错误也重试（指数退避）
                    if attempt < max_retries - 1:
                        wait = 2.0 * (attempt + 1)
                        print(f"[rss] HTTP {resp.status_code}，{wait}s 后重试 ({attempt+2}/{max_retries})...")
                        await asyncio.sleep(wait)
                        continue
                    return []

                # 解析 RSS XML
                root = ET.fromstring(resp.text)
                papers = []
                for item in root.findall(".//item")[:max_papers]:
                    papers.append({
                        "title": (item.findtext("title", "") or "").strip(),
                        "link": (item.findtext("link", "") or "").strip(),
                        "author": (item.findtext("author", "") or "").strip(),
                        "description": (item.findtext("description", "") or "").strip(),
                        "pub_date": (item.findtext("pubDate", "") or "").strip(),
                    })

                # 写入缓存
                self._rss_cache[journal_code] = (time.time(), papers)
                return papers

            except ET.ParseError as e:
                self._log_error("rss_parse", f"XML 解析失败: {e}", url=url)
                if attempt < max_retries - 1:
                    wait = 2.0 * (attempt + 1)
                    print(f"[rss] XML 解析失败，{wait}s 后重试 ({attempt+2}/{max_retries})...")
                    await asyncio.sleep(wait)
                    continue
                return []
            except Exception as e:
                self._log_error("rss_fetch", str(e), url=url)
                if attempt < max_retries - 1:
                    wait = 2.0 * (attempt + 1)
                    print(f"[rss] 请求异常，{wait}s 后重试 ({attempt+2}/{max_retries})...")
                    await asyncio.sleep(wait)
                    continue
                return []

        return []

    # ── Detail Page Extraction ─────────────────────────────────

    async def extract_detail_page(self, paper_url: str, discipline: str = "") -> FullPaperData:
        """Extract ALL metadata from a CNKI paper detail page using curl_cffi + BeautifulSoup."""
        self._stats["total_attempted"] += 1
        start = time.time()
        paper = FullPaperData(cnki_url=paper_url, discipline=discipline)

        try:
            tls = await self._get_tls()
            resp = await tls.get(paper_url, headers=self.default_headers)

            # CNKI 418 自动检测：检测到拦截时切换代理并重试一次
            if self._is_cnki_blocked(resp):
                self._stats["detail_failed"] += 1
                paper.errors.append("detail_http: HTTP 418 — CNKI EdgeOne CDN 拦截")
                # 尝试切换到未封锁代理后重试一次
                if await self._switch_proxy_for_cnki():
                    print(f"[detail] 418 拦截，已切换代理 → {self._current_proxy}，重试中...")
                    tls = await self._get_tls()
                    resp = await tls.get(paper_url, headers=self.default_headers)
                    if self._is_cnki_blocked(resp):
                        paper.errors.append("detail_http: 重试后仍 418")
                        return paper
                else:
                    paper.errors.append("detail_http: 所有代理均被 CNKI 封锁")
                    return paper

            if resp.status_code != 200:
                self._log_error(
                    "detail_http",
                    f"HTTP {resp.status_code}",
                    url=paper_url[:120],
                )
                self._stats["detail_failed"] += 1
                paper.errors.append(f"detail_http: status={resp.status_code}")
                return paper

            html = resp.text

            if "verify" in resp.url.lower() or "验证" in html[:500]:
                self._log_error("detail_captcha", "CAPTCHA/verify page", url=paper_url[:120])
                self._stats["detail_failed"] += 1
                paper.errors.append("detail_captcha: redirected to verification")
                return paper

            soup = BeautifulSoup(html, "html.parser")

            # ── Title ──
            title_el = (
                soup.select_one("h1")
                or soup.select_one(".title")
                or soup.select_one('[class*="title"]')
                or soup.select_one("h2")
            )
            if title_el:
                # 移除 type 标记（如 "附视频"、"附音频"），这些 <span class="type">
                # 虽在浏览器中 display:none，但 get_text() 会提取其文本
                for span in title_el.find_all('span', class_='type'):
                    span.decompose()
                paper.title = title_el.get_text(strip=True)[:300]

            # ── Authors ──
            author_el = (
                soup.select_one(".author")
                or soup.select_one('[class*="author"]')
                or soup.select_one('[class*="writer"]')
            )
            if author_el:
                # 移除上标/下标（机构编号）和隐藏 input（authorcode）
                # 这些标签的文本会被 get_text() 误并入作者名
                for tag in author_el.find_all(['sup', 'sub']):
                    tag.decompose()
                for inp in author_el.find_all('input'):
                    inp.decompose()
                # 优先按 <a> 元素逐个提取作者（CNKI 详情页每个作者一个 <a>）
                author_links = author_el.find_all('a')
                if author_links:
                    paper.authors = [
                        a.get_text(strip=True)
                        for a in author_links
                        if a.get_text(strip=True) and len(a.get_text(strip=True)) > 1
                    ]
                else:
                    # 兜底：按分隔符切分纯文本
                    author_text = author_el.get_text(strip=True)
                    paper.authors = [
                        a.strip().rstrip(";；,，")
                        for a in re.split(r"[;；,，\n]+", author_text)
                        if a.strip() and len(a.strip()) > 1
                    ]

            # ── Abstract ──
            abstract_el = (
                soup.select_one(".abstract-text")
                or soup.select_one('[class*="abstract"]')
                or soup.select_one("#abstract")
            )
            if abstract_el:
                text = abstract_el.get_text(strip=True)
                # Clean common prefixes
                text = re.sub(r'^[摘\s]*要[：:\s]*', '', text)
                paper.abstract = text[:5000]

            if not paper.abstract:
                # Try regex extraction
                abs_match = re.search(
                    r'<span[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</span>',
                    html, re.DOTALL
                )
                if abs_match:
                    paper.abstract = re.sub(r'<[^>]+>', '', abs_match.group(1)).strip()[:5000]

            # ── Keywords ──
            kw_elements = soup.select(
                ".keywords a, [class*='keyword'] a, .keywords span, [class*='keyword'] span"
            )
            for kw_el in kw_elements:
                text = kw_el.get_text(strip=True).rstrip(";；,，")
                if text and len(text) > 1 and len(text) < 50:
                    paper.keywords.append(text)

            if not paper.keywords:
                # Regex fallback
                kw_section = re.search(
                    r'(?:关键词|關鍵詞|Key ?words?)\s*[：:]\s*(.{0,300})',
                    html
                )
                if kw_section:
                    kw_text = kw_section.group(1)
                    paper.keywords = [
                        k.strip().rstrip(";；")
                        for k in re.split(r'[;；,，\s]+', kw_text)
                        if k.strip() and len(k.strip()) > 1
                    ]

            # ── DOI ──
            doi_match = re.search(r'10\.\d{4,}/[^\s"\'<>&]+', html)
            if doi_match:
                paper.doi = doi_match.group(0).rstrip(".")

            # ── Year ── (8 strategies, CNKI year format varies widely)
            # 优先级调整：DOI 年份提取提前到 Strategy 1，避免被 HTML 中
            # CSS/JS 路径里的数字（如 piccache.cnki.net/.../20260624r/）干扰
            year = 0

            # Strategy 1: DOI contains year (CNKI DOIs: 10.13495/j.cnki.cjjc.2026.03.004)
            # DOI 是最可靠的年份来源，优先级最高
            # 正则匹配 .2026.03.004 格式（年份.期号.序号）
            if paper.doi:
                dm = re.search(r'\.(\d{4})\.\d{2}\.\d{3}', paper.doi)
                if dm: year = int(dm.group(1))
                if not year:
                    dm = re.search(r'/j\.[^/]+/(\d{4})\.', paper.doi)
                    if dm: year = int(dm.group(1))

            # Strategy 2: CNKI-specific year pattern in JSON-LD / meta tags
            if not year:
                ym = re.search(r'(?:发表年份|出版年份|年份)[：:]\s*(\d{4})', html)
                if ym: year = int(ym.group(1))

            # Strategy 3: Explicit year label in text
            if not year:
                ym = re.search(r'(?:年|year|date|发表年)[:\s]*(\d{4})', html, re.IGNORECASE)
                if ym: year = int(ym.group(1))

            # Strategy 4: Year from pub_date in RSS (e.g. "Sat, 14 Mar 2026 16:00:00 GMT")
            if not year:
                dm = re.search(r'(?:pubDate|pub_date|date)[:\s]*\w{3},\s*\d{1,2}\s+\w{3}\s+(\d{4})', html)
                if dm: year = int(dm.group(1))
                if not year:
                    dm = re.search(r'(?:pubDate|pub_date|date)[:\s]*(\d{4})', html)
                    if dm: year = int(dm.group(1))

            # Strategy 5: CNKI 文献年份+期号格式 "2026, 48"（排除 CSS/JS 路径）
            # 排除 piccache/js/css 等资源路径中的数字
            if not year:
                # 先移除 <script>/<style>/<link> 标签内容，避免匹配到资源路径
                cleaned_html = re.sub(
                    r'<(?:script|style|link)[^>]*>.*?(?:</(?:script|style)>|/>)',
                    '', html, flags=re.DOTALL | re.IGNORECASE
                )
                dm = re.search(r'(\d{4})[年/\.]', cleaned_html)
                if dm and dm.group(1).startswith(('20', '19')): year = int(dm.group(1))

            # Strategy 6: CNKI issue number format like "2026.03"
            if not year:
                dm = re.search(r'(?:期|No\.|issue)[\s\.]*(\d{4})\.\d{1,2}', html, re.IGNORECASE)
                if dm: year = int(dm.group(1))

            # Strategy 7: Year in URL pattern
            if not year:
                dm = re.search(r'/(\d{4})/\d{2}/', paper.cnki_url)
                if dm: year = int(dm.group(1))

            # Strategy 8: Any 20xx in the first 5000 chars (兜底，最后才用)
            if not year:
                dm = re.search(r'(20[2-9]\d)', html[:5000])
                if dm: year = int(dm.group(1))

            if year > 1900:
                paper.year = year

            # ── Journal Name ──
            # 扩展选择器：CNKI 详情页期刊名可能在多种位置
            journal_el = (
                soup.select_one(".journal-name")
                or soup.select_one('[class*="journal-name"]')
                or soup.select_one(".top-tip a")
                or soup.select_one(".breadcrumb a:last-child")
                or soup.select_one(".source")
                or soup.select_one('[class*="source"]')
                or soup.select_one(".journal")
                or soup.select_one('[class*="journal"]')
            )
            if journal_el:
                text = journal_el.get_text(strip=True)
                # 排除空文本和资源 URL 类元素
                if text and "http" not in text and len(text) < 100:
                    # 清理多余字符：CNKI 详情页 .top-tip a 文本可能包含
                    # "国际新闻界 ." 或 "国际新闻界 .2026 ,48" 等多余后缀
                    # 去除末尾的 " ."、年份、期号等非期刊名内容
                    text = re.sub(r'\s*\.\s*$', '', text)  # 去除末尾 " ."
                    text = re.sub(r'\s*\.\d{4}.*$', '', text)  # 去除 ".2026,48" 等
                    text = re.sub(r'\s*,\s*\d+', '', text)  # 去除 ",48" 等
                    text = text.strip()
                    if text:
                        paper.journal_name = text[:100]

            # ── Citations ──
            # CNKI 详情页被引次数获取策略：
            #   1. HTML 文本 "被引：N" / "被引:N" / "cited: N"（旧版页面）
            #   2. <a class="citation">N</a> / <span class="cite-count">N</span> 等元素
            #   3. data-citation="N" 属性
            #   4. REST API: /citation-api/v1/literature/quotations/metrics
            #      （新版页面，引用次数通过 JS AJAX 动态加载，需要 clientverify 令牌）
            #      纯 HTTP 客户端无法获取令牌，需 Playwright 浏览器自动化
            cite_match = re.search(
                r'(?:被引|引用|cited?)\s*[：:]\s*(\d+)', html, re.IGNORECASE
            )
            if cite_match:
                paper.citations = int(cite_match.group(1))
            else:
                # 兜底 1：查找带 citation/cite 类名的元素
                cite_el = (
                    soup.select_one('.citation')
                    or soup.select_one('[class*="cite-count"]')
                    or soup.select_one('[class*="citation"]')
                    or soup.select_one('.citations')
                )
                if cite_el:
                    cite_text = cite_el.get_text(strip=True)
                    cite_num = re.search(r'(\d+)', cite_text)
                    if cite_num:
                        paper.citations = int(cite_num.group(1))
                # 兜底 2：查找 data-citation 属性
                if not paper.citations:
                    attr_match = re.search(
                        r'data-citation["\']?\s*[:=]\s*["\']?(\d+)', html, re.IGNORECASE
                    )
                    if attr_match:
                        paper.citations = int(attr_match.group(1))
                # 兜底 3：查找 #rc3 元素（CNKI 新版页面引用次数容器）
                # 注意：#rc3 的内容由 JS 动态填充，纯 HTTP 获取的 HTML 中可能为空
                if not paper.citations:
                    rc3_el = soup.select_one('#rc3')
                    if rc3_el:
                        rc3_text = rc3_el.get_text(strip=True)
                        rc3_num = re.search(r'(\d+)', rc3_text)
                        if rc3_num:
                            paper.citations = int(rc3_num.group(1))

            # ── Core Journal ──
            paper.is_core = bool(
                re.search(r'核心|CSSCI|北大核心|CSCD|SCI|EI', html, re.IGNORECASE)
            )

            # ── Download URLs ──
            # CNKI internal file identifiers
            fn_match = re.search(r'filename=([^&"\'\\s]+)', html)
            if fn_match:
                paper.filename = fn_match.group(1)

            db_match = re.search(r'dbcode=([^&"\'\\s]+)', html)
            if db_match:
                paper.dbcode = db_match.group(1)

            # 新增：提取下载所需的其他参数
            tb_match = re.search(r'tablename=([^&"\'\\s]+)', html)
            if tb_match:
                paper.tablename = tb_match.group(1)

            fs_match = re.search(r'filesourcetype=([^&"\'\\s]+)', html)
            if fs_match:
                paper.filesourcetype = fs_match.group(1)

            # bar.cnki.net download order URLs
            # 去重并保持顺序：CNKI 详情页可能有重复的下载按钮，
            # 去重后确保 pdf_order_url 和 caj_order_url 指向不同文件
            order_urls = re.findall(
                r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html
            )
            # 去重（保持顺序）
            order_urls = list(dict.fromkeys(order_urls))
            if len(order_urls) >= 1:
                paper.pdf_order_url = f"https://bar.cnki.net/bar/download/order?id={order_urls[0]}"
            if len(order_urls) >= 2:
                paper.caj_order_url = f"https://bar.cnki.net/bar/download/order?id={order_urls[1]}"

            # x.cnki.net auth-check URL (alternative path)
            auth_match = re.search(
                r'https://x\.cnki\.net/web/page/auth-check\?[^"\'\\s]+', html
            )
            if auth_match:
                paper.auth_check_url = auth_match.group(0).replace("&amp;", "&")

            # Also try finding direct download links
            download_links = re.findall(
                r'href="(https?://[^"]*(?:download|pdf|全文)[^"]*)"', html, re.IGNORECASE
            )
            if download_links and not paper.pdf_order_url:
                paper.pdf_order_url = download_links[0]

            # ── Issue Number ──
            # CNKI 详情页期号格式多样：
            #   1. DOI 中嵌入期号（如 10.13495/j.cnki.cjjc.2026.03.004 中的 "03"）— 最可靠
            #   2. "第3期" / "No.3" / "issue 3"
            #   3. "2026, 48"（年份, 总期号/卷号）— 兜底
            # 优先从 DOI 提取（精确期号），再尝试文本格式
            if paper.doi:
                doi_issue = re.search(r'\.\d{4}\.(\d{2})\.\d{3}', paper.doi)
                if doi_issue:
                    paper.issue_number = doi_issue.group(1)
            if not paper.issue_number:
                issue_match = re.search(r'(?:期|No\.|issue)\s*(\d+)', html, re.IGNORECASE)
                if issue_match:
                    paper.issue_number = issue_match.group(1)
                else:
                    # 兜底：匹配 "2026, 48" 格式（年份后跟期号/卷号）
                    issue_match = re.search(r'\d{4},\s*(\d+)', html)
                    if issue_match:
                        paper.issue_number = issue_match.group(1)

            paper.extraction_time = time.time() - start
            self._stats["detail_success"] += 1

        except Exception as e:
            self._log_error("detail_exception", str(e), url=paper_url[:120])
            self._stats["detail_failed"] += 1
            paper.errors.append(f"detail_exception: {str(e)[:200]}")

        return paper

    # ── PDF Download ───────────────────────────────────────────

    async def download_pdf(self, paper: FullPaperData) -> FullPaperData:
        """多策略 PDF 下载（动态优先级 + 浏览器优先）。

        CNKI 已将下载流程改为在线阅读器 SPA + JS 中转模式，
        纯 HTTP 策略（bar/auth_check/gateway/legacy）全部失效。
        本方法优先使用 Playwright 浏览器自动化作为主要下载方式，
        HTTP 策略作为辅助探测。

        策略优先级：
          1. browser（Playwright 浏览器自动化）— 主要方式，处理 SPA/JS 中转
          2. bar.cnki.net 下载订单 — 辅助探测
          3. x.cnki.net auth-check — 辅助探测
          4. gateway.cnki.net — 辅助探测（已废弃）
          5. 旧版 kcms/detail — 辅助探测（触发验证码）

        Args:
            paper: 论文数据，需包含 filename/dbcode 等参数

        Returns:
            更新后的论文数据，包含下载结果
        """
        self._stats["total_attempted"] += 1 if not paper.download_success else 0

        # ── 策略 0: Playwright 浏览器自动化（主要方式） ──
        # CNKI 下载流程已变更，HTTP 策略全部失效，优先使用浏览器自动化
        if self._browser_fallback_enabled:
            browser_result = await self._try_browser_download(paper)
            self._update_strategy_stats("browser", browser_result.download_success)
            if browser_result.download_success:
                self._save_progress(browser_result)
                return browser_result
            # 浏览器失败，继续尝试 HTTP 策略作为辅助探测

        # ── HTTP 策略（辅助探测） ──
        # Task 7: 按成功率降序获取策略优先级
        strategy_order = self._get_strategy_priority()

        # 策略名 → (执行方法, 前置条件)
        strategy_map = {
            "bar": (self._try_bar_download, bool(paper.pdf_order_url)),
            "auth_check": (self._try_auth_check_download, bool(paper.filename)),
            "gateway": (self._try_gateway_download, bool(paper.filename)),
            "legacy": (self._try_legacy_download, bool(paper.filename)),
        }

        for strategy_name in strategy_order:
            method, precondition = strategy_map[strategy_name]
            if not precondition:
                continue

            result = await method(paper)

            # Task 7: 更新策略统计
            self._update_strategy_stats(strategy_name, result.download_success)

            if result.download_success:
                # Task 6: 下载成功后保存进度
                self._save_progress(result)
                return result

            # 如果检测到 418 反爬虫拦截，跳过后续策略（也会 418）
            if any("418" in err for err in result.errors):
                self._stats["pdf_failed"] += 1
                return result

        # 所有策略失败
        if not paper.errors:
            paper.errors.append("pdf_download: all strategies failed")
        self._stats["pdf_failed"] += 1
        return paper

    async def _try_browser_download(self, paper: FullPaperData) -> FullPaperData:
        """策略 0: Playwright 浏览器自动化下载（主要方式）。

        CNKI 已将下载流程改为在线阅读器 SPA + JS 中转，
        纯 HTTP 客户端无法处理，使用 Playwright 浏览器自动化。

        Args:
            paper: 论文数据

        Returns:
            更新后的论文数据，包含下载结果
        """
        try:
            from .browser_fallback import BrowserFallback
            if self._browser_fallback is None:
                self._browser_fallback = BrowserFallback(
                    cookies=self.cookies,
                    output_dir=str(self.output_dir / "pdfs")
                )
        except Exception as e:
            paper.errors.append(f"browser_download init failed: {e}")
            return paper

        # 使用当前代理（如果有）
        proxy_url = self._current_proxy

        try:
            fb_result = await self._browser_fallback.download_pdf(
                paper_url=paper.cnki_url,
                filename=paper.filename or "",
                proxy_url=proxy_url,
            )

            if fb_result["success"]:
                paper.download_success = True
                paper.file_path = fb_result["file_path"]
                paper.file_format = "pdf" if fb_result["file_path"].endswith(".pdf") else "caj"
                # 计算文件大小和校验和
                from pathlib import Path as P
                p = P(fb_result["file_path"])
                paper.file_size = p.stat().st_size
                paper.file_checksum = hashlib.md5(p.read_bytes()).hexdigest()
                # 提取正文（如果是 PDF）
                if paper.file_format == "pdf":
                    body_text = self._extract_pdf_text(p.read_bytes())
                    paper.body_text = body_text
                    paper.body_text_length = len(body_text)
                    if body_text and len(body_text) > 100:
                        self._stats["body_text_success"] += 1
                    else:
                        self._stats["body_text_failed"] += 1
                        paper.errors.append(f"body_text: too short ({len(body_text)} chars)")
                print(f"       [browser] 浏览器下载成功: {paper.file_path}")
            else:
                # 检查是否为 418 拦截
                fb_errors = fb_result.get("errors", [])
                is_418 = any("418" in err or "拦截" in err for err in fb_errors)
                if is_418 and proxy_url:
                    # 浏览器 + 代理也 418，标记该代理为 CNKI 封锁
                    print(f"       [browser] 代理 {proxy_url} 浏览器也 418，标记为封锁")
                    self._block_tracker.mark_blocked(proxy_url)
                    if self._proxy_pool is not None:
                        self._proxy_pool.mark_failed(proxy_url)
                paper.errors.extend(fb_errors)
        except Exception as e:
            paper.errors.append(f"browser_download: {str(e)[:200]}")

        return paper

    async def _try_bar_download(self, paper: FullPaperData) -> FullPaperData:
        """策略 1: bar.cnki.net 下载订单（完整流程）"""
        download_url = paper.pdf_order_url
        try:
            tls = await self._get_tls()
            resp = await tls.get(
                download_url,
                headers={
                    **self.default_headers,
                    "Referer": paper.cnki_url,
                    "Accept": "application/pdf,text/html,*/*",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-site",
                    "Upgrade-Insecure-Requests": "1",
                },
            )

            # 检查是否重定向到登录页
            if "login.cnki.net" in resp.url or "login" in resp.url.lower():
                self._log_error(
                    "pdf_auth_failed",
                    "bar.cnki.net 重定向到登录页",
                    original_url=download_url[:120],
                    final_url=resp.url[:120],
                )
                paper.errors.append("bar_download: redirected to login")
                return paper

            # 处理 418 反爬虫拦截（使用增强检测）
            if self._is_cnki_blocked(resp):
                paper.errors.append("bar_download: HTTP 418")
                return paper

            if resp.status_code != 200:
                self._log_error(
                    "bar_http",
                    f"HTTP {resp.status_code}",
                    url=download_url[:120],
                )
                paper.errors.append(f"bar_download: HTTP {resp.status_code}")
                return paper

            content = resp.content
            if content[:5] == b"%PDF-" or content[:4] == b"PK\x03\x04":
                return await self._save_pdf(paper, content)

            # 如果是 HTML，尝试解析其中的实际下载链接
            if b"<!DOCTYPE html>" in content[:100] or b"<html" in content[:100]:
                pdf_url_match = re.search(
                    r'(https?://[^"\']*\.(?:pdf|caj)[^"\']*)', resp.text
                )
                if pdf_url_match:
                    actual_url = pdf_url_match.group(1)
                    resp2 = await tls.get(actual_url, headers=self.default_headers)
                    if resp2.content[:5] == b"%PDF-" or resp2.content[:4] == b"PK\x03\x04":
                        return await self._save_pdf(paper, resp2.content)

                # 查找 meta refresh 或 window.location 重定向
                meta_match = re.search(
                    r'(?:window\.location|meta.*?refresh.*?url=)["\']?(https?://[^"\'>\s]+)',
                    resp.text, re.IGNORECASE
                )
                if meta_match:
                    redirect_url = meta_match.group(1)
                    resp3 = await tls.get(redirect_url, headers=self.default_headers)
                    if resp3.content[:5] == b"%PDF-" or resp3.content[:4] == b"PK\x03\x04":
                        return await self._save_pdf(paper, resp3.content)

                # HTML 但没有找到 PDF 链接
                paper.errors.append(
                    f"bar_download: HTML response, no PDF link found "
                    f"(content-type: {resp.headers.get('Content-Type', 'unknown')[:50]}, "
                    f"size: {len(content)} bytes)"
                )
            else:
                # 非 PDF 非 HTML 响应
                paper.errors.append(
                    f"bar_download: unexpected content "
                    f"(first bytes: {content[:20]!r}, "
                    f"size: {len(content)} bytes)"
                )

        except Exception as e:
            self._log_error("bar_exception", str(e), url=download_url[:120])
            paper.errors.append(f"bar_download: {str(e)[:100]}")

        return paper

    async def _try_auth_check_download(self, paper: FullPaperData) -> FullPaperData:
        """策略 2: x.cnki.net auth-check 完整流程。

        使用从详情页提取的 filename/dbcode/tablename/filesourcetype 参数，
        通过 x.cnki.net 的 auth-check 接口完成下载。
        """
        if not paper.filename:
            return paper

        auth_url = (
            f"https://x.cnki.net/web/page/auth-check"
            f"?redirectsource=zkjbj&redirectjump=yxread"
            f"&filesourcetype={paper.filesourcetype or '1'}"
            f"&dbcode={paper.dbcode or 'CJFQ'}"
            f"&tablename={paper.tablename}"
            f"&filename={paper.filename}"
        )

        try:
            tls = await self._get_tls()
            headers = {
                **self.default_headers,
                "Referer": paper.cnki_url,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-site",
            }

            resp = await tls.get(auth_url, headers=headers)

            # 检查是否重定向到登录页
            if "login.cnki.net" in resp.url or "login" in resp.url.lower():
                paper.errors.append("auth_check: redirected to login")
                return paper

            # 处理 418 反爬虫拦截（使用增强检测）
            if self._is_cnki_blocked(resp):
                paper.errors.append("auth_check: HTTP 418")
                return paper

            if resp.status_code != 200:
                paper.errors.append(f"auth_check: HTTP {resp.status_code}")
                return paper

            content = resp.content
            if content[:5] == b"%PDF-" or content[:4] == b"PK\x03\x04":
                return await self._save_pdf(paper, content)

            # 如果是 HTML，解析其中的实际下载链接
            if b"<!DOCTYPE html>" in content[:100] or b"<html" in content[:100]:
                # 查找页面中的实际 PDF 下载链接
                pdf_url_match = re.search(
                    r'(https?://[^"\']*\.(?:pdf|caj)[^"\']*)', resp.text
                )
                if pdf_url_match:
                    actual_pdf_url = pdf_url_match.group(1)
                    resp2 = await tls.get(actual_pdf_url, headers=headers)
                    if resp2.content[:5] == b"%PDF-" or resp2.content[:4] == b"PK\x03\x04":
                        return await self._save_pdf(paper, resp2.content)

                # 查找 bar.cnki.net 下载链接
                bar_url_match = re.search(
                    r'(https?://bar\.cnki\.net/[^"\']+)', resp.text
                )
                if bar_url_match:
                    bar_url = bar_url_match.group(1)
                    resp3 = await tls.get(bar_url, headers=headers)
                    if resp3.content[:5] == b"%PDF-" or resp3.content[:4] == b"PK\x03\x04":
                        return await self._save_pdf(paper, resp3.content)

                # HTML 但没有找到下载链接
                paper.errors.append(
                    f"auth_check: HTML response, no download link found "
                    f"(size: {len(content)} bytes)"
                )
            else:
                paper.errors.append(
                    f"auth_check: unexpected content "
                    f"(first bytes: {content[:20]!r}, size: {len(content)} bytes)"
                )

        except Exception as e:
            self._log_error("auth_check_exception", str(e), url=auth_url[:120])
            paper.errors.append(f"auth_check: {str(e)[:100]}")

        return paper

    async def _try_gateway_download(self, paper: FullPaperData) -> FullPaperData:
        """策略 3: gateway.cnki.net 直接下载"""
        if not paper.filename:
            return paper

        gw_urls = [
            f"https://gateway.cnki.net/web/page/download?filename={paper.filename}&dbcode={paper.dbcode or 'CJFQ'}",
            f"https://gateway.cnki.net/download/file?filename={paper.filename}&dbcode={paper.dbcode or 'CJFQ'}",
        ]

        tls = await self._get_tls()
        headers = {
            **self.default_headers,
            "Referer": paper.cnki_url,
            "Accept": "application/pdf,text/html,*/*",
        }

        for gw_url in gw_urls:
            try:
                resp = await tls.get(gw_url, headers=headers)

                if "login.cnki.net" in resp.url or "login" in resp.url.lower():
                    continue

                # 处理 418 反爬虫拦截（使用增强检测）
                if self._is_cnki_blocked(resp):
                    paper.errors.append("gateway: HTTP 418")
                    return paper

                content = resp.content
                if content[:5] == b"%PDF-" or content[:4] == b"PK\x03\x04":
                    return await self._save_pdf(paper, content)
            except Exception as e:
                self._log_error("gateway_exception", str(e), url=gw_url[:120])

        paper.errors.append("gateway: all URLs failed")
        return paper

    async def _try_legacy_download(self, paper: FullPaperData) -> FullPaperData:
        """策略 4: 旧版 kcms/detail 接口"""
        if not paper.filename:
            return paper

        legacy_urls = [
            f"https://kns.cnki.net/kcms/detail/detail.aspx?dbcode={paper.dbcode or 'CJFQ'}&filename={paper.filename}&flag=download",
            f"https://kns.cnki.net/kcms/detail/detail.aspx?dbcode={paper.dbcode or 'CJFQ'}&filename={paper.filename}&v=&type=download",
            f"https://kns.cnki.net/kcms2/article/abstract?v=&filename={paper.filename}&type=download",
        ]

        tls = await self._get_tls()
        headers = {
            **self.default_headers,
            "Referer": paper.cnki_url,
            "Accept": "application/pdf,text/html,*/*",
        }

        for legacy_url in legacy_urls:
            try:
                resp = await tls.get(legacy_url, headers=headers)

                if "login.cnki.net" in resp.url or "login" in resp.url.lower():
                    continue

                # 处理 418 反爬虫拦截（使用增强检测）
                if self._is_cnki_blocked(resp):
                    paper.errors.append("legacy: HTTP 418")
                    return paper

                content = resp.content
                if content[:5] == b"%PDF-" or content[:4] == b"PK\x03\x04":
                    return await self._save_pdf(paper, content)

                # 解析 HTML 中的下载链接
                if b"<!DOCTYPE html>" in content[:100] or b"<html" in content[:100]:
                    pdf_url_match = re.search(
                        r'(https?://[^"\']*\.(?:pdf|caj)[^"\']*)', resp.text
                    )
                    if pdf_url_match:
                        actual_url = pdf_url_match.group(1)
                        resp2 = await tls.get(actual_url, headers=headers)
                        if resp2.content[:5] == b"%PDF-" or resp2.content[:4] == b"PK\x03\x04":
                            return await self._save_pdf(paper, resp2.content)

            except Exception as e:
                self._log_error("legacy_exception", str(e), url=legacy_url[:120])

        paper.errors.append("legacy: all URLs failed")
        return paper

    async def _save_pdf(self, paper: FullPaperData, content: bytes) -> FullPaperData:
        """保存 PDF/CAJ 文件并提取正文"""
        # 确定格式
        if content[:5] == b"%PDF-":
            paper.file_format = "pdf"
        elif content[:4] == b"PK\x03\x04":
            paper.file_format = "caj"
        else:
            paper.file_format = "unknown"
            paper.errors.append("save_pdf: unknown format")
            return paper

        # 验证最小大小
        if len(content) < 1000:
            self._log_error("pdf_too_small", f"{len(content)} bytes")
            paper.errors.append(f"save_pdf: file too small ({len(content)} bytes)")
            return paper

        # 保存到磁盘
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', paper.title)[:80]
        ext = paper.file_format
        safe_dir = self.output_dir / (paper.discipline or "papers")
        safe_dir.mkdir(parents=True, exist_ok=True)
        file_path = safe_dir / f"{safe_title}_{paper.year}.{ext}"

        file_path.write_bytes(content)
        paper.file_path = str(file_path)
        paper.file_size = len(content)
        paper.file_checksum = hashlib.sha256(content).hexdigest()[:12]
        paper.download_success = True
        self._stats["pdf_success"] += 1

        # 提取正文
        if paper.file_format == "pdf":
            body_text = self._extract_pdf_text(content)
            paper.body_text = body_text
            paper.body_text_length = len(body_text)
            if body_text and len(body_text) > 100:
                self._stats["body_text_success"] += 1
            else:
                self._stats["body_text_failed"] += 1
                paper.errors.append(f"body_text: too short ({len(body_text)} chars)")

        return paper

    async def download_pdf_with_retry(
        self, paper: FullPaperData, max_retries: int = 2
    ) -> FullPaperData:
        """带重试的 PDF 下载。

        处理两种失败场景：
          - 418 反爬虫拦截：优先切换代理，无可用代理时冷却后重试
          - 登录重定向：重新预热会话后重试

        Task 4: 418 冷却等待使用 CooldownScheduler.wait(attempt)，
        替代固定 30.0 * (attempt + 1) 延迟。
        CNKI 418 增强：检测到 418 时优先调用 _switch_proxy_for_cnki() 切换代理。

        重构说明：浏览器自动化现在是 download_pdf() 的主要策略（策略 0），
        不再需要在重试结束后单独调用 _browser_fallback_with_proxies()。
        但保留该方法作为多代理浏览器降级的兜底（当主代理浏览器也失败时，
        尝试其他代理）。
        """
        for attempt in range(max_retries):
            try:
                result = await self.download_pdf(paper)
                if result.download_success:
                    return result

                # 检测 418 反爬虫拦截 — 优先切换代理，无代理时冷却等待
                if any("418" in err for err in result.errors):
                    # CNKI 418 增强：优先尝试切换到未封锁代理
                    switched = await self._switch_proxy_for_cnki()
                    if switched:
                        print(f"       [retry] 418 拦截，已切换代理 → {self._current_proxy}")
                        # 清除 418 错误，避免累积
                        result.errors = [e for e in result.errors if "418" not in e]
                        continue

                    # 无可用代理 — 使用冷却调度器指数退避后重试
                    print(f"       [retry] 418 拦截，无可用代理，冷却等待...")
                    wait_sec = await self._cooldown.wait(attempt)
                    print(f"       [retry] 冷却 {wait_sec:.0f}s 完成，重试中...")
                    # 重新预热会话
                    await self.warmup_session()
                    # 清除 418 错误，避免累积
                    result.errors = [e for e in result.errors if "418" not in e]
                    continue

                # 如果重定向到登录页，刷新会话后重试
                if any("login" in err.lower() for err in result.errors):
                    await asyncio.sleep(3.0 * (attempt + 1))
                    await self.warmup_session()
                    result.errors = [e for e in result.errors if "login" not in e.lower()]
                    continue

                # 其他错误（gateway/legacy 失败等）— 不重试，直接返回
                break

            except Exception as e:
                self._log_error("pdf_retry", f"Attempt {attempt+1} failed: {e}")
                await asyncio.sleep(5.0 * (attempt + 1))

        # ── 浏览器自动化多代理降级（兜底） ──
        # 当主代理的浏览器下载也失败时，尝试其他可用代理（含直连）
        # 这是最后的兜底方案，确保不遗漏任何可用的下载路径
        if self._browser_fallback_enabled and not paper.download_success:
            await self._browser_fallback_with_proxies(paper)

        return paper

    async def _browser_fallback_with_proxies(self, paper: FullPaperData) -> None:
        """浏览器降级下载：依次尝试每个可用代理（含直连）。

        流程：
          1. 收集所有候选代理：当前代理 + 代理池中未封锁的代理 + 直连(None)
          2. 对每个代理调用 BrowserFallback.download_pdf(proxy_url=...)
          3. 若浏览器也返回 418 拦截，标记该代理为 CNKI 封锁
          4. 任一代理成功即返回，全部失败则记录错误

        Args:
            paper: 论文数据，下载结果会写入 paper 字段
        """
        try:
            from .browser_fallback import BrowserFallback
            if self._browser_fallback is None:
                self._browser_fallback = BrowserFallback(
                    cookies=self.cookies,
                    output_dir=str(self.output_dir / "pdfs")
                )
        except Exception as e:
            paper.errors.append(f"browser_fallback init failed: {e}")
            return

        # 收集候选代理列表：当前代理 + 池中未封锁代理
        # 去重并保留顺序
        candidate_proxies: list[Optional[str]] = []
        seen: set[str] = set()

        if self._current_proxy and self._current_proxy not in seen:
            candidate_proxies.append(self._current_proxy)
            seen.add(self._current_proxy)

        if self._proxy_pool is not None:
            for proxy_info in self._proxy_pool.all_proxies():
                url = proxy_info.get("url")
                if not url or url in seen:
                    continue
                if not proxy_info.get("enabled", True):
                    continue
                if proxy_info.get("fail_count", 0) >= self._proxy_pool.MAX_FAIL_COUNT:
                    continue
                if self._block_tracker.is_blocked(url):
                    continue
                candidate_proxies.append(url)
                seen.add(url)

        # 最后添加直连作为兜底（None 表示不使用代理）
        candidate_proxies.append(None)

        print(f"       [fallback] 尝试浏览器自动化下载（{len(candidate_proxies)} 个候选代理）...")

        for idx, proxy_url in enumerate(candidate_proxies):
            proxy_label = proxy_url or "直连"
            print(f"       [fallback] ({idx + 1}/{len(candidate_proxies)}) 代理: {proxy_label}")

            try:
                fb_result = await self._browser_fallback.download_pdf(
                    paper_url=paper.cnki_url,
                    filename=paper.filename or "",
                    proxy_url=proxy_url,
                )

                if fb_result["success"]:
                    paper.download_success = True
                    paper.file_path = fb_result["file_path"]
                    paper.file_format = "pdf" if fb_result["file_path"].endswith(".pdf") else "caj"
                    # 计算文件大小和校验和
                    from pathlib import Path as P
                    p = P(fb_result["file_path"])
                    paper.file_size = p.stat().st_size
                    paper.file_checksum = hashlib.md5(p.read_bytes()).hexdigest()
                    print(f"       [fallback] 浏览器下载成功（代理: {proxy_label}）: {paper.file_path}")
                    return

                # 检查是否为 418 拦截
                fb_errors = fb_result.get("errors", [])
                is_418 = any("418" in err or "拦截" in err for err in fb_errors)

                if is_418 and proxy_url:
                    # 浏览器 + 代理也 418，标记该代理为 CNKI 封锁
                    print(f"       [fallback] 代理 {proxy_label} 浏览器也 418，标记为封锁")
                    self._block_tracker.mark_blocked(proxy_url)
                    if self._proxy_pool is not None:
                        self._proxy_pool.mark_failed(proxy_url)

                paper.errors.extend(fb_errors)

            except Exception as e:
                paper.errors.append(f"browser_fallback ({proxy_label}): {str(e)}")

        # 所有代理均失败 — 进入长冷却（24h）并报告
        print("       [fallback] 所有代理的浏览器降级均失败")
        self._log_error(
            "browser_fallback_all_failed",
            f"所有代理（含直连）的浏览器降级均失败 — "
            f"候选代理数: {len(candidate_proxies)}",
            error_type=ErrorType.HTTP_418,
            paper_url=paper.cnki_url[:120],
            candidate_proxies=[p or "direct" for p in candidate_proxies],
        )

    @staticmethod
    def _extract_pdf_text(content: bytes) -> str:
        """Extract text from PDF bytes using pypdf or pdfplumber."""
        text = ""

        # Try pypdf first (already a dependency)
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(content))
            pages = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            text = "\n\n".join(pages)
            if text.strip():
                return text.strip()
        except Exception:
            pass

        # Try pdfplumber as fallback
        try:
            import pdfplumber
            with pdfplumber.open(BytesIO(content)) as pdf:
                pages = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages.append(page_text)
                text = "\n\n".join(pages)
                if text.strip():
                    return text.strip()
        except ImportError:
            pass
        except Exception:
            pass

        return text.strip()

    # ── End-to-End Pipeline ────────────────────────────────────

    async def harvest_paper(
        self,
        journal_code: str,
        journal_name: str,
        discipline: str,
        max_papers: int = 5,
        download_pdfs: bool = True,
    ) -> list[FullPaperData]:
        """Complete paper harvesting pipeline: RSS → detail → PDF → text.

        Task 4: 418 处理使用冷却调度器，连续 5 次后调用 switch_proxy()
        Task 6: 处理每篇论文前检查 _is_downloaded()，跳过已下载的
        Task 8: 请求前后使用 _human_delay() 替代固定延迟

        Args:
            journal_code: CNKI journal product code (e.g., 'GJXW')
            journal_name: Human-readable name (e.g., '国际新闻界')
            discipline: Research discipline (e.g., '新闻传播学')
            max_papers: Maximum number of papers to harvest
            download_pdfs: Whether to download PDFs and extract body text

        Returns:
            List of FullPaperData with all extracted fields
        """
        results: list[FullPaperData] = []
        # Task 4: 连续 418 计数器，达到阈值后切换代理
        consecutive_418: int = 0

        # CNKI 418 增强：检查所有代理是否已被 CNKI 封锁
        if self._proxy_pool is not None:
            blocked = self._block_tracker.blocked_proxies()
            available = self._proxy_pool.available_count()
            if blocked and available == 0:
                # 所有代理均被封锁 — 进入长冷却（24h）并报告
                min_cooldown = min(
                    (self._block_tracker.cooldown_remaining(p) for p in blocked),
                    default=0.0,
                )
                print(
                    f"[harvest] 所有 {len(blocked)} 个代理均被 CNKI 封锁，"
                    f"最近解除需 {min_cooldown:.0f}s（约 {min_cooldown/3600:.1f}h）"
                )
                self._log_error(
                    "harvest_all_proxies_blocked",
                    f"所有 {len(blocked)} 个代理均被 CNKI 封锁 — "
                    f"进入 24h 长冷却，最近解除需 {min_cooldown:.0f}s",
                    error_type=ErrorType.HTTP_418,
                    blocked_proxies=blocked,
                    min_cooldown_seconds=min_cooldown,
                )
                # 尝试浏览器降级（直连模式）作为最后手段
                if self._browser_fallback_enabled:
                    print("[harvest] 尝试浏览器降级（直连模式）作为最后手段...")
                else:
                    return results

        # 会话预热：建立 CNKI 会话，确保后续请求能通过认证
        warmup_ok = await self.warmup_session()
        if not warmup_ok:
            # 418 拦截 — 使用冷却调度器等待后重试一次
            print("[harvest] Warmup failed, cooling down and retrying...")
            await self._cooldown.wait(0)
            # 关闭旧会话，创建新会话
            await self.close()
            warmup_ok = await self.warmup_session()
            if not warmup_ok:
                print("[harvest] Warmup still failing after cooldown. Aborting.")
                self._log_error(
                    "harvest_warmup_failed",
                    "Session warmup failed after cooldown — CNKI 418 blocking",
                )
                return results
        await asyncio.sleep(1.0)

        # Step 1: RSS Discovery
        rss_papers = await self.discover_papers_rss(journal_code, max_papers)
        if not rss_papers:
            self._log_error(
                "harvest_rss_empty",
                f"No RSS papers found for {journal_code}",
                journal=journal_name,
            )
            return results

        for i, rss_item in enumerate(rss_papers):
            if len(results) >= max_papers:
                break

            # Task 6: 断点续传 — 检查是否已下载，跳过已下载的
            rss_link = rss_item.get("link", "")
            if rss_link and self._is_downloaded(rss_link):
                print(f"  [{i+1}/{len(rss_papers)}] 已下载，跳过: {rss_item.get('title', '')[:60]}")
                continue

            # Task 8: 请求前人类延迟（替代固定延迟）
            await self._human_delay()
            # Task 8: 模拟浏览行为
            await self._browse_behavior()

            # Step 2: Detail page extraction
            paper = await self.extract_detail_page(rss_item["link"], discipline)
            paper.journal_name = journal_name

            # 如果详情页返回 418，使用冷却调度器，连续 5 次后切换代理
            if any("418" in err for err in paper.errors):
                consecutive_418 += 1
                print(f"  [{i+1}/{len(rss_papers)}] HTTP 418 detected (连续 {consecutive_418} 次)...")

                # CNKI 418 增强：使用 _switch_proxy_for_cnki() 标记封锁并切换
                if self._cooldown.should_switch_proxy(consecutive_418):
                    print(f"  [{i+1}/{len(rss_papers)}] 连续 {consecutive_418} 次 418，尝试切换代理...")
                    switched = await self._switch_proxy_for_cnki()
                    if switched:
                        print(f"  [{i+1}/{len(rss_papers)}] 已切换代理 → {self._current_proxy}")
                        consecutive_418 = 0
                    else:
                        print(f"  [{i+1}/{len(rss_papers)}] 所有代理均被 CNKI 封锁，无法切换")
                else:
                    # Task 4: 使用冷却调度器等待
                    wait_sec = await self._cooldown.wait(consecutive_418 - 1)
                    print(f"  [{i+1}/{len(rss_papers)}] 冷却 {wait_sec:.0f}s 后重试...")

                # 重试一次
                await self._human_delay()
                paper = await self.extract_detail_page(rss_item["link"], discipline)
                paper.journal_name = journal_name
                if not any("418" in err for err in paper.errors):
                    consecutive_418 = 0
            else:
                consecutive_418 = 0

            # Merge RSS basic info as fallback
            if not paper.title and rss_item.get("title"):
                paper.title = rss_item["title"]
            if not paper.authors and rss_item.get("author"):
                paper.authors = [
                    a.strip()
                    for a in rss_item["author"].split(";")
                    if a.strip()
                ]
            # Extract year from RSS pub_date (e.g. "Sat, 14 Mar 2026 16:00:00 GMT")
            if paper.year == 0 and rss_item.get("pub_date"):
                ym = re.search(r"(20\d{2})", rss_item["pub_date"])
                if ym:
                    paper.year = int(ym.group(1))

            # Step 3: PDF download and body text extraction
            if download_pdfs:
                if paper.pdf_order_url or paper.auth_check_url or paper.filename:
                    # Task 8: 下载前人类延迟（替代固定延迟）
                    await self._human_delay()
                    paper = await self.download_pdf_with_retry(paper)
                else:
                    paper.errors.append("pdf_download: no download URL found on detail page")

            # Print status
            fields_present = sum([
                bool(paper.title), bool(paper.authors), bool(paper.abstract),
                bool(paper.keywords), bool(paper.doi), paper.year > 0,
                bool(paper.journal_name), bool(paper.body_text),
            ])
            total_fields = 8
            status = "OK" if fields_present >= 5 else f"PARTIAL ({fields_present}/{total_fields} fields)"

            print(f"  [{i+1}/{len(rss_papers)}] {status} | {paper.title[:60]}...")
            if paper.body_text:
                print(f"       body_text: {paper.body_text_length} chars extracted")
            if paper.errors:
                for err in paper.errors[:2]:
                    print(f"       ERROR: {err[:120]}")

            results.append(paper)

        return results

    # ── Error Logging ──────────────────────────────────────────

    def _classify_error(self, msg: str) -> ErrorType:
        """根据错误消息字符串分类错误类型。

        Args:
            msg: 错误消息文本

        Returns:
            对应的 ErrorType 枚举值
        """
        lower = msg.lower()
        if "418" in msg:
            return ErrorType.HTTP_418
        if "403" in msg:
            return ErrorType.HTTP_403
        if "login" in lower or "登录" in msg or "重定向" in msg or "redirect" in lower:
            return ErrorType.HTTP_302_LOGIN
        if "html" in lower or "doctype" in lower:
            return ErrorType.HTML_RESPONSE
        if "timeout" in lower or "connection" in lower or "网络" in msg or "network" in lower:
            return ErrorType.NETWORK_ERROR
        if "pdf" in lower or "魔数" in msg or "magic" in lower or "format" in lower:
            return ErrorType.INVALID_PDF
        return ErrorType.OTHER

    def _log_error(
        self,
        category: str,
        message: str,
        *,
        error_type: Optional[ErrorType] = None,
        **context,
    ):
        """Record error with context for later markdown export.

        Args:
            category: 错误分类标签（如 "warmup_home"），存入 "type" 字段
            message: 错误消息文本
            error_type: ErrorType 枚举分类，默认根据 message 自动分类
            **context: 额外上下文字段
        """
        if error_type is None:
            error_type = self._classify_error(message)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": category,  # 保留原字段名，向后兼容 export_error_log_md
            "error_type": error_type.name,  # Task 5: ErrorType 分类字段
            "message": message[:500],
            **context,
        }
        self.error_log.append(entry)

    def _generate_diagnostic_report(self) -> str:
        """按错误类型统计并生成诊断报告字符串。

        Returns:
            多行诊断报告文本，包含各错误类型计数与建议
        """
        from collections import Counter

        type_counts: Counter[str] = Counter(
            e.get("error_type", "OTHER") for e in self.error_log
        )

        suggestions: dict[str, str] = {
            ErrorType.HTTP_418.name: "建议切换代理或等待冷却（指数退避）",
            ErrorType.HTTP_403.name: "建议检查 cookies 是否过期或权限不足",
            ErrorType.HTTP_302_LOGIN.name: "建议重新预热会话或更新登录 cookies",
            ErrorType.HTML_RESPONSE.name: "建议检查下载链接解析逻辑，可能需要跟进重定向",
            ErrorType.NETWORK_ERROR.name: "建议检查网络连接或代理可用性",
            ErrorType.INVALID_PDF.name: "建议检查文件完整性或更换下载策略",
            ErrorType.OTHER.name: "建议查看详细错误日志进一步分析",
        }

        lines = [
            "=== CNKI 爬虫诊断报告 ===",
            f"生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"错误总数: {len(self.error_log)}",
            "",
            "── 错误类型统计 ──",
        ]
        for etype, count in type_counts.most_common():
            suggestion = suggestions.get(etype, suggestions[ErrorType.OTHER.name])
            lines.append(f"  {etype}: {count} 次 → {suggestion}")

        lines.extend([
            "",
            "── 统计指标 ──",
            f"  详情页成功: {self._stats['detail_success']}",
            f"  详情页失败: {self._stats['detail_failed']}",
            f"  PDF 下载成功: {self._stats['pdf_success']}",
            f"  PDF 下载失败: {self._stats['pdf_failed']}",
            f"  正文提取成功: {self._stats['body_text_success']}",
            f"  正文提取失败: {self._stats['body_text_failed']}",
        ])
        return "\n".join(lines)

    # ── Task 6: 断点续传 ────────────────────────────────────────

    def _load_progress(self) -> dict:
        """读取已下载论文记录。

        Returns:
            {"downloaded": [{"doi": ..., "url": ..., "filename": ...}]}
            文件不存在或解析失败时返回空结构
        """
        lock_path = self._progress_path.with_suffix(".json.lock")
        with _file_lock(lock_path):
            return self._load_progress_unlocked()

    def _load_progress_unlocked(self) -> dict:
        """读取已下载论文记录（无锁，供持锁调用方使用）。

        Returns:
            {"downloaded": [{"doi": ..., "url": ..., "filename": ...}]}
            文件不存在或解析失败时返回空结构
        """
        if not self._progress_path.exists():
            return {"downloaded": []}
        try:
            data = json.loads(self._progress_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "downloaded" not in data:
                return {"downloaded": []}
            return data
        except (json.JSONDecodeError, OSError):
            return {"downloaded": []}

    def _save_progress(self, paper: FullPaperData) -> None:
        """追加一条已下载论文记录并写入 progress.json。

        Args:
            paper: 已成功下载的论文数据
        """
        lock_path = self._progress_path.with_suffix(".json.lock")
        with _file_lock(lock_path):
            data = self._load_progress_unlocked()
            data["downloaded"].append({
                "doi": paper.doi,
                "url": paper.cnki_url,
                "filename": paper.filename,
                "title": paper.title[:200],
                "file_path": paper.file_path,
            })
            try:
                self._progress_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except OSError:
                pass

    def _is_downloaded(self, paper_url: str, doi: str = "") -> bool:
        """检查论文是否已下载（基于 URL 或 DOI）。

        Args:
            paper_url: 论文详情页 URL
            doi: 论文 DOI（可选）

        Returns:
            True 表示已下载过
        """
        data = self._load_progress()
        for item in data.get("downloaded", []):
            if paper_url and item.get("url") == paper_url:
                return True
            if doi and item.get("doi") and item.get("doi") == doi:
                return True
        return False

    # ── Task 7: 策略统计与动态优先级 ────────────────────────────

    def _load_strategy_stats(self) -> None:
        """从 strategy_stats_path 加载策略统计到 self._strategy_stats。

        文件不存在或解析失败时使用默认空统计。
        """
        default = {
            "browser": {"success": 0, "fail": 0},
            "bar": {"success": 0, "fail": 0},
            "auth_check": {"success": 0, "fail": 0},
            "gateway": {"success": 0, "fail": 0},
            "legacy": {"success": 0, "fail": 0},
        }
        if self._strategy_stats_path is None or not self._strategy_stats_path.exists():
            self._strategy_stats = default
            return
        try:
            data = json.loads(self._strategy_stats_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # 合并默认值，确保所有策略键存在
                self._strategy_stats = {
                    k: {"success": int(v.get("success", 0)), "fail": int(v.get("fail", 0))}
                    for k, v in data.items()
                }
                # 补全缺失的策略
                for k, v in default.items():
                    self._strategy_stats.setdefault(k, v)
            else:
                self._strategy_stats = default
        except (json.JSONDecodeError, OSError):
            self._strategy_stats = default

    def _get_strategy_priority(self) -> list[str]:
        """按成功率降序返回策略名列表。

        成功率 = success / (success + fail)，无数据时按默认顺序。
        成功率相同的策略按默认顺序（bar > auth_check > gateway > legacy）。

        Returns:
            策略名列表，如 ["bar", "auth_check", "gateway", "legacy"]
        """
        default_order = ["bar", "auth_check", "gateway", "legacy"]

        def success_rate(name: str) -> float:
            stats = self._strategy_stats.get(name, {"success": 0, "fail": 0})
            total = stats.get("success", 0) + stats.get("fail", 0)
            if total == 0:
                return -1.0  # 无数据的策略排到最后（但保持默认相对顺序）
            return stats.get("success", 0) / total

        # 稳定排序：先按默认顺序，再按成功率降序（Python sort 稳定）
        ordered = sorted(default_order, key=success_rate, reverse=True)
        return ordered

    def _update_strategy_stats(self, strategy: str, success: bool) -> None:
        """更新策略统计并写入文件。

        Args:
            strategy: 策略名（bar/auth_check/gateway/legacy）
            success: 是否成功
        """
        if strategy not in self._strategy_stats:
            self._strategy_stats[strategy] = {"success": 0, "fail": 0}
        if success:
            self._strategy_stats[strategy]["success"] += 1
        else:
            self._strategy_stats[strategy]["fail"] += 1

        if self._strategy_stats_path is not None:
            try:
                self._strategy_stats_path.write_text(
                    json.dumps(self._strategy_stats, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

    def export_error_log_md(self, output_path: Optional[str] = None) -> str:
        """Export all errors as a markdown log file."""
        if output_path is None:
            output_path = str(self.output_dir / f"error_log_{datetime.now():%Y%m%d_%H%M%S}.md")

        lines = [
            "# CNKI Hybrid Scraper — Error Log",
            "",
            f"**Generated**: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"**Total papers attempted**: {self._stats['total_attempted']}",
            f"**Detail page success**: {self._stats['detail_success']}/{self._stats['total_attempted']}",
            f"**PDF download success**: {self._stats['pdf_success']}",
            f"**PDF download failed**: {self._stats['pdf_failed']}",
            f"**Body text extracted**: {self._stats['body_text_success']}",
            f"**Body text failed**: {self._stats['body_text_failed']}",
            f"**CNKI 418 blocks detected**: {self._stats.get('cnki_blocks_detected', 0)}",
            f"**Proxy switches (CNKI)**: {self._stats.get('proxy_switches', 0)}",
            f"**Total errors**: {len(self.error_log)}",
            "",
            "---",
            "",
            "## CNKI Block Status",
            "",
        ]

        # CNKI 封锁状态报告
        block_status = self.get_cnki_block_status()
        if block_status["blocked_proxies"]:
            lines.append(f"**Blocked proxies**: {block_status['blocked_count']}")
            for proxy in block_status["blocked_proxies"]:
                remaining = block_status["cooldown_remaining"].get(proxy, 0)
                hours = remaining / 3600
                lines.append(f"  - `{proxy}` — cooldown remaining: {remaining:.0f}s ({hours:.1f}h)")
        else:
            lines.append("**Blocked proxies**: None")
        lines.append(f"**Available proxies**: {block_status['available_proxies']}")
        lines.append(f"**Current proxy**: `{block_status['current_proxy'] or 'None'}`")
        lines.extend([
            "",
            "---",
            "",
            "## Error Summary by Type",
            "",
        ])

        # Group errors by type
        from collections import Counter
        type_counts = Counter(e["type"] for e in self.error_log)
        for etype, count in type_counts.most_common():
            lines.append(f"- **{etype}**: {count} occurrences")

        lines.extend([
            "",
            "---",
            "",
            "## Detailed Error Log",
            "",
        ])

        # Detailed log
        if not self.error_log:
            lines.append("✅ **No errors recorded!**")
        else:
            lines.append("| # | Time | Type | Message | Context |")
            lines.append("|---|------|------|---------|---------|")
            for i, entry in enumerate(self.error_log, 1):
                context_str = ", ".join(
                    f"{k}={str(v)[:80]}"
                    for k, v in entry.items()
                    if k not in ("timestamp", "type", "message")
                )
                lines.append(
                    f"| {i} | {entry['timestamp'][:19]} | "
                    f"`{entry['type']}` | {entry['message'][:200]} | "
                    f"{context_str[:200]} |"
                )

        md_content = "\n".join(lines)
        Path(output_path).write_text(md_content, encoding="utf-8")
        return md_content

    def export_results_summary(self, papers: list[FullPaperData]) -> str:
        """Export harvest results summary as markdown."""
        path = str(self.output_dir / f"harvest_summary_{datetime.now():%Y%m%d_%H%M%S}.md")

        lines = [
            "# CNKI Paper Harvest Results",
            "",
            f"**Date**: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"**Papers harvested**: {len(papers)}",
            "",
            "---",
            "",
            "## Field Completeness",
            "",
        ]

        # Calculate field completion stats
        fields = ["title", "authors", "year", "journal_name", "abstract",
                   "keywords", "doi", "body_text", "pdf_order_url"]
        for field in fields:
            count = sum(1 for p in papers if getattr(p, field, None))
            pct = count * 100 // max(len(papers), 1)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            lines.append(f"- **{field:16s}** {bar} {count}/{len(papers)} ({pct}%)")

        lines.extend([
            "",
            "---",
            "",
            "## Individual Papers",
            "",
        ])

        for i, paper in enumerate(papers, 1):
            lines.extend([
                f"### Paper {i}: {paper.title[:100]}",
                "",
                f"| Field | Value |",
                f"|-------|-------|",
                f"| Title | {paper.title[:200]} |",
                f"| Authors | {', '.join(paper.authors[:5])} |",
                f"| Year | {paper.year} |",
                f"| Journal | {paper.journal_name} |",
                f"| DOI | {paper.doi} |",
                f"| Citations | {paper.citations} |",
                f"| Core Journal | {paper.is_core} |",
                f"| Keywords | {', '.join(paper.keywords[:8])} |",
                f"| Abstract Length | {len(paper.abstract)} chars |",
                f"| Body Text Length | {paper.body_text_length} chars ({len(paper.body_text.split())} words) |",
                f"| File Format | {paper.file_format} |",
                f"| File Size | {paper.file_size} bytes |",
                f"| Download Success | {paper.download_success} |",
            ])
            if paper.errors:
                lines.append(f"| Errors | {', '.join(paper.errors[:3])} |")
            lines.append("")
            if paper.body_text:
                lines.append(f"**Body Text Preview** (first 300 chars):")
                lines.append(f"> {paper.body_text[:300]}...")
                lines.append("")

        md_content = "\n".join(lines)
        Path(path).write_text(md_content, encoding="utf-8")
        return md_content

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "total_errors": len(self.error_log),
            "cnki_blocked_proxies": self._block_tracker.blocked_proxies(),
        }

    def get_cnki_block_status(self) -> dict:
        """获取 CNKI 封锁状态报告。

        Returns:
            包含被封锁代理列表、剩余冷却时间等信息的字典
        """
        blocked = self._block_tracker.blocked_proxies()
        return {
            "blocked_proxies": blocked,
            "blocked_count": len(blocked),
            "available_proxies": (
                self._proxy_pool.available_count() if self._proxy_pool else 0
            ),
            "current_proxy": self._current_proxy,
            "current_proxy_blocked": (
                self._block_tracker.is_blocked(self._current_proxy)
                if self._current_proxy else False
            ),
            "cooldown_remaining": {
                proxy: self._block_tracker.cooldown_remaining(proxy)
                for proxy in blocked
            },
        }

    # ── Cookie Management ──────────────────────────────────────

    @staticmethod
    def load_cookies_from_file(cookies_path: str = "cookies.json") -> dict[str, str]:
        """Load CNKI cookies from a JSON configuration file.

        The JSON file should have a "cookies" key containing a dict of name→value pairs.
        """
        path = Path(cookies_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Cookies file not found: {path.resolve()}\n"
                f"Create cookies.json with your CNKI cookies (see cookies.json.example)"
            )

        data = json.loads(path.read_text("utf-8"))
        cookies = data.get("cookies", {})
        if not cookies:
            raise ValueError("No cookies found in cookies.json (need 'cookies' key)")

        return cookies

    @staticmethod
    def check_cookie_expiry(cookies: dict[str, str]) -> dict:
        """检查 CNKI cookies 的有效性。

        真正的认证 cookie 是 LID、Ecp_ClientId、Ecp_LoginStuts，
        这些通常有效期 7-30 天。c_m_expire 只是会话字段过期时间（约 2 小时），
        不代表真正的认证 cookie 过期。

        Returns dict with:
          - is_expired: bool
          - expires_in_hours: float (negative if expired)
          - warning: str or None
        """
        # 检查关键认证 cookie 是否存在
        auth_cookies = ["LID", "Ecp_ClientId", "Ecp_LoginStuts"]
        missing = [c for c in auth_cookies if c not in cookies or not cookies[c]]
        if missing:
            return {
                "is_expired": True,
                "expires_in_hours": None,
                "warning": f"缺少关键认证 cookie: {missing}，请重新导出 cookies。",
            }

        # c_m_expire 只是会话字段，不代表真正的认证 cookie 过期
        # 只有当 c_m_expire 存在且所有关键 cookie 都缺失时才认为过期
        expire_str = cookies.get("c_m_expire", "")
        if not expire_str:
            return {
                "is_expired": False,
                "expires_in_hours": None,
                "warning": None,
            }

        try:
            from urllib.parse import unquote
            expire_clean = unquote(expire_str).strip()
            if not expire_clean:
                return {
                    "is_expired": False,
                    "expires_in_hours": None,
                    "warning": None,
                }
            expire_dt = datetime.strptime(expire_clean, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            delta = expire_dt - now
            hours = delta.total_seconds() / 3600

            # c_m_expire 过期不等于认证 cookie 过期
            # 只有当关键认证 cookie 也失效时才认为真正过期
            if hours < 0:
                return {
                    "is_expired": False,  # 关键认证 cookie 仍可能有效
                    "expires_in_hours": round(hours, 1),
                    "warning": f"会话字段 c_m_expire 已过期 {abs(round(hours, 1))} 小时，但认证 cookie 可能仍有效。",
                }
            elif hours < 2:
                return {
                    "is_expired": False,
                    "expires_in_hours": round(hours, 1),
                    "warning": f"会话字段 c_m_expire 将在 {round(hours, 1)} 小时后过期。",
                }
            else:
                return {
                    "is_expired": False,
                    "expires_in_hours": round(hours, 1),
                    "warning": None,
                }
        except Exception:
            return {"is_expired": False, "expires_in_hours": None, "warning": None}

    # ── Download List Generation ───────────────────────────────

    def generate_download_html(
        self, papers: list[FullPaperData], output_path: Optional[str] = None
    ) -> str:
        """Generate a browser-friendly HTML download page.

        Creates an HTML file with a table of papers and one-click download buttons
        that open the CNKI download order page in a new tab.

        Returns the file path.
        """
        if output_path is None:
            output_path = str(self.output_dir / f"download_list_{datetime.now():%Y%m%d_%H%M%S}.html")

        rows_html = ""
        for i, paper in enumerate(papers, 1):
            download_url = paper.pdf_order_url or paper.caj_order_url or paper.auth_check_url or paper.cnki_url
            rows_html += f"""
            <tr>
                <td class="num">{i}</td>
                <td class="title">
                    <div class="title-text">{paper.title}</div>
                    <div class="meta">
                        {", ".join(paper.authors[:3])} | {paper.journal_name} | {paper.year} | DOI: {paper.doi}
                    </div>
                </td>
                <td class="action">
                    <a href="{download_url}" target="_blank" class="btn-download" onclick="markDownloaded(this, {i})">
                        PDF下载
                    </a>
                </td>
                <td class="status" id="status-{i}">等待下载</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CNKI 论文下载列表 — {datetime.now():%Y-%m-%d}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f5f5f5; color: #333; }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
    h1 {{ font-size: 24px; margin-bottom: 8px; }}
    .info {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
    .info span {{ background: #e3f2fd; padding: 2px 8px; border-radius: 3px; }}
    .stats {{ display: flex; gap: 20px; margin-bottom: 20px; }}
    .stat {{ background: white; padding: 12px 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
    .stat .num {{ font-size: 28px; font-weight: bold; color: #1976d2; }}
    .stat .label {{ font-size: 12px; color: #999; margin-top: 4px; }}
    table {{ width: 100%; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    th {{ background: #1976d2; color: white; padding: 10px 15px; text-align: left; font-size: 13px; }}
    td {{ padding: 12px 15px; border-bottom: 1px solid #eee; font-size: 14px; }}
    tr:last-child td {{ border-bottom: none; }}
    .num {{ width: 40px; color: #999; text-align: center; }}
    .title-text {{ font-weight: 500; margin-bottom: 4px; }}
    .meta {{ font-size: 12px; color: #888; }}
    .action {{ width: 100px; text-align: center; }}
    .btn-download {{ display: inline-block; padding: 6px 16px; background: #1976d2; color: white; text-decoration: none; border-radius: 4px; font-size: 13px; }}
    .btn-download:hover {{ background: #1565c0; }}
    .btn-download.done {{ background: #4caf50; }}
    .status {{ width: 80px; font-size: 12px; color: #999; text-align: center; }}
    .status.done {{ color: #4caf50; }}
    .tip {{ background: #fff3e0; border: 1px solid #ff9800; padding: 12px 20px; border-radius: 8px; margin-top: 20px; font-size: 13px; }}
</style>
</head>
<body>
<div class="container">
    <h1>CNKI 论文下载列表</h1>
    <div class="info">
        生成时间: {datetime.now():%Y-%m-%d %H:%M} |
        期刊: {papers[0].journal_name if papers else 'N/A'} |
        共 <span>{len(papers)}</span> 篇论文
    </div>

    <div class="stats">
        <div class="stat">
            <div class="num" id="total">{len(papers)}</div>
            <div class="label">总计</div>
        </div>
        <div class="stat">
            <div class="num" id="downloaded">0</div>
            <div class="label">已下载</div>
        </div>
        <div class="stat">
            <div class="num" id="remaining">{len(papers)}</div>
            <div class="label">剩余</div>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>论文信息</th>
                <th>下载</th>
                <th>状态</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <div class="tip">
        <strong>使用说明：</strong>
        1. 点击「PDF下载」按钮，在弹出的新标签页中等待下载自动开始<br>
        2. 下载完成后，将 PDF 文件放入 <code>downloads/pdf/</code> 目录<br>
        3. 关闭下载完成的标签页，继续点击下一篇<br>
        4. <strong>建议安装 CNKI Auto-Download 浏览器扩展</strong> 来自动触发下载<br>
        5. 全部下载完成后，运行 <code>python run_full_pipeline.py --extract-only</code> 提取正文
    </div>
</div>

<script>
let downloaded = 0;
function markDownloaded(btn, id) {{
    btn.classList.add('done');
    btn.textContent = '已下载';
    const status = document.getElementById('status-' + id);
    status.textContent = '已下载';
    status.classList.add('done');
    downloaded++;
    document.getElementById('downloaded').textContent = downloaded;
    document.getElementById('remaining').textContent = {len(papers)} - downloaded;
}}
</script>
</body>
</html>"""

        Path(output_path).write_text(html, encoding="utf-8")
        print(f"Download list HTML saved: {output_path}")
        return output_path

    def generate_download_bat(
        self, papers: list[FullPaperData], output_path: Optional[str] = None
    ) -> str:
        """Generate a Windows batch file that opens download URLs in the default browser.

        Each URL is opened with a delay to avoid overwhelming the browser.
        """
        if output_path is None:
            output_path = str(self.output_dir / f"download_{datetime.now():%Y%m%d_%H%M%S}.bat")

        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "echo ==============================================",
            "echo  CNKI Paper Downloader",
            "echo  Total papers: " + str(len(papers)),
            "echo  Each paper will open in a new browser tab",
            "echo  Press Ctrl+C to cancel at any time",
            "echo ==============================================",
            "echo.",
        ]

        for i, paper in enumerate(papers, 1):
            url = paper.pdf_order_url or paper.caj_order_url or paper.cnki_url
            title = paper.title[:60]
            lines.append(f"echo [{i}/{len(papers)}] {title}")
            lines.append(f'start "" "{url}"')
            lines.append("timeout /t 3 /nobreak >nul")
            lines.append("echo.")

        lines.append("echo All downloads opened!")
        lines.append("pause")

        bat_content = "\n".join(lines)
        Path(output_path).write_text(bat_content, encoding="utf-8")
        print(f"Download batch file saved: {output_path}")
        return output_path


# ── Built-in Test ──────────────────────────────────────────────

async def run_test():
    """Run end-to-end hybrid scraper test and save results."""
    print("=" * 70)
    print("CNKI Hybrid Scraper — End-to-End Test")
    print("=" * 70)

    # Load cookies from external config file
    try:
        COOKIES = CNKIHybridScraper.load_cookies_from_file("cookies.json")
        print("[0] Cookies loaded from cookies.json")
    except FileNotFoundError:
        print("[0] cookies.json not found, using fallback cookies")
        COOKIES = {
            "_c_WBKFRo": "vx7kYIApPT34yebAB2MBy5vLlRPtOf0EKg8vA1ME",
            "cnkiUserKey": "491cb460-3573-3ad7-a2d7-b2af30c2634f",
            "Ecp_loginuserbk": "dx0741",
            "Ecp_loginuserjf": "dx0741",
            "Ecp_ClientId": "e78899f8ed56aab5b3373cc6276273240VN81Etde6",
            "SID": "zhuye091002",
            "Ecp_session": "1",
            "Ecp_notFirstLogin": "Ly4MHj",
        }

    # Check cookie expiry
    expiry = CNKIHybridScraper.check_cookie_expiry(COOKIES)
    if expiry["warning"]:
        print(f"[!] {expiry['warning']}")
    if expiry["is_expired"]:
        print("[!] WARNING: Cookies are EXPIRED! PDF downloads will likely fail.")
        print("[!] Please update cookies.json with fresh values from your browser.")
        print()

    scraper = CNKIHybridScraper(
        cookies=COOKIES,
        output_dir="../数据库/cnki/hybrid",
        browser_fallback=True,  # Task 9: 启用浏览器自动化降级
    )

    print("[1] Phase 1: RSS discovery + metadata extraction for 国际新闻界...")
    print()

    try:
        papers = await scraper.harvest_paper(
            journal_code="GJXW",
            journal_name="国际新闻界",
            discipline="新闻传播学",
            max_papers=3,
            download_pdfs=True,  # 启用 PDF 下载（已实现 4 策略 + 重试机制）
        )

        pdf_count = sum(1 for p in papers if p.download_success)
        print(f"\n[2] Harvested {len(papers)} papers (PDF downloaded: {pdf_count})")

        # Print field completeness
        if papers:
            print("\n[3] Field completeness per paper:")
            for p in papers:
                fields = {
                    "title": bool(p.title),
                    "authors": bool(p.authors),
                    "year": p.year > 0,
                    "journal": bool(p.journal_name),
                    "abstract": bool(p.abstract),
                    "keywords": bool(p.keywords),
                    "doi": bool(p.doi),
                }
                present = sum(fields.values())
                total = len(fields)
                status = "FULL" if present == total else f"PARTIAL({present}/{total})"
                print(f"  [{status:12s}] {(p.title or '(no title)')[:60]}...")
                if p.errors:
                    for e in p.errors[:2]:
                        print(f"                   E: {e[:100]}")

        # Generate download resources
        if papers:
            print(f"\n[4] Generating download resources...")
            html_path = scraper.generate_download_html(papers)
            bat_path = scraper.generate_download_bat(papers)

            # Save detailed markdown report
            scraper.export_results_summary(papers)

            print(f"\n[5] Download resources ready:")
            print(f"    HTML download page: {html_path}")
            print(f"    Batch script:       {bat_path}")
            print(f"\n[6] Next steps for the user:")
            print(f"    1. Open the HTML file in your browser")
            print(f"    2. Click 'PDF下载' for each paper")
            print(f"    3. Save PDFs to downloads/pdf/ directory")
            print(f"    4. Run: python run_full_pipeline.py --extract")

    except Exception as e:
        traceback.print_exc()
        print(f"\nFATAL: {e}")

    finally:
        # Export error log
        log_content = scraper.export_error_log_md()
        print(f"\n[7] Error log saved ({len(scraper.error_log)} entries)")
        print(f"Stats: {json.dumps(scraper.stats, ensure_ascii=False, indent=2)}")

        await scraper.close()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(run_test())
