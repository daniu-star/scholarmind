"""免费代理抓取器 — 从多个公开源抓取免费代理 IP。

支持的源（均返回纯文本，每行一个 ip:port）：
- ProxyScrape API (https://api.proxyscrape.com/v2/)
- Proxy-List-Download API (https://www.proxy-list.download/api/v1/)

使用 curl_cffi 以 chrome124 指纹请求，避免被源站识别为爬虫。

返回格式：list[dict]，每个 dict 形如：
    {"url": "http://ip:port", "enabled": True, "fail_count": 0,
     "source": "free", "ip_type": "unknown"}
"""
from __future__ import annotations

from typing import Optional

from curl_cffi.requests import Session


class FreeProxyFetcher:
    """免费代理抓取器：从公开 API 抓取代理列表并合并去重。"""

    #: 公开代理源（返回纯文本，每行一个 ip:port）
    #: 包含 API 源与 GitHub raw 备用源（API 源常不稳定，GitHub 源更可靠）
    SOURCES: list[str] = [
        # API 源（可能不稳定）
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http"
        "&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=https"
        "&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://www.proxy-list.download/api/v1/get?type=https",
        "https://www.proxy-list.download/api/v1/get?type=http",
        # GitHub raw 备用源（更稳定，由社区维护）
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/https.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ]

    #: 单源请求超时（秒）
    TIMEOUT: int = 15

    def __init__(self, impersonate: str = "chrome124") -> None:
        self._impersonate = impersonate

    # ── 抓取全部源并合并 ─────────────────────────────────────

    def fetch_all(self) -> list[dict]:
        """从所有源抓取代理并按 URL 去重合并。

        Returns:
            代理 dict 列表，每个形如：
            {"url": "http://ip:port", "enabled": True, "fail_count": 0,
             "source": "free", "ip_type": "unknown"}
        """
        seen: set[str] = set()
        proxies: list[dict] = []
        for source in self.SOURCES:
            for line in self._fetch_source(source):
                url = self._normalize(line)
                if not url or url in seen:
                    continue
                seen.add(url)
                proxies.append({
                    "url": url,
                    "enabled": True,
                    "fail_count": 0,
                    "source": "free",
                    "ip_type": "unknown",
                })
        return proxies

    # ── 单源抓取 ─────────────────────────────────────────────

    def _fetch_source(self, url: str) -> list[str]:
        """抓取单个源，返回按行切分的列表。

        使用 curl_cffi chrome124 指纹请求；失败时返回空列表。
        """
        try:
            with Session(
                impersonate=self._impersonate,
                timeout=self.TIMEOUT,
                verify=False,
            ) as s:
                resp = s.get(url)
                if resp.status_code != 200:
                    return []
                text = resp.text or ""
                return text.splitlines()
        except Exception:
            return []

    # ── 规范化 ───────────────────────────────────────────────

    @staticmethod
    def _normalize(line: str) -> Optional[str]:
        """将一行 ip:port 规范化为 http://ip:port 形式。

        - 已带 scheme（http:// https:// socks5:// 等）则原样返回
        - 形如 ip:port 则补 http:// 前缀
        - 非法格式返回 None
        """
        line = line.strip()
        if not line:
            return None
        # 已带 scheme
        if "://" in line:
            return line
        # 形如 ip:port，简单校验端口为数字
        host, _, port = line.rpartition(":")
        if not host or not port.isdigit():
            return None
        return f"http://{line}"
