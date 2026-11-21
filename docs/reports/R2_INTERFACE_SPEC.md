# R2 接口与写范围契约（T21–T23 + 浏览器验收）

> 制定：2026-11-20 · Lead。执行子代理必须把本文件与 `docs/reports/R0_INTERFACE_SPEC.md`、
> `docs/reports/R1_INTERFACE_SPEC.md`、PRD v1.0、Playbook §6 一起读，冲突时以 PRD 为准并在汇报里指出。
> 目的：把 R2 的并行写范围切干净，避免互相覆盖文件。

## 0. 通用约束（所有代理）

1. **共享地基只读**：`src/backend/research/contracts.py`、`models.py`、`errors.py`、`ownership.py`、
   `capabilities.py`、`runtime.py`（除 Lead 已改的 stub 分支）、`config.py`、`routers/research.py`、
   `app.py`、迁移目录、`docs/prd/**`。需要改动先报 Lead，不要直接改。
2. **不联网、不调真实模型**：所有单测用替身客户端；`RESEARCH_MODEL_STUB` 只用于本地联调，
   生产环境被 `runtime.get_client` 忽略。**禁止**把替身模型输出写成质量结论。
3. **不伪造人工评估**：T21 需要真实授权论文与两位真人评审；没有就是"质量验收未完成"，
   不允许模型自评、不允许编造评分/评审人/样本。
4. **诚实失败**：任何能力缺失、数据不足、渲染失败都要显式错误码或 `partial`，禁止回退成
   示例数据、随机样例或"看起来成功"的占位图。
5. 只跑相关子集测试（`pytest src/backend/tests/test_research* -q` 指定文件），不跑全量；
   提交前 `ruff check` 自己的文件必须通过；汇报 ≤250 字 + 真实命令输出。

## 1. 写范围（互斥）

| 代理 | 独占写范围 | 禁止触碰 |
| --- | --- | --- |
| charts | `src/backend/research/chart_data_source.py`、`src/backend/research/chart_render.py`、`src/backend/research/chart_service.py` | 路由、config、capabilities、其他 research 模块 |
| eval | `tools/research_quality_eval.py`、`docs/reports/R2_EVAL_SPEC.md`、`docs/reports/R2_SAMPLE_MANIFEST.template.json`、`docs/reports/R2_EVAL_STATUS.md` | 生产代码、测试目录 |
| budget | `src/backend/research/budget.py`、`tools/research_budget_report.py`、`docs/reports/R2_BUDGET_PROTOCOL.md`；对 `task_service.py` / `task_runner.py` / `review_workflow.py` / `pipelines/base.py` 的最小接线（只加预算读取/落盘） | 其他模块、路由、config |
| e2e | `scripts/research_e2e.mjs`、`scripts/build-frontend.js`、根 `package.json` scripts、`docs/reports/R2_E2E.md` | 后端代码、前端页面/服务 |
| verifier | `src/backend/tests/test_research_r2/**`、`docs/reports/R2_VERIFICATION.md` | 任何生产代码 |

Lead 独占：`config.py`、`runtime.py`、`stub_model.py`、`capabilities.py`、`routers/research.py`、
`app.py`、迁移、`docs/reports/R2_DELIVERY.md`、最终浏览器验收运行。

## 2. 图表（T22 / FR-13 / AT-055）

### 2.1 `research/chart_data_source.py`

```python
@dataclass(frozen=True)
class TableData:
    columns: tuple[str, ...]          # 表头，去空白、按出现顺序
    rows: tuple[tuple[float, ...], ...]  # 与 columns 等宽，全部已转 float
    table_index: int                  # 命中的第几张表（0 起）
    source_text_hash: str             # 该版本 text 的 content_hash

async def load_table(
    db: AsyncSession, actor: Actor, *, document_version_id: str, table_index: int = 0
) -> TableData: ...
def select_columns(table: TableData, *, x_column: str, y_columns: Sequence[str]) -> TableData: ...
```

- 解析来源**只允许**已授权文档版本正文：Markdown 管道表（`| a | b |` + 分隔行 `|---|`）与
  纯 CSV 块。`require_version(db, actor, document_version_id)` 先授权，失败 404。
  上传 `.csv` / `.xlsx` 数据文件时，`document_parser` 已把它们转成 Markdown 管道表写入
  版本正文（CSV 单表；XLSX 每 sheet 一表，最多前 5 个 sheet），图表侧无需专门分支。
- 错误码（全部 `ResearchAPIError`）：`CHART_NO_TABLE`(422)、`CHART_TABLE_INVALID`(422)、
  `CHART_UNKNOWN_COLUMN`(422)、`CHART_NON_NUMERIC`(422, details 给列名与首个坏值)、
  `CHART_EMPTY_DATA`(422)、`CHART_TOO_MANY_ROWS`(413, 用 `settings.RESEARCH_CHART_MAX_ROWS`)。
- 不猜类型、不插值、不丢行：某行某列不是数值 → 整个请求 422（给出列/行号），不做静默跳过。

### 2.1b 分类轴（R2.1 增补，`bar` / `line`）

```python
@dataclass(frozen=True)
class SeriesTable:
    x_name: str                       # 第一列表头（分类标签列）
    x_labels: tuple[str, ...]         # 原样保留的分类标签（去首尾空白，不转数值、不排序）
    y_columns: tuple[str, ...]        # 数值列名（按出现顺序）
    rows: tuple[tuple[float, ...], ...]  # 只含 y 列，与 y_columns 等宽
    table_index: int
    source_text_hash: str

async def load_series_table(
    db: AsyncSession, actor: Actor, *, document_version_id: str, table_index: int = 0
) -> SeriesTable: ...
def select_series(
    table: SeriesTable, *, x_column: str, y_columns: Sequence[str]
) -> SeriesTable: ...
```

- 只有 `bar` / `line` 走分类轴分支；其余 12 种仍要求全数值表（含 x 列），分类表 → 422 `CHART_NON_NUMERIC`。
- x 列必须是第一列（`x_column` 只接受第一列表头），否则 422 `CHART_TABLE_INVALID`（message 含「第一列」）。
- 空标签、y 列非数值、y 列全空 → 422 `CHART_NON_NUMERIC`（`details.column` 指明列名）。
- 分类标签**不进入** `value_ranges`、不参与数值计算；`data_digest` 用 `series_digest`（标签参与摘要）。

### 2.2 `research/chart_service.py`

```python
CHART_TYPES: frozenset[str]           # 12 个灰阶类型（CHART_FUNCTIONS）+ "bar"/"line" 分类轴，共 14 个
def chart_capability() -> dict        # {"enabled": bool, "reason": str}
async def create_chart(
    db, actor, *, project_id: str, document_version_id: str, chart_type: str,
    x_column: str, y_columns: Sequence[str], title: str | None = None,
    table_index: int = 0, task_id: str | None = None,
) -> Artifact: ...
```

- 开关关：`unavailable("CHART_CAPABILITY_DISABLED", ...)`（503），绝不降级出图。
- 归属：`require_project` + `require_version`，版本不属于该项目 → 404（不泄露）。
- 未知图表类型 → 422 `CHART_UNSUPPORTED_TYPE`（details 给 supported）。
- **禁止回退图**：不得调用 `services.chart_service.generate_chart`（它吞异常返回"图表生成失败"
  占位图）。直接调用 `CHART_FUNCTIONS[chart_type]`，异常 → 500 `CHART_RENDER_FAILED`（retryable=true）。
- 产物：`artifact_service.create_artifact(kind="chart", mime="image/png", body=base64, ...)`；
  `validation_json` 至少含：`chart_type`、`source_document_version_id`、`source_content_hash`、
  `table_index`、`row_count`、`x_column`、`y_columns`、`value_ranges`（每列 min/max）、
  `data_digest`（规范化 CSV 的 sha256）、`render_verified: true`、`png_sha256`。
- 同样输入必须字节级可复现是**目标**；若 matplotlib 元数据导致字节不稳定，改为断言
  `data_digest`/`png_sha256` 稳定并在报告里说明差异来源（不得声称"完全确定"）。

## 2.3 私有全文检索 API（FR-05，2026-11-21 增补）

```text
POST /api/v1/research/documents/{document_id}/search
body: {"query": "…(1–500)", "version_id": "可选", "limit": 1–20（默认 8）}
200: {document_id, version_id, query, retrieval_method: "vector"|"lexical"|"mixed"|null,
      degraded: bool, degraded_reason: str|null,
      items: [{ordinal, text, start, end, score, retrieval_method, degraded, degraded_reason}]}
```

- 授权先于检索：`document_service.get_document` 统一 404；未指定 `version_id` 时用当前版本；
  无版本 → 422 `DOCUMENT_VERSION_MISSING`。
- 后端选择：`RESEARCH_EMBEDDING_MODEL` 为空 → 词法（`degraded=true`）；配置后走余弦；
  provider 失败/模型缺失 → 降级词法并在 `degraded_reason` 写机器可读原因
  （`vector_backend_unavailable:<reason>`），绝不把词法冒充向量。
- 只读、无副作用、不跨文档；结果条数受 `limit` 限制，排序按分数降序、同分按块序号。

## 3. 质量评估（T21 / FR-15/16 / AT-050）

`tools/research_quality_eval.py`（纯标准库，Python 3.10+）：

```text
python tools/research_quality_eval.py --manifest samples.json --rater-a a.csv \
    --rater-b b.csv --out out/report.json
```

- manifest：`{"samples":[{"sample_id","title","license","source","length","method","reference_findings":[...]}]}`，
  至少 10 条；缺 `license`/`source` 直接拒绝（**不得提交真实论文正文**，只登记清单）。
- 评分 CSV：`sample_id,dimension,verdict,notes`，dimension ∈
  `defect_recall,false_positive,evidence_support,revision_conservation,time_minutes`；
  verdict ∈ `pass/partial/fail` 或数值（time_minutes）。
- 校验：两位评审 id 不同、都不是 `model/ai/self`；否则 exit 2 并写清原因。
- 计算：逐维一致率、Cohen's κ（分类）、缺陷召回/误报率（以 manifest 的 reference_findings 为参照）、
  人工时间均值、分歧清单；输出 JSON + Markdown 摘要到 stdout。
- 报告必须写"本次为人工评分汇总，不代表模型自评"；工具**不生成**评分。

文档：`R2_EVAL_SPEC.md`（维度定义、抽样、独立性、样本偏差、AT-050 映射）、
`R2_SAMPLE_MANIFEST.template.json`（结构模板，不含真实论文）、
`R2_EVAL_STATUS.md`（当前状态：外部资源缺失 → 质量验收未完成，写明需要什么才能完成）。

## 4. 预算与流程增益（T23 / FR-10/11/16 / AT-056）

`research/budget.py`：

```python
@dataclass(frozen=True)
class AcceptedBudget:
    max_model_calls: int | None
    max_tokens: int | None
    max_duration_seconds: int | None
    max_cost_usd: float | None

@dataclass(frozen=True)
class BudgetUsage:
    model_calls: int
    tokens: int
    duration_seconds: float
    cost_usd: float | None      # 未知必须 None，禁止 0

def accepted_budget(task) -> AcceptedBudget        # 读 task.constraints_json["accepted_budget"]
def usage_from_events(events) -> BudgetUsage       # 按 task 事件累计，重复事件按 sequence 去重
def evaluate_budget(budget, usage) -> dict         # {"state":"within|exceeded","overruns":[...],"cost_known":bool}
```

- 接线：任务创建时把 `accepted_budget` 写进 `constraints_json`（缺省用 settings 的
  `RESEARCH_REVIEW_MAX_MODEL_CALLS` / `RESEARCH_MAX_TOKENS_PER_TASK` / `RESEARCH_TASK_TIMEOUT_SECONDS`）；
  终态时把 `evaluate_budget` 结果写进 `snapshot_summary["budget_evaluation"]`。
- 超预算：`state="exceeded"` 时任务终态只能是 `partial` 或 `needs_input`，不得 `succeeded`；
  费用未知时 `cost_usd=None` 且报告显示"未知"，不得写 0。
- `tools/research_budget_report.py --db <sqlite path>` 打印基线/变体对比表（调用数、tokens、
  耗时、覆盖率、预算状态）；只汇总真实任务行，不编造。
- 文档 `R2_BUDGET_PROTOCOL.md`：固定输入/模型/评分标准；候选优化（按问题触发角色、复用检查点、
  局部补丁）；判据"质量下降或后半篇遗漏不算提速"；不新增 Agent 节点；T21 未完成前只写"待验证"。

## 5. 浏览器 E2E（T20 发布门槛 / AT-047/048/053）

`scripts/research_e2e.mjs`（Node ≥18，纯标准库 + 可选 Playwright）：

- 依赖检查：`import('playwright')` 失败 → 打印安装命令并 exit 3（**不得假装通过**）。
- 起隔离后端：`python -m uvicorn src.backend.app:create_app --factory --port <p>`，环境
  `DATABASE_URL=sqlite+aiosqlite:///<临时目录>/e2e.db`、`RESEARCH_MODEL_STUB=true`、
  `ENVIRONMENT=test`、`ENABLE_VERIFIED_CHARTS=true`；**不得连生产库、不得用开发 .env**。
- 静态服务：用 `dist/`（正式构建产物）起本地 HTTP 服务并把 `/api`、`/ws` 代理到后端；
  **不允许**用 vite dev server 顶替。
- 流程：注册/登录拿 token → API 建项目/上传文档 → 浏览器注入 `localStorage.sm_token` →
  `#research` 打开工作区 → 断言能力状态、项目列表、诊断任务事件流、报告正文、导出下载。
- 退出码：0 通过；1 断言失败；2 环境/依赖缺失；3 Playwright 未安装。
- `scripts/build-frontend.js` 改为构建**模块化产物**（`vite build`），断言 `dist/index.html`
  含模块化入口而不是原型 HTML；根 `package.json` 增 `test:research:e2e`。
- `R2_E2E.md` 记录真实运行命令与结果，未跑过就写"未运行"，不得写"已通过"。

## 6. verifier（`src/backend/tests/test_research_r2/**` + `R2_VERIFICATION.md`）

必须覆盖：图表开关关闭 503、未知列/非数值/空数据/超行数 422、跨用户 404、无表格 422、
`data_digest` 与 `value_ranges` 真实性、**不存在回退占位图**（monkeypatch 渲染抛错 → 500 且无 Artifact）；
评估工具拒绝 <10 样本 / <2 真人 / model 评审人；预算 `cost_usd=None` 不为 0、超预算不得 succeeded、
事件去重；E2E 脚本静态契约（用 dist、不连生产、缺 Playwright 退出 3）；以及"不得出现真实论文
正文/伪造评分"的检查。报告逐条映射 AT-055/AT-056/AT-050，并写明未覆盖项。
