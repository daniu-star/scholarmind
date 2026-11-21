# ScholarMind R1 核心任务版 · 交付记录

> 阶段：R1（T10–T20，核心可完成的任务版）
> 依据：`docs/prd/ScholarMind_Optimization_PRD_v1.0.md`、`ScholarMind_Coding_Agent_Playbook_v1.0.md` §5、
> `ScholarMind_Acceptance_Matrix_v1.0.md`、`docs/reports/R1_INTERFACE_SPEC.md`
> 编制：2026-11-20 · 执行：Lead + 5 个子代理（review-depth / sources / workspace-ui / metrics / verifier）

## 0. 结论

R1 的"能跑完一条真实任务"链路已落地并有可复核证据：项目与版本 → 全文诊断（检查点续跑 + 文档级完整性）
→ 证据四字段与真实来源解析 → 逐项修改提案（受保护片段 / 409 / 幂等）→ 导出（DOCX 重开校验 + 附章开关 +
幂等重放）→ 前端研究工作区（6 态 + SSE 断流不取消任务）→ 验收指标端点 → CI 研究域门槛。

放行结论：**有条件放行**。条件与未覆盖项见 §6，发布说明不得写成"全部验收通过"。

## 1. 任务交付矩阵（T10–T20）

| 任务 | 内容 | 状态 | 证据 |
| --- | --- | --- | --- |
| T10 | 项目与文档版本（归属、复用、版本自增） | implemented + verified | R0 `test_documents.py`、R1 `test_workspace_boundaries.py` |
| T11 | 解析（TXT/MD/PDF/DOCX，页码与标题路径） | implemented + verified | R0 `test_documents.py`（39 例） |
| T12 | 检索（先授权、词法降级标注） | implemented，向量索引未接 | R0 `test_documents.py`；见 §5 偏差 3 |
| T13 | 证据四字段 + 真实来源解析 | implemented + verified | R1 `test_source_adapters.py`(40) / `test_source_fidelity.py`(29) |
| T14 | 任务登记 / 额度账本 / outbox / dispatcher | implemented，生产恢复未验证 | R1 `test_recovery.py`(6)；见 §5 偏差 4 |
| T15 | 全文诊断的完整性与续跑 | implemented + verified | R1 `test_checkpoints.py`(10) / `test_completeness.py`(21) / `test_review_flow.py`(10) |
| T16 | 逐项修改（受保护片段、原文哈希、409、幂等） | implemented + verified | R0 `test_revision.py`(30) |
| T17 | 导出（绑已存版本、DOCX 重开、附章、幂等） | implemented + verified | R1 `test_export_hardening.py`(8) / `test_export_idempotency.py`(4) |
| T18 | 前端研究工作区（8 步 + 6 态 + SSE） | implemented + verified（mock 数据） | R1 `test_frontend_contract.py`(14)、`test_workspace_boundaries.py`、`npm run build:frontend` |
| T19 | 验收指标（成功率、重试、去重、分位耗时） | implemented + verified | R1 `test_analytics_metrics.py`(13)、`GET /research/metrics` |
| T20 | 发布门槛（CI 研究域 gate + 迁移可执行性） | implemented + verified | `.github/workflows/ci.yml` 的 `research-gate`；`scripts/research_migration_check.py` |

## 2. 新增与修改文件

### 2.1 后端（研究域）

| 文件 | 说明 |
| --- | --- |
| `src/backend/research/checkpoints.py`（新） | 分析单元检查点读写（`load_checkpoint` / `save_checkpoint`），四键：`analyzed_ordinals`/`cursor`/`model_calls`/`tokens` |
| `src/backend/research/completeness.py`（新） | 纯函数：`expected_sections` / `section_coverage` / `document_level_findings`（引言/方法/结论/参考文献） |
| `src/backend/research/source_adapters.py`（新） | `SourceAdapter` 协议、注册表、`DoiAdapter`（注入 HTTP 客户端，测试不联网）、`map_crossref_message`、URL 安全校验 |
| `src/backend/research/analytics.py`（新） | `task_metrics`（13 字段）/ `funnel_metrics`（11 字段），口径写进 docstring |
| `src/backend/research/review_workflow.py`（改） | 只分析剩余块、每窗写检查点、末块强制分析、结构 findings；`_chunk_text_for_block` 按块/分块交集裁剪索引文本 |
| `src/backend/research/pipelines/review/pipeline.py`（改） | 续跑预算（`max_calls - checkpoint.model_calls`）、`on_progress`、未评估原因 |
| `src/backend/research/pipelines/base.py`（改） | `BudgetTracker` 初值、`ReviewRequest` 续跑字段、`ReviewBlock.kind` |
| `src/backend/research/evidence_service.py`（重写） | 解析顺序：显式 provider > 注册 adapter > DB 词法；abstract 不得冒充 supported；私网 URL 422 |
| `src/backend/research/export_service.py`（改） | 附章（诊断/改动日志，来源缺失 422）、导出幂等重放、partial 标记 |
| `src/backend/research/models.py`（改） | `TaskAttempt.checkpoint_json`（T15 检查点） |
| `src/backend/routers/research.py`（改） | `GET /research/metrics`；导出透传 `include_report`/`include_change_log`/`Idempotency-Key` |
| `src/backend/middleware/request_size_limit.py` | 研究域 22MiB 请求体上限（ASGI 中间件，真实生效） |

### 2.2 迁移

| 文件 | 说明 |
| --- | --- |
| `src/backend/db/migrations/versions/m5_research_domain.py` | 15 张 `research_*` 表（离线模式直接用 `sorted_tables`） |
| `src/backend/db/migrations/versions/m6_research_attempt_checkpoint.py` | `research_task_attempts.checkpoint_json`，幂等 add/drop |
| `m3_verification_email_qr.py` / `m4_audit_security_models.py` | 回归修复：内联 `sa.ForeignKey` 提升为具名约束（SQLite batch 重放必需） |

### 2.3 前端

| 文件 | 说明 |
| --- | --- |
| `src/frontend/src/services/researchApi.js`（新） | 全契约 API 客户端；SSE 用 `fetch` + `ReadableStream`，支持 `after_sequence`/`Last-Event-ID`/`AbortSignal`；幂等键 `crypto.randomUUID()` |
| `src/frontend/src/pages/ResearchWorkspace.js`（新） | 8 步流程（项目→上传→确认范围→全文诊断→问题与依据→选目标→采纳→导出），6 态渲染 |
| `src/frontend/src/components/research/*`（新，8 文件） | `ProjectList` / `DocumentUpload` / `DiagnosisReport` / `FindingCard` / `RevisionDiff` / `TaskStream` / `WorkspaceStates` / `shared` |
| `src/frontend/src/app/router.js`（改） | 注册 `research` 路由（标题「研究工作区」） |

### 2.4 测试与脚本

| 文件 | 说明 |
| --- | --- |
| `src/backend/tests/test_research_r1/*`（新，11 文件） | R1 用例 160 条：analytics 13、checkpoints 10、completeness 21、export_hardening 8、export_idempotency 4、frontend_contract 14、recovery 6、review_flow 10、source_adapters 40、source_fidelity 29、workspace_boundaries 5 |
| `scripts/research_migration_check.py`（新） | ① 离线 SQL 断言 15 张表 + 4 个唯一约束 + 不改既有表；② 临时 SQLite 上 upgrade→downgrade→upgrade |
| `.github/workflows/ci.yml`（改） | 新增 `research-gate` job：ruff + R0 + R1 + `node --check` + `npm run build:frontend`；`build` 依赖它 |

### 2.5 文档

`docs/reports/R1_INTERFACE_SPEC.md`（Lead 契约）、`docs/reports/R1_VERIFICATION.md`（verifier 验收）、
本文件（交付记录）。

## 3. 关键契约落点

- **检查点续跑**：`ResearchTaskAttempt.checkpoint_json` 存 `analyzed_ordinals`；重跑任务只分析剩余块，
  预算按"剩余调用数"计算；末尾块必被分析，避免"最后一段永远没被看过"。
- **文档级完整性**：`document_level_findings` 把缺失必备章节写成 document 范围 finding，
  `verification_method="structural"`，与模型结论分开标注。
- **来源可信**：`abstract` 级别不得支撑 `supported` 结论（`EVIDENCE_UNSUPPORTED_MATERIAL`）；
  解析失败保持 `unresolved` 且不写作者/年份/DOI；私网与变形 IP 一律 `422 UNSAFE_SOURCE_URL`。
- **导出诚实**：`include_report` / `include_change_log` 只从真实 Finding / 已采纳 RevisionProposal 取数，
  无来源直接 `422 EXPORT_SECTION_UNAVAILABLE`；DOCX 重新打开段落数不符 → `500 EXPORT_RENDER_MISMATCH`
  且不落成果行；`partial` 版本在 validation 里带 `partial=true` 与 `partial_reason`。
- **导出幂等**：`Idempotency-Key` + 请求指纹；同键同指纹返回同一 Artifact，同键不同指纹 `409 IDEMPOTENCY_CONFLICT`。

## 4. 验证命令与结果

```powershell
# R1 用例
.venv\Scripts\python.exe -m pytest src/backend/tests/test_research_r1 -q      # 160 passed
# R0 回归
.venv\Scripts\python.exe -m pytest src/backend/tests/test_research -q         # 290 passed
# 静态检查
.venv\Scripts\python.exe -m ruff check src/backend                            # All checks passed
# 迁移可执行性
.venv\Scripts\python.exe scripts/research_migration_check.py                  # OK（离线 333 行 SQL）
# 前端语法与构建
node --check src/frontend/src/services/researchApi.js
node --check src/frontend/src/pages/ResearchWorkspace.js
npm --prefix src/frontend run build                                           # ✓ built
```

## 5. 与 PRD 的偏差（评审须知）

1. **导出附章默认关闭**：`include_report` / `include_change_log` 在请求体里默认 `false`（PRD 未规定默认值）。
   理由：默认追加会让"只想导出正文"的请求因缺少诊断来源被 422 拦住；UI 侧两个勾选框始终显式传值。
2. **无 hunk 级采纳**：`apply` 只接受整份提案（前端已知限制）。PRD 的 `hunk_ids` 参数已支持，但缺少
   "列出可采纳 hunk" 的读取端点，UI 暂不能逐条勾选。
3. **向量检索未接**：`retrieval_service` 仍是词法 + 显式 `degraded` 标注；Chroma 索引构建、版本切换与
   删除清理属 R2。
4. **生产恢复未验证**：`test_recovery.py` 用 SQLite 替身验证"崩溃后 `drain_once` 续跑、重复投递只执行一次、
   取消后迟到写入拒绝、SSE 重放幂等"；PostgreSQL 租约/Redis 事件流/Celery 真实环境不具备。
5. **`/research/metrics` 只读自身**：`scope="self"`，不做跨用户聚合（避免越权与管理面缺口）；运营口径待 R2。
6. **`create_task` 归属收紧**：传入他人或不存在的 `document_version_id` 一律 404，对旧客户端是破坏性收紧。

## 6. 未覆盖验收项与放行条件

- 未覆盖 AT：**AT-016、AT-017、AT-028、AT-041、AT-044、AT-050、AT-053、AT-054**（生产环境 / 跨阶段 /
  性能类），发布说明不得宣称全部通过。
- 放行条件（本次已满足）：R0 290 例与 R1 160 例在同一工作区复跑通过、`ruff` 全绿、前端构建通过、
  迁移脚本通过。
- 仍需人工确认：真实模型调用下的诊断质量（PRD 要求 R2 阶段做质量验证），以及生产部署层的
  请求体上限/并发预算是否与代码默认一致。

## 7. R2 边界（不在本次范围）

质量验证（人工标注集、诊断准确率）、Chroma 索引版本化与清理、跨任务聚合指标、批量导出与
期刊体例扩展、生产环境（PG/Redis/Celery）压测与恢复演练。
