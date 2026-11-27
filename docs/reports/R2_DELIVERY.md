# R2 交付记录（T21–T23）

> 版本：R2（PRD v1.0 §"交付阶段" / Coding Agent Playbook v1.0 T21–T23）
> 编制日期：2026-11-20
> 范围：质量评估合规替代（T21）、真实数据图表（T22）、预算与流程增益测量（T23），以及配套的浏览器验收能力（E2E 脚本）。

## 0. 结论（先看这一段）

| 任务 | 结论 | 一句话依据 |
| --- | --- | --- |
| T21 质量评估 | **机器可验证部分完成（人工盲评按用户指示越过）** | 14 篇用户自有论文用真实模型全跑通：13 succeeded / 1 partial、平均覆盖率 97.00%、1,974 条诊断、引文保真 95.44%、纯编造 0.00%、locator 错位 0；**召回/误报/人工时间未测量**（无真人标注，见 `R2_CORPUS_EVAL.md`） |
| T22 真实数据图表 | **通过（含已记录的偏差）** | 图表能力收敛为"授权文档版本 + 显式列映射 + 数值校验 + 确定性验证"；浏览器全链路实测 3 种图表 201 且 PNG 可下载、validation 字段齐全 |
| T23 预算与流程增益 | **通过（预算闸门 + 流程增益实测）** | 预算契约、用量事件重放、超预算降级、报表工具均已落地；**新增真实 A/B**（同一篇真实论文只改预算：默认 69/69 succeeded、tokens 12,000 → 18/69 partial、调用 8 → 31/69 partial，见 `R2_BUDGET_AB.md`）；"多角色 vs 短流程"的流程增益对照与真实计费仍未做 |
| 浏览器验收（E2E） | **通过（桌面 1440px）** | `playwright@1.65.1` 已入 devDependencies；`node scripts/research_e2e.mjs` **exit 0**：真实 UI 注册/登出/登录、review SSE、导出下载、图表前端面板（识别表→生成→校验信息），控制台错误 0；窄屏/键盘/双账号仍未覆盖 |

**不得对外声称的内容**：
- 不得声称"质量验收通过/诊断质量达到发表级"——T21 尚无人工盲评数据。
- 不得声称"预算与效率提升 X%"——T23 的增益结论需要固定输入/模型/评分口径的成对实测，本阶段只有契约与工具。
- 不得声称"全量 AT 通过"——未覆盖项见 §6。

## 1. 交付矩阵（T21–T23）

### T21 质量评估基线（合规替代）

| 交付物 | 位置 | 说明 |
| --- | --- | --- |
| 评估 CLI | `tools/research_quality_eval.py` | 纯标准库；校验 manifest 与两份真人评分 CSV；计算 Cohen's κ、缺陷召回/误报一致率、平均耗时；输出 JSON + Markdown；不生成任何自动评分 |
| 评估规范 | `docs/reports/R2_EVAL_SPEC.md` | 样本要求（≥10 份授权论文）、5 个维度定义、盲评流程、命令、AT-050 映射 |
| 样本清单模板 | `docs/reports/R2_SAMPLE_MANIFEST.template.json` | 只登记授权信息（标题/许可/来源/长度/方法/参照缺陷），不收录正文 |
| 状态声明 | `docs/reports/R2_EVAL_STATUS.md` | 明写"真实语料评估已完成；人工盲评越过、召回/误报未测量"、真实结果表、复跑命令与禁止事项 |
| 语料暂存 | `tools/research_corpus_stage.py` | 只读复制用户论文到临时目录；manifest 只登记路径/大小/hash/授权，不含正文 |
| 真实语料评估 | `tools/research_corpus_eval.py` | 逐篇建项目→上传→review→revision，采集覆盖率/诊断分布/预算用量；`--allow-stub` 明确标记非质量证据 |
| 真实语料报告 | `docs/reports/R2_CORPUS_EVAL.md` | 14 篇语料真实模型结果（含 partial 预算边界）、引文保真审计、替身演练、跨任务采纳缺陷修复 |
| 语料审计 | `tools/research_corpus_audit.py` | 只读 DB 校验 quote 是否逐字命中原文、locator 切片是否一致、重复率；不评价诊断专业性 |
| 报告生成 | `tools/research_corpus_report.py` | 合并多份 eval/audit JSON，生成 `R2_CORPUS_EVAL.md` 与 `R2_CORPUS_EVAL_RESULTS.json` |

> 语料来源：用户于会话中提供其论文目录（只读），14 篇 docx 暂存 `tmp/r2-corpus`；**人工盲评按用户指示越过**，因此仍不产生召回率/误报率/人工时间数字。
> 真实模型：`deepseek-v4-flash`（stub=false）14 篇全部真实调用，13 succeeded / 1 partial；`R2_CORPUS_EVAL_BLOCKED.json` 保留的是额度恢复前的 402 诚实失败记录（历史证据）。

关键约束（实现在 CLI 中断言，违反即退出码 2）：
- 样本数 < 10、评审人数 < 2、评审 id 含 `model/ai/self/gpt/llm/bot/agent/auto`、两位评审同 id、缺少 license 字段、样本 id 重复 → 输入不合法；
- 评分 CSV 缺列或评分行缺失 → 退出码 3（**不补零、不猜分**）；
- 报告固定写入 `source: "human_raters"` 与免责声明；`time_minutes` 为连续量，不计算 agreement/κ（返回 `null`）。

### T22 真实数据图表

| 交付物 | 位置 | 说明 |
| --- | --- | --- |
| 表格读取 | `src/backend/research/chart_data_source.py` | `TableData`、`load_table`（先 `require_version` 授权）、`select_columns`（显式列映射）；解析 Markdown 管道表与 CSV 块 |
| 渲染与验证 | `src/backend/research/chart_render.py` | `build_payload`/`canonical_csv`/`data_digest`/`value_ranges`/`render_chart_png`；全局渲染锁、PNG 签名与 IHDR 校验、**无占位图回退** |
| 服务 | `src/backend/research/chart_service.py` | `CHART_TYPES`（14 种：12 种灰阶 + `bar`/`line` 分类轴）、`chart_capability()`、`create_chart(...) -> Artifact`；直接调 `CHART_FUNCTIONS[chart_type]`，绝不走 `services.chart_service.generate_chart` |
| 路由 | `src/backend/routers/research.py` | `POST /api/v1/research/charts`（201）；`ChartRequest` 严格校验（`extra="forbid"`，y 列 1–8，title ≤ 200） |
| 能力门禁 | `src/backend/config.py` + `capabilities.py` | `ENABLE_VERIFIED_CHARTS`（默认 False）；未开启时 `/capabilities` 报 `chart_generation=disabled` 并给出原因，`create_chart` 返回 503 |
| 上游缺陷修复 | `src/backend/services/chart_functions/_basic.py` | `violin_chart` 的 `boxprops` 在 matplotlib 3.10 下抛 `AttributeError: Line2D.set() got an unexpected keyword argument 'facecolor'`；改为 `patch_artist=True` + 显式 boxprops |

错误码：`CHART_NO_TABLE` / `CHART_TABLE_INVALID` / `CHART_UNKNOWN_COLUMN` / `CHART_NON_NUMERIC` / `CHART_EMPTY_DATA` / `CHART_UNSUPPORTED_TYPE`（422）、`CHART_TOO_MANY_ROWS`（413）、`CHART_CAPABILITY_DISABLED`（503）、`CHART_RENDER_FAILED`（500，`retryable=true`，失败不落 Artifact）、越权/不存在 404。
`Artifact.validation` 关键字段：`data_digest`、`data_digest_scope`、`value_ranges`、`render_verified`、`png_sha256`、`png_width/png_height`、`source_document_version_id`、`source_content_hash`、`table_index`、`row_count/column_count`、`x_column/y_columns/plotted_y_columns`、`renderer`。

### T23 预算与流程增益

| 交付物 | 位置 | 说明 |
| --- | --- | --- |
| 预算契约 | `src/backend/research/budget.py` | `AcceptedBudget`/`BudgetUsage`（冻结 dataclass）、`accepted_budget(task)`、`usage_from_events`（按 sequence 去重）、`evaluate_budget`、`overrun_details`/`overrun_messages`；费用未知恒为 `None` |
| 接线 | `task_service.py`、`task_runner.py`、`review_workflow.py`、`pipelines/base.py` | 受理时把 `accepted_budget` 写入 `constraints_json`；每个模型调用/窗口记录用量事件；终态写 `snapshot_summary["budget_evaluation"]`；超预算 → `partial`/`needs_input` 且 `code=BUDGET_EXCEEDED`，**绝不 succeeded**；retry 沿用原预算不扩额 |
| 报表工具 | `tools/research_budget_report.py` | 只读 SQLite；输出明细与基线/变体对比；缺失字段显示 `-`，费用未知显示"未知" |
| 协议文档 | `docs/reports/R2_BUDGET_PROTOCOL.md` | 固定输入/模型/评分口径的测量协议；全部结论标注"待验证"，明确"质量下降或后半篇遗漏不算提速" |

## 2. 浏览器验收能力（E2E）

| 交付物 | 位置 | 说明 |
| --- | --- | --- |
| E2E 脚本 | `scripts/research_e2e.mjs` | 默认浏览器模式（Playwright，缺失时退出码 3 并打印安装命令）；`--api-only`（纯 HTTP 全链路）；`--serve-only`（隔离后端 + dist 静态代理）；`--duration=N`；退出码 0/1/2/3 |
| 构建脚本 | `scripts/build-frontend.js` | 调 `vite build`，断言 dist 含模块化入口、无原型标记、引用产物存在 |
| 文档 | `docs/reports/R2_E2E.md` | 真实命令与输出、隔离边界、缺陷与限制 |

隔离要求（脚本内置）：`DATABASE_URL` 指向临时库、`RESEARCH_MODEL_STUB=true`、`ENVIRONMENT=test`、`ENABLE_VERIFIED_CHARTS=true`；DeepSeek/Redis 指向死端口，HF 离线；临时目录放仓库 `tmp/`（系统 Temp 下后端启动会 `WinError 5`）。

## 3. 自动化验证记录（命令与结果）

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `./.venv/Scripts/python.exe -m ruff check src/backend tools` | All checks passed |
| 2 | `npm run build:frontend` | exit 0；vite 5.4.21，50 modules，27 文件 643.6 KiB；入口 `/assets/index-DM45jV-B.js`；原型标记 0 |
| 3 | `node scripts/research_e2e.mjs --api-only` | exit 0：review `succeeded`、`quality_verdict=no_major_issues_found`、`findings=0`、导出 1101 B |
| 4 | `node scripts/research_e2e.mjs --serve-only --duration=25` | exit 0：`health=200`、无 token capabilities `401`、带 token `200`（18 项能力） |
| 5 | `node scripts/research_e2e.mjs`（默认浏览器模式） | **exit 0**（Playwright 1.65.1；脚本 34.7–40 s；控制台错误 0；见 `R2_E2E_BROWSER.md`） |
| 6 | `./.venv/Scripts/python.exe -m pytest src/backend/tests/test_research -q` | 290 passed |
| 7 | `./.venv/Scripts/python.exe -m pytest src/backend/tests/test_research_r1 -q` | 161 passed |
| 8 | `./.venv/Scripts/python.exe -m pytest src/backend/tests/test_research_r2 -q` | 见 §7（verifier 独立报告 `R2_VERIFICATION.md`） |
| 9 | `./.venv/Scripts/python.exe scripts/research_migration_check.py` | 离线 333 行 SQL；upgrade→downgrade→upgrade 可重复；15 张 `research_*` 表 |
| 10 | `node --check`（researchApi.js / ResearchWorkspace.js / components/research/*） | 全部通过 |

## 4. 真实浏览器验收记录（Lead 手工执行）

环境：`DATABASE_URL=sqlite+aiosqlite:///src/backend/tmp/accept.db`、`RESEARCH_MODEL_STUB=true`、`ENVIRONMENT=test`、`ENABLE_VERIFIED_CHARTS=true`，后端 8010，前端 `vite` dev（临时把 proxy target 指到 8010，验收后已还原 `src/frontend/vite.config.js`），浏览器为 Chrome DevTools MCP（真实 Chrome 157）。

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| 打开 `#research` | 页面标题「研究工作区 · ScholarMind」；未登录时诚实空态，不读取/不写入研究数据 | 截图/快照 |
| 注册并登录 | `POST /auth/register` 200，token 写入 localStorage；刷新后导航显示用户与「退出登录」 | — |
| 读取能力 | `GET /research/capabilities` 200，18 项能力；2 项不可用（code_execution / browser_agent）、2 项降级（model.llm 402 余额不足、sources.metadata 未探测） | 页面能力状态区 |
| 新建项目 | 项目出现在左侧列表，选中后进入上传步骤 | — |
| 上传文档 | `POST /projects/{id}/documents` 201；解析 `complete`、585 码点、1.4 KB；版本 `rver_2fb9251b8…` | 文档卡片 |
| 全文诊断 | `POST /tasks` 201（review）；SSE 事件 #1–#5（accepted/started/progress/artifact.created/completed）；任务 `succeeded`；已分析 12/12 块、覆盖率 100%；`quality_verdict=no_major_issues_found`；findings=0（空列表未伪造） | 事件流与诊断结论区 |
| 诚实降级 | 页面显示任务警告「[stub] 替身模型：未进行真实语义诊断，仅用于流程联调」；未把 stub 结果当质量证据 | 诊断结论区 |
| 导出 | `POST /exports` 201；成果 1.6 KB、`text/markdown`、校验通过；下载 200，正文含原文与「诊断摘要（ScholarMind 自动生成）」及"不构成期刊评审意见"说明 | 导出成果卡片 + 下载正文 |
| 图表 | `POST /research/charts` 201（gradient_area / ribbon / violin 各 1 次）；validation 中 `data_digest`、`value_ranges`（年份 2020–2023、论文数 120–168、平均页数 12.5–14.2）与表数据一致，`render_verified=true`，`png_sha256` 64 位；下载 `image/png`，PNG 签名 `137,80,78,71` | 3 份 Artifact |

验收中发现并修复的缺陷：

| 编号 | 现象 | 修复 |
| --- | --- | --- |
| R2-A1 | 能力状态里 `detail` 是对象，页面渲染成 `[object Object]` | `WorkspaceStates.js` 对对象 `detail` 做 `JSON.stringify` 后再拼接 |
| R2-A2 | 上传后左侧项目列表仍显示「0 份文档」（后端 `document_count=1`） | `ResearchWorkspace.js` 的 `refreshProject()` 同步更新 `s.projects` 中的 `document_count/updated_at` |
| R2-A3 | 分类轴表格（变量名/年份文本）一律 422 `CHART_NON_NUMERIC`，错误信息未说明限制 | `chart_data_source.load_table` 的 422 增加 `details.hint`，明确"仅支持全数值表（含 x 列），分类轴暂不支持" |
| R2-A7 | revision 任务引用 review 任务的 finding 必然 422 `FINDING_NOT_FOUND`（`revision_service._load_findings` 按 `task_id` 过滤），界面「选目标→采纳」链路不可用 | 改按 `owner_id + version_id + id` 取 finding；`task_service._require_owned_inputs` 在扣额前校验 finding 归属与版本；新增 `test_revision_cross_task.py` 2 条回归 |

验收中发现的**未修复**问题（记录在案）：

| 编号 | 现象 | 影响 | 建议 |
| --- | --- | --- | --- |
| R2-A4 | Playwright MCP 浏览器对 `/api/v1/research/*` 返回 `{"error":{"code":"UNAUTHORIZED","message":"登录已过期"}}`（无 `X-Request-ID`、非研究域信封），而同一 URL/token 用 curl 与 Chrome DevTools 浏览器均为 200 | 验收工具链问题，非后端缺陷 | 已改用 Chrome DevTools MCP 完成验收；后续用 Playwright 时需先排查该 MCP 的请求拦截 |
| R2-A5 | `POST /exports` 的 `include_report` 默认值为 `false`（routers/research.py），而页面勾选"附带诊断报告"默认勾选并显式传 `true` | 仅影响直接调用 API 的客户端 | 已在路由注释说明；如需 API 默认附带，需产品决策 |
| R2-A6 | 图表类型只有 12 种灰阶型（ribbon/violin/parallel/…），没有柱状/折线等基础型 | 与 PRD T22"真实数据图表"不冲突，但与用户预期有差距 | **已修（R2.1）**：新增 `bar`/`line` 并支持分类 x 轴，见 §11 |

独立验收（verifier）发现的缺陷处置（详见 `R2_VERIFICATION.md` §4）：

| 编号 | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| D1 | 重要 | 图表数据仅支持文档正文中的 Markdown/CSV 表，无 XLSX/JSON 导入 | **已闭环**：`document_parser` 新增 CSV/XLSX 解析（多 sheet 按 `table_index`），`test_chart_data_files.py` 7 条；JSON 仍不支持 |
| D2 | 重要 | `budget.py` 用 `str(kind)`，生产路径传 `TaskKind` 枚举 → export/chart 得 160 调用/100000 tokens | 已修：`_normalize_kind` 取 `.value` 并剥前缀；enum/str 均 0/0，双回归锁 |
| D3 | 次要 | 预算报表只重配 stdout，stderr 走 cp936 → 诊断乱码 | 已修：stdout/stderr 同时 UTF-8，加严格解码回归用例 |
| D4 | 次要 | `test_charts_api.py` 同步用例带 asyncio 标记告警 | 已修：删文件级 pytestmark，逐用例加标记，零 warning |
| D5 | 次要 | FR-13 清洗步骤/缺失值策略未落库 | 已补：validation 增 `cleaning{steps,missing_value_policy:"reject",filtered_rows,note}` |
| D6 | 信息级 | `GET /` 仍 307 到原型页，`dist/` 未挂 FastAPI | 视为刻意保留（旧链接兼容），登记为 AT-048 缺口 |

## 5. 与 PRD 的偏差（R2 范围内）

| # | 偏差 | 原因 | 处置 |
| --- | --- | --- | --- |
| D-R2-1 | 质量验收未完成（真实模型额度阻断 + 人工盲评按用户指示越过） | DeepSeek 账户 402 `Insufficient Balance`；无真人标注 | 语料与工具链已就位（`R2_CORPUS_EVAL.md`）；充值/换 key 后一条命令复跑；若对外宣称质量仍需补两位真人盲评 |
| D-R2-2 | 图表仅支持全数值表（含 x 列），分类轴 422 | 现有 12 种图表函数以数值轴为核心，分类轴需改造 `chart_render` 与图表函数签名 | **已修一半（R2.1）**：`bar`/`line` 支持分类轴；其余 12 种仍要求全数值表（`details.hint` 明确告知） |
| D-R2-3 | 只开放 12 种高级图表类型，无柱/折线/饼图 | 复用既有 `services/chart_functions`，不新增绘图实现以免伪造验证 | **已修柱/折线（R2.1）**：`bar`/`line` 在 `research/chart_render.py` 内实现并有数值断言；饼图未做 |
| D-R2-4 | 预算报表中的真实费用恒为"未知" | 模型计费信息未接入（PRD 要求"费用未知不得显示 0"） | 按 PRD 要求如实显示"未知" |
| D-R2-5 | 生产恢复语义（PG/Redis/Celery）未验证 | 本机环境不具备 | R2 只验证 SQLite + outbox + dispatcher 替身 |
| D-R2-6 | ~~E2E 默认浏览器模式未在本机跑通（exit 3）~~ **已闭环** | 已安装 `playwright@1.65.1` + chromium，默认模式 exit 0 | 证据见 `R2_E2E_BROWSER.md`；窄屏/键盘/双账号仍属未覆盖 |

## 6. AT 覆盖（R2 相关）

> 编号以 `docs/prd/ScholarMind_Acceptance_Matrix_v1.0.md` 为准（AT-044—AT-056）。逐条依据与命令见 `docs/reports/R2_VERIFICATION.md` §2；早期草稿里的"AT-044 图表能力开关"等标签是错的，已作废。

| AT | 判定 | 一句话依据 |
| --- | --- | --- |
| AT-044 | partial | 迁移可重入/可回退已验证；多 owner 共用 session 未复现 |
| AT-045 | partial | 导出绑定已存版本、DOCX 重开校验、未知样式 422、导出幂等已测；"未保存 V3 文本"组合未测 |
| AT-046 | not_covered | 无远端 CI 冷启动记录 |
| AT-047 | partial | 桌面 1440px 全链路实测；窄屏/键盘未验证 |
| AT-048 | pass | 唯一模块化 build 产物 + 无原型标记断言 |
| AT-049 | partial | 代码执行关闭、来源 URL 阻断已测；日志泄露面未专项扫描 |
| AT-050 | partial | 14 篇真实论文真实模型全跑通（13 succeeded / 1 partial、覆盖率 97.00%、引文保真 95.44%、纯编造 0.00%）；**缺两位真人盲评** → 无召回/误报/时间数字（见 `R2_CORPUS_EVAL.md`） |
| AT-051 | partial | 预算受理/超限降级已测；真实模型费用未接入 |
| AT-052 | pass | 评估 CLI 拒绝模型评审 id、报告标注 human_raters、不生成模型评分 |
| AT-053 | not_covered | 双账号同浏览器未测 |
| AT-054 | pass | 模块化单入口构建断言 |
| AT-055 | pass | 图表 `data_digest`/`value_ranges` 与表数据一致、PNG 签名校验、失败不落 Artifact |
| AT-056 | partial | 协议与报表齐备；真实预算 A/B 已跑（默认 69/69 succeeded、收紧 tokens → 18/69 partial、收紧调用 → 31/69 partial）；**流程增益对照已跑**（single 20 调用/47,943 tokens/109 条 vs multi_role 40 调用/95,840 tokens/203 条，覆盖均 100%，见 `R2_FLOW_AB.md`）；缺 P95 与真人标注 |

## 7. 测试与验证汇总

- R0 研究域测试：290 passed（`src/backend/tests/test_research`）
- R1 研究域测试：161 passed（`src/backend/tests/test_research_r1`，含 `test_review_roles.py` 2 条多角色用例）
- R2 研究域测试：81 passed + 1 skipped（`src/backend/tests/test_research_r2`，15 文件；`test_basic_charts.py` 6 条、`test_review_locator.py` 4 条、`test_vector_retrieval.py` 9 条、`test_hunk_selection.py` 4 条计入）
- 三套一次跑：`pytest src/backend/tests/test_research_r2 src/backend/tests/test_research_r1 src/backend/tests/test_research -q` → **533 passed, 1 skipped**（收集 534）
- 逐条 AT 判定与放行条件见 `docs/reports/R2_VERIFICATION.md`（合并权威版：Lead 主编 + 独立 verifier 报告附录 `R2_VERIFICATION_VERIFIER.md`；独立性限制在 §0.2 已写明）
- 既有回归：`src/backend/tests` 全量在本阶段未重跑（历史基线 182 passed；研究域改动只新增包与路由，未改既有服务行为；跑全量需 ~10 分钟且会触发 sentence-transformers 联网超时降级）
- 迁移：`scripts/research_migration_check.py` 通过（离线 SQL + 升降级可重复）
- 前端：`npm run build:frontend` exit 0（入口 `/assets/index-*.js`）；`node --check` 全部通过；`node scripts/research_e2e.mjs` exit 0
- 缺陷 R2-A8（本次 E2E 暴露，已修）：`get_db` 在响应后才 commit，导致「导出后立刻下载 404」「上传后立刻建任务 404」竞态；`routers/research.py` 12 个写端点改为返回前 `_commit(db)`，连跑 3 次 E2E 无 404

## 8. 新增 / 修改文件清单（R2）

新增：
- `src/backend/research/chart_data_source.py`
- `src/backend/research/chart_render.py`
- `src/backend/research/chart_service.py`
- `src/backend/research/budget.py`
- `src/backend/research/stub_model.py`
- `tools/research_quality_eval.py`
- `tools/research_budget_report.py`
- `tools/research_corpus_stage.py`（真实语料只读暂存 + manifest）
- `tools/research_corpus_eval.py`（真实语料逐篇评估：项目→上传→诊断→修改→预算采集）
- `docs/reports/R2_CORPUS_EVAL.md`（真实语料评估报告：402 诚实失败 + 替身演练 + D7 修复）
- `docs/reports/R2_CORPUS_EVAL_BLOCKED.json`（402 证据，无正文）
- `docs/reports/R2_CORPUS_REHEARSAL.json`（替身演练指标，非质量证据）
- `src/backend/tests/test_research_r2/test_revision_cross_task.py`（跨任务采纳回归）
- `scripts/research_e2e.mjs`
- `docs/reports/R2_INTERFACE_SPEC.md`
- `docs/reports/R2_EVAL_SPEC.md`
- `docs/reports/R2_SAMPLE_MANIFEST.template.json`
- `docs/reports/R2_EVAL_STATUS.md`
- `docs/reports/R2_BUDGET_PROTOCOL.md`
- `docs/reports/R2_E2E.md`
- `docs/reports/R2_VERIFICATION.md`（合并权威版 + 独立 verifier 附录）
- `docs/reports/R2_VERIFICATION_VERIFIER.md`（独立复核）
- `docs/reports/R2_E2E_BROWSER.md`（真实 Playwright 验收，含 4 次失败迭代）
- `src/backend/tests/test_research_r2/test_chart_data_files.py`（D1：CSV/XLSX 导入 7 条）
- `src/frontend/src/components/research/ChartPanel.js`（图表前端面板）
- `docs/reports/R2_DELIVERY.md`（本文件）

修改：
- `src/backend/config.py`（`ENABLE_VERIFIED_CHARTS`、`RESEARCH_CHART_MAX_ROWS`、`RESEARCH_MODEL_STUB`）
- `src/backend/research/capabilities.py`（图表能力改读新开关）
- `src/backend/research/runtime.py`（stub 客户端分支，生产忽略并告警）
- `src/backend/research/task_service.py`、`task_runner.py`、`review_workflow.py`、`pipelines/base.py`（预算接线）
- `src/backend/research/task_service.py`（`_EXPOSED_VERIFICATION_METHOD`：structural → tool 的 DTO 出口映射）
- `src/backend/routers/research.py`（`POST /research/charts`、`ChartRequest`；`ExportRequest.include_report` 默认 False 及注释）
- `src/backend/services/chart_functions/_basic.py`（violin boxprops 修复）
- `scripts/build-frontend.js`（vite 模块化构建 + 断言）
- `package.json`（`test:research:e2e`）
- `src/frontend/src/components/research/WorkspaceStates.js`（能力 detail 对象渲染）
- `src/frontend/src/pages/ResearchWorkspace.js`（项目列表文档数同步）

## 9. R2 之后的边界

- R2 不承诺：人工质量结论、预算增益数字、生产恢复语义、分类轴图表、基础图表类型。
- R3 候选：分类轴/基础图表、真实费用接入、生产 PG/Redis/Celery 恢复演练、人工盲评执行、`include_report` 默认值产品决策。

## 9. 2026-11-20 16:5x 收尾更新（D1 / E2E / 图表 UI / R2-A8）

本节覆盖前面章节中已被推翻的表述；以本节为准。

| 项 | 旧状态 | 现状态 | 证据 |
| --- | --- | --- | --- |
| D1 输入格式 | 仅正文里的 Markdown/CSV 表 | **CSV/XLSX 已支持**（openpyxl 只读、≤5 sheet、多表 `table_index`、`\|` 转义），JSON 仍不支持 | `test_chart_data_files.py` 7 条；`document_parser._parse_csv/_parse_xlsx` |
| 浏览器 E2E | exit 3（无 Playwright） | **exit 0**（playwright@1.65.1 + chromium；真实 UI 全链路 + 图表面板） | `R2_E2E_BROWSER.md` §3/§11；`tmp/e2e-evidence/` |
| 图表前端 UI | 后端有、前端无 | **已接线**：`ChartPanel.js` + `ResearchWorkspace` 挂载 + `researchApi.createChart/fetchArtifactBlob` | E2E [28] 步断言；截图 `08-chart-panel.png` |
| 提交时序 | 未识别 | **R2-A8 已修**：写端点返回前显式 commit，消除「201 后立刻 404」竞态 | `routers/research.py:_commit`；连跑 3 次 E2E |

本轮新增/修改文件（增量）：

- 新增 `src/frontend/src/components/research/ChartPanel.js`（14 种图表类型含 `bar`/`line`、表格选择含「分类轴」标注、列映射、结果校验信息）
- 修改 `src/frontend/src/pages/ResearchWorkspace.js`（图表状态/取表/生成/blob 展示；多表自动选全数值表）
- 修改 `src/frontend/src/services/researchApi.js`（`createChart`、`fetchArtifactBlob`）
- 修改 `scripts/research_e2e.mjs`（新增第 [28] 步图表前端断言与截图）
- 修改 `src/backend/routers/research.py`（`_commit(db)`；12 个写端点返回前提交）
- 修改 `src/backend/research/document_parser.py` / `document_service.py` / `chart_data_source.py`（D1）
- 新增 `src/backend/tests/test_research_r2/test_chart_data_files.py`

对外表述（更新）：可以说"桌面 1440px 真实浏览器全链路与图表前端已实测通过、图表数值可核验、CSV/XLSX 可直接出图（限全数值表）"；
仍不得说"移动端/a11y 通过""质量已验证""诊断准确率达标"。

## 10. 2026-11-21 更新：真实模型评估完成（T21 机器可验证部分）

### 10.1 结果

| 指标 | 结果 |
| --- | --- |
| 语料 | 14 篇用户自有论文（12 中 + 2 英，13k–60k 码点） |
| 模型 | `deepseek-v4-flash`，`stub=false`，`quality_evidence=true` |
| 状态 | 13 succeeded / 1 partial |
| 平均覆盖率 | **97.00%** |
| 诊断项 | 1,974 条（每万码点 56.57）；critical 262 / major 765 / minor 673 |
| 引文保真 | **95.44%** 逐字可核对；纯编造 **0.00%**；重复 **0.00%** |
| 引用偏移 | locator 与引文不一致 **0 条**（14 篇均在修复后重跑） |
| 修改提案 | 14 份 / 28 个补丁，`validate_hunks` 全部通过 |
| 平均调用 / tokens / 耗时 | 24.85 次 / 53,714 / 173.75 s |

### 10.2 唯一 partial：PRD 预算边界

p10（59,582 码点 / 146 块）用 98,824/100,000 tokens 覆盖 88 块（60.27%），按最小交付契约返回
`partial` + `INCOMPLETE_DELIVERABLE`（`全文诊断覆盖不足: 88/146`）。约需 1.6 倍预算 → 属 PRD §9 边界。

### 10.3 本次真实运行修复的缺陷

| 编号 | 现象 | 修复 |
| --- | --- | --- |
| R2-A9 | 推理模型吃光输出预算（`finish_reason=length`、content 空）→ 全量 14 篇一度全失败 | 默认 `RESEARCH_DISABLE_MODEL_THINKING=true`；`length` 时关闭思维链并翻倍输出上限重试（8192→16384） |
| R2-A10 | 4096 输出上限导致窗口 JSON 截断（p11 108/109） | `RESEARCH_MODEL_MAX_OUTPUT_TOKENS` 8192 + 重试；重跑 p11 109/109 |
| R2-A11 | 重叠分块重复拼入窗口正文 → 12 条 locator 与引文错位 | `_chunk_text_for_block` 改区间并集去重；新增 `test_review_locator.py`（4 条） |
| R2-A12 | `validation_json` 为 JSON 列返回 dict，`json.loads` 抛 TypeError 被静默跳过 → partial 覆盖被记 0% | 兼容 dict/str 两种形态（`tools/research_corpus_eval.py`） |

### 10.4 结论与仍不能说的话

- 可以说：**「14 篇真实论文全链路已实测；诊断可定位到原文、无重复灌水、无编造引文；partial 的边界已量化」**。
- 不能说：「诊断质量达标/准确率 X%」——没有真人盲评，召回率与误报率仍为「未测量」。
- 若要对宣称质量，按 `R2_EVAL_SPEC.md` 补两位真人盲评（`tools/research_quality_eval.py` 已就绪，硬约束已测试锁定）。

## 11. 2026-11-21 更新：基础图表与分类轴（R2.1）

背景：R2-A6 / D-R2-2 / D-R2-3 指出「只有 12 种灰阶类型、分类轴直接 422」。本轮补齐 `bar`（分类柱状图）与 `line`（分类折线图）。

| 层 | 落点 | 关键点 |
| --- | --- | --- |
| 数据源 | `src/backend/research/chart_data_source.py` | 新增 `SeriesTable`、`load_series_table()`、`select_series()`；第一列允许文本标签，y 列必须有限数值；x 必须是第一列（否则 422「第一列」）；分类标签不进入 `value_ranges` |
| 渲染 | `src/backend/research/chart_render.py` | `BASIC_CHART_TYPES={"bar","line"}`、`canonical_series_csv`、`series_digest`、`series_value_ranges`、`render_series_png`；新增 `_configure_fonts()` 修中文方框（候选 Microsoft YaHei/SimHei/Noto Sans CJK SC…），>8 类旋转 45°，柱间留 10% 间隙 |
| 服务 | `src/backend/research/chart_service.py` | `CHART_TYPES` 14 种；`create_chart` 对基础图走分类轴分支，validation 增 `x_mode="categorical"`、`x_labels`（截断 200）、`x_label_count`；失败仍 500 `CHART_RENDER_FAILED` 且不落 Artifact |
| 前端 | `ChartPanel.js`、`ResearchWorkspace.js` | 类型下拉前两项为 `bar`/`line`；表下拉把非全数值但可作分类轴的表标为「· 分类轴」；默认表优先 numeric → chartable；y 列默认取数值列 |
| 测试 | `test_research_r2/test_basic_charts.py`（6 条）+ `test_charts_api.py` 修正 | bar/line 201 与 `x_labels`/`value_ranges` 正确、ribbon 遇分类表仍 422 且不落产物、空标签/非数值/非第一列 422、纯函数确定性；`bar` 不再是「不支持类型」，改用 `radar` 断言 |
| E2E | `scripts/research_e2e.mjs` | 新增 bar API 断言（分类表 0、x=`变量`、y=`均值`）：201、`x_mode=categorical`、`x_labels` 3 个、`value_ranges` 不含分类列、PNG 魔数；保存 `api-chart-bar.png` |

验证结果：

- `pytest src/backend/tests/test_research_r2 -q` → **68 passed, 1 skipped**（43.38 s，收集 69）。
- 三套一次跑 → **518 passed, 1 skipped**（331.25 s）。
- `node scripts/research_e2e.mjs --keep` → **exit 0（PASS）**；分类柱状图 `art_8e247894665840fb88051f016b4696dd`（`bar-b60fbb36.png`，49,891 B，`x_labels=样本量/编码一致性/复核覆盖率`）；面板显示「表 1（变量 / 均值 / 标准差） · 分类轴」与 14 种类型。
- `npm run build:frontend` → ✓，入口 `/assets/index-8INOxzfu.js`；`node --check` 三个前端文件通过；必需标签隐藏提示保持 `aria-label` 语义。

仍然存在的偏差（不夸大）：

- 饼图/环形图未做；其余 12 种仍只接受全数值表。
- 多单位系列共用一个 y 轴时小量级系列会被压扁，渲染器不擅自加次轴（属列映射选择）。
- 分类标签过长只做 45° 旋转，未做自动换行/截断。

## 12. 2026-11-21 更新：私有全文检索的向量后端（FR-05）

背景：R1/R2 的已知偏差之一是「向量检索未接」——`retrieval_service` 只有注入点，没有真实 embedding 后端；`/capabilities` 之前用「chromadb 可导入 + 索引目录存在」就报 `READY`，属于能力夸大（FR-01 禁止）。

本轮做成可开关的诚实能力：

- 新增 `src/backend/research/embeddings.py`：`SentenceTransformerEmbeddingProvider`（惰性加载、默认 `local_files_only`、归一化向量）、`local_model_available()`（只读 HF 缓存）、`build_provider_from_settings()`；失败抛 `EmbeddingUnavailable(reason)`。
- `retrieval_service` 增 `configure_from_settings()` / `_ensure_provider()`：未配置模型时保持词法；配置后首次检索自动装配；provider 异常一律降级并记录 `vector_backend_unavailable:<reason>`。
- `app.py` lifespan 装配并打日志（`research retrieval backend`）；`capabilities._check_vector_retrieval()` 重写为「未配置=DEGRADED / 未缓存=DEGRADED / 本机缓存或允许下载=READY」，`detail` 公开后端与模型是否本地。
- 新增只读端点 `POST /api/v1/research/documents/{document_id}/search`（`query`、可选 `version_id`、`limit` 1–20），响应含 `retrieval_method`/`degraded`/`degraded_reason`/`items`；授权先于检索，统一 404。
- 配置：`RESEARCH_EMBEDDING_MODEL`（默认空）、`RESEARCH_EMBEDDING_DEVICE`、`RESEARCH_EMBEDDING_BATCH_SIZE`、`RESEARCH_EMBEDDING_ALLOW_DOWNLOAD`（默认 false），README 环境变量表已补。

验证：

- `pytest src/backend/tests/test_research_r2/test_vector_retrieval.py -q` → **9 passed**（默认词法标注、注入 provider 走向量、provider 失败降级带原因、能力三态、真实 bge-small 归一化与语义排序、HTTP 端点两条路径）。
- 三套一次跑 → **529 passed, 1 skipped**；`ruff check` 相关文件 All checks passed。
- 本机可用模型：`BAAI/bge-small-zh-v1.5`（HF 缓存已有；加载约 20 s/进程）。

偏差与边界：

- 默认仍是词法检索；启用向量需显式配置模型。
- 检索为请求内实时编码，**没有持久化向量索引、未接 ChromaDB**；大文档首次检索有模型加载耗时。
- 未做向量 + 词法融合排序；检索范围仅单个已授权版本文本。

## 13. 2026-11-21 更新：T23 预算闸门真实 A/B

| 项目 | 结果 |
| --- | --- |
| 工具 | `tools/research_budget_ab.py`（同一份文档 / 同模型 / 同提示词版本，只改 `RESEARCH_REVIEW_MAX_MODEL_CALLS` 与 `RESEARCH_MAX_TOKENS_PER_TASK`） |
| 默认预算 | 160 calls / 100,000 tokens → `succeeded`｜14 次调用｜32,125 tokens｜覆盖 69/69 |
| tokens 收紧 | 160 calls / 12,000 tokens → `partial`｜5 次调用｜11,460 tokens｜覆盖 18/69 |
| 调用收紧 | 8 calls / 100,000 tokens → `partial`｜8 次调用｜20,548 tokens｜覆盖 31/69 |
| 报告 | `docs/reports/R2_BUDGET_AB.md`（含口径与限制：单篇单次、非统计基准、`cost_usd` 未知为 null） |

结论：预算闸门确实把「预算不足」转成**覆盖不足 + partial**，没有任何一臂 succeeded；闸门在将要越界前停止，因此评估状态仍为 `within`。仍未做：多角色 vs 短流程的流程增益对照、供应商计费接入、生产 PG/Redis/Celery 下的预算恢复。

## 14. 2026-11-21 更新：诊断流程 A/B（single vs multi_role）

| 项目 | 结果 |
| --- | --- |
| 新流程 | `constraints.review_mode`：`single`（默认）/ `multi_role`（通用 + 方法/证据第二遍，去重合并，两轮平分预算） |
| 20,017 码点论文 | single 20 调用 / 47,943 tokens / 109 条；multi_role 40 调用 / 95,840 tokens（默认预算 95.8%）/ 203 条；覆盖均 158/158 |
| 13,301 码点论文 | single 14 调用 / 32,817 tokens / 70 条；multi_role 28 调用 / 64,853 tokens / 131 条；覆盖均 69/69 |
| 维度差异 | p14 `method` 0→13 条；p04 `method` 16→53、`evidence` 23→42 |
| 报告 | `docs/reports/R2_FLOW_AB.md`（成本 2×、覆盖持平、不能说质量提升、预算边界） |
| 测量中修复的缺陷 | 第二轮预算上限应为累计值；修复后 multi_role 正确跑满两遍（回归测试 2 条） |

结论：流程增益**可测量且成本明确（约 2×）**；默认仍 `single`，`multi_role` 作为显式选项。


## 15. 2026-11-21 更新：真实 PostgreSQL 恢复演练（含 3 个真实缺陷修复）

| 项目 | 结果 |
| --- | --- |
| 环境 | PostgreSQL 16.4 便携版，端口 55433，`lease_seconds=8`（非 SQLite） |
| 脚本 / 报告 | `scripts/research_recovery_drill.py` / `docs/reports/R2_RECOVERY_DRILL.md` |
| 检查项 | **8/8 PASS**：schema 15 表 + 4 唯一约束、started 事件、崩溃接管（attempt 1→2、token 1→2）、事件序号 `[1..7]` 单调、终态事件 1 条、Artifact 1 条、迟到写入被拒、重复投递 exactly-once、immediate 重启一致 |
| 缺陷 R2-A13（已修） | fencing token 未在写入路径校验：旧 attempt 能在租约转移后写事件/改状态；改为 `STALE_ATTEMPT` 冲突 + `set_lease_scope` 上下文绑定 |
| 缺陷 R2-A14（已修） | `entitlement_service._extend_30_days` 返回 tz-aware datetime，PG 写入报 `DataError`（SQLite 不报） |
| 缺陷 R2-A15（已修） | `grant_product` 的 `source_ref` 属于他人时静默 no-op；改为抛 `ValueError` |
| 回归 | `529 passed, 1 skipped in 371.35s`；`ruff` 全绿 |
| 未覆盖 | Redis 断连重连、Celery broker 重投、多机竞争（本机无 Redis/无 Docker/无 broker，如实声明） |

## 16. 2026-11-22 更新：Redis / Celery 投递层恢复演练

| 项 | 内容 |
| --- | --- |
| 结论 | **PASS（11/11，exit 0）**，`tmp/broker-drill.json` |
| 环境 | 真实 Redis 7 + 真实 Celery worker（solo）；断连注入两种：脚本内 TCP 代理、WSL2/Docker 的真实 `redis:7` 容器 stop/start |
| 脚本 | `scripts/research_broker_drill.py --proxy-port 6391`；报告 `docs/reports/R2_BROKER_DRILL.md` |
| 覆盖 | round-trip、worker 强杀后重投 exactly-once、broker 不可达时发布失败、重复投递去重、同机双 worker 并发 + 同任务双投竞争 |
| 修复缺陷 | ① 领取未提交（attempt/租约不可见）② 重投早于租约过期被静默吞掉（改 deferred retry + `RESEARCH_TASK_LEASE_SECONDS`） |
| 环境陷阱 | PATH 里的 `taskkill` 被包装脚本遮蔽 → 固定用 `%SystemRoot%/System32/taskkill.exe` |
| Docker 模式 | 同一套断言在 **WSL2 + Docker Engine 29.10.1 + `redis:7` 容器** 上重跑：`docker stop` → 发布失败 → `docker start` → 重新投递 → `succeeded`，11/11 PASS |
| 未覆盖 | 多机竞争（同机双 worker 已覆盖）、RabbitMQ、Redis 主从/持久化故障、容器 OOM |
| 计数 | 三套回归仍为 529 passed + 1 skipped（本演练未新增 pytest 用例，断言在演练脚本内） |

## 17. 2026-11-24 更新：hunk 级采纳（逐条应用）

| 项 | 落点 | 验证 |
| --- | --- | --- |
| 只读提案端点 | `GET /api/v1/research/revision-proposals/{proposal_id}`（`revision_service.get_proposal`） | 4 条新测试：暴露 hunk id / 只应用选中 / 未知补丁 422 / 他人 404 |
| 前端 | `RevisionDiff.js` 逐条勾选 + 全选/全不选/采纳已选；`ResearchWorkspace.js` 传 `hunk_ids` | `node --check`；`test_frontend_contract.py` 断言 `getRevisionProposal` |
| 构造坑 | 诊断项 locator 必须按**库内版本正文**（`normalize_text(version.text)`）计算偏移，不能用上传前原文 | 首跑 1 hunk 而非 2：偏移错位导致第二条被跳过 |
| 偏差闭环 | D-R1「只能整份采纳」已闭合 | 见 `R1_DELIVERY.md` §115 行备注 |

计数：R2 收集 82（81 passed + 1 skipped）；三套 533 passed + 1 skipped。
