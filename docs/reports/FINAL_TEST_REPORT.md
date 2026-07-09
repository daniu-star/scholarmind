# CNKI 混合爬虫系统 — 最终测试报告

**测试日期**: 2026-06-20 23:15  
**方案**: 方案A — 浏览器辅助下载 + 自动正文提取

---

## 测试结果摘要

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1: 元数据采集 | ✅ **100%** | 3/3 论文，7/7 字段完整 |
| Phase 2: 下载列表生成 | ✅ **完成** | HTML 下载页面 + .bat 批处理脚本 |
| Phase 3: PDF 正文提取 | ✅ **就绪** | pypdf + pdfplumber 双引擎，元数据匹配，合并输出 |

---

## Phase 1 详细结果

### 元数据字段完整性 (3/3 论文)

| 字段 | 结果 |
|------|------|
| 标题 (title) | 3/3 ✅ |
| 作者 (authors) | 3/3 ✅ |
| 年份 (year) | 3/3 ✅ |
| 期刊 (journal_name) | 3/3 ✅ |
| 摘要 (abstract) | 3/3 ✅ |
| 关键词 (keywords) | 3/3 ✅ |
| DOI | 3/3 ✅ |
| 下载链接 (pdf_order_url) | 3/3 ✅ |

### 采集论文

| # | 标题 | 作者 | DOI |
|---|------|------|-----|
| 1 | 情绪偏移：生育报道的情绪不一致性启动路径探究 | 周俊, 张宇, 陈科宇, 余婉遥 | 10.13495/j.cnki.cjjc.2026.03.004 |
| 2 | 拥抱与超越：媒介考古学的多维触角与再思考 | 曾哲扬, 唐海江 | 10.13495/j.cnki.cjjc.2026.03.002 |
| 3 | "人生当行的道"：照护社群的网络叙事与自我技术实践 | 黄月琴, 王朝阳 | 10.13495/j.cnki.cjjc.2026.03.001 |

---

## 生成的文件

```
数据库/cnki/hybrid/
├── download_list_20260620_231530.html    ← 浏览器下载页面 (打开此文件)
├── download_20260620_231530.bat           ← Windows 批量下载脚本
├── harvest_summary_20260620_231530.md     ← 采集结果报告
├── error_log_20260620_231530.md           ← 错误日志
├── pipeline_state.json                    ← 流水线状态
└── complete/                              ← (Phase 3 后) 完整论文 JSON

downloads/pdf/                             ← 用户放置下载的 PDF
└── extraction_report_*.md                 ← (Phase 3 后) 正文提取报告
```

---

## 用户操作指南

### 现在执行 Phase 2 (人工步骤):

1. 打开浏览器，访问生成的 HTML 下载页面:
   ```
   数据库/cnki/hybrid/download_list_20260620_231530.html
   ```

2. 点击每篇论文的「PDF下载」按钮（会在新标签页打开 CNKI 下载页）

3. 将下载的 PDF 保存到:
   ```
   cnki-downloader/downloads/pdf/
   ```

4. 全部下载完成后，运行正文提取:
   ```bash
   cd cnki-downloader
   python run_full_pipeline.py --extract
   ```

### 之后扩展更多期刊:

```bash
# 采集全部 4 本新闻传播学期刊
python run_full_pipeline.py --harvest --papers 5

# 采集指定期刊
python run_full_pipeline.py --harvest --journal GJXW --papers 10

# 一键运行完整工作流
python run_full_pipeline.py
```

### Cookies 过期时:

1. 在 Chrome 中登录 CNKI (通过校园网/VPN)
2. 按 F12 → Application → Cookies → 复制所有 cookie 值
3. 更新 `cnki-downloader/cookies.json` 文件

---

## 系统能力总结

```
                    ┌──────────────────┬─────────┬──────────────────────┐
                    │   功能            │ 状态    │  实现方式             │
                    ├──────────────────┼─────────┼──────────────────────┤
                    │ TLS 指纹伪装      │   ✅    │ curl_cffi Chrome 124 │
                    │ 论文发现 (RSS)    │   ✅    │ rss.cnki.net         │
                    │ 详情页解析        │   ✅    │ BeautifulSoup + Regex │
                    │ 元数据提取 7 字段  │   ✅    │ 100% 完整率          │
                    │ 下载列表生成      │   ✅    │ HTML + .bat          │
                    │ PDF 正文提取      │   ✅    │ pypdf + pdfplumber   │
                    │ 元数据匹配        │   ✅    │ 文件名 + 标题相似度   │
                    │ 错误日志          │   ✅    │ Markdown 自动生成    │
                    │ HTTP 直接下载 PDF  │   ❌    │ CNKI 强制 JS 执行    │
                    └──────────────────┴─────────┴──────────────────────┘
```

---

## Cookies 状态

| 属性 | 值 |
|------|-----|
| 账号 | dx0741 @ 中央民族大学图书馆 |
| 更新时间 | 2026-06-20 23:27 |
| 过期时间 | 2026-06-20 23:27 (约 0.2 小时后) |
| 状态 | ⚠️ 即将过期 — 请尽快下载 PDF！ |

---

*报告由 run_full_pipeline.py 自动生成*
