"""CNKI 浏览器自动化 PDF 下载模块（重构版）。

CNKI 已将 PDF 下载流程从直接 HTTP 下载改为：
  1. bar.cnki.net → 返回 Vue.js SPA 在线阅读器页面（kns.cnki.net/reader/read）
  2. x.cnki.net → 返回 JS 中转页面（"知网研学 - 中转中..."）
  3. gateway.cnki.net → 已废弃，重定向到 x.cnki.net
  4. legacy kcms/detail → 触发验证码

纯 HTTP 客户端（curl_cffi）无法处理 JS 中转和 SPA 渲染，
因此本模块使用 Playwright 浏览器自动化作为主要下载方式。

设计要点：
  - 延迟导入 Playwright：仅在首次调用 download_pdf() 时导入
  - headless=True：批量运行时避免窗口卡死
  - 只点击 #pdfDown 按钮：用户要求只下载 PDF，不下载 CAJ/KDH
  - 文件魔数严格验证：只接受 %PDF-，拒绝 KDH/CAJ 并删除
  - 代理支持：通过 launch(proxy=...) 参数
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional


class BrowserFallback:
    """使用 Playwright 浏览器自动化下载 CNKI PDF。

    重构版支持 CNKI 新下载流程：
      - 在线阅读器 SPA 页面（bar.cnki.net → kns.cnki.net/reader/read）
      - JS 中转认证页面（x.cnki.net auth-check）
      - 多种下载按钮检测策略
    """

    # PDF 下载按钮候选选择器（按优先级排序）
    # CNKI 详情页的下载按钮有多种形态：
    #   - <a id="pdfDown"> / <a class="btn-dlpdf">
    #   - <a href="...download..."> 
    #   - <button class="btn-download">
    DOWNLOAD_SELECTORS: list[str] = [
        '#pdfDown',
        'a.btn-dlpdf',
        'a[href*="download"]',
        '.btn-download',
        'a[class*="download"]',
        'button[class*="download"]',
        'a[href*="bar.cnki.net"]',
    ]

    # 下载按钮文本匹配模式（CNKI 按钮可能没有 href，只有文本）
    DOWNLOAD_TEXT_PATTERNS: list[str] = [
        "PDF下载", "PDF 下载", "pdf下载",
        "下载全文", "全文下载",
        "CAJ下载", "CAJ 下载",
        "下载", "download",
    ]

    # 下载超时（秒）
    DOWNLOAD_TIMEOUT: float = 90.0

    # 页面加载超时（毫秒）
    # CNKI EdgeOne CDN 在速率限制时会变慢，需要更长超时
    PAGE_LOAD_TIMEOUT: int = 60_000

    # JS 中转等待超时（秒）：x.cnki.net 中转页面需要 JS 执行后跳转
    JS_REDIRECT_TIMEOUT: float = 15.0

    # SPA 渲染等待超时（秒）：在线阅读器需要 Vue.js 渲染
    SPA_RENDER_TIMEOUT: float = 10.0

    def __init__(
        self,
        cookies: dict,
        output_dir: str = "../数据库/cnki/hybrid/pdfs",
    ):
        """初始化浏览器降级下载器。

        Args:
            cookies: CNKI cookies 字典（name → value）
            output_dir: PDF 文件保存目录
        """
        self.cookies = cookies
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def download_pdf(
        self,
        paper_url: str,
        filename: str = "",
        proxy_url: Optional[str] = None,
    ) -> dict:
        """使用 Playwright 下载 PDF（重构版）。

        支持三种 CNKI 下载场景：
          1. 详情页直接下载：访问详情页 → 点击 PDF 下载按钮 → 等待下载
          2. 在线阅读器 SPA：bar.cnki.net 重定向到阅读器 → 等待渲染 → 提取下载链接
          3. JS 中转认证：x.cnki.net auth-check → 等待 JS 跳转 → 获取下载链接

        Args:
            paper_url: CNKI 论文详情页 URL
            filename: 期望的文件名（不含扩展名），为空时使用时间戳
            proxy_url: 代理 URL（如 http://ip:port），为 None 时直连

        Returns:
            dict: {"success": bool, "file_path": str, "errors": list[str]}
        """
        # 延迟导入 Playwright：仅在真正需要时导入
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            return {
                "success": False,
                "file_path": "",
                "errors": [f"playwright not installed: {e}"],
            }

        errors: list[str] = []
        # 下载事件捕获：通过 future 在事件回调与协程间传递下载对象
        download_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def _on_download(download) -> None:
            """download 事件回调：保存下载文件到 output_dir。"""
            if not download_future.done():
                download_future.set_result(download)

        try:
            async with async_playwright() as p:
                # 1. 启动 Chromium（headless=True 避免打开窗口导致卡死）
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
                launch_kwargs: dict = {"headless": True, "args": launch_args}
                if proxy_url:
                    launch_kwargs["proxy"] = {"server": proxy_url}
                    launch_args.append(f"--proxy-server={proxy_url}")

                browser = await p.chromium.launch(**launch_kwargs)

                # 2. 创建上下文，设置 User-Agent 和 viewport
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1366, "height": 768},
                    accept_downloads=True,
                )

                # 3. 加载 cookies
                # 先访问 cnki.net 首页，使浏览器处于 cnki.net 域下
                try:
                    init_page = await context.new_page()
                    await init_page.goto(
                        "https://www.cnki.net/",
                        wait_until="domcontentloaded",
                        timeout=self.PAGE_LOAD_TIMEOUT,
                    )
                except Exception as e:
                    errors.append(f"init_page goto failed: {e}")

                # 构建 Playwright cookies 格式
                pw_cookies = []
                for name, value in self.cookies.items():
                    if not value:
                        continue
                    pw_cookies.append({
                        "name": name,
                        "value": str(value),
                        "domain": ".cnki.net",
                        "path": "/",
                    })
                if pw_cookies:
                    try:
                        await context.add_cookies(pw_cookies)
                    except Exception as e:
                        errors.append(f"add_cookies failed: {e}")

                # 4. 访问详情页
                page = init_page
                try:
                    await page.goto(
                        paper_url,
                        wait_until="domcontentloaded",
                        timeout=self.PAGE_LOAD_TIMEOUT,
                    )
                except Exception as e:
                    errors.append(f"detail page goto failed: {e}")
                    await browser.close()
                    return {
                        "success": False,
                        "file_path": "",
                        "errors": errors,
                    }

                # 检测 418 拦截：页面内容过短
                try:
                    content = await page.content()
                    if len(content) < 50:
                        errors.append(
                            f"browser_fallback: 可能被 418 拦截 "
                            f"(页面内容过短: {len(content)} chars)"
                        )
                        await browser.close()
                        return {
                            "success": False,
                            "file_path": "",
                            "errors": errors,
                        }
                except Exception:
                    pass

                # 注册 download 事件监听（在整个 context 上，确保新标签页也能捕获）
                # 必须在点击下载按钮之前注册，否则会错过事件
                def _register_download_handler(pg):
                    pg.on("download", _on_download)
                context.on("page", _register_download_handler)
                page.on("download", _on_download)

                # 5. 直接点击 #pdfDown 按钮触发下载
                # 用户要求：只下载 PDF，不下载 CAJ/KDH 格式
                # （CAJ/KDH 无法转换为 PDF，且 #cajDown 返回 KDH 格式）
                download_result = None
                for selector in ["#pdfDown"]:
                    try:
                        btn = await page.wait_for_selector(selector, timeout=5000)
                        if btn:
                            await btn.scroll_into_view_if_needed(timeout=2000)
                            await btn.click(timeout=5000)
                            # 等待下载事件（30 秒超时，下载通常在 5-15 秒内完成）
                            try:
                                download_result = await asyncio.wait_for(
                                    download_future, timeout=30.0
                                )
                                break
                            except asyncio.TimeoutError:
                                # 该按钮未触发下载，重置 future 尝试下一个
                                if not download_future.done():
                                    download_future.set_result(None)
                                download_future = asyncio.get_event_loop().create_future()
                                page.on("download", _on_download)
                    except Exception:
                        continue

                # 6. 如果 #pdfDown 失败，尝试文本匹配 "PDF下载"（不尝试 CAJ）
                if download_result is None:
                    for pattern in ["PDF下载", "PDF 下载", "pdf下载", "下载全文", "全文下载"]:
                        try:
                            btn = await page.query_selector(f'text="{pattern}"')
                            if btn:
                                await btn.click(timeout=5000)
                                try:
                                    download_result = await asyncio.wait_for(
                                        download_future, timeout=30.0
                                    )
                                    break
                                except asyncio.TimeoutError:
                                    if not download_future.done():
                                        download_future.set_result(None)
                                    download_future = asyncio.get_event_loop().create_future()
                                    page.on("download", _on_download)
                        except Exception:
                            continue

                if download_result is None:
                    errors.append(
                        "所有下载策略失败：未找到下载按钮或下载超时"
                    )
                    await browser.close()
                    return {
                        "success": False,
                        "file_path": "",
                        "errors": errors,
                    }

                # 6. 保存下载文件
                download = download_result
                base_name = filename or f"cnki_paper_{int(asyncio.get_event_loop().time())}"
                save_path = self.output_dir / f"{base_name}.pdf"

                try:
                    await download.save_as(str(save_path))
                except Exception as e:
                    errors.append(f"save_as failed: {e}")
                    await browser.close()
                    return {
                        "success": False,
                        "file_path": "",
                        "errors": errors,
                    }

                await browser.close()

                # 7. 验证文件魔数（只接受 PDF 格式，拒绝 CAJ/KDH）
                if not save_path.exists():
                    errors.append(f"saved file not found: {save_path}")
                    return {
                        "success": False,
                        "file_path": "",
                        "errors": errors,
                    }

                try:
                    with open(save_path, "rb") as f:
                        magic = f.read(5)
                except OSError as e:
                    errors.append(f"read magic failed: {e}")
                    return {
                        "success": False,
                        "file_path": "",
                        "errors": errors,
                    }

                is_pdf = magic[:5] == b"%PDF-"
                is_caj = magic[:4] == b"PK\x03\x04"
                is_kdh = magic[:3] == b"KDH"

                if not is_pdf:
                    # 检测到 CAJ/KDH 格式，明确拒绝并删除文件
                    if is_caj or is_kdh:
                        fmt_name = "KDH (CAJ变体)" if is_kdh else "CAJ"
                        errors.append(
                            f"downloaded file is {fmt_name} format, not PDF "
                            f"(magic: {magic!r}). "
                            f"用户要求只下载 PDF，已删除该文件。"
                        )
                    else:
                        errors.append(
                            f"invalid file magic: {magic!r} "
                            "(expected %PDF- for PDF format)"
                        )
                    try:
                        save_path.unlink()
                    except OSError:
                        pass
                    return {
                        "success": False,
                        "file_path": "",
                        "errors": errors,
                    }

                # 8. 返回成功结果
                return {
                    "success": True,
                    "file_path": str(save_path),
                    "errors": errors,
                }

        except Exception as e:
            errors.append(f"browser_fallback exception: {e}")
            return {
                "success": False,
                "file_path": "",
                "errors": errors,
            }

    async def _try_download_strategies(
        self,
        page,
        context,
        download_future: asyncio.Future,
        paper_url: str,
    ) -> Optional[object]:
        """尝试多种下载策略，返回下载对象或 None。

        策略顺序：
          1. CSS 选择器匹配下载按钮
          2. 文本匹配下载按钮
          3. 在线阅读器 SPA 提取下载链接
          4. JS 中转页面等待自动跳转

        Args:
            page: Playwright Page 对象
            context: Playwright BrowserContext
            download_future: 用于捕获下载事件的 Future
            paper_url: 论文详情页 URL

        Returns:
            Download 对象，或 None（所有策略失败）
        """
        # 策略 1: CSS 选择器匹配下载按钮
        download = await self._try_css_selectors(page, download_future)
        if download:
            return download

        # 策略 2: 文本匹配下载按钮
        download = await self._try_text_buttons(page, download_future)
        if download:
            return download

        # 策略 3: 检查是否重定向到在线阅读器 SPA
        current_url = page.url
        if "reader/read" in current_url or "bar.cnki.net" in current_url:
            download = await self._try_spa_reader(page, download_future)
            if download:
                return download

        # 策略 4: 检查是否在 JS 中转页面（x.cnki.net）
        if "x.cnki.net" in current_url or "auth-check" in current_url:
            download = await self._try_js_intermediary(page, download_future)
            if download:
                return download

        # 策略 5: 尝试直接访问 bar.cnki.net 下载链接（如果详情页有提取到）
        # 这个策略由 hybrid_scraper 的 HTTP 层处理，这里不重复

        return None

    async def _try_css_selectors(
        self, page, download_future: asyncio.Future
    ) -> Optional[object]:
        """策略 1: 通过 CSS 选择器查找下载按钮并点击。

        Args:
            page: Playwright Page 对象
            download_future: 用于捕获下载事件的 Future

        Returns:
            Download 对象，或 None
        """
        for selector in self.DOWNLOAD_SELECTORS:
            try:
                btn = await page.wait_for_selector(selector, timeout=3000)
                if btn:
                    # 滚动到可见区域
                    await btn.scroll_into_view_if_needed(timeout=2000)
                    # 点击下载按钮
                    await btn.click(timeout=5000)
                    # 等待下载事件
                    try:
                        download = await asyncio.wait_for(
                            download_future, timeout=self.DOWNLOAD_TIMEOUT
                        )
                        return download
                    except asyncio.TimeoutError:
                        # 该按钮未触发下载，尝试下一个选择器
                        # 重置 future 以便下次尝试
                        if not download_future.done():
                            download_future.set_result(None)
                        download_future = asyncio.get_event_loop().create_future()
                        page.on("download", lambda d: (
                            download_future.set_result(d)
                            if not download_future.done() else None
                        ))
                        continue
            except Exception:
                continue
        return None

    async def _try_text_buttons(
        self, page, download_future: asyncio.Future
    ) -> Optional[object]:
        """策略 2: 通过文本匹配查找下载按钮并点击。

        CNKI 部分下载按钮没有 href 或特定 class，只有文本内容。

        Args:
            page: Playwright Page 对象
            download_future: 用于捕获下载事件的 Future

        Returns:
            Download 对象，或 None
        """
        for text_pattern in self.DOWNLOAD_TEXT_PATTERNS:
            try:
                # 使用 text= 选择器查找包含指定文本的可点击元素
                btn = await page.query_selector(f'text="{text_pattern}"')
                if btn:
                    await btn.scroll_into_view_if_needed(timeout=2000)
                    await btn.click(timeout=5000)
                    try:
                        download = await asyncio.wait_for(
                            download_future, timeout=self.DOWNLOAD_TIMEOUT
                        )
                        if download is not None:
                            return download
                    except asyncio.TimeoutError:
                        continue
            except Exception:
                continue
        return None

    async def _try_spa_reader(
        self, page, download_future: asyncio.Future
    ) -> Optional[object]:
        """策略 3: 处理在线阅读器 SPA 页面。

        bar.cnki.net 重定向到 kns.cnki.net/reader/read（Vue.js SPA），
        需要等待 SPA 渲染完成后，查找页面内的下载按钮。

        Args:
            page: Playwright Page 对象
            download_future: 用于捕获下载事件的 Future

        Returns:
            Download 对象，或 None
        """
        try:
            # 等待 SPA 渲染完成（等待 networkidle 或特定元素出现）
            await page.wait_for_load_state("networkidle", timeout=int(self.SPA_RENDER_TIMEOUT * 1000))
        except Exception:
            pass  # networkidle 超时不影响后续尝试

        # 在阅读器页面中查找下载按钮
        reader_selectors = [
            'a[href*="download"]',
            'button[class*="download"]',
            'a[class*="download"]',
            '#downloadBtn',
            '.download-btn',
            'text="下载"',
            'text="PDF下载"',
        ]
        for selector in reader_selectors:
            try:
                btn = await page.wait_for_selector(selector, timeout=3000)
                if btn:
                    await btn.scroll_into_view_if_needed(timeout=2000)
                    await btn.click(timeout=5000)
                    try:
                        download = await asyncio.wait_for(
                            download_future, timeout=self.DOWNLOAD_TIMEOUT
                        )
                        if download is not None:
                            return download
                    except asyncio.TimeoutError:
                        continue
            except Exception:
                continue
        return None

    async def _try_js_intermediary(
        self, page, download_future: asyncio.Future
    ) -> Optional[object]:
        """策略 4: 处理 x.cnki.net JS 中转认证页面。

        x.cnki.net auth-check 返回 "知网研学 - 中转中..." JS 中转页面，
        需要 JS 执行后自动跳转到实际下载链接。

        Args:
            page: Playwright Page 对象
            download_future: 用于捕获下载事件的 Future

        Returns:
            Download 对象，或 None
        """
        try:
            # 等待 JS 中转完成（页面会自动跳转）
            # 监听 URL 变化，最长等待 JS_REDIRECT_TIMEOUT 秒
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < self.JS_REDIRECT_TIMEOUT:
                # 检查是否已跳转到非中转页面
                current_url = page.url
                if "中转" not in await self._get_page_text(page):
                    # 已离开中转页面，检查是否触发下载
                    if download_future.done():
                        download = download_future.result()
                        if download is not None:
                            return download
                    # 等待下载事件
                    try:
                        download = await asyncio.wait_for(
                            download_future, timeout=10.0
                        )
                        if download is not None:
                            return download
                    except asyncio.TimeoutError:
                        pass
                    break
                await asyncio.sleep(1.0)

            # 中转后可能直接触发下载，也可能跳转到新页面
            # 再等待一次下载事件
            try:
                download = await asyncio.wait_for(
                    download_future, timeout=self.DOWNLOAD_TIMEOUT
                )
                if download is not None:
                    return download
            except asyncio.TimeoutError:
                pass
        except Exception:
            pass
        return None

    async def _get_page_text(self, page) -> str:
        """安全获取页面文本内容。"""
        try:
            return await page.inner_text("body")
        except Exception:
            return ""
