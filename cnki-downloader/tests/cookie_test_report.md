# CNKI 爬虫系统 Cookie 测试报告

**测试时间**: 2026-06-24
**测试人员**: 测试工程师（GLM-5.2）
**项目路径**: `c:\Users\13067\Desktop\AI产品\cnki-downloader`
**Cookie 来源**: `cookies.json`（用户名：dx0741，中央民族大学图书馆）

---

## 1. 测试概述

本次测试基于用户提供的最新知网 cookie，对 CNKI 爬虫系统进行全面测试，覆盖 Cookie 有效性验证、会话预热、RSS 论文发现、详情页提取、PDF 下载等核心功能，梳理所有 badcase 并提供修复建议。

### 测试阶段完成情况

| 阶段 | 测试内容 | 状态 | 结果 |
|------|----------|------|------|
| 阶段 1 | Cookie 有效性验证 | ✅ 完成 | 通过（c_m_expire 已过期 0.3h，但认证 cookie 有效） |
| 阶段 2 | 会话预热测试 | ✅ 完成 | 通过（HTTP 200，未被 418 拦截） |
| 阶段 3 | RSS 论文发现测试 | ✅ 完成 | 通过（发现 40 篇论文，字段完整） |
| 阶段 4 | 详情页提取测试 | ✅ 完成 | 部分通过（多个字段解析错误） |
| 阶段 5 | PDF 下载测试 | ✅ 完成 | 失败（所有 4 个策略均失败） |
| 阶段 6 | 端到端完整流程 | ⏭️ 跳过 | 阶段 5 已失败，跳过 |
| 阶段 7 | 梳理 Badcase | ✅ 完成 | 发现 9 个 badcase |
| 阶段 8 | 生成测试报告 | ✅ 完成 | 本报告 |

---

## 2. Cookie 有效性

### Cookie 字段状态

| 字段名 | 状态 | 值（截断） |
|--------|------|------------|
| LID | ✓ 存在 | `WEEvREcwSlJHSldSdmVpZ0doelJ3VkM3Qm4weGZoZ2lENEFTaTBiQm95cz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!` |
| Ecp_ClientId | ✓ 存在 | `e78899f8ed56aab5b3373cc6276273240VN81Etde6` |
| Ecp_LoginStuts | ✓ 存在 | `{"IsAutoLogin":false,"UserName":"dx0741","ShowName":"%E4%B8%AD%E5%A4%AE%E6%B0%91%E6%97%8F%E5%A4%A7%E5%AD%A6%E5%9B%BE%E4%B9%A6%E9%A6%86",...}` |
| cnkiUserKey | ✓ 存在 | `603203c9-3fcf-6f51-b120-a912a5fa8cbc` |
| SID | ✓ 存在 | `zhuye091004` |
| Ecp_session | ✓ 存在 | `1` |
| Ecp_notFirstLogin | ✓ 存在 | `8onxbk` |
| c_m_LinID | ✓ 存在 | `LinID=WEEvREcwSlJHSldSdmVpZ0doelJ3VkM3Qm4weGZoZ2lENEFTaTBiQm95cz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&ot=06%2F24%2F2026%2012%3A46%3A34` |
| c_m_expire | ⚠ 已过期 | `2026-06-24%2012%3A46%3A34`（已过期 0.3 小时） |

### Cookie 检查结果

```json
{
  "is_expired": false,
  "expires_in_hours": -0.3,
  "warning": "会话字段 c_m_expire 已过期 0.3 小时，但认证 cookie 可能仍有效。"
}
```

**结论**: 所有关键认证 cookie（LID、Ecp_ClientId、Ecp_LoginStuts）均存在且有效。`c_m_expire` 会话字段已过期约 18 分钟，但根据代码逻辑，这只是会话字段过期，认证 cookie 仍可能有效。实际测试证明认证 cookie 确实有效（会话预热、RSS、详情页均成功）。

---

## 3. 各阶段测试结果

### 阶段 2: 会话预热测试

| 测试项 | 结果 | 详情 |
|--------|------|------|
| 访问首页 www.cnki.net | ✓ 通过 | HTTP 200, 0.21s, content_len=105696, server=nginx |
| 访问搜索页 kns.cnki.net/kns8s/ | ✓ 通过 | HTTP 200, 0.17s, content_len=16775, server=（空） |
| warmup_session() 完整流程 | ✓ 通过 | 返回 True, 0.62s |
| 是否被 418 拦截 | 否 | cnki_blocks_detected=0 |
| 登录标识检测 | ✗ 未检测到 | 校园网 IP 认证可能不显示登录标识 |
| 错误日志 | 0 条 | 无错误 |

**结论**: 会话预热完全成功，未被 418 拦截，curl_cffi 的 TLS 指纹模拟有效。

### 阶段 3: RSS 论文发现测试

| 期刊 | 代码 | 发现论文数 | 耗时 | 字段完整性 |
|------|------|-----------|------|-----------|
| 国际新闻界 | GJXW | 20 篇 | 0.25s | title=20, link=20, author=20, description=20, pub_date=20 (100%) |
| 新闻大学 | XWDX | 20 篇 | 0.15s | title=20, link=20, author=18, description=20, pub_date=20 (author 缺失 2 篇) |

**结论**: RSS 论文发现功能正常，能发现 20 篇论文，字段完整性高。新闻大学有 2 篇论文缺失 author 字段（可能是编辑部文章或公告）。

### 阶段 4: 详情页提取测试

测试 3 篇国际新闻界论文的详情页提取，字段完整性统计：

| 字段 | 完整性 | 说明 |
|------|--------|------|
| title | 3/3 (100%) | ⚠ 但被附加 "附视频" 后缀 |
| authors | 3/3 (100%) | ⚠ 但解析错误，包含数字上标 |
| abstract | 3/3 (100%) | ✓ 正常（长度 283-336 字符） |
| keywords | 3/3 (100%) | ✓ 正常 |
| year | 3/3 (100%) | ⚠ 1 篇提取为 2023（应为 2026） |
| doi | 3/3 (100%) | ✓ 正常 |
| filename | 3/3 (100%) | ✓ 正常 |
| dbcode | 3/3 (100%) | ✓ 正常 |
| tablename | 3/3 (100%) | ✓ 正常 |
| filesourcetype | 3/3 (100%) | ✓ 正常 |
| pdf_order_url | 3/3 (100%) | ✓ 正常 |
| caj_order_url | 3/3 (100%) | ⚠ 与 pdf_order_url 相同 |
| auth_check_url | 3/3 (100%) | ✓ 正常 |
| is_core | 3/3 (100%) | ✓ 正常（True） |
| journal_name | 0/3 (0%) | ✗ 全部缺失 |
| issue_number | 0/3 (0%) | ✗ 全部缺失 |
| citations | 0/3 (0%) | ✗ 全部为 0 |

### 阶段 5: PDF 下载测试

| 策略 | 结果 | 详情 |
|------|------|------|
| bar (bar.cnki.net) | ✗ 失败 | 重定向到 kns.cnki.net/reader/read（在线阅读器），返回 HTML 2457 bytes |
| auth_check (x.cnki.net) | ✗ 失败 | 返回 "知网研学 - 中转中..." JS 中转页面，HTML 4263 bytes |
| gateway (gateway.cnki.net) | ✗ 失败 | 重定向到 x.cnki.net/，返回 HTML 103 bytes（window.location='search'） |
| legacy (kcms/detail) | ✗ 失败 | 重定向到 kns.cnki.net/verify/home（验证码页面），HTML 2154 bytes |

**下载结果**: 失败（所有 4 个策略均失败）
- 文件大小: 0 bytes
- 魔数校验: 无文件
- 是否被 418 拦截: 否
- 是否重定向到登录页: 否

---

## 4. Badcase 清单（按严重程度排序）

### Badcase 1: PDF 下载完全失败（所有策略均失效）

- **严重程度**: 严重
- **测试阶段**: 阶段 5
- **现象**: 所有 4 个 PDF 下载策略（bar/auth_check/gateway/legacy）均失败，无法下载任何 PDF 文件
- **预期行为**: 至少有一个策略能成功下载 PDF 文件
- **实际行为**:
  - bar.cnki.net 重定向到 `kns.cnki.net/reader/read?invoice=...`（在线阅读器页面，Vue.js SPA），返回 HTML 2457 bytes
  - x.cnki.net auth-check 返回 "知网研学 - 中转中..." JS 中转页面，HTML 4263 bytes
  - gateway.cnki.net 重定向到 `x.cnki.net/`，返回 HTML 103 bytes（`window.location.href = 'search'`）
  - legacy kcms/detail 重定向到 `kns.cnki.net/verify/home?captchaType=clickWord`（验证码页面），HTML 2154 bytes
- **相关文件**: `crawler/hybrid_scraper.py` 第 957-1221 行（`_try_bar_download`、`_try_auth_check_download`、`_try_gateway_download`、`_try_legacy_download`）
- **错误日志/输出**:
  ```
  bar_download: HTML response, no PDF link found (content-type: text/html, size: 2457 bytes)
  auth_check: HTML response, no download link found (size: 4263 bytes)
  gateway: all URLs failed
  legacy: all URLs failed
  ```
- **根因分析**:
  1. CNKI 下载流程已变更：bar.cnki.net 不再直接返回 PDF，而是返回在线阅读器入口
  2. x.cnki.net auth-check 需要 JavaScript 执行才能完成中转认证
  3. gateway.cnki.net 已废弃，重定向到 x.cnki.net
  4. legacy 策略触发了 clickWord 类型验证码
  5. 纯 HTTP 客户端（curl_cffi）无法处理 JS 中转和验证码
- **建议修复方案**:
  1. 启用浏览器自动化降级（`browser_fallback=True`），使用 Playwright 处理 JS 中转
  2. 分析 bar.cnki.net 返回的在线阅读器页面，从中提取实际 PDF 下载链接
  3. 对 legacy 策略的验证码，集成验证码识别服务（如 capsolver/2captcha）
  4. 考虑使用 CNKI 官方 API（如果有的话）替代网页抓取

### Badcase 2: Title 字段被附加 "附视频" 后缀

- **严重程度**: 中等
- **测试阶段**: 阶段 4
- **现象**: 所有 3 篇论文的 title 都被附加了 "附视频" 后缀
  - "情绪偏移：生育报道的情绪不一致性启动路径探究**附视频**"
  - "拥抱与超越：媒介考古学的多维触角与再思考——与尤西·帕里卡（Jussi Parikka）教授对谈**附视频**"
  - ""人生当行的道"：照护社群的网络叙事与自我技术实践**附视频**"
- **预期行为**: title 应为纯标题文本，不包含 "附视频" 等附加标记
- **实际行为**: title 包含 `<span class="type">附视频</span>` 子元素的文本
- **相关文件**: `crawler/hybrid_scraper.py` 第 693-701 行（title 提取逻辑）
- **错误日志/输出**: 无（逻辑错误，不报错）
- **根因分析**: HTML 中 `<h1>` 元素包含一个 `<span class="type" style="display: none">附视频</span>` 子元素。虽然 `style="display: none"` 在浏览器中不显示，但 BeautifulSoup 的 `get_text(strip=True)` 会提取所有文本节点，包括隐藏元素的文本。
  ```html
  <h1>情绪偏移：生育报道的情绪不一致性启动路径探究
    <span id="corr-video" class="type" style="display: none">附视频</span>
  </h1>
  ```
- **建议修复方案**: 在提取 title 前，移除 `<span class="type">` 子元素：
  ```python
  if title_el:
      # 移除 type 标记（如 "附视频"、"附音频"）
      for span in title_el.find_all('span', class_='type'):
          span.decompose()
      paper.title = title_el.get_text(strip=True)[:300]
  ```

### Badcase 3: Authors 字段解析错误，包含数字上标

- **严重程度**: 中等
- **测试阶段**: 阶段 4
- **现象**: 所有 3 篇论文的 authors 解析错误，作者名后附加了机构编号上标
  - 论文 1: `['周俊1', '2张宇2陈科宇3余婉遥2']`（应为 `['周俊', '张宇', '陈科宇', '余婉遥']`）
  - 论文 2: `['曾哲扬1唐海江2']`（应为 `['曾哲扬', '唐海江']`）
  - 论文 3: `['黄月琴王朝阳']`（应为 `['黄月琴', '王朝阳']`，未正确分割）
- **预期行为**: authors 应为清洁的作者名列表，不包含机构编号
- **实际行为**: authors 包含 `<sup>` 标签的文本（机构编号），且分割逻辑不正确
- **相关文件**: `crawler/hybrid_scraper.py` 第 703-716 行（authors 提取逻辑）
- **错误日志/输出**: 无（逻辑错误，不报错）
- **根因分析**: HTML 中作者名后面有 `<sup>` 标签表示机构编号上标：
  ```html
  <h3 class="author" id="authorpart">
    <span><a href="...">周俊<sup>1,2</sup></a><input class="authorcode" type="hidden" value="..."/></span>
    <span><a href="...">张宇<sup>2</sup></a><input class="authorcode" type="hidden" value="..."/></span>
    ...
  </h3>
  ```
  `get_text(strip=True)` 会把 "周俊" 和 "1,2" 合并成 "周俊1,2"。另外，分割逻辑 `re.split(r"[;；,，\n]+", author_text)` 无法正确分割，因为作者之间没有分隔符（只有空格）。
- **建议修复方案**:
  1. 在提取作者前，移除 `<sup>` 和 `<sub>` 标签：
     ```python
     if author_el:
         # 移除上标/下标（机构编号）
         for sup in author_el.find_all(['sup', 'sub']):
             sup.decompose()
         # 移除 hidden input
         for inp in author_el.find_all('input'):
             inp.decompose()
         # 按 <a> 或 <span> 提取每个作者
         author_links = author_el.find_all('a')
         if author_links:
             paper.authors = [
                 a.get_text(strip=True)
                 for a in author_links
                 if a.get_text(strip=True) and len(a.get_text(strip=True)) > 1
             ]
         else:
             author_text = author_el.get_text(strip=True)
             paper.authors = [
                 a.strip().rstrip(";；,，")
                 for a in re.split(r"[;；,，\n]+", author_text)
                 if a.strip() and len(a.strip()) > 1
             ]
     ```

### Badcase 4: Journal Name 字段全部缺失

- **严重程度**: 中等
- **测试阶段**: 阶段 4
- **现象**: 所有 3 篇论文的 journal_name 字段为空
- **预期行为**: journal_name 应为 "国际新闻界"
- **实际行为**: journal_name 为空字符串
- **相关文件**: `crawler/hybrid_scraper.py` 第 818-826 行（journal_name 提取逻辑）
- **错误日志/输出**: 无（逻辑错误，不报错）
- **根因分析**: 代码查找 `.source` 或 `[class*="source"]` 元素，但找到的是 `<span class="resource-url">` 元素，文本为空。CNKI 详情页中期刊名可能在其他位置（如 `<a class="journal-name">` 或通过 JS 动态加载）。
- **建议修复方案**:
  1. 扩展选择器，查找更多可能的期刊名元素：
     ```python
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
     ```
  2. 如果选择器都失败，从 RSS 的 pub_date 或详情页 URL 中推断期刊名
  3. 作为兜底，使用 `harvest_paper()` 调用时传入的 `journal_name` 参数（当前代码已在 `harvest_paper` 中设置 `paper.journal_name = journal_name`，但 `extract_detail_page` 本身不设置）

### Badcase 5: Issue Number 字段全部缺失

- **严重程度**: 轻微
- **测试阶段**: 阶段 4
- **现象**: 所有 3 篇论文的 issue_number 字段为空
- **预期行为**: issue_number 应为期号（如 "03" 或 "3"）
- **实际行为**: issue_number 为空字符串
- **相关文件**: `crawler/hybrid_scraper.py` 第 882-885 行（issue_number 提取逻辑）
- **错误日志/输出**: 无（逻辑错误，不报错）
- **根因分析**: 代码使用正则 `r'(?:期|No\.|issue)\s*(\d+)'` 匹配期号，但 HTML 中没有 "期" 或 "No." 关键字。从 HTML 中看到 `2026, 48` 文本，可能是年份和期号，但格式不匹配正则。
- **建议修复方案**:
  1. 扩展正则模式，匹配更多期号格式：
     ```python
     # 匹配 "2026, 48" 格式（年份后跟期号）
     issue_match = re.search(r'\d{4},\s*(\d+)', html)
     if issue_match:
         paper.issue_number = issue_match.group(1)
     ```
  2. 从 DOI 中提取期号（如 `10.13495/j.cnki.cjjc.2026.03.004` 中的 "03"）：
     ```python
     if paper.doi:
         doi_issue = re.search(r'\.\d{4}\.(\d{2})\.', paper.doi)
         if doi_issue:
             paper.issue_number = doi_issue.group(1)
     ```

### Badcase 6: Citations 字段全部为 0

- **严重程度**: 轻微
- **测试阶段**: 阶段 4
- **现象**: 所有 3 篇论文的 citations 字段为 0
- **预期行为**: citations 应为被引次数（如果有的话）
- **实际行为**: citations 为 0
- **相关文件**: `crawler/hybrid_scraper.py` 第 828-833 行（citations 提取逻辑）
- **错误日志/输出**: 无（逻辑错误，不报错）
- **根因分析**: 代码使用正则 `r'(?:被引|引用|cited?)\s*[：:]\s*(\d+)'` 匹配被引次数，但 HTML 中只有 "同被引文献" 链接，没有 "被引: N" 这样的文本。CNKI 可能将引用次数通过 JS 动态加载或放在其他位置。
- **建议修复方案**:
  1. 查找其他可能的引用次数位置（如 `.citations`、`.cite-count` 等选择器）
  2. 如果引用次数通过 JS 动态加载，考虑使用浏览器自动化获取
  3. 作为兜底，从 CNKI REST API 获取引用次数

### Badcase 7: Year 提取可能错误（2023 vs 2026）

- **严重程度**: 轻微
- **测试阶段**: 阶段 4
- **现象**: 论文 1 的 year 提取为 2023，但 DOI 是 `10.13495/j.cnki.cjjc.2026.03.004`，应为 2026 年
- **预期行为**: year 应为 2026
- **实际行为**: year 为 2023
- **相关文件**: `crawler/hybrid_scraper.py` 第 767-816 行（year 提取逻辑，8 个策略）
- **错误日志/输出**: 无（逻辑错误，不报错）
- **根因分析**: 代码的 Strategy 5 `re.search(r'(\d{4})[年/\.]', html)` 会匹配到 HTML 中第一个 4 位数字后跟 `年`、`/` 或 `.` 的位置。HTML 中有很多 2026（在 CSS/JS 路径中如 `20260624r`），但可能某个位置先匹配到了 2023。实际上从 HTML 中看到 `2026, 48` 文本，这是正确的年份和期号。
- **建议修复方案**:
  1. 优先从 DOI 中提取年份（Strategy 3 已实现，但可能优先级不够高）：
     ```python
     # Strategy 3 应该在 Strategy 5 之前执行
     if not year and paper.doi:
         dm = re.search(r'/j\.[^/]+/(\d{4})\.', paper.doi)
         if dm: year = int(dm.group(1))
     ```
  2. 调整策略优先级，将 DOI 年份提取放在更前面
  3. 排除 CSS/JS 路径中的年份（如 `piccache.cnki.net/nxgp/kcms/20260624r/`）

### Badcase 8: pdf_order_url 和 caj_order_url 可能相同

- **严重程度**: 轻微
- **测试阶段**: 阶段 4
- **现象**: 阶段 4 测试中，3 篇论文的 pdf_order_url 和 caj_order_url 完全相同
- **预期行为**: pdf_order_url 和 caj_order_url 应为不同的下载链接（PDF 和 CAJ 格式）
- **实际行为**: 两个 URL 完全相同
- **相关文件**: `crawler/hybrid_scraper.py` 第 860-866 行（download URLs 提取逻辑）
- **错误日志/输出**: 无（逻辑错误，不报错）
- **根因分析**: 代码使用 `re.findall(r'bar\.cnki\.net/bar/download/order\?id=([^"\'&\s]+)', html)` 提取所有 order URLs，然后取 `order_urls[0]` 作为 pdf，`order_urls[1]` 作为 caj。在阶段 7 辅助检查中发现 HTML 中有 6 个 order URLs，前 2 个是不同的。但在阶段 4 测试中两个 URL 相同，可能是因为：
  1. RSS 返回的论文不同，HTML 结构可能不同
  2. 或者正则匹配到了重复的 URL（如页面中有两个相同的下载按钮）
- **建议修复方案**:
  1. 去重 order_urls，确保 pdf 和 caj 是不同的 URL：
     ```python
     order_urls = list(dict.fromkeys(order_urls))  # 去重并保持顺序
     if len(order_urls) >= 1:
         paper.pdf_order_url = f"https://bar.cnki.net/bar/download/order?id={order_urls[0]}"
     if len(order_urls) >= 2:
         paper.caj_order_url = f"https://bar.cnki.net/bar/download/order?id={order_urls[1]}"
     ```
  2. 检查 HTML 中下载按钮的文本（如 "PDF 下载" vs "CAJ 下载"）来区分

### Badcase 9: RSS 论文发现偶尔失败

- **严重程度**: 轻微
- **测试阶段**: 阶段 7 辅助测试
- **现象**: 在阶段 7 辅助测试中，调用 `discover_papers_rss("GJXW")` 返回空列表（未发现论文）
- **预期行为**: 应能稳定发现论文
- **实际行为**: 偶尔返回空列表
- **相关文件**: `crawler/hybrid_scraper.py` 第 604-643 行（discover_papers_rss）
- **错误日志/输出**: 无错误日志（返回空列表但不报错）
- **根因分析**: 可能是频繁请求导致 CNKI 临时限制 RSS 访问，或者 RSS 服务偶尔不稳定。在阶段 3 中连续测试 2 个期刊都成功，但在阶段 7 辅助测试中失败（之前已进行了多次请求）。
- **建议修复方案**:
  1. 增加重试机制（当前只有 418 时重试一次，其他情况不重试）
  2. 增加请求间隔（当前 `_human_delay` 是 5-15 秒，但 RSS 发现可能需要更长间隔）
  3. 缓存 RSS 结果，避免短时间内重复请求

---

## 5. 架构问题总结

### 5.1 PDF 下载架构过时

CNKI 的 PDF 下载流程已经发生重大变更，当前的 4 策略架构（bar/auth_check/gateway/legacy）全部失效：

1. **bar.cnki.net 策略**: CNKI 已将直接 PDF 下载改为在线阅读器模式，返回 Vue.js SPA 页面
2. **x.cnki.net auth-check 策略**: 需要 JavaScript 执行才能完成中转认证
3. **gateway.cnki.net 策略**: 已废弃，重定向到 x.cnki.net
4. **legacy kcms/detail 策略**: 触发验证码机制

**根本问题**: 纯 HTTP 客户端（curl_cffi）无法处理 CNKI 的 JS 中转、验证码和在线阅读器流程。需要引入浏览器自动化（Playwright）作为主要下载方式，而非降级方案。

### 5.2 详情页解析逻辑不精确

详情页解析依赖 CSS 选择器和正则表达式，但 CNKI 的 HTML 结构包含许多干扰元素：

1. **隐藏元素干扰**: `<span style="display: none">` 的文本被提取
2. **上标/下标干扰**: `<sup>`/`<sub>` 标签的文本被合并到作者名中
3. **选择器不匹配**: journal_name、issue_number、citations 的选择器无法匹配 CNKI 实际 HTML 结构
4. **正则误匹配**: year 提取的正则可能匹配到 CSS/JS 路径中的数字

### 5.3 错误处理不够细致

当前代码在以下方面错误处理不够细致：

1. **PDF 下载失败不区分原因**: bar_download 返回 HTML 时，没有区分是登录页、阅读器页面还是错误页
2. **RSS 发现失败不重试**: 非 418 错误时不重试
3. **字段提取失败不报告**: journal_name、issue_number、citations 提取失败时不记录错误日志

---

## 6. 修复优先级建议

### P0（紧急，阻塞核心功能）

1. **修复 PDF 下载**（Badcase 1）:
   - 启用并完善浏览器自动化降级（Playwright）
   - 分析 bar.cnki.net 返回的在线阅读器页面，提取实际 PDF 下载链接
   - 集成验证码识别服务处理 legacy 策略的验证码

### P1（重要，影响数据质量）

2. **修复 Title 解析**（Badcase 2）: 移除 `<span class="type">` 子元素
3. **修复 Authors 解析**（Badcase 3）: 移除 `<sup>`/`<sub>` 标签，按 `<a>` 元素提取
4. **修复 Journal Name 提取**（Badcase 4）: 扩展选择器，添加兜底逻辑
5. **修复 Year 提取**（Badcase 7）: 调整策略优先级，优先从 DOI 提取

### P2（次要，影响数据完整性）

6. **修复 Issue Number 提取**（Badcase 5）: 扩展正则模式，从 DOI 提取
7. **修复 Citations 提取**（Badcase 6）: 查找其他选择器或使用 REST API
8. **修复 pdf/caj URL 区分**（Badcase 8）: 去重并检查按钮文本

### P3（优化，提升稳定性）

9. **增加 RSS 重试机制**（Badcase 9）: 非 418 错误也重试，增加请求间隔

---

## 7. 测试结论

### 7.1 反爬虫突破状态

| 功能 | 状态 | 说明 |
|------|------|------|
| TLS 指纹模拟 | ✓ 突破 | curl_cffi Chrome 124 指纹有效，未被 418 拦截 |
| Cookie 认证 | ✓ 有效 | 认证 cookie 有效，会话预热成功 |
| RSS 论文发现 | ✓ 正常 | 能稳定发现论文（偶尔失败） |
| 详情页访问 | ✓ 正常 | 能访问详情页并提取 HTML |
| 详情页解析 | △ 部分成功 | 多个字段解析错误（title/authors/journal_name/issue_number/citations） |
| PDF 下载 | ✗ 失败 | 所有策略均失效，CNKI 下载流程已变更 |

### 7.2 总体评价

当前爬虫系统的**元数据采集能力部分可用**（RSS 发现 + 详情页访问成功），但**详情页解析逻辑存在多个 bug**，且**PDF 下载功能完全失效**。

**核心阻塞问题**: CNKI 已将 PDF 下载流程从直接 HTTP 下载改为在线阅读器 + JS 中转模式，纯 HTTP 客户端无法处理。必须引入浏览器自动化（Playwright）作为主要下载方式。

**建议下一步行动**:
1. 立即启用浏览器自动化降级，验证 Playwright 能否完成 PDF 下载
2. 修复详情页解析的 5 个 bug（title/authors/journal_name/issue_number/year）
3. 完善错误处理和重试机制

---

## 8. 测试文件清单

| 文件 | 说明 |
|------|------|
| `tests/test_warmup_phase2.py` | 阶段 2 会话预热测试脚本 |
| `tests/test_rss_phase3.py` | 阶段 3 RSS 论文发现测试脚本 |
| `tests/test_detail_phase4.py` | 阶段 4 详情页提取测试脚本 |
| `tests/test_pdf_phase5.py` | 阶段 5 PDF 下载测试脚本 |
| `tests/test_pdf_debug.py` | 阶段 5 PDF 下载调试脚本（查看 HTML 内容） |
| `tests/test_html_inspect2.py` | 阶段 7 HTML 结构检查脚本 |
| `tests/output/warmup_test_result.json` | 阶段 2 测试结果 |
| `tests/output/rss_test_result.json` | 阶段 3 测试结果 |
| `tests/output/detail_test_result.json` | 阶段 4 测试结果 |
| `tests/output/pdf_test_result.json` | 阶段 5 测试结果 |
| `tests/output/pdf_debug/bar_response.html` | bar.cnki.net 返回的 HTML |
| `tests/output/pdf_debug/auth_check_response.html` | x.cnki.net auth-check 返回的 HTML |
| `tests/output/pdf_debug/gateway_response.html` | gateway.cnki.net 返回的 HTML |
| `tests/output/pdf_debug/legacy_response.html` | legacy kcms/detail 返回的 HTML |
| `tests/output/html_inspect/detail_page.html` | 详情页 HTML 原文 |

---

*本报告由测试工程师自动生成，基于 2026-06-24 的测试数据。*
