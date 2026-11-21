# R2 验证报告（T21–T23 / AT-044—AT-056）

- 阶段：R2 质量验证版
- 编制：2026-11-20，**Lead 主编**（合并 Lead 复核与本轮独立 verifier 报告）
- 独立报告原文：`docs/reports/R2_VERIFICATION_VERIFIER.md`（未改动，作为本报告附录 A）
- 依据：`docs/prd/ScholarMind_Optimization_PRD_v1.0.md`、`ScholarMind_Coding_Agent_Playbook_v1.0.md`（T21–T23）、`ScholarMind_Acceptance_Matrix_v1.0.md`（AT-044—AT-056，矩阵第 86–100 行）
- 配套：`docs/reports/R2_DELIVERY.md`、`R2_EVAL_STATUS.md`、`R2_BUDGET_PROTOCOL.md`、`R2_E2E.md`

## 0. 结论

**R2 有条件放行。** 机器可验证项全部实测通过（R2 套件 78 passed + 1 skipped、ruff 全绿、三套回归 529 passed + 1 skipped、迁移可重入、构建为唯一模块化产物、真实浏览器全链路跑通）；**T21 的真实模型评估已完成**（14 篇用户自有论文，13 succeeded / 1 partial，平均覆盖率 97.00%，1,974 条诊断，引文保真 95.44%，纯编造 0.00%，locator 错位 0 条，见 `R2_CORPUS_EVAL.md`）；**人工盲评按用户指示越过**；**AT-056 的「短流程 vs 多角色流程」20000 字对照已跑**（single 109 条 / multi_role 203 条，成本约 2×，见 §15），因此对外只能说"全链路已实测、结论可追溯到原文"，**不得说"诊断质量已验证/准确率达标"**。

### 0.1 放行条件

1. **AT-050**：语料与真实模型评估已完成（14 篇、13 succeeded / 1 partial、覆盖率 97.00%、引文保真 95.44%）；**仍缺两位真人独立盲评** → 召回/误报/人工时间无数字（盲评工具 `tools/research_quality_eval.py` 已就绪）。
2. ~~**AT-056**：同一 20000 字论文、真实模型，跑短流程 vs 多角色流程，记录覆盖率、P95、调用与 token。~~ **已闭环（2026-11-21）**：`constraints.review_mode` 已落地，p04（20,017 码点）single vs multi_role 真实 A/B 完成（109 vs 203 条、成本约 2×、覆盖均 100%，`R2_FLOW_AB.md`）；仍缺 P95 统计（单篇单次测量）。
3. ~~**D1**：产品书面确认"图表数据仅支持文档正文中的 Markdown 管道表 / CSV 代码块"，或补 XLSX/JSON 表格导入入口。~~ **已闭环（2026-11-20）**：已支持 CSV/XLSX（`document_parser` 新增 `_parse_csv`/`_parse_xlsx`，多 sheet 按 `table_index` 选表），新增 `test_chart_data_files.py`（7 条）；JSON 仍不支持，见 §8。
4. ~~**浏览器项**：装 Playwright 后 `npm run test:research:e2e` 默认模式必须 exit 0（当前 exit 3，不伪装）。~~ **已闭环（2026-11-20）**：`playwright@1.65.1` 已入 devDependencies，默认模式实测 exit 0（详见 §8）。
5. **部署项**：生产环境演练 PG/Redis/Celery 恢复语义；`ENABLE_VERIFIED_CHARTS` 保持默认关闭。
6. 发布说明必须写明：14 种图表类型（12 灰阶 + `bar`/`line` 分类轴），除 `bar`/`line` 外仅接受全数值表、预算费用显示"未知"、图表能力默认关闭。

### 0.2 两份报告的关系（如实说明）

本轮有两个执行体：Lead 与独立 R2 verifier 子代理。verifier 在 12:12 报告"独占目录被并行写入"后继续新增测试（未覆盖他人文件，只加新文件），共新增 5 文件 22 条用例，并产出独立报告。本文件为**合并权威版**：

- 数字、AT 判定、缺陷编号（D1–D6）以 verifier 的实测为准，Lead 版早期结论（AT-048 pass、AT-052/054 pass 等）已按矩阵语义改判；
- 独立性限制：D2/D3/D5 由 Lead 修复、Lead 复跑验证，因此这三项不具备"复核者独立"性质；
- 若需正式签核，第三方按 §1 命令重跑即可。

## 1. 命令与真实结果

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `pytest src/backend/tests/test_research_r2 src/backend/tests/test_research_r1 src/backend/tests/test_research -q` | **495 passed**（R2=45、R1=160、R0=290） |
| 2 | `pytest src/backend/tests/test_research_r2 -q` | **45 passed**（9 文件） |
| 3 | `ruff check src/backend/research src/backend/routers/research.py src/backend/tests/test_research{,_r1,_r2} src/backend/middleware tools/research_quality_eval.py tools/research_budget_report.py scripts/research_migration_check.py` | All checks passed |
| 4 | `python scripts/research_migration_check.py` | 离线 SQL 建 15 张研究表 + 4 个唯一约束；upgrade→downgrade→upgrade 可重复，`users` 保留 |
| 5 | `npm run build:frontend` | exit 0，`dist/index.html` 引用 `/assets/index-*.js` 模块入口，无原型标记 |
| 6 | `node scripts/research_e2e.mjs --api-only` | exit 0（review `succeeded`、findings 0、导出 1101 B） |
| 7 | `node scripts/research_e2e.mjs --serve-only --duration=10` | exit 0（首页入口、health 200、无 token 401、带 token 18 项能力） |
| 8 | `node scripts/research_e2e.mjs` | **exit 3**（缺 Playwright，打印安装命令） |
| 9 | `python tools/research_quality_eval.py …` | 10 样本 exit 0；<10 样本/模型评审 id/缺列 exit 2；缺一条评分 exit 3 |
| 10 | `python tools/research_budget_report.py --db …` | 越界 `exceeded[tokens]`、覆盖率 8/10、费用"未知"、缺失显示 `-` |

真实浏览器验收（Chrome DevTools MCP，Chrome 157，桌面 1440px）：注册 → 建项目 → 上传 585 码点文档 → review 任务 `succeeded`（12/12 块、覆盖率 100%、`no_major_issues_found`、findings=0）→ 导出 201（正文含诊断摘要）→ 数值表文档 gradient_area/ribbon/violin 各 201 且 `value_ranges` 与表数据一致、PNG 签名校验通过。步骤与截图证据见 `R2_DELIVERY.md` §4。

## 2. AT 逐条判定（矩阵语义为准）

| AT | 判定 | 依据与缺口 |
| --- | --- | --- |
| AT-044 迁移/归属 | partial | 迁移可重入与回退已验证；多 owner 共用 session、旧会话缓存未复现 |
| AT-045 V2 导出/DOCX | partial | 绑已存版本、DOCX 重开段落数校验、未知样式 422、导出幂等均有测试；"浏览器另有未保存 V3"组合未测 |
| AT-046 冷启动/日志目录 | not_covered | 无远端 CI 冷启动记录；路径与日志目录未专项演练 |
| AT-047 浏览器 1440/390、键盘 | **partial（已扩到 390px + 键盘）** | 1440px 全链路与 390×844 窄屏、键盘可达（Tab 至「新建项目」→ Enter 聚焦输入 → 键盘创建项目）均在真实 Chromium 中跑通，见 §11；仍未覆盖真实 iOS Safari/Android 设备与读屏软件 |
| AT-048 构建产物/唯一模块化 | partial | `dist` 模块入口存在且构建断言通过；但后端 `GET /` 仍 307 到原型页（D6），"root 只交付模块化产物"无法从应用入口自证 |
| AT-049 安全/日志负例 | partial | 代码执行默认关闭、来源 URL 阻断 file/私网/回环有测试；日志泄露面未专项扫描 |
| AT-050 ≥10 授权论文 + 2 位真人 | **partial** | 14 篇真实论文 + 真实模型全跑通（13 succeeded / 1 partial、覆盖率 97.00%、1,974 条诊断、引文保真 95.44%、纯编造 0.00%）；**缺两位真人盲评** → 召回/误报/时间无数字；工具硬约束（<10→exit 2、model 评审→exit 2、缺评分→exit 3）已被测试锁定 |
| AT-051 retry/预算不清零 | partial | 受理预算落库、retry 不膨胀、越界降级已测；并发重试/预留释放未测。D2 曾使生产路径 export 得 160 调用，已修 |
| AT-052 隔离/指标聚合 | not_covered | 矩阵语义为"切换项目/用户、检索降级、指标聚合、埋点去重"；R2 只回归未新增证据 |
| AT-053 同浏览器双账号 | **partial** | 已做双账号隔离：新注册账号 B 在 UI 中看不到账号 A 的项目，B 直连 A 的项目 ID 得统一 404（`NOT_FOUND`），见 §11.3；refresh≠access 的 token 混用仍由 R1 用例覆盖、未在浏览器里做 |
| AT-054 删除撤权/迟到 worker | **partial** | 新增 `test_research_r2/test_deletion_revocation.py` 5 条：删除后读路径全 404 且不泄露文件名、已删版本建任务 404、版本与分块级联清理、非 owner 删除前后均 404、租约 `LEASE_HELD`、终态任务 `TASK_NOT_CLAIMABLE` 且迟到执行器不写事件；未覆盖事件重放泄露（需 Redis 生产环境） |
| AT-055 R2 图表数据一致性 | partial | 摘要可独立复算、值域与表数据一致、PNG sha256/宽高互证、同输入字节一致、越权 404、失败不落 Artifact；缺口：输入格式收窄（D1）、单位校验未显式（D5 已补策略字段） |
| AT-056 R2 预算/20000 字对照 | partial | 越界→`partial`+`BUDGET_EXCEEDED` 且成果保留、未知费用 `None`/报表"未知"、事件按 sequence 去重；**已补真实 A/B**：同一篇真实论文只改预算三臂，默认 69/69 succeeded、tokens 收紧到 12,000 → 18/69 partial、调用收紧到 8 → 31/69 partial（`R2_BUDGET_AB.md`）；**流程增益对照已跑**（同一篇 20,017 码点论文：single 20 调用/47,943 tokens/109 条 → multi_role 40 调用/95,840 tokens/203 条，覆盖均 100%，见 `R2_FLOW_AB.md`）；缺口：单篇单次、P95 未统计、无真人标注 |

## 3. 关键证据

### 3.1 图表数值保真（AT-055，`test_charts_api.py` + `test_charts_edges.py`）

- 成功路径独立复算：用 `load_table`+`select_columns` 重算 `data_digest` 与 `value_ranges`，与 API 返回一致；下载 PNG 的 sha256/IHDR 宽高与 validation 互证；同输入两次渲染字节级一致。
- 失败语义：503（开关关闭）/422（无表、未知列、非数值含 `hint`、空数据、不支持类型）/413（超行数）/404（跨用户与项目版本不匹配）/500（渲染异常，`retryable=true`）——**每种失败都不落 Artifact**，不使用 `generate_chart` 的"图表生成失败"占位图。
- `validation` 新增 `cleaning{steps[],missing_value_policy:"reject",filtered_rows:0,note}`（D5），使"非数值即拒绝、不清洗不插值"成为可审计记录。

### 3.2 预算（AT-051/AT-056，`test_budget_contract.py` / `test_budget_runner.py` / `test_budget_report_tool.py`）

- 默认预算：review 160 调用/100000 tokens/1200s、revision 128、export 0/0、chart 0/0（**枚举入口与字符串入口一致**，D2 回归锁）。
- 超限：`state=exceeded`、`overruns=["model_calls","tokens"]`、`cost_known=false`、`cost_usd is None`；任务终态 `BUDGET_EXCEEDED`、不 `succeeded`、成果保留。
- 报表：未知费用"未知"、缺失 `-`、重复 sequence 去重、空库不造表。

### 3.3 结构性检查出口（`test_findings_mapping.py`）

库内 `structural` 保留（导出文案用），API 出口映射为契约四值之一（`tool`）；`GET /tasks/{id}/findings` 200 返回 `{"items":[...]}`，不再 500。

### 3.4 人工评估工具诚实性（AT-052 工具侧，`test_eval_cli.py` + `test_eval_cli_edges.py`）

报告 `source=human_raters`；拒绝 `model/ai/self/gpt/…` 评审 id；同 id 不能冒充双评审；样本不足/缺列 exit 2；缺一条评分 exit 3 且不补 0；`time_minutes` 不算一致性（`agreement=None`）。

## 4. 发现的问题与处置

| 编号 | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| D1 | 重要 | FR-13 输入格式收窄为"文档正文里的 Markdown/CSV 表"，无 XLSX/JSON 导入入口 | **已修（2026-11-20）**：新增 CSV/XLSX 解析与多表 `table_index`，7 条用例；JSON 仍不支持 |
| D2 | 重要 | `budget.py` 用 `str(kind)`，生产路径传 `TaskKind` 枚举 → export/chart 得 160 调用、100000 tokens | **已修**：新增 `_normalize_kind`（取 `.value` 再剥前缀）；`TaskKind.EXPORT/CHART` 现为 0/0；xfail 改为回归锁，枚举与字符串双入口断言 |
| D3 | 次要 | 报表工具只重配 stdout，stderr 走 cp936 → 诊断信息乱码 | **已修**：stdout/stderr 同时 `reconfigure(encoding="utf-8")`；新增严格 UTF-8 解码回归用例 |
| D4 | 次要（测试卫生） | `test_charts_api.py` 同步用例带 asyncio 标记产生告警 | **已修**：删文件级 `pytestmark`，逐 async 用例加标记，套件零 warning |
| D5 | 次要 | FR-13 清洗步骤/缺失值规则未落库 | **已补**：`validation.cleaning` 显式记录策略，成功路径断言 |
| D6 | 信息级 | `GET /` 仍 307 到 `prototypes/interactive-prototype.html`，`dist/` 未挂到 FastAPI | **刻意保留**（旧链接兼容），登记为 AT-048 缺口说明 |

## 5. 未覆盖与风险

| 项 | 原因 | 影响 |
| --- | --- | --- |
| AT-050 真人盲评 | 真实模型评估已完成；**无真人评审**（用户指示越过） | 无召回率/误报率/人工时间真实数字（覆盖率/引文保真/重复率已有） |
| AT-056 20000 字对照 | 禁网、禁真实模型 | 无覆盖率/P95/真实消耗 |
| AT-047/048/053 浏览器与 a11y | 已跑通桌面 1440px + 390px 窄屏 + 键盘 + 双账号隔离；未覆盖真机与读屏软件 | 不能宣称完整移动端/无障碍通过；AT-048 的 `GET /` 307 仍未改 |
| AT-052/054 | 属 R1 范围，R2 未新增 | 依赖 R1 证据，本次仅回归未破坏 |
| 图表 14 种渲染器 | 抽测 gradient_area 全链路、`bar`/`line` 六条契约用例 + 纯函数覆盖类型表 | 其余 11 种未逐一冒烟 |
| 图表单位校验 | 实现无显式单位字段 | AT-055"单位"项未验证 |
| SQLite≠PG/Redis/Celery | 本机环境不具备 | 生产恢复语义未验证 |

## 6. 放行结论

- **研究域自动化验收**：通过——R2 78 passed + 1 skipped、R0 290 passed、R1 161 passed（合计 529，实跑 529 passed + 1 skipped）、ruff 全绿、迁移可重入、构建唯一模块化入口、真实 Playwright 浏览器全链路 exit 0（含图表前端面板）、14 篇真实论文语料链路可复跑。
- **T21**：**机器可验证部分完成**（14 篇真实论文真实模型全跑通，13 succeeded / 1 partial、覆盖率 97.00%、引文保真 95.44%、纯编造 0.00%、locator 0 错位；`R2_CORPUS_EVAL.md`/`R2_EVAL_STATUS.md`），**人工盲评按用户指示越过 → 质量召回/误报仍属未测量**；**T22**：通过（含 D1/D5 偏差）；**T23**：有条件通过（协议与降级证据齐备，真实对照未跑）。
- **对外表述基线**："研究域自动化验收通过、图表数值可核验、预算与评估工具诚实可用"；禁止："质量已验证""诊断准确率达标""桌面与移动端全适配"。
- **2026-11-20 复核更新**：XLSX/CSV 已可直接出图（D1 闭环）；当时仅支持"全数值表"，分类轴 422 `CHART_NON_NUMERIC`。
- **2026-11-21 复核更新（R2.1）**：新增 `bar`/`line` 分类轴图表（14 种类型），分类表对这两种类型可出图且 `x_mode=categorical`、分类标签不进 `value_ranges`；其余 12 种仍要求全数值表，误差范围与偏差见 §12。

## 7. 附录：真实语料补充（2026-11-20）

- 用户提供论文目录并指示跳过人工盲评（m02717）；14 篇 docx 暂存 `tmp/r2-corpus`（manifest 不含正文）。
- 新增 `tools/research_corpus_stage.py`（只读暂存）与 `tools/research_corpus_eval.py`（建项目→上传→review→revision→采集）；真实模型 `deepseek-v4-flash` 返回 402 `Insufficient Balance`，任务进 `recoverable` + `MODEL_UNAVAILABLE`（0 调用、0 tokens、覆盖率 0），证据 `docs/reports/R2_CORPUS_EVAL_BLOCKED.json`。
- 替身演练：14/14 `succeeded`、覆盖率 100%、31 条 structural findings、平均 28.29 次调用 / 19,450.8 tokens；9 篇有诊断项的 revision 全部 `REVISION_NO_VALID_HUNKS`（结构性 finding 无补丁区间，属诚实拒绝）。
- 演练同时暴露并修复 **D7 跨任务采纳缺陷**：revision 任务引用 review finding 时 422 `FINDING_NOT_FOUND`；已改 `revision_service._load_findings` 与 `task_service._require_owned_inputs`，新增 `test_revision_cross_task.py`（2 条）。
- 计数更新：R2 47、合计 497（此为语料补充时点；D1 与图表 UI 用例加入后见 §8）。AT-050 判定不变（仍需真实质量对照）。

## 8. 附录：D1 闭环、真实 Playwright E2E 与提交时序缺陷（2026-11-20 16:5x）

### 8.1 D1（FR-13 输入格式收窄）已闭环

- `src/backend/research/document_parser.py` 新增 CSV（`text/csv`、`	`/`;`/`,` 分隔探测、utf-8-sig）与 XLSX
  （openpyxl 只读、≤5 sheet、每 sheet 输出 `## Sheet: <name>` + Markdown 管道表、`|`/`\` 转义、超码点记
  `xlsx_truncated`）解析；`document_service` 的 415 文案同步列出 CSV/XLSX；
  `chart_data_source._split_pipe_row` 支持转义竖线。
- 新增 `src/backend/tests/test_research_r2/test_chart_data_files.py`（7 条：xlsx/csv 201、非数值 422 hint、
  坏 xlsx 422、多 sheet `table_index`、行数上限 413 等）。
- 仍不支持：JSON 表格、XLSX 合并单元格展开、日期列（按 ISO 字符串处理）。属可接受偏差，已写入交付文档。

### 8.2 真实 Playwright 浏览器 E2E：exit 0

- 依赖：`playwright@1.65.1`（根 devDependencies）+ `npx playwright install chromium`；脚本保留
  `E2E_CHROMIUM_EXECUTABLE` 与 `%LOCALAPPDATA%\ms-playwright` 兜底。
- 结果：`node scripts/research_e2e.mjs` **exit 0**（脚本内 34.7–40 s），页面控制台错误 0；覆盖真实 UI 注册 →
  刷新登录态 → 登出 → 登录、`#research` 能力/项目/上传、review 任务 SSE 5 条事件、诊断 0 findings 空态、
  导出 201 并真实下载 md 1315 B、图表 API 201 PNG、**图表前端面板**（识别 2 张表 → 选全数值表 → 生成 →
  1351×963 图片 → 校验信息含「重开校验通过 / PNG 摘要 / 值域」）。
- 证据：`docs/reports/R2_E2E_BROWSER.md`（含 4 次失败迭代与未覆盖项）、`tmp/e2e-evidence/` 截图。
- 未覆盖（不得宣称通过）：390px 窄屏、键盘可达性、同浏览器双账号、有 findings 的卡片渲染。

### 8.3 新缺陷 R2-A8（提交时序，已修）

- 现象：`POST /research/exports` 201 后紧接 `GET /artifacts/{id}/download` 偶发 404；上传成功后紧接建
  review 任务偶发 `NOT_FOUND: 文档版本不存在`。
- 根因：`src/backend/db/session.py` 的 `get_db` 在响应发出后才 `commit`，客户端立即读取刚创建的资源会撞提交竞态。
- 修复：`src/backend/routers/research.py` 增加 `_commit(db)`，在 12 个写端点返回前显式提交（项目建/改、
  上传/删除、来源、任务建/续跑/取消/重试、图表、采纳、导出）。修复后连跑 3 次 E2E，无 404。

### 8.4 计数与门禁（2026-11-20 终态）

- `pytest src/backend/tests/test_research_r2 src/backend/tests/test_research_r1 src/backend/tests/test_research -q`
  → **503 passed, 1 skipped in 475.90s**（收集 504：R2 54、R1 160、R0 290；1 skip 为既有条件跳过）。
- `ruff check`（研究域 + 三个测试目录 + tools + 迁移脚本）→ All checks passed。
- `npm run build:frontend` → 唯一模块化入口 `/assets/index-*.js`；`node scripts/research_e2e.mjs` → exit 0。

## 9. 附录：真实模型评估完成与两处真实缺陷（2026-11-21）

### 9.1 真实模型评估结果（`deepseek-v4-flash`，stub=false）

| 指标 | 结果 |
| --- | --- |
| 论文 | 14 篇（12 中 + 2 英，13k–60k 码点） |
| 状态 | 13 succeeded / 1 partial |
| 平均覆盖率 | **97.00%** |
| 诊断项 | 1,974 条（每万码点 56.57） |
| 严重度 | critical 262 / major 765 / minor 673 |
| 引文保真 | **95.44%** 逐字可核对；纯编造 **0.00%**；重复 **0.00%** |
| 引用偏移 | locator 与引文不一致 **0 条**（修复后 14 篇全部重跑） |
| 修改提案 | 14 份 / 28 个补丁，`validate_hunks` 全部通过 |
| 平均调用/tokens/耗时 | 24.85 次 / 53,714 / 173.75 s |

数据：`R2_CORPUS_EVAL.md`、`R2_CORPUS_EVAL_RESULTS.json`。**无真人标注 → 召回率/误报率/节省时间仍为"未测量"，不补 0。**

### 9.2 partial 的唯一原因：PRD 预算边界

p10（59,582 码点 / 146 块）用 98,824/100,000 tokens 覆盖 88 块（60.27%），按最小交付契约诚实返回
`partial` + `INCOMPLETE_DELIVERABLE`（`全文诊断覆盖不足: 88/146`），报告与诊断项仍交付。
约需 1.6 倍预算才能全覆盖 → 属 PRD §9 边界，改进方向（放大窗口/精简提示词/长文单独提预算）留待产品决策。

### 9.3 本次真实运行暴露并修复的两处缺陷

1. **输出截断**：`finish_reason=length` 时内容为空或被截断（推理模型吃光预算 / 4096 上限不足）。
   修复：默认 `RESEARCH_DISABLE_MODEL_THINKING=true`、`RESEARCH_MODEL_MAX_OUTPUT_TOKENS` 8192，
   并对 length 结果做「关闭思维链 + 上限翻倍（8192→16384）」最多两次重试，日志 `research.model_output_length_retry`。
2. **引用偏移**：重叠分块被重复拼进窗口正文，`块起点 + 块内下标` 换算全文偏移错位（真实语料 12 条）。
   修复：`review_workflow._chunk_text_for_block` 改为区间**并集去重**并从 `block.text` 切片；新增 `test_review_locator.py`（4 条）。

两处修复后 14 篇全部重跑，得到 §9.1 的结果；修复前的 partial/错位记录保留在 `tmp/r2-corpus-eval-v3.json` 与历史审计 JSON。

### 10.3 真实浏览器 E2E 最终状态（2026-11-21 02:2x）

- `node scripts/research_e2e.mjs --keep` → **exit 0（PASS）**，139.3 s，控制台错误 0；含图表前端面板（识别 2 张表 → 生成 1351×963 → 校验信息）。
- 期间修掉两个环境级缺陷：`DISABLE_VECTOR_PREWARM`（预热线程饿死事件循环 → health 长时间不可达）与 `E2E_HEALTH_TIMEOUT_MS`（健康检查超时改为可配置，默认 180 s）。
- 因此 §2 中 AT-047 的"真实 Playwright 桌面已跑通"进一步固定为：**整脚本 exit 0、含图表前端**。

## 11. 附录：零成本验收第二轮（窄屏 / 键盘 / 双账号 / 删除撤权，2026-11-21 20:0x）

- 命令：`node scripts/research_e2e.mjs --a11y --keep` → **exit 0（PASS）**，新增三段真实浏览器断言（截图在 `tmp/e2e-evidence/a11y-01..03-*.png`）。
- 11.1 窄屏 390×844（`isMobile: true, hasTouch: true`）：`document.documentElement.scrollWidth = 409`、`window.innerWidth = 409` → **无横向溢出**；项目列表与工作区标题可见；图表卡片在窄屏下未渲染（无文档选中，属正常空态），布局卡片宽度均未超视口。
- 11.2 键盘可达：不注入脚本，仅用 `keyboard.press('Tab')` 从文档起点正向遍历（最多 80 次），命中文本/aria-label 含「新建项目」的按钮 → `Enter` 后 `document.activeElement.className` 含 `rw-input`（焦点落到新建项目输入框）→ `keyboard.type('键盘创建项目-XXXXXX')` + `Enter` → 该项目真实出现在项目列表。
- 11.3 双账号隔离：同一浏览器新 context 注册账号 B，进入 `#research` 后项目列表**不含**账号 A 的项目（含 A 用键盘创建的项目）；页面内 `fetch('/api/v1/research/projects/{A 的 id}')` 返回 **404**（统一 `NOT_FOUND`，不泄露存在性）。
- 11.4 删除撤权（AT-054）：`test_research_r2/test_deletion_revocation.py` 5 passed；R2 目录收集 **63 条**（62 passed + 1 skipped）。
- 11.5 E2E 脚本的两处判定细化（都为「不让环境噪音掩盖真实失败」）：
  1. 控制台错误分类：CodeMirror 等 jsdelivr 外链资源在离线环境必然失败，控制台文本不含 URL；脚本改用 `requestfailed` 的 URL 判定——**只有出现本项目源（web/`/api/v1/`）连接级失败时才失败**，否则把无 URL 的资源加载错误归因为外链并在日志打印外链主机。
  2. a11y 流程只把「非外链归因的 pageerror」计为失败（CodeMirror 未定义由外链失败连带产生），资源加载错误按条数记录供核对。
- 复跑数字：`pytest src/backend/tests/test_research_r2 -q` → **62 passed, 1 skipped（收集 63）**；`ruff check src/backend/tests/test_research_r2` → All checks passed；`node --check scripts/research_e2e.mjs` 通过。

## 12. 附录：基础图表与分类轴（R2.1，2026-11-21）

- 能力面：`CHART_TYPES` 由 12 种扩到 14 种（`bar`/`line`）。`bar`/`line` 的 x 轴为分类标签（第一列，原样保留），y 列必须有限数值；`x_column` 不是第一列 → 422 `CHART_TABLE_INVALID`。
- 数值保真：`x_labels` 单独返回（截断 200），**不进入** `value_ranges`；`data_digest` 由 `canonical_series_csv` 计算（标签参与摘要，改标签即变摘要）；PNG 仍走 `_verify_png`（签名 + IHDR），失败不落 Artifact。
- 中文可读性：`chart_render._configure_fonts()` 选 Microsoft YaHei / SimHei / Noto Sans CJK SC / Source Han Sans SC / WenQuanYi Zen Hei / PingFang SC，并设 `axes.unicode_minus=False`；实测生成的 PNG 中文标签正常、无方框（`describe_image` 复核）。
- 失败语义未变：能力关闭 503 `CHART_CAPABILITY_DISABLED`；分类表配 ribbon 等仍 422 `CHART_NON_NUMERIC`（`details.hint` 提示改用 `bar`/`line`）；渲染异常 500 `CHART_RENDER_FAILED`（`retryable=true`）且不落 Artifact。
- 测试：`src/backend/tests/test_research_r2/test_basic_charts.py` 6 条 + `test_charts_api.py` 的「不支持类型」改用 `radar`；R2 套件 **68 passed + 1 skipped**。
- 浏览器：`node scripts/research_e2e.mjs --keep` → exit 0；bar 断言通过（`x_labels` 3 个、PNG 49,891 B）；图表面板显示「分类轴」标注与 14 种类型。
- 仍存在的缺口：饼图未做；多单位共轴会压扁小量级系列；分类标签只做 45° 旋转，未自动换行。

## 13. 附录：私有全文检索的向量后端（FR-05，2026-11-21）

此前偏差是「向量检索未接」：`retrieval_service` 只支持调用方注入 provider，产品里没有任何真实 embedding 后端，`/capabilities` 还曾用「chromadb 依赖可导入 + 索引目录存在」冒充向量可用。

本轮改动：

| 层 | 落点 | 关键点 |
| --- | --- | --- |
| 后端 | `src/backend/research/embeddings.py`（新增） | `SentenceTransformerEmbeddingProvider`（惰性加载、`local_files_only`、归一化向量）、`local_model_available()`（只查 HF 缓存不联网）、`build_provider_from_settings()`；失败抛 `EmbeddingUnavailable(reason)` |
| 装配 | `src/backend/research/retrieval_service.py` | `configure_from_settings()` + `_ensure_provider()`：未配置模型保持词法；首次检索自动装配一次；`EmbeddingUnavailable` 映射为 `vector_backend_unavailable:<reason>` |
| 启动 | `src/backend/app.py` | lifespan 里按 settings 装配并记录 `research retrieval backend`（`lexical` / `sentence-transformers`），装配失败不阻断启动 |
| 能力 | `src/backend/research/capabilities.py` | `retrieval.vector` 重写：未配置模型 = `DEGRADED`（理由写明「使用词法匹配」）、模型未缓存且未允许下载 = `DEGRADED`、只有本机缓存（或显式允许下载）= `READY`；`detail` 公开 `embedding_model_configured`/`embedding_model_local`/`backend` |
| 接口 | `src/backend/routers/research.py` | 新增只读端点 `POST /api/v1/research/documents/{document_id}/search`（`query` 1–500、`version_id` 可选、`limit` 1–20）；响应含 `retrieval_method`/`degraded`/`degraded_reason`/`items`；未指定版本时用文档当前版本；无版本 422 `DOCUMENT_VERSION_MISSING` |
| 配置 | `src/backend/config.py` + `README.md` | `RESEARCH_EMBEDDING_MODEL`（默认空）、`RESEARCH_EMBEDDING_DEVICE`、`RESEARCH_EMBEDDING_BATCH_SIZE`、`RESEARCH_EMBEDDING_ALLOW_DOWNLOAD`（默认 `false`） |

验证（`src/backend/tests/test_research_r2/test_vector_retrieval.py`，9 条）：

- 默认无模型：`POST /documents/{id}/search` 返回 `retrieval_method="lexical"`、`degraded=true`、`degraded_reason` 非空，每条命中一致；能力为 `DEGRADED` 且理由含「词法」。
- 注入 provider：同一范围改走余弦，`retrieval_method="vector"`、`degraded=false`、`degraded_reason=null`，分数降序且落在 `[0,1]`。
- provider 抛 `EmbeddingUnavailable("embedding_model_not_cached")`：诚实降级，`degraded_reason` 保留机器可读原因。
- 真实本地模型（`BAAI/bge-small-zh-v1.5`，本机缓存）：能力 `READY`、`backend="sentence-transformers"`；编码向量归一化（模长 ≈ 1）且语义相近句子的余弦显著更高（>0.5）。
- 三套回归：**529 passed, 1 skipped**（324.16 s，含 R1 新增 2 条 `test_review_roles.py`）；`ruff check` 相关文件 All checks passed。

边界（不得夸大）：

- 默认仍是词法检索；只有显式配置模型才走向量，且不会联网下载（除非打开 `RESEARCH_EMBEDDING_ALLOW_DOWNLOAD`）。
- 检索是**请求内实时编码**（无持久化向量索引，也未接 ChromaDB），大文档首次检索会有模型加载耗时（本机 bge-small 约 20 s/进程，之后复用）。
- 未做混合排序（向量 + BM25 融合），也未做跨版本/跨文档检索；`search` 只在单个已授权版本内进行。

## 14. 附录：T23 预算闸门真实 A/B（2026-11-21）

- 工具：`tools/research_budget_ab.py`（同一份文档、同模型 `deepseek-v4-flash`、同提示词版本，只改受理预算）。
- 命令：`python tools/research_budget_ab.py --corpus tmp/r2-corpus --only p14-intelligent-communication --db tmp/budget-ab.db --out tmp/budget-ab.json --md docs/reports/R2_BUDGET_AB.md`
- 结果（`docs/reports/R2_BUDGET_AB.md`）：默认预算 160 calls / 100,000 tokens → **succeeded**，14 次调用 / 32,125 tokens，覆盖 69/69；tokens 收紧到 12,000 → **partial**，5 次调用 / 11,460 tokens，覆盖 18/69；调用收紧到 8 → **partial**，8 次调用 / 20,548 tokens，覆盖 31/69。
- 语义说明：闸门在「将要越界」前停止继续调用，因此三臂的 `budget_evaluation.state` 都是 `within`；越界的可见后果是覆盖不足并终态降为 `partial`，**没有任何一臂 succeeded**，符合 FR-15。
- 边界：单篇、单次测量，不是统计基准；`cost_usd` 仍为 `null`（未接供应商计费）。

## 15. 附录：T23 流程增益 A/B（single vs multi_role，2026-11-21）

- 新增流程：`constraints.review_mode`（`single` | `multi_role`，默认 `single`）。`multi_role` = 通用审稿一遍 + 「方法/证据核查员」再读一遍全文，两遍诊断项按（引文，问题）去重合并，覆盖取并集；两轮平分预算。
- 命令：`python tools/research_budget_ab.py --corpus tmp/r2-corpus --only p04-emotional-structure --modes single,multi_role --db tmp/flow-ab-20k.db --out tmp/flow-ab-20k.json --md docs/reports/R2_FLOW_AB.md`
- 20,017 码点样本：single succeeded（20 调用 / 47,943 tokens / 155.22 s / 109 条）；multi_role succeeded（40 调用 / 95,840 tokens / 314.88 s / 203 条）；两者覆盖均 158/158。
- 13,301 码点样本：single 14 调用 / 32,817 tokens / 70 条；multi_role 28 调用 / 64,853 tokens / 131 条；覆盖均 69/69。
- 维度变化：p14 的 `method` 从 0 条变成 13 条；p04 的 `method` 16→53、`evidence` 23→42。属可复现的行为差异，不等于质量提升（无真人标注）。
- 预算边界：p04 的 multi_role 用掉默认预算 95.8%；更长文档（p10 单遍已 98,824 tokens）两遍必然转 `partial`。因此默认 `single`，`multi_role` 仅作显式可选项。
- 测量中发现并修复：第二轮预算上限误用「份额」而非「已用+份额」，导致第二遍只跑 2 次调用却报 succeeded；修复后 40 调用 / 95,840 tokens / 覆盖 100%。回归用例 `src/backend/tests/test_research_r1/test_review_roles.py`（2 条）。


## 16. 附录：真实 PostgreSQL 恢复演练（2026-11-21）

- 环境：**PostgreSQL 16.4**（官方 Windows 便携版二进制，端口 55433，`lease_seconds=8`），非 SQLite、非替身。
- 脚本：`scripts/research_recovery_drill.py`；报告：`docs/reports/R2_RECOVERY_DRILL.md`。
- 结论：**PASS（8/8）**——迁移与 schema（15 张 research_* 表 + 4 个唯一约束、server 16.4）、领取即写 started、崩溃后租约过期被 attempt 2 接管、事件序号 `[1..7]` 单调且终态事件 1 条、Artifact 1 条、迟到写入被拒、重复投递 exactly-once、`stop -m immediate` 重启后状态一致。
- 演练中发现 3 个真实缺陷：
  1. `src/backend/services/entitlement_service.py` 的 `_extend_30_days` 返回 tz-aware datetime → asyncpg 写 `TIMESTAMP WITHOUT TIME ZONE` 报 `DataError`（SQLite 不校验，R0–R2 全程未暴露）；已改为 UTC naive。
  2. `EntitlementService.grant_product` 的 `source_ref` 若已属于另一用户会**静默 no-op**；已改为抛 `ValueError`。
  3. **R2-A13（FR-11）**：fencing token 只落库、未在写入路径校验——租约转移后旧 attempt 仍能 `append_event` 与 `transition`；已修复（`task_repository` 新增 `set_lease_scope`/`_enforce_fence`，`append_event`/`transition`/`close_attempt` 校验 token，冲突码 `STALE_ATTEMPT`；`task_runner.execute_task` 执行期绑定 token）。
- 回归：三套 `529 passed, 1 skipped in 371.35s`（R0 290 / R1 161 / R2 78），`ruff` 全绿。
- 未覆盖（如实声明）：Redis 真实断连重连（本机无 redis-server、Docker 引擎不可用）、Celery worker 被杀后 broker 重投（无 broker，研究域走进程内 dispatcher）、多机竞争。
- 残留风险：崩溃 attempt 行保留 `running`（按设计，回收靠 `lease_expires_at`）；从未达终态的任务可能残留 `reserved` 计费行（无独立 reaper）。
