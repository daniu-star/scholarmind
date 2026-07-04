"""CNKI 端到端流水线测试 — 验证反爬虫突破效果。

测试路径：
  Path A: Hybrid Scraper（RSS → 详情页 → PDF 下载 → 正文提取）
  Path B: REST API（QueryJson → JSON 结果 → 元数据）

输出：
  - tests/output/test_report_<timestamp>.md  结构化测试报告
  - tests/output/papers/                     论文 JSON 数据
  - tests/output/pdfs/                       下载的 PDF 文件

用法：
  cd cnki-downloader
  python tests/test_full_pipeline.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.hybrid_scraper import CNKIHybridScraper, FullPaperData
from crawler.cnki_rest_api import CNKIRestAPI

# 输出目录
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
PAPERS_DIR = OUTPUT_DIR / "papers"
PDFS_DIR = OUTPUT_DIR / "pdfs"


# ── Path A: Hybrid Scraper ─────────────────────────────────────


async def test_hybrid_path(cookies: dict[str, str]) -> dict:
    """Path A: Hybrid Scraper 完整流水线测试。

    测试 RSS 发现 → 详情页元数据提取 → PDF 下载 → 正文提取。
    """
    result = {
        "path": "A (Hybrid Scraper)",
        "success": False,
        "papers": [],
        "paper_count": 0,
        "pdf_success_count": 0,
        "pdf_failed_count": 0,
        "body_text_count": 0,
        "errors": [],
        "duration_sec": 0.0,
    }

    start = datetime.now()
    scraper = CNKIHybridScraper(
        cookies=cookies,
        output_dir=str(PDFS_DIR.parent / "hybrid_output"),
    )

    try:
        print("\n" + "=" * 60)
        print("Path A: Hybrid Scraper 完整流水线")
        print("=" * 60)

        print("[A.1] 调用 harvest_paper（含会话预热 + RSS + 详情 + PDF）...")
        papers = await scraper.harvest_paper(
            journal_code="GJXW",
            journal_name="国际新闻界",
            discipline="新闻传播学",
            max_papers=3,
            download_pdfs=True,
        )

        result["paper_count"] = len(papers)
        print(f"[A.2] 发现论文 {len(papers)} 篇")

        for i, p in enumerate(papers, 1):
            print(f"  [{i}] {p.title[:50]}...")
            print(f"      PDF: {'✓' if p.download_success else '✗'} | "
                  f"正文: {p.body_text_length} 字符 | "
                  f"错误: {len(p.errors)} 个")

            if p.download_success:
                result["pdf_success_count"] += 1
            else:
                result["pdf_failed_count"] += 1

            if p.body_text_length > 100:
                result["body_text_count"] += 1

            # 保存论文 JSON
            paper_data = {
                "title": p.title,
                "authors": p.authors,
                "year": p.year,
                "journal_name": p.journal_name,
                "abstract": p.abstract[:200] if p.abstract else "",
                "keywords": p.keywords,
                "doi": p.doi,
                "cnki_url": p.cnki_url,
                "download_success": p.download_success,
                "file_path": p.file_path,
                "file_format": p.file_format,
                "file_size": p.file_size,
                "body_text_length": p.body_text_length,
                "errors": p.errors,
            }
            result["papers"].append(paper_data)

            # 保存到文件
            safe_title = "".join(c for c in p.title[:30] if c.isalnum() or c in "_-") or f"paper_{i}"
            (PAPERS_DIR / f"path_a_{safe_title}.json").write_text(
                json.dumps(paper_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        result["success"] = len(papers) > 0
        print(f"\n[A.3] 结果: {len(papers)} 篇论文, "
              f"PDF 成功 {result['pdf_success_count']}/{len(papers)}, "
              f"正文提取 {result['body_text_count']}/{len(papers)}")

    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        result["errors"].append(err_msg)
        print(f"[A.ERROR] {err_msg}")
        traceback.print_exc()
    finally:
        await scraper.close()

    result["duration_sec"] = (datetime.now() - start).total_seconds()
    return result


# ── Path B: REST API ───────────────────────────────────────────


async def test_rest_api_path(cookies: dict[str, str]) -> dict:
    """Path B: REST API 搜索测试。

    测试凭据提取 → QueryJson 搜索 → 结果解析。
    """
    result = {
        "path": "B (REST API)",
        "success": False,
        "credentials_extracted": False,
        "results_count": 0,
        "sample_titles": [],
        "errors": [],
        "duration_sec": 0.0,
    }

    start = datetime.now()
    rest_api = CNKIRestAPI(cookies=cookies)

    try:
        print("\n" + "=" * 60)
        print("Path B: REST API 搜索")
        print("=" * 60)

        print("[B.1] 预热会话并提取 REST API 凭据...")
        creds_ok = await rest_api.warmup_and_extract_credentials()
        result["credentials_extracted"] = creds_ok

        if creds_ok:
            print("[B.1] ✓ 成功提取 restApiToken 和 restApiClientId")
        else:
            print("[B.1] ✗ 未能提取 REST API 凭据")
            result["errors"].append("凭据提取失败")

        print("[B.2] 搜索 '国际新闻界'...")
        results = await rest_api.search(
            query="国际新闻界",
            field="LY",  # 文献来源
            page=1,
            page_size=5,
        )

        result["results_count"] = len(results)
        print(f"[B.2] 返回 {len(results)} 条结果")

        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "") or r.get("name", "") or "(无标题)"
            result["sample_titles"].append(title)
            print(f"  [{i}] {title[:60]}")

        result["success"] = len(results) > 0

    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        result["errors"].append(err_msg)
        print(f"[B.ERROR] {err_msg}")
        traceback.print_exc()

    result["duration_sec"] = (datetime.now() - start).total_seconds()
    return result


# ── 报告生成 ───────────────────────────────────────────────────


def generate_report(
    hybrid_result: dict,
    rest_result: dict,
    cookies: dict[str, str],
    cookie_status: dict,
) -> Path:
    """生成 Markdown 测试报告。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"test_report_{timestamp}.md"

    # Cookie 关键字段状态
    key_cookies = ["LID", "Ecp_ClientId", "Ecp_LoginStuts", "Ecp_ClientIp", "c_m_expire"]
    cookie_table = []
    for name in key_cookies:
        value = cookies.get(name, "")
        status = "✓ 存在" if value else "✗ 缺失"
        display = value[:40] + "..." if len(value) > 40 else value
        cookie_table.append(f"| {name} | {status} | `{display}` |")

    # Path A 错误汇总
    hybrid_errors = hybrid_result.get("errors", [])
    paper_errors = []
    for p in hybrid_result.get("papers", []):
        for err in p.get("errors", []):
            paper_errors.append(err)

    # 错误分类
    error_categories = {"login_redirect": 0, "http_error": 0, "captcha": 0, "format_error": 0, "other": 0}
    for err in paper_errors + hybrid_errors:
        err_lower = err.lower()
        if "login" in err_lower or "登录" in err_lower:
            error_categories["login_redirect"] += 1
        elif "http" in err_lower or "status" in err_lower:
            error_categories["http_error"] += 1
        elif "captcha" in err_lower or "验证" in err_lower:
            error_categories["captcha"] += 1
        elif "format" in err_lower or "pdf" in err_lower or "magic" in err_lower:
            error_categories["format_error"] += 1
        else:
            error_categories["other"] += 1

    report = f"""# CNKI 爬虫端到端测试报告

**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 1. 环境信息

| 项目 | 值 |
|------|-----|
| 测试脚本 | `tests/test_full_pipeline.py` |
| Cookie 来源 | `cookies.json` |
| Cookie 过期警告 | {cookie_status.get('warning', '无')} |
| Cookie 是否过期 | {'是' if cookie_status.get('is_expired') else '否'} |

### Cookie 关键字段状态

| 字段名 | 状态 | 值（截断） |
|--------|------|------------|
{chr(10).join(cookie_table)}

---

## 2. Path A: Hybrid Scraper 结果

| 指标 | 值 |
|------|-----|
| 测试状态 | {'✓ 成功' if hybrid_result['success'] else '✗ 失败'} |
| 发现论文数 | {hybrid_result['paper_count']} |
| PDF 下载成功 | {hybrid_result['pdf_success_count']} |
| PDF 下载失败 | {hybrid_result['pdf_failed_count']} |
| 正文提取成功 | {hybrid_result['body_text_count']} |
| 耗时 | {hybrid_result['duration_sec']:.1f} 秒 |

### 论文详情

"""
    for i, p in enumerate(hybrid_result.get("papers", []), 1):
        report += f"""#### 论文 {i}: {p.get('title', '(无标题)')[:80]}

| 字段 | 值 |
|------|-----|
| 作者 | {', '.join(p.get('authors', []))} |
| 年份 | {p.get('year', '未知')} |
| 期刊 | {p.get('journal_name', '未知')} |
| DOI | {p.get('doi', '无')} |
| PDF 下载 | {'✓ 成功' if p.get('download_success') else '✗ 失败'} |
| 文件格式 | {p.get('file_format', '无')} |
| 文件大小 | {p.get('file_size', 0)} bytes |
| 正文长度 | {p.get('body_text_length', 0)} 字符 |
| 错误数 | {len(p.get('errors', []))} |

"""
        if p.get("errors"):
            report += "**错误详情:**\n"
            for err in p["errors"]:
                report += f"- {err}\n"
            report += "\n"

    report += f"""---

## 3. Path B: REST API 结果

| 指标 | 值 |
|------|-----|
| 测试状态 | {'✓ 成功' if rest_result['success'] else '✗ 失败'} |
| 凭据提取 | {'✓ 成功' if rest_result['credentials_extracted'] else '✗ 失败'} |
| 搜索结果数 | {rest_result['results_count']} |
| 耗时 | {rest_result['duration_sec']:.1f} 秒 |

### 搜索结果样例

"""
    for i, title in enumerate(rest_result.get("sample_titles", []), 1):
        report += f"{i}. {title}\n"

    report += f"""
---

## 4. 错误汇总与分类

| 错误类型 | 数量 | 说明 |
|----------|------|------|
| 登录重定向 | {error_categories['login_redirect']} | 被重定向到登录页，Cookie 或会话问题 |
| HTTP 错误 | {error_categories['http_error']} | HTTP 状态码异常 |
| 验证码 | {error_categories['captcha']} | 触发验证码 |
| 格式错误 | {error_categories['format_error']} | PDF 格式或魔数错误 |
| 其他 | {error_categories['other']} | 未分类错误 |

### 所有错误详情

"""
    all_errors = hybrid_errors + paper_errors + rest_result.get("errors", [])
    if all_errors:
        for err in all_errors:
            report += f"- {err}\n"
    else:
        report += "（无错误）\n"

    report += f"""
---

## 5. 结论与建议

### 反爬虫突破状态

"""
    if hybrid_result["pdf_success_count"] > 0:
        report += "**✓ PDF 下载成功** — 反爬虫机制已被突破，爬虫可正常工作。\n\n"
    elif hybrid_result["paper_count"] > 0 and hybrid_result["pdf_success_count"] == 0:
        report += "**△ 元数据提取成功，但 PDF 下载失败** — 部分突破，需进一步排查 PDF 下载链路。\n\n"
    else:
        report += "**✗ 完全失败** — 反爬虫机制未被突破，需检查 Cookie 有效性或网络环境。\n\n"

    report += f"""
### 改进建议

"""
    if error_categories["login_redirect"] > 0:
        report += "- **登录重定向问题**: 检查 Cookie 域设置，确保 `.bar.cnki.net` 子域能继承 cookies；尝试重新预热会话。\n"
    if error_categories["http_error"] > 0:
        report += "- **HTTP 错误**: 检查请求头完整性，特别是 Sec-Ch-Ua 和 Sec-Fetch-* 字段；可能需要调整 TLS 指纹。\n"
    if error_categories["captcha"] > 0:
        report += "- **验证码**: 触发了 CNKI 验证码机制，需降低请求频率或使用代理轮换。\n"
    if error_categories["format_error"] > 0:
        report += "- **格式错误**: 下载的文件不是有效 PDF，可能返回了 HTML 错误页，需检查下载链接提取逻辑。\n"
    if not all_errors:
        report += "- 无错误，爬虫运行正常。\n"

    report += f"""
---

## 6. 输出文件

| 文件 | 路径 |
|------|------|
| 测试报告 | `{report_path}` |
| 论文 JSON | `{PAPERS_DIR}/` |
| PDF 文件 | `{PDFS_DIR}/` |

---

*本报告由 `test_full_pipeline.py` 自动生成。*
"""

    report_path.write_text(report, encoding="utf-8")
    return report_path


# ── 主入口 ─────────────────────────────────────────────────────


async def main():
    """主测试入口。"""
    print("=" * 60)
    print("CNKI 端到端流水线测试")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 加载 cookies
    cookies_path = PROJECT_ROOT / "cookies.json"
    print(f"\n[0] 加载 cookies: {cookies_path}")
    try:
        cookies = CNKIHybridScraper.load_cookies_from_file(str(cookies_path))
        print(f"[0] ✓ 加载成功，共 {len(cookies)} 个字段")
    except FileNotFoundError:
        print(f"[0] ✗ cookies.json 未找到: {cookies_path}")
        return

    # 检查 cookie 状态
    cookie_status = CNKIHybridScraper.check_cookie_expiry(cookies)
    if cookie_status["warning"]:
        print(f"[0] ! {cookie_status['warning']}")
    if cookie_status["is_expired"]:
        print("[0] ! 警告: Cookie 已过期，PDF 下载可能失败")

    # 2. 运行 Path A (Hybrid Scraper)
    hybrid_result = await test_hybrid_path(cookies)

    # 3. 运行 Path B (REST API)
    rest_result = await test_rest_api_path(cookies)

    # 4. 生成报告
    print("\n" + "=" * 60)
    print("生成测试报告...")
    report_path = generate_report(hybrid_result, rest_result, cookies, cookie_status)
    print(f"报告已保存: {report_path}")

    # 5. 打印摘要
    print("\n" + "=" * 60)
    print("测试摘要")
    print("=" * 60)
    print(f"Path A (Hybrid): {'✓' if hybrid_result['success'] else '✗'} | "
          f"论文 {hybrid_result['paper_count']} 篇 | "
          f"PDF {hybrid_result['pdf_success_count']}/{hybrid_result['paper_count']}")
    print(f"Path B (REST):   {'✓' if rest_result['success'] else '✗'} | "
          f"凭据 {'✓' if rest_result['credentials_extracted'] else '✗'} | "
          f"结果 {rest_result['results_count']} 条")
    print(f"\n详细报告: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
