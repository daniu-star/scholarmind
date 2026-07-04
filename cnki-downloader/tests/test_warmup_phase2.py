"""CNKI Cookie 测试脚本 — 阶段 2: 会话预热测试

测试 warmup_session() 的 HTTP 状态码、响应时间、是否被 418 拦截。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper


async def test_warmup_detailed():
    """详细测试会话预热，记录每个步骤的 HTTP 状态码和响应时间。"""
    print("=" * 70)
    print("阶段 2: 会话预热测试（详细）")
    print("=" * 70)

    # 加载 cookies
    cookies = CNKIHybridScraper.load_cookies_from_file(str(PROJECT_ROOT / "cookies.json"))
    print(f"[0] Cookies 加载成功，共 {len(cookies)} 个字段")

    # 创建 scraper 实例（不使用代理池，不启用浏览器降级）
    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=str(PROJECT_ROOT / "tests" / "output" / "warmup_test"),
        browser_fallback=False,
    )

    result = {
        "phase": "warmup",
        "steps": [],
        "blocked": False,
        "block_info": None,
        "warmup_success": False,
        "total_duration_sec": 0.0,
    }

    start_total = time.time()

    # Step 1: 访问首页 https://www.cnki.net/
    print("\n[Step 1] 访问 CNKI 首页 https://www.cnki.net/")
    tls = await scraper._get_tls()
    step1 = {"name": "home", "url": "https://www.cnki.net/", "success": False}
    t0 = time.time()
    try:
        resp = await tls.get("https://www.cnki.net/", headers=scraper.default_headers)
        elapsed = time.time() - t0
        step1["status_code"] = resp.status_code
        step1["elapsed_sec"] = round(elapsed, 2)
        step1["content_length"] = len(resp.content)
        step1["server"] = resp.headers.get("server", "") or resp.headers.get("Server", "")
        step1["content_type"] = resp.headers.get("Content-Type", "") or resp.headers.get("content-type", "")
        step1["final_url"] = resp.url

        # 检查 418 拦截
        is_blocked = scraper._is_cnki_blocked(resp)
        step1["is_cnki_blocked"] = is_blocked
        if is_blocked:
            result["blocked"] = True
            result["block_info"] = {
                "status_code": resp.status_code,
                "server": step1["server"],
                "body_length": len(resp.content),
            }
            print(f"  ✗ HTTP 418 拦截！status={resp.status_code}, server={step1['server']}, body_len={len(resp.content)}")
        else:
            print(f"  ✓ status={resp.status_code}, elapsed={elapsed:.2f}s, content_len={len(resp.content)}, server={step1['server']}")
            if resp.status_code == 200:
                step1["success"] = True
            else:
                print(f"  ! 非 200 状态码: {resp.status_code}")
    except Exception as e:
        elapsed = time.time() - t0
        step1["elapsed_sec"] = round(elapsed, 2)
        step1["exception"] = f"{type(e).__name__}: {e}"
        print(f"  ✗ 异常: {type(e).__name__}: {e}")
    result["steps"].append(step1)

    # 如果首页被拦截，不再继续
    if result["blocked"]:
        result["total_duration_sec"] = round(time.time() - start_total, 2)
        print(f"\n[结果] 首页即被 418 拦截，跳过后续步骤")
        await scraper.close()
        return result

    # Step 2: 访问搜索页 https://kns.cnki.net/kns8s/
    print("\n[Step 2] 访问 CNKI 搜索页 https://kns.cnki.net/kns8s/")
    step2 = {"name": "search", "url": "https://kns.cnki.net/kns8s/", "success": False}
    t0 = time.time()
    try:
        resp = await tls.get("https://kns.cnki.net/kns8s/", headers=scraper.default_headers)
        elapsed = time.time() - t0
        step2["status_code"] = resp.status_code
        step2["elapsed_sec"] = round(elapsed, 2)
        step2["content_length"] = len(resp.content)
        step2["server"] = resp.headers.get("server", "") or resp.headers.get("Server", "")
        step2["content_type"] = resp.headers.get("Content-Type", "") or resp.headers.get("content-type", "")
        step2["final_url"] = resp.url

        is_blocked = scraper._is_cnki_blocked(resp)
        step2["is_cnki_blocked"] = is_blocked
        if is_blocked:
            result["blocked"] = True
            result["block_info"] = {
                "status_code": resp.status_code,
                "server": step2["server"],
                "body_length": len(resp.content),
            }
            print(f"  ✗ HTTP 418 拦截！status={resp.status_code}, server={step2['server']}, body_len={len(resp.content)}")
        else:
            print(f"  ✓ status={resp.status_code}, elapsed={elapsed:.2f}s, content_len={len(resp.content)}, server={step2['server']}")
            if resp.status_code == 200:
                step2["success"] = True
                # 检查登录状态
                has_login_marker = "dx0741" in resp.text or "中央民族大学" in resp.text
                step2["has_login_marker"] = has_login_marker
                print(f"  登录标识检测: {'✓ 检测到' if has_login_marker else '✗ 未检测到（校园网 IP 认证可能不显示）'}")
    except Exception as e:
        elapsed = time.time() - t0
        step2["elapsed_sec"] = round(elapsed, 2)
        step2["exception"] = f"{type(e).__name__}: {e}"
        print(f"  ✗ 异常: {type(e).__name__}: {e}")
    result["steps"].append(step2)

    # 调用 warmup_session() 完整流程
    if not result["blocked"]:
        print("\n[Step 3] 调用 scraper.warmup_session() 完整流程")
        step3 = {"name": "warmup_session", "success": False}
        t0 = time.time()
        try:
            ok = await scraper.warmup_session()
            elapsed = time.time() - t0
            step3["elapsed_sec"] = round(elapsed, 2)
            step3["return_value"] = ok
            step3["success"] = ok
            result["warmup_success"] = ok
            print(f"  warmup_session() 返回: {ok}, 耗时: {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - t0
            step3["elapsed_sec"] = round(elapsed, 2)
            step3["exception"] = f"{type(e).__name__}: {e}"
            print(f"  ✗ 异常: {type(e).__name__}: {e}")
        result["steps"].append(step3)

    # 检查 CNKI 封锁状态
    print("\n[Step 4] 检查 CNKI 封锁状态")
    block_status = scraper.get_cnki_block_status()
    print(f"  当前代理: {block_status['current_proxy'] or '直连'}")
    print(f"  被封锁代理数: {block_status['blocked_count']}")
    print(f"  可用代理数: {block_status['available_proxies']}")

    result["total_duration_sec"] = round(time.time() - start_total, 2)
    result["error_log_count"] = len(scraper.error_log)
    if scraper.error_log:
        result["error_log_sample"] = scraper.error_log[:3]

    await scraper.close()

    print("\n" + "=" * 70)
    print("阶段 2 测试结果摘要")
    print("=" * 70)
    print(f"是否被 418 拦截: {'是' if result['blocked'] else '否'}")
    print(f"warmup_session 是否成功: {'是' if result['warmup_success'] else '否'}")
    print(f"总耗时: {result['total_duration_sec']}s")
    print(f"错误日志条数: {result['error_log_count']}")

    # 保存结果
    output_path = PROJECT_ROOT / "tests" / "output" / "warmup_test_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n结果已保存: {output_path}")

    return result


if __name__ == "__main__":
    asyncio.run(test_warmup_detailed())
