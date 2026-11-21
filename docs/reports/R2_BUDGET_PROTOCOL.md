# R2 预算与流程增益协议（T23 / AT-056）

本文件定义 ScholarMind R2 阶段"省调用、省 tokens、省时间"的唯一合法测量方式与升降级判据。
**任何未经本协议记录的数字都不算基线，任何没有质量对照的节省都不算优化。**

- 对应验收：AT-056（预算与流程增益）
- 对应接口：`R2_INTERFACE_SPEC.md` §4（`AcceptedBudget` / `BudgetUsage` / `accepted_budget` / `usage_from_events` / `evaluate_budget`）
- 实现：`src/backend/research/budget.py`、`tools/research_budget_report.py`
- 状态：**待验证**（T21 未完成；本文件所有优化项均未在真实语料上取得可复现对照，暂不宣称任何提速比例）

---

## 1. 目的与边界

目标是在**不降低成果质量**的前提下，减少单任务的模型调用次数、输出 tokens 与墙钟耗时，并把"是否超预算"变成终态可审计的事实，而不是事后口头说明。

边界：

- 只调整**流程与调度**（何时调用、调用谁、复用哪个检查点）；不调整模型、不改提示词质量标准、不新增 Agent 节点。
- 预算超限不伪装成功：终态必须是 `partial` 或 `needs_input`，并记录已覆盖/未覆盖范围。
- 费用未知一律 `cost_usd=None`，报告显示"未知"，**禁止写 0**（0 表示真的没花钱，未知不等于免费）。

---

## 2. 固定输入（基线可复现的前提）

一次"基线—变体"对比必须同时满足下列固定项，否则两组数字不可比，直接作废重跑：

| 固定项 | 要求 |
| --- | --- |
| 任务输入 | 同一 `input_json` / `constraints_json`（除 `accepted_budget` 外逐字段一致），记录 `request_fingerprint` |
| 文档版本 | 同一 `document_version_id`（`input_version_ids` 一致），禁止换稿后与旧数字对比 |
| 任务类型 | 同一 `kind`（`review` / `literature_review` / `revision` / `draft_from_outline`）；`export` 不产生模型调用，不参与提速统计 |
| 模型 | 同一 provider + model + mode，记录在 `snapshot_summary.model_snapshot`（`actual_model` 不得留 `unknown` 参与对比） |
| 流水线版本 | 同一 `pipeline_version` / `prompt_version`（`PIPELINE_VERSION`、`REVIEW_PROMPT_VERSION`）；变更提示词即视为新一组，需重跑基线 |
| 预算口径 | 同一 `accepted_budget`（同一 `max_model_calls` / `max_tokens` / `max_duration_seconds`）；若变体故意放宽预算，必须单独分组标注，不与收紧组混算 |
| 评分标准 | 见 §3，两组用同一评分器、同一 `DIMENSIONS`、同一 `quality_verdict` 阈值 |
| 运行环境 | 同一台机器、同一 DB 后端、同一并发额度（系统并发 3）；避免并发争抢导致的耗时差被误记为优化收益 |

标注方式：在 `snapshot_summary` 写入 `variant`（或 `experiment_variant` / `optimization` / `optimization_tag` / `experiment`）作为分组键，报告工具按此分组。

---

## 3. 固定评分标准（质量不可下降的判据）

两组必须使用**完全相同**的诊断/修改评分流程，不得因为"少跑几个角色"就换一套宽松评分：

1. `DIMENSIONS` 维度全覆盖（同一套维度定义、同一权重），逐维度产出 `QualityVerdict`。
2. `quality_verdict` 的 `score` / `band`（`pass` / `warn` / `fail`）按既有阈值判定，阈值不得为提速而放宽。
3. 覆盖完整性以 `coverage` 为准：`expected_eligible_blocks` 与 `analyzed_eligible_blocks` 必须来自同一文档版本，`analyzed_eligible_blocks / expected_eligible_blocks` 为覆盖率。
4. **后半篇遗漏视为质量缺陷**：末段（最后一窗口及之后的所有 eligible block）必须被分析过；任何"提前收尾/预算耗尽截断"都必须显式出现在 `coverage_json`、`unresolved_items` 与 `warnings` 中，并计入质量对照。
5. 人工评估只在确有需要时进行，且必须在报告里如实标注"人工/自动"，**不得伪造人工评估结论**。

---

## 4. 测量字段（每个任务必记）

每个任务在终态（`succeeded` / `partial` / `failed` / `cancelled`）写入 `snapshot_summary["budget_evaluation"]`，字段来自 `evaluate_budget()`：

| 字段 | 含义 | 缺失时 |
| --- | --- | --- |
| `accepted_budget.max_model_calls` | 受理的调用上限（创建时落 `constraints_json`） | 用 PRD 缺省值并在报告标 `*` |
| `accepted_budget.max_tokens` | 受理的 tokens 上限 | 同上 |
| `accepted_budget.max_duration_seconds` | 受理的墙钟上限（默认 1200s） | 同上 |
| `accepted_budget.max_cost_usd` | 费用上限（当前未配置） | `None`，评估时该维度不判超限 |
| `usage.model_calls` | 实际调用数（事件按 `sequence` 去重累计） | 显示 `-`，不写 0 |
| `usage.tokens` | 实际输出 tokens | 显示 `-` |
| `usage.duration_seconds` | 首个到末个事件的时间跨度 | 显示 `-` |
| `usage.cost_usd` | 实际费用 | `None` → 报告"未知" |
| `state` | `within` / `exceeded` | — |
| `overruns` | 超限维度列表（如 `["tokens"]`） | — |
| `cost_known` | 是否所有用量事件都带可信费用 | `false` 时费用列必须"未知" |

另外记录质量侧字段：`coverage`（`analyzed/expected` + 比例）、`quality_verdict`、`unresolved_items` 数量、`truncated` 标记、`warnings`。

累计口径（重要）：

- 同一 `sequence` 只计一次（重投递/重试重放不得重复计费）。
- `task.progress` 默认按**累计值**解释；带 `payload.usage_mode="delta"` 的事件按增量解释。`review_workflow` 与 `review_pipeline` 逐窗口发 delta 事件；`revision` / `draft_from_outline` 在终态发一条 `usage_mode="cumulative"` 的汇总事件。
- 续跑（checkpoint 恢复）时，续跑基数不得重复计入：先补记"本 attempt 之外的已用量"，再逐窗口累加。
- 超预算后的重试累计计入，**不清零**。

---

## 5. 采集命令

只读，不改数据库；缺失值打印 `-`，费用未知打印"未知"：

```bash
./.venv/Scripts/python.exe tools/research_budget_report.py --db <sqlite 路径>
./.venv/Scripts/python.exe tools/research_budget_report.py --db <path> --variant-key variant --kind review --json
```

输出两段：`## 任务明细`（逐任务调用数/tokens/耗时/覆盖率/预算状态/费用）与 `## 基线 / 变体对比`（指标 × 变体）。只有一个分组时会明确提示"未构成对比"，不会凭空生成对比表。

报告中的 `*` 表示该任务未记录受理预算（评估回落到 PRD 缺省值）；对比表中出现 `-` 表示该类数据无任何可采信记录，不得在结论里当成 0。

---

## 6. 候选优化（按触发条件分别验证）

三类候选均为**流程级**改动，彼此独立验证，禁止叠加后一次性比较（否则无法归因）。

### 6.1 按问题触发角色（problem-triggered roles）

- 触发条件：`matched_ordinals` 小且 `finding_count == 0` 的窗口比例高（小改动却跑满全部诊断角色）。
- 做法：仅当窗口命中 `protected_block_ids` / `no_new_empirical_claims` / 结构冲突等问题信号时，才需要该角色；否则跳过该角色的一轮调用。
- 预期节省：调用数为主要指标（tokens 次之），耗时随调用数下降。
- 风险：漏检边缘性结构问题；后半篇若因角色跳过而未被审读，则直接判为质量缺陷。
- 验证方式：与基线同输入同模型跑 N=3 次取中位数，逐维度 `quality_verdict` 不降、覆盖率不降，且末段 block 均被分析。
- 状态：**待验证**（T21 未完成，取消/恢复与部分交付语义尚未定稿，跳过角色的边界条件无法冻结）。

### 6.2 复用检查点（checkpoint reuse）

- 触发条件：同一文档版本重复诊断（重试、续跑、或用户在 `needs_input` 后补充材料但正文未变）。
- 做法：按 `document_version_id` + `attempt_no` 复用 `analyzed_ordinals` / `cursor` / `findings`，只补未分析窗口。
- 预期节省：重试类任务调用数显著下降；首次运行不应有收益。
- 风险：文档版本变更但未换 `document_version_id` 会造成旧结论污染；续跑基数重复计入会虚高用量。
- 验证方式：同一任务强制失败一次后再跑，比较"重跑总调用数"与"基线一次性跑完调用数"，并核对 `usage.model_calls` 无重复累计。
- 状态：**待验证**（当前仅有事件级去重与续跑补记的实现，缺少真实重试样本对照）。

### 6.3 局部补丁（local patch）

- 触发条件：`unresolved_items` 集中在少数连续 block，且其余维度已 `pass`。
- 做法：只对问题 block 重新生成补丁并局部替换，不重跑整篇诊断。
- 预期节省：tokens 与耗时下降，调用数小幅下降。
- 风险：局部替换可能破坏上下位衔接与前文一致性；若只在局部重判评分，等于换了评分标准。
- 验证方式：整篇评分器在补丁前后各跑一次完整 `DIMENSIONS` 评估（不允许只看补丁段），覆盖率与末段分析不降。
- 状态：**待验证**（依赖 T21 的修改流稳定）。

---

## 7. 提速判据（硬性，任一不满足即不算提速）

同时满足以下全部条件，才可以写"该优化降低 X% 调用 / Y% tokens / Z 耗时"：

1. 固定项（§2）全部一致，且两组各有 ≥3 次可复现运行（取中位数，不用最优单次）。
2. 质量不下降：`quality_verdict` 的 `score` 不降、`band` 不降（`fail`→`warn`/`pass` 属于下降，不允许）。
3. **后半篇不遗漏**：末段 eligible block 全部被分析，`truncated=false`；若因预算截断，算质量缺陷而非优化。
4. 覆盖率不降：`analyzed_eligible_blocks / expected_eligible_blocks` 不低于基线。
5. 用量口径可信：`cost_known` 与调用/tokens 均有事件支撑；缺事件的任务不能进对比表，只能进"数据不足"清单。
6. 预算状态未变差：不得把"超预算转 partial"当成提速成果。

一句话判据：**质量下降或后半篇遗漏不算提速；只有"同样的质量、更少的调用/tokens/时间"才算。**

---

## 8. 不做的事

- 不新增 Agent 节点（不引入新角色、新并行分支、新评审层）；只在既有节点内决定"调用/跳过/复用"。
- 不改 `contracts.py` / `models.py` / 迁移 / `capabilities` / 路由 / 配置语义；不改 PRD 缺省预算数值。
- 不为凑指标减少 `DIMENSIONS` 覆盖、放宽 `quality_verdict` 阈值、或缩短文档范围。
- 不把 `cost_usd=None` 写成 `0`，不在报告中填补缺失数值。
- 不在 T21 完成前宣称任何具体提速比例。

---

## 9. 验收清单（AT-056）

- [ ] 创建任务时 `constraints_json["accepted_budget"]` 有四个上限（缺省 160/100000/1200/None；`revision` 用 128；`export`/`chart` 为 0）。
- [ ] 终态 `snapshot_summary["budget_evaluation"]` 存在，含 `state` / `overruns` / `cost_known` / `usage` / `checks`。
- [ ] 超预算任务终态为 `partial`（有成果）或 `failed`（无成果），错误码 `BUDGET_EXCEEDED`，`partial` 时不得是 `succeeded`；已 `failed`/`cancelled` 的终态不被改写。
- [ ] 重试累计计入且不清零；同 `sequence` 事件只计一次。
- [ ] `cost_usd` 未知时报 `None` 且报告显示"未知"。
- [ ] `tools/research_budget_report.py --db <path>` 只读，缺失显示 `-`，单分组不生成对比表。
- [ ] 本文件中每个优化项状态为**待验证**，直到 T21 完成并有真实对照数据。

---

## 10. 当前状态汇总

| 优化项 | 触发条件 | 状态 |
| --- | --- | --- |
| 按问题触发角色 | 空命中窗口比例高 | 待验证（阻塞于 T21） |
| 复用检查点 | 同版本重复诊断/续跑 | 待验证（阻塞于 T21，实现已就位） |
| 局部补丁 | `unresolved_items` 局部集中 | 待验证（阻塞于 T21） |

预算计量侧（`accepted_budget` 落库、事件累计去重、超预算转 `partial`、费用未知 `None`、只读报表）已实现并有本地自测，但**流程增益本身尚无真实对照数据**，故全部标"待验证"。
