# R2 独立验收测试报告（T21 / T22 / T23）

> 执行者：R2 verifier 子代理（独立于实现方）
> 时间：2026-11-20（+08:00）
> 环境：Windows；Python 3.14.5（`.venv/Scripts/python.exe`）；pytest；node v24.16.0；Playwright **未安装**
> 只读约束：除本文件与 `src/backend/tests/test_research_r2/**` 外未改动任何文件；发现的问题只登记，修复归实现方。

## 0. 先读这一段

### 0.1 为什么本报告不在 `R2_VERIFICATION.md`

任务约定的产物路径是 `docs/reports/R2_VERIFICATION.md`，但该文件已于 12:38 由 Lead 写成"Lead 直接复核"版本，并在其 §0.2 明确标注**不具备实现者/复核者分离的独立性**（原因：其接管的并行 verifier 中途不可寻址）。为不覆盖他人未提交的文档，独立 verifier 报告写在本文件；两份并存，冲突处以本文件的实测命令与数字为准（差异清单见 §8）。

### 0.2 结论：**有条件通过**

机器可验证的 R2 契约全部实测通过：图表数值可独立复算、失败不留占位成果、预算越界降级为 `partial`、费用未知时不补 0、评估工具与预算报表都拒绝编造。**没有阻断缺陷，也没有发现"测试绿但行为造假"的路径。** 但两条关键验收仍缺外部资源（真人盲评、20000 字真实对照），且 FR-13 的输入格式被收窄，因此不能写成"通过"。

| 维度 | 结果 | 依据（§1 有原始输出） |
| --- | --- | --- |
| R2 用例 | **44 passed / 0 failed**（32.18s） | `pytest src/backend/tests/test_research_r2 -q`，exit 0 |
| 静态检查 | **All checks passed!** | `ruff check ...`，exit 0 |
| R0/R1 回归 | **290 passed / 160 passed**，无回归 | `pytest test_research -q`、`pytest test_research_r1 -q` |
| 图表数据真实性（AT-055 数据级） | 通过 | 摘要复算、`value_ranges`、行列数、下载 sha256/尺寸互证 |
| 图表失败语义 | 通过 | 422/413/503/404/500 每例均无 Artifact；渲染异常 → `CHART_RENDER_FAILED` 且不落盘 |
| 预算降级（AT-056 机器部分） | 通过 | 越界任务 `partial` + `BUDGET_EXCEEDED`，成果仍在；未知费用 `None`/报表"未知" |
| 人工质量（AT-050） | **未完成** | 无真实论文、无两位真人评分；工具侧约束已被测试锁定 |
| 20000 字对照（AT-056 实验部分） | **未完成** | 禁网、禁真实模型，无法产出覆盖率/P95/真实消耗 |
| E2E 浏览器（AT-047/048/053） | 部分（仅脚本契约） | `node scripts/research_e2e.mjs` → exit 3 且打印安装命令；浏览器未驱动 |

**为什么不是"通过"**：AT-050 要求两位领域评审独立评价真实授权论文，AT-056 要求 20000 字论文的真实对照数据；两者都依赖本环境没有的资源。把它们记为已通过就是编造。

**为什么不是"不通过"**：所有被执行到的验收点都通过；未完成项属于"未覆盖"而非"失败"，且相关工具已就绪并强制拒假（<10 样本、模型评审人、缺评分均按退出码失败）。

## 1. 实测命令与真实输出

| # | 命令 | 真实输出（末行） | 退出码 |
| --- | --- | --- | --- |
| 1 | `./.venv/Scripts/python.exe -m ruff check src/backend/tests/test_research_r2 tools/research_quality_eval.py tools/research_budget_report.py` | `All checks passed!` | 0 |
| 2 | `./.venv/Scripts/python.exe -m pytest src/backend/tests/test_research_r2 -q` | `44 passed in 32.18s` | 0 |
| 3 | `timeout 900 ./.venv/Scripts/python.exe -m pytest src/backend/tests/test_research -q` | `290 passed in 255.33s (0:04:15)` | 0 |
| 4 | `timeout 900 ./.venv/Scripts/python.exe -m pytest src/backend/tests/test_research_r1 -q` | `160 passed in 82.85s (0:01:22)` | 0 |
| 5 | `node --check scripts/research_e2e.mjs`；`node --check scripts/build-frontend.js` | 无输出 | 0 / 0 |
| 6 | `node scripts/research_e2e.mjs` | `[e2e] 缺少浏览器驱动：playwright 未安装或不可用。` + `npm i -D playwright && npx playwright install chromium` | **3** |

命令 3/4 的输出重定向到文件后再取 `$?`，得到的是 pytest 自身的退出码（均为 0）；命令 2 无管道，同样确认为 exit 0。

**D2 在验收过程中被修好了**：12:47 实现方在 `budget.py` 增加 `_kind_name()`（先取枚举 `.value` 再剥 `TaskKind.` 前缀），本 verifier 用 `xfail(strict=False)` 标记的用例已撤掉标记、转为普通回归锁；并行方也在 `test_budget_contract.py` 新增 `test_enum_kind_is_normalized_before_budget_lookup`。因此最终套件没有 xfail/xpass，44 条全绿。

## 2. 测试清单（9 个文件 / 44 个用例）

`src/backend/tests/test_research_r2/` 由多个代理并行写入：22 条来自并行 verifier / Lead 接管的文件（我只读、未改；其中 1 条是 D2 修复后新增的回归），22 条由本次 verifier 新增（只新增文件名，不覆盖他人文件）。

| 文件 | 用例 | 覆盖 | 作者 |
| --- | --- | --- | --- |
| `test_charts_api.py` | 7 | 503 开关关闭、201 validation、非数值 hint、未知列+不支持类型、跨用户 404、渲染异常 500 无 Artifact、digest/range 纯函数 | 并行 verifier |
| `test_charts_edges.py` | 8 | 无表 422、`table_index` 越界、只有表头 → 空数据、413 超行数、`extra` 字段拒绝、成功路径可复算+下载互证、同输入渲染稳定、跨项目 404 | verifier |
| `test_budget_contract.py` | 9 | 受理预算默认值、显式预算覆盖、事件按 sequence 去重、cumulative 取 max、超限判定、创建任务落库、retry 不膨胀预算、枚举归一回归（D2） | 并行 verifier |
| `test_budget_runner.py` | 3 | 默认预算导出 `succeeded` 对照、越界 → `partial` 且成果在、枚举/字符串 0 预算回归锁（D2 已修） | verifier |
| `test_budget_report_tool.py` | 6 | 未知费用"未知"、事件去重、空库不造表、缺库/非本库拒绝、可读报告 exit 0 | verifier |
| `test_eval_cli.py` | 4 | 10 样本 happy path（`human_raters`、time agreement=null）、<10 样本、模型评审 id、缺评分 → incomplete | 并行 verifier |
| `test_eval_cli_edges.py` | 3 | 缺 CSV 列 → 输入不合法（非 incomplete）、manifest 缺字段、同一评审 id 冒充双评 | verifier |
| `test_findings_mapping.py` | 2 | `structural` → 契约值 `tool`、接口不 500 | 并行 verifier |
| `test_e2e_contract.py` | 2 | 用 `dist/` + 临时库 + 模型替身 + `ENVIRONMENT=test`；缺 Playwright 必须 exit 3 | verifier |

> **关于"缺评分列 → exit 3"**：任务提示写的是 3，但 `docs/reports/R2_EVAL_SPEC.md:61` 规定 `2` = 输入不合法、`3` = 数据不完整。**列缺失是结构问题**（输入不合法），**缺某条评分是数据问题**（不完整）。实现与规格一致，所以本套件按 **exit 2** 断言缺列（`test_missing_csv_column_is_invalid_input_not_incomplete`），缺评分行则由 `test_eval_cli::test_missing_rating_is_incomplete_not_zero` 断言 exit 3。若产品希望缺列也走 3，应先改规格。

### 2.1 对 `R2_INTERFACE_SPEC.md` §6 覆盖清单的逐项映射

| §6 要求 | 覆盖情况 |
| --- | --- |
| 图表开关关闭 503 | `test_charts_api::test_disabled_capability_returns_503`（并断言 Artifact 数为 0） |
| 未知列/非数值/空数据/超行数 | `test_charts_api::test_unknown_column_and_bad_type`、`test_non_numeric_table_has_actionable_hint`（`details.hint` 非空）、`test_charts_edges::test_header_only_table_reports_empty_data`、`test_too_many_rows_returns_413` |
| 跨用户 404 | `test_charts_api::test_cross_owner_returns_404`、`test_charts_edges::test_project_version_mismatch_is_404`（B 用自己项目 + A 的版本） |
| 无表格 422 | `test_charts_edges::test_document_without_table_is_rejected`、`test_table_index_out_of_range_is_rejected`（越界报 `CHART_NO_TABLE` 且带 `tables_found`） |
| `data_digest`/`value_ranges` 真实性 | `test_charts_edges::test_success_is_recomputable_and_download_matches_digest`（用 `load_table`+`select_columns` 独立复算摘要，下载 PNG 的 sha256 与 IHDR 宽高同 validation 互证）、`test_same_input_is_render_stable` |
| 不存在回退占位图 | `test_charts_api::test_render_failure_leaves_no_artifact`（500 + 无 Artifact）；另每个 422/413/503 用例都断言 `research_artifacts` 计数不变 |
| 评估工具拒 <10 / <2 真人 / model 评审 | `test_eval_cli` 三条 + `test_eval_cli_edges::test_same_rater_id_cannot_fake_two_reviewers`、`test_manifest_missing_required_field_is_rejected`、`test_missing_csv_column_is_invalid_input_not_incomplete` |
| 预算 `cost_usd=None` 不为 0、超预算不得 succeeded、事件去重 | `test_budget_contract` 纯函数与落库用例 + `test_budget_runner` 两条链路 + `test_budget_report_tool`（未知/去重） |
| E2E 脚本静态契约 | `test_e2e_contract` 两条（`dist/`、临时 SQLite、模型替身、test 环境、exit 3） |
| 不得出现真实论文正文/伪造评分 | 套件内所有样本均为合成短文本；评估 CLI 的分数只来自 CSV，缺评分走 exit 3，不补 0 |

## 3. AT 逐条判定

判据来自 `docs/prd/ScholarMind_Acceptance_Matrix_v1.0.md:86-100`。R2 只做 R2 项，其余条目按"是否有本次实测证据"标注，不借他人结论。

| AT | 判定 | 依据 / 说明 |
| --- | --- | --- |
| AT-044 迁移与归属（R1） | not_covered | R2 未测迁移；回归 290 passed 不构成迁移演练证据 |
| AT-045 V2 导出/DOCX（R1） | not_covered | 未重新解析 DOCX、未验证未知样式 422 |
| AT-046 冷启动/日志目录（R0/R1） | not_covered | 无新目录冷启动记录 |
| AT-047 浏览器 1440/390（R1） | not_covered | Playwright 未安装；只验证了"缺依赖必须 exit 3"的契约 |
| AT-048 构建产物/模块化入口（R0/R1） | **partial** | `dist/index.html` 存在且引用 `assets/index-DM45jV-B.js`（模块化入口，非原型 HTML），`node --check scripts/build-frontend.js` 通过；但我没有重跑 `npm run build:frontend`（避免改写共享构建产物），且后端 `GET /` 仍 307 到原型页（D6），"root 交付唯一模块化产物"无法从应用入口自证 |
| AT-049 安全/日志负例（R0/R1） | not_covered | 未做代码执行/私网来源/日志脱敏负例 |
| AT-050 ≥10 授权论文 + 2 位真人（R1/R2） | **not_covered** | 外部资源缺失，`R2_EVAL_STATUS.md` 亦记为"未完成"；工具侧硬约束已被 3 条测试锁定（<10 → 2、model 评审 → 2、缺评分 → 3） |
| AT-051 retry 预算不清零（R0/R1） | **partial** | 并行用例 `test_retry_does_not_inflate_budget` + 本次 `test_budget_runner`（越界不清零、直接降级）；并发重试/预留释放未测。D2（生产路径 export 预算 160/100000）已于 12:47 修复并有双回归锁，不再影响本条 |
| AT-052 隔离/指标（R1） | not_covered | 未测跨项目记忆与指标聚合 |
| AT-053 同浏览器双账号（R0/R1） | not_covered | 无浏览器 |
| AT-054 删除撤权（R0/R1） | not_covered | 未测迟到 worker/事件重放 |
| AT-055 R2 图表数据一致性 | **partial** | 通过：摘要可独立复算、`value_ranges` 与表数据一致、行列数与选中列一致、下载 PNG 的 sha256/宽高与 validation 互证、同输入两次字节级一致、越权 404、失败不落 Artifact、默认 `ENABLE_VERIFIED_CHARTS=False` 且能力表披露原因。缺口：输入格式收窄（D1）、清洗/缺失值策略未落库（D5） |
| AT-056 R2 预算/20000 字对照 | **partial** | 通过：越界 → `partial` + `BUDGET_EXCEEDED` + 成果保留；未知费用 `cost_usd=None`、报表显示"未知"且不打印 0；事件重复序号不污染累计。缺口：没有 20000 字对照实验，故无覆盖率/P95/调用与消耗的真实数字 |

## 4. 发现的问题

### 4.1 阻断

无。

### 4.2 重要

**D1｜FR-13 输入格式被收窄为"文档正文里的表格"**

- 期望（`docs/prd/ScholarMind_Optimization_PRD_v1.0.md:246`）：首批输入为 **CSV、JSON 表格与 XLSX（不含宏）**，沿用文件大小与所有权规则，服务端保存受验证的行列结构与列类型。
- 实际：`src/backend/research/chart_data_source.py` 的 `_extract_candidates()` 只在**已授权文档版本的正文**里解析 Markdown 管道表与 `csv` 代码块；`POST /api/v1/research/charts`（`src/backend/routers/research.py:999`）没有文件参数，项目上传接口也不把 XLSX/JSON 转成可解析表格。
- 复现：上传一个 `.xlsx` 文档后调用 `POST /charts` → `422 CHART_NO_TABLE`（`tables_found: 0`）。
- 影响：以 XLSX/JSON 交付的数据表无法出图；AT-055 Given 的"已知数据表"实际只能以 Markdown/CSV 形式进入。
- 说明：`docs/reports/R2_INTERFACE_SPEC.md:44-46` 已显式收窄范围，属于**有记录的偏离**，但仍需产品书面确认；否则按 PRD 字面判不达标。

### 4.3 次要

**D2｜"不调用模型"的任务拿到模型预算（枚举未归一）——已修复（2026-11-20 12:47）**

- 位置：`src/backend/research/budget.py:166`（`value = str(kind or "").strip().lower()`）、`budget.py:31`（`NO_MODEL_KINDS = {"export", "chart"}`）、调用方 `src/backend/research/task_service.py:431`（传入 `data.kind`，是 `TaskKind` 枚举）。
- 期望：`TaskKind.EXPORT`/`TaskKind.CHART` → `max_model_calls=0, max_tokens=0`（模块注释即如此声明）。
- 实际（修复前）：`str(TaskKind.EXPORT) == "TaskKind.EXPORT"`，匹配不到 `NO_MODEL_KINDS`，落进 else 分支 → **160 次调用 / 100000 tokens**。字符串调用 `default_accepted_budget("export")` 仍然是 0/0，所以只测字符串的用例不会发现它。
- 复现（修复前输出）：
  ```
  ./.venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'src');from backend.research.budget import default_accepted_budget;from backend.research.contracts import TaskKind;print('enum ->',default_accepted_budget(TaskKind.EXPORT));print('str  ->',default_accepted_budget('export'))"
  enum -> AcceptedBudget(max_model_calls=160, max_tokens=100000, max_duration_seconds=1200.0, max_cost_usd=None)
  str  -> AcceptedBudget(max_model_calls=0, max_tokens=0, max_duration_seconds=1200.0, max_cost_usd=None)
  ```
- 修复（12:47，实现方）：`budget.py` 新增 `_kind_name()`，`raw = getattr(kind, "value", kind)` 后再剥 `TaskKind.` 前缀；同一命令现状为 `enum -> max_model_calls=0, max_tokens=0`、`str -> 0/0`。
- 回归锁：`test_budget_runner.py::test_enum_kind_gets_zero_budget_for_no_model_tasks`（枚举 + 字符串两种入口）＋ `test_budget_contract.py::test_enum_kind_is_normalized_before_budget_lookup`（并行方）。
- 影响（修复前）：预算比设计更宽松。不会造成"假成功"（导出任务实际用量为 0），但 §9 的"不调用模型的任务 0 预算"未生效；若将来开放 chart 任务入口，同样会被放宽。

**D3｜预算报表工具的 stderr 在 Windows 下乱码**

- 位置：`tools/research_budget_report.py:443` 只对 `sys.stdout` 做了 UTF-8 重配置；`_connect()` 与 `_load_tasks()` 用 `SystemExit("数据库不存在：…")`、`SystemExit("…不是 ScholarMind 数据库")` 走 stderr。
- 期望：同一次运行的两个输出流编码一致、中英文诊断在任何终端/管道下都可读。
- 实际：stdout 是 UTF-8，stderr 仍是控制台代码页（cp936）。实测 `--db Z:/nope.db` 的 stderr 原始字节为 `\xca\xfd\xbe\xdd\xbf\xe2\xb2\xbb\xb4\xe6\xd4\xda\xa3\xba…`（GBK 的"数据库不存在："），按 UTF-8 解码得到 `U+FFFD` 替换字符；退出码 1。
- 复现：`./.venv/Scripts/python.exe -c "import subprocess,sys;p=subprocess.run([sys.executable,'tools/research_budget_report.py','--db','Z:/nope.db'],capture_output=True);print(repr(p.stderr[:60]));print(repr(p.stderr.decode('utf-8','replace')[:40]))"`。
- 影响：只影响诊断可读性，不影响报表数据。

**D4｜一条同步测试带 asyncio 标记（测试卫生）**

- 位置：`src/backend/tests/test_research_r2/test_charts_api.py:228`（`test_digest_and_ranges_are_deterministic` 是同步函数，但文件级 `pytestmark = pytest.mark.asyncio`）。
- 实际：产生 1 条 `PytestWarning`，不影响结果。
- 归属：并行写入的文件，我未修改。

**D5｜FR-13 的"清洗步骤/缺失值规则"未落库**

- 期望（PRD `FR-13`，`:238-246`）：保存清洗步骤、过滤/缺失值规则和数据摘要。
- 实际：`src/backend/research/chart_service.py:194-221` 的 `validation_json` 只有 `table_index`、列映射、`row_count`/`column_count`、`value_ranges`、`data_digest`、`source_content_hash`、`render_verified`、`png_sha256` 等；"非数值即拒绝、不清洗不插值"这一策略只体现在 422 行为里，没有作为字段记录。
- 影响：AT-055"有数据版本与处理记录"只能判部分（摘要可复算、源哈希在，但处理策略未显式化）。
- 建议：`validation_json` 增 `cleaning: {"steps": [], "missing_value_policy": "reject", "filtered_rows": 0}` 之类的显式字段。

### 4.4 信息级 / 待确认

**D6｜应用根路径仍指向原型页，`dist/` 未被后端挂载**

- `src/backend/app.py:201`：`GET /` → 307 `/app/interactive-prototype.html`；`app.py:299-301` 只 mount `prototypes/`，全仓库没有把 `dist/` 挂进 FastAPI；`dist/` 只被 `scripts/research_e2e.mjs` 的静态服务消费。
- 影响：AT-048 的"root build 交付唯一模块化产物"无法从应用入口自证；本地打开 `/` 看到的仍是原型（`R2_E2E.md` 称"旧链接安全兼容"，可能是刻意保留）。是否可接受需 R0/R1 负责人确认，本报告不判缺陷。

## 5. 未覆盖项与原因

| 未覆盖项 | 原因 | 影响 |
| --- | --- | --- |
| AT-050 真人盲评（≥10 份授权论文、2 位评审） | 无真实论文与真人评审，外部资源缺失 | 无召回率/误报率/人工时间真实数字；只能报"工具就绪" |
| AT-056 的 20000 字对照实验 | 禁网、禁真实模型，无法产出覆盖率/P95/真实消耗 | 只有预算降级与未知费用的机器证据 |
| AT-047/048/053 浏览器交互与 a11y | Playwright 未安装（`node_modules/playwright` 不存在） | 仅锁定"缺依赖必须 exit 3"，无截图与真实点击 |
| AT-044/045/046/049/051/052/054 | 属 R0/R1 范围，R2 无对应改动 | 依赖 R1 证据；本次仅回归未破坏 |
| 图表 XLSX/JSON 输入 | 见 D1，实现未提供入口 | 数据表格式受限 |
| 图表类型全覆盖（12 种渲染器） | 真实渲染每种约 1–3s，只抽测 1 种（`gradient_area`）走完整 201 链路 | 其余 11 种渲染器未逐一冒烟；类型注册表由纯函数用例覆盖 |
| 图表单位/显示范围校验 | PRD 要求"单位/缺失值/范围"参与放行，实现未见显式单位校验 | AT-055"单位"一项未验证 |

## 6. 放行条件

1. **AT-050**：拿到 ≥10 份书面授权论文 + 两位真人独立盲评后，按 `R2_EVAL_STATUS.md` §3 跑 `tools/research_quality_eval.py`，把真实一致率/召回/误报写入报告；在此之前发布说明只能写"评估方法与工具就绪"。
2. **AT-056**：在同一 20000 字论文上用真实模型跑短流程 vs 多角色流程，记录覆盖率、P95、调用与 token；预算/超时分支已有机器证据。
3. **D1**：产品书面确认"仅支持文档正文中的 Markdown/CSV 表格"，或补 XLSX/JSON 表格导入；二者必须落一个，否则 AT-055 的 Given 不成立。
4. **D5**：`validation_json` 补清洗步骤/缺失值策略字段（哪怕值是"无清洗、拒绝非数值"）。
5. **D2/D3**：D2 已于 12:47 修复并有回归锁；**D3（报表工具 stderr 编码）仍待修**（低风险，建议随 R2 收尾一起进）。
6. **开关**：`ENABLE_VERIFIED_CHARTS` 保持默认关闭；开启前需数据授权、单位/范围校验与能力表回传齐全（当前默认值与 `src/backend/research/capabilities.py:640-663` 的披露已符合"权限与回传完整后才开启"的形态要求）。
7. **浏览器项**：安装 Playwright 后跑 `npm run test:research:e2e` 并完成 Lead 手动验收，再关闭 AT-047/048/053。

## 7. 附录 A：并行写入说明（如实记录）

- 任务约定的独占目录 `src/backend/tests/test_research_r2/` 在 12:08–12:14 期间出现了另一代理写入的文件（`conftest.py`、`test_charts_api.py`、`test_eval_cli.py`、`test_budget_contract.py`、`test_findings_mapping.py`）。我向 Lead 报告该冲突后未收到回复，据 Lead 的 `R2_VERIFICATION.md` §0.2，该并行 verifier 随后不可寻址、由 Lead 接管测试目录。
- 处理方式：**不覆盖、不修改**对方的 5 个文件，只新增独立文件名补缺口；最终套件是多方用例的并集（44 条）。
- 副作用：①计数里有一半用例不是本次 verifier 写的；②`test_charts_api.py` 的 asyncio 标记告警（D4）属他人文件，未修。
- 12:47 实现方修复 D2 后，并行方与 Lead 改写了 `test_budget_runner.py` 的 xfail 用例并在 `test_budget_contract.py` 补了回归；本报告数字以 12:50:10 的最后一次运行为准（44 passed、exit 0）。
- 前一轮快照中 `test_task_creation_persists_accepted_budget` 曾红（断言 `constraints.get("max_model_calls") == 160`，但实现只写 `constraints_json["accepted_budget"]`，legacy 键叫 `max_calls` 且只在 `snapshot_summary` 里），该断言已被其作者修好，最终全绿。

## 8. 附录 B：与 `R2_VERIFICATION.md`（Lead 版）的差异

| 项 | Lead 版 | 本报告 | 说明 |
| --- | --- | --- | --- |
| R2 用例数 | 40 passed（8 文件） | **44 passed / 0 failed（9 文件，32.18s）** | Lead 的 40 早于本次新增的 4 条（2 条 E2E 契约 + 1 条 D2 回归 + 1 条并行方枚举回归）；合并回归应为 494 passed |
| AT-048 | pass | **partial** | 我没有重跑 `npm run build:frontend`（避免改写共享产物），且后端根路径仍指向原型页（D6），"唯一模块化产物"无法从应用入口自证 |
| AT-051 | 依据写"`export` = 0/0" | **partial，D2 已修复** | 修复前字符串入口 0/0、生产路径（枚举）160/100000；12:47 修复后两者均 0/0，并留两条回归锁 |
| AT-052 / AT-054 | pass（依据分别为评估工具、构建产物） | **not_covered** | 矩阵里 AT-052 是"切换项目/用户、检索降级、指标聚合"，AT-054 是"删除文档后的撤权与迟到 worker"；Lead 版写的依据与条目语义不对应 |
| AT-047 / AT-049 | partial（依据真实 Chrome 与 R1 用例） | not_covered | Lead 有 Chrome DevTools MCP，可做 1440 桌面验收；本环境无浏览器，只能给脚本契约证据。两者不矛盾，是证据来源不同 |

## 9. 附录 C：可复现性与清理

- 所有临时文件写在系统临时目录（`/tmp`），套件内数据库均由 `tmp_path` 生成；未在仓库留下 `*.db`/`*.log`/截图。
- 测试不联网、不调用真实模型：图表用例用真实 matplotlib 渲染（1 次成功路径 + 2 次同输入复现），其余走 monkeypatch。
- 套件耗时 32.18s（目标 <120s），回归 255.33s + 82.85s；最终运行为 12:50:10（44 passed，exit 0）。
- 图表分辨率 1200×800、DPI 300（`chart_render.py`），下载 PNG 的 IHDR 与 `png_width/png_height` 一致，说明不是占位图。
## 10. 附录 D：Lead 后续处置记录（本段由 Lead 追加，未改动上文）

verifier 报告提交后，Lead 根据本报告修复并复跑，结果如下（以 Lead 实测为准）：

| 项 | verifier 报告状态 | Lead 处置后 |
| --- | --- | --- |
| D2 枚举预算 | 已由 Lead 修复（12:47），双回归锁 | 保留；`budget._normalize_kind` 取 `.value` 再剥前缀，`TaskKind.EXPORT/CHART`=0/0，另有 `default_accepted_budget(TaskKind.*)` 纯函数用例 |
| D3 stderr 编码 | 待修 | **已修**：`tools/research_budget_report.py` 对 stdout **与 stderr** 同时 `reconfigure(encoding="utf-8")`；新增严格 UTF-8 解码回归用例 |
| D4 asyncio 标记告警 | 未修（属他人文件） | **已修**：`test_charts_api.py` 删文件级 `pytestmark`，逐 async 用例加标记，套件零 warning |
| D5 清洗记录 | 缺失 | **已补**：`chart_service` validation 增 `cleaning{steps[],missing_value_policy:"reject",filtered_rows:0,note}`，成功路径断言 |
| D1 输入格式收窄 | 重要，需产品确认 | 未改实现，写入 `R2_VERIFICATION.md` 放行条件 |
| D6 根路径 307 原型页 | 信息级 | 视为刻意保留，登记为 AT-048 缺口 |

复跑数字（含 Lead 新增的 2 条用例：D2 枚举归一回归锁、D3 UTF-8 解码回归锁）：

- `pytest src/backend/tests/test_research_r2 -q` → **45 passed**
- `pytest src/backend/tests/test_research_r2 src/backend/tests/test_research_r1 src/backend/tests/test_research -q` → **495 passed in 353.99s**
- `ruff check`（研究域 + tools + scripts/research_migration_check.py）→ All checks passed

canonical 报告为 `docs/reports/R2_VERIFICATION.md`（合并版，§4 列出 D1–D6 处置状态）；本文件保留为独立验收原文。
