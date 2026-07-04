"""CNKI 爬虫代理池 — 支持轮询、健康检查、失败计数、IP 类型检测与质量评分。

从 proxies.json 加载代理列表，按质量评分排序轮询取下一个可用代理，
跳过 fail_count >= 3 的代理；支持用 curl_cffi 对 cnki.net 做健康检查，
并检测 418 状态码（CNKI 封锁）。支持抓取免费代理、IP 类型识别（住宅/数据中心）。

JSON 格式：
    {
      "proxies": [
        {"url": "http://ip:port", "enabled": true, "fail_count": 0,
         "note": "...", "source": "free", "ip_type": "residential",
         "cnki_status": "cnki_ok"}
      ]
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from curl_cffi.requests import Session


class ProxyPool:
    """代理池：加载、轮询、健康检查、失败标记、IP 类型检测、质量评分。

    所有方法均为同步实现（health_check 使用同步 curl_cffi Session），
    以便在异步 scraper 中按需调用。
    """

    #: 失败次数达到该阈值后跳过该代理
    MAX_FAIL_COUNT: int = 3

    #: CNKI 健康检查目标 URL
    CNKI_TEST_URL: str = "https://www.cnki.net/"

    #: ip-api 查询模板（免费层仅支持 http）
    IP_API_URL: str = "http://ip-api.com/json/{ip}?fields=country,isp,org,as,proxy,hosting"

    #: curl_cffi 浏览器指纹
    IMPERSONATE: str = "chrome124"

    def __init__(self) -> None:
        self._proxies: list[dict] = []
        self._cursor: int = 0
        #: IP 类型检测缓存：ip -> ip_type，避免重复调用 ip-api
        self._ip_type_cache: dict[str, str] = {}

    # ── 加载 / 保存 ──────────────────────────────────────────

    def load(self, path: str | Path) -> int:
        """从 JSON 文件加载代理列表。

        Args:
            path: proxies.json 路径

        Returns:
            加载的代理数量（enabled=True 的）
        """
        p = Path(path)
        if not p.exists():
            self._proxies = []
            return 0

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._proxies = []
            return 0

        raw_list = data.get("proxies", []) if isinstance(data, dict) else []
        # 规范化字段，确保 enabled/fail_count 存在；保留新增字段（向后兼容）
        self._proxies = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            self._proxies.append({
                "url": url,
                "enabled": bool(item.get("enabled", True)),
                "fail_count": int(item.get("fail_count", 0)),
                "note": item.get("note", ""),
                # 新增字段（缺失时为默认值，兼容旧版 proxies.json）
                "source": item.get("source", ""),
                "ip_type": item.get("ip_type", "unknown"),
                "cnki_status": item.get("cnki_status", ""),
            })
        self._cursor = 0
        return len(self._proxies)

    def save(self, path: str | Path) -> int:
        """将当前代理列表保存到 JSON 文件。

        Args:
            path: proxies.json 路径

        Returns:
            保存的代理数量
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"proxies": self._proxies}
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(self._proxies)

    # ── 轮询取下一个可用代理 ────────────────────────────────────

    def next(self) -> Optional[str]:
        """返回下一个可用代理 URL（按质量评分排序轮询）。

        排序规则：按 score_proxy 降序；评分相同时保持稳定顺序。
        跳过：disabled、fail_count >= 阈值、cnki_status="cnki_blocked"。

        Returns:
            代理 URL 字符串，无可用代理时返回 None
        """
        return self._next_filtered(cnki_only=False)

    def next_for_cnki(self) -> Optional[str]:
        """返回下一个 CNKI 可用代理 URL（仅返回 cnki_status="cnki_ok" 的代理）。

        若没有已验证为 cnki_ok 的代理，则退化为普通 next() 行为，
        以便在尚未做健康检查时仍可返回候选代理。

        Returns:
            代理 URL 字符串，无可用代理时返回 None
        """
        return self._next_filtered(cnki_only=True)

    def _next_filtered(self, cnki_only: bool) -> Optional[str]:
        """内部轮询：按评分排序后跳过不可用代理，round-robin 返回。

        Args:
            cnki_only: True 表示仅返回 cnki_ok 的代理（无则回退普通模式）
        """
        if not self._proxies:
            return None

        # 按评分降序构建候选列表（评分高者优先）
        ranked = sorted(
            self._proxies,
            key=lambda p: self.score_proxy(p),
            reverse=True,
        )

        def usable(p: dict) -> bool:
            if not p.get("enabled", True):
                return False
            if p.get("fail_count", 0) >= self.MAX_FAIL_COUNT:
                return False
            # CNKI 爬虫场景下跳过被封锁的代理
            if p.get("cnki_status") == "cnki_blocked":
                return False
            return True

        candidates = [p for p in ranked if usable(p)]

        # CNKI 专用模式：优先仅返回 cnki_ok 的代理
        if cnki_only:
            strict = [p for p in candidates if p.get("cnki_status") == "cnki_ok"]
            if strict:
                candidates = strict
            # 无 cnki_ok 代理时回退到普通候选（可能为空）

        if not candidates:
            return None

        # round-robin 游标在候选列表上轮转
        idx = self._cursor % len(candidates)
        self._cursor = (self._cursor + 1) % len(candidates)
        return candidates[idx]["url"]

    # ── 健康检查 ───────────────────────────────────────────────

    def health_check(self, test_url: str = "https://www.cnki.net/") -> dict[str, bool]:
        """用 curl_cffi 测试每个代理是否可访问 CNKI。

        检测 418 状态码（CNKI 封锁），并写入 cnki_status 字段：
        - "cnki_ok"     : HTTP 200
        - "cnki_blocked": HTTP 418
        - "cnki_error"  : 其他状态码或异常

        Args:
            test_url: 测试目标 URL，默认 CNKI 首页

        Returns:
            dict[proxy_url, bool] — 代理 URL → 是否可达（200）
        """
        results: dict[str, bool] = {}
        for proxy in self._proxies:
            if not proxy.get("enabled", True):
                results[proxy["url"]] = False
                proxy["cnki_status"] = "cnki_error"
                continue
            status, ok = self._probe_cnki(proxy["url"], test_url)
            # 分类 CNKI 状态
            if ok:
                proxy["cnki_status"] = "cnki_ok"
            elif status == 418:
                proxy["cnki_status"] = "cnki_blocked"
            else:
                proxy["cnki_status"] = "cnki_error"
            results[proxy["url"]] = ok
            # 健康检查失败时累加 fail_count
            if not ok:
                proxy["fail_count"] = int(proxy.get("fail_count", 0)) + 1
        return results

    @staticmethod
    def _probe(proxy_url: str, test_url: str, timeout: int = 10) -> bool:
        """单代理探测：返回 True 表示可达且非 418（向后兼容）。"""
        _, ok = ProxyPool._probe_cnki(proxy_url, test_url, timeout)
        return ok

    @staticmethod
    def _probe_cnki(proxy_url: str, test_url: str, timeout: int = 10) -> tuple[int, bool]:
        """单代理探测 CNKI：返回 (status_code, is_ok)。

        is_ok 仅在 status_code == 200 时为 True；异常时返回 (0, False)。
        使用 chrome124 指纹绕过 TLS 指纹检测。
        """
        try:
            with Session(
                impersonate=ProxyPool.IMPERSONATE,
                timeout=timeout,
                verify=False,
                proxy=proxy_url,
            ) as s:
                resp = s.get(test_url)
                status = resp.status_code
                return (status, status == 200)
        except Exception:
            return (0, False)

    # ── IP 类型检测 ───────────────────────────────────────────

    def detect_ip_type(self, proxy_url: str) -> str:
        """检测代理 IP 类型（residential / datacenter / unknown）。

        通过 ip-api.com 查询 IP 是否属于托管/数据中心，结果缓存以避免重复调用。
        同时更新代理池中对应代理 dict 的 ip_type 字段。

        Args:
            proxy_url: 代理 URL（如 http://ip:port）

        Returns:
            "residential" : 非托管 IP（家庭/ISP，可访问 CNKI）
            "datacenter"  : 托管/数据中心 IP（通常被 CNKI 封锁）
            "unknown"     : 查询失败或无法解析 IP
        """
        ip = self._extract_ip(proxy_url)
        if not ip:
            return "unknown"

        # 命中缓存
        if ip in self._ip_type_cache:
            ip_type = self._ip_type_cache[ip]
        else:
            ip_type = self._query_ip_type(ip)
            self._ip_type_cache[ip] = ip_type

        # 同步更新代理 dict 的 ip_type 字段
        for proxy in self._proxies:
            if proxy.get("url") == proxy_url:
                proxy["ip_type"] = ip_type
                break
        return ip_type

    @staticmethod
    def _extract_ip(proxy_url: str) -> Optional[str]:
        """从代理 URL 中提取 IP 地址（去除 scheme 与端口）。"""
        if not proxy_url:
            return None
        parsed = urlparse(proxy_url)
        # hostname 已去除端口和 scheme
        return parsed.hostname or None

    @staticmethod
    def _query_ip_type(ip: str) -> str:
        """调用 ip-api.com 查询单个 IP 的类型。"""
        url = ProxyPool.IP_API_URL.format(ip=ip)
        try:
            with Session(
                impersonate=ProxyPool.IMPERSONATE,
                timeout=10,
                verify=False,
            ) as s:
                resp = s.get(url)
                if resp.status_code != 200:
                    return "unknown"
                data = resp.json()
                if not isinstance(data, dict):
                    return "unknown"
                hosting = data.get("hosting")
                if hosting is None:
                    return "unknown"
                return "datacenter" if bool(hosting) else "residential"
        except Exception:
            return "unknown"

    # ── 代理质量评分 ─────────────────────────────────────────

    def score_proxy(self, proxy: dict) -> int:
        """计算代理质量评分（0-100，越高越优）。

        评分规则：
        - +40 if ip_type="residential"
        - +20 if ip_type="datacenter"（非 CNKI 场景仍可用）
        - +30 if cnki_status="cnki_ok"
        - -50 if cnki_status="cnki_blocked"
        - +10 if fail_count=0
        - -5  per fail_count

        Args:
            proxy: 代理 dict

        Returns:
            质量评分（int）
        """
        score = 0
        ip_type = proxy.get("ip_type", "unknown")
        if ip_type == "residential":
            score += 40
        elif ip_type == "datacenter":
            score += 20

        cnki_status = proxy.get("cnki_status", "")
        if cnki_status == "cnki_ok":
            score += 30
        elif cnki_status == "cnki_blocked":
            score -= 50

        fail_count = int(proxy.get("fail_count", 0))
        if fail_count == 0:
            score += 10
        else:
            score -= 5 * fail_count

        return score

    # ── 失败标记 ───────────────────────────────────────────────

    def mark_failed(self, proxy: str) -> None:
        """标记指定代理失败一次（fail_count +1）。

        Args:
            proxy: 代理 URL 字符串
        """
        for item in self._proxies:
            if item.get("url") == proxy:
                item["fail_count"] = int(item.get("fail_count", 0)) + 1
                return

    def mark_cnki_blocked(self, proxy: str) -> None:
        """标记指定代理被 CNKI 封锁（设置 cnki_status="cnki_blocked"）。

        与 mark_failed 不同，本方法专门用于 CNKI 418 拦截场景，
        设置 cnki_status 字段使 next_for_cnki() 跳过该代理。

        Args:
            proxy: 代理 URL 字符串
        """
        for item in self._proxies:
            if item.get("url") == proxy:
                item["cnki_status"] = "cnki_blocked"
                return

    # ── 免费代理自动刷新 ───────────────────────────────────────

    def refresh_free_proxies(self, save_path: Optional[str | Path] = None) -> int:
        """抓取免费代理并合并到当前代理池。

        流程：
        1. 调用 FreeProxyFetcher 抓取新代理
        2. 与现有代理按 URL 去重合并
        3. 对新增代理运行 CNKI 健康检查（写入 cnki_status）
        4. 可选保存到 proxies.json

        Args:
            save_path: 保存路径；为 None 时不保存

        Returns:
            新增的代理数量
        """
        # 延迟导入，避免循环依赖
        from crawler.free_proxy_fetcher import FreeProxyFetcher

        fetcher = FreeProxyFetcher()
        new_proxies = fetcher.fetch_all()

        existing_urls = {p.get("url") for p in self._proxies}
        added = 0
        for item in new_proxies:
            if item["url"] in existing_urls:
                continue
            self._proxies.append(item)
            existing_urls.add(item["url"])
            added += 1

        # 对新增代理运行健康检查（仅检查新加的，避免重复探测已有代理）
        if added > 0:
            new_urls = {p["url"] for p in new_proxies}
            for proxy in self._proxies:
                if proxy.get("url") not in new_urls:
                    continue
                if not proxy.get("enabled", True):
                    proxy["cnki_status"] = "cnki_error"
                    continue
                status, ok = self._probe_cnki(proxy["url"], self.CNKI_TEST_URL)
                if ok:
                    proxy["cnki_status"] = "cnki_ok"
                elif status == 418:
                    proxy["cnki_status"] = "cnki_blocked"
                else:
                    proxy["cnki_status"] = "cnki_error"
                if not ok:
                    proxy["fail_count"] = int(proxy.get("fail_count", 0)) + 1

        # 保存更新后的列表
        if save_path is not None:
            self.save(save_path)

        return added

    # ── 辅助 ───────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._proxies)

    def available_count(self) -> int:
        """返回当前可用代理数量（enabled 且 fail_count < 阈值）。"""
        return sum(
            1 for p in self._proxies
            if p.get("enabled", True) and p.get("fail_count", 0) < self.MAX_FAIL_COUNT
        )

    def all_proxies(self) -> list[dict]:
        """返回代理列表的浅拷贝。"""
        return list(self._proxies)
