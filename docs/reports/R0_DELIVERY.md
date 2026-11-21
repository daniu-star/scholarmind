# R0 交付记录（ScholarMind 研究域 · PRD v1.0）

> 依据：`docs/prd/ScholarMind_Optimization_PRD_v1.0.md`（FR-01 — FR-16）、
> `docs/prd/ScholarMind_Coding_Agent_Playbook_v1.0.md`（T00 — T09）、
> `docs/prd/ScholarMind_Acceptance_Matrix_v1.0.md`（AT-001 — AT-056）。
> 交付日期：2026-11-19 / 2026-11-20。集成分工见 `docs/reports/R0_INTERFACE_SPEC.md`。

## 0. 一句话结论

R0（修复版）已落地：`/api/v1/research/*` 22 个端点可用，任务从受理 → outbox
派发 → 租约执行 → 最小交付校验 → 结算/释放 → 终态事件的链路端到端可跑；
能力状态、归属隔离、诚实失败、幂等与账本都由代码与测试同时约束。
**R0 通过 ≠ R1 通过**：全文诊断/修改的"质量深度"仍属 R1 验收（见 §6）。

## 1. 交付清单（T00 — T09）

| 任务 | 状态 | 交付物 | 证据 |
| --- | --- | --- | --- |
| T00 基线夹具 | implemented / verified | `src/backend/tests/test_research/conftest.py`（每用例独立临时库、双用户 A/B、真实 `create_app()`）；`src/backend/research/contracts.py`（SCHEMA_VERSION="1.0"） | 夹具自检 + 全量 182 用例回归未破坏 |
| T01 能力收敛 | implemented / verified | `research/capabilities.py`（18 项能力真实探测）、`config.py` 研究开关、`app.py` 请求体上限 22MiB | `GET /api/v1/research/capabilities`；`test_capabilities.py` |
| T02 意图路由 + Skill 契约 | implemented / verified | `routers/research.py::POST /tasks`、`contracts.ResearchTaskInput`、`task_service.validate_skill_ids`（最多 8、去重、未知/禁用扣额前 422） | `test_tasks_api.py`、`test_contracts.py` |
| T03 文件归属 / 容量 | implemented / verified | `document_service.py`、`project_service.py`（20MiB、22MiB multipart、50 文件/项目、1GiB/用户、同哈希复用、404 不泄露） | `test_documents.py` |
| T04 独立流水线包 + 实例运行时 | implemented / verified | `research/pipelines/`（base/review/generation，零 FastAPI/DB/全局配置导入）、`runtime.py`（ModelSnapshot 注入） | AT-021 静态断言 + `test_contracts.py` |
| T05 统一 TaskInput/Result | implemented / verified | `contracts.ResearchTaskInput/TaskResult/TaskSnapshot`、`extra="forbid"`、服务端生成 ID | `test_contracts.py` |
| T06 诚实失败 / 截断 / 完成验证 | implemented / verified | `contracts.completion_errors`、`task_runner` 终态收敛、`coverage` 记录、`insufficient_evidence` 不伪造结论 | `test_honesty` 相关用例 |
| T07 成果 / 工具回传 / 流式闭环 | implemented / verified | `artifact_service.py`、`export_service.py`、`review_workflow.py`、`revision_service.py`、`task_events.py`、SSE | `test_tasks_api.py`（SSE/游标）、`test_revision.py` |
| T08 任务登记 / 额度账本 / 模型快照 | implemented / verified | `task_repository.py`、`task_service.py`、`billing_service.py`、`outbox.py`、`dispatcher.py` | `test_billing.py`、`test_tasks_api.py` |
| T09 R0 放行记录 | implemented | 本文档 + `docs/reports/R0_VERIFICATION.md` | 见 §4 |

## 2. 新增/修改文件

**新增（研究域，`src/backend/research/`）**：`contracts.py`、`models.py`、`errors.py`、
`ownership.py`、`project_service.py`、`document_parser.py`、`document_service.py`、
`retrieval_service.py`、`evidence_service.py`、`task_repository.py`、`task_service.py`、
`billing_service.py`、`outbox.py`、`task_events.py`、`runtime.py`、`review_workflow.py`、
`revision_service.py`、`artifact_service.py`、`export_service.py`、`task_runner.py`、
`capabilities.py`、`dispatcher.py`、`pipelines/{__init__,base}.py`、
`pipelines/review/{__init__,pipeline}.py`、`pipelines/generation/{__init__,pipeline}.py`。

**新增（入口与迁移）**：`src/backend/routers/research.py`（22 路由）、
`src/backend/db/migrations/versions/m5_research_domain.py`。

**修改（装配与既有缺陷）**：`src/backend/app.py`（研究路由 + 错误处理器 + 任务派发器
lifespan + 请求体上限 10MiB→22MiB）、`src/backend/config.py`（研究预算与开关、
`RESEARCH_REQUIRE_IDEMPOTENCY_KEY=True`）、`src/backend/db/session.py`（研究表纳入
`init_db`）、`src/backend/db/migrations/env.py`（autogenerate 可见研究表）、
`src/backend/models/schemas/agent.py`（`skill_ids` 改为「未提供 ≠ 显式空」、
去重、≤8）、`src/backend/routers/agent.py`（不再无条件覆盖 `selected_skill_ids`，
修问题 08）。

## 3. 关键契约落地位置

- **能力真实性**：`capabilities.py` 每项独立探测；异常 → `unknown`；未实现 →
  `disabled`；无额度 → `unauthorized`。`kind=chart` 一律 422（FR-13）。
- **归属隔离**：`ownership.py` 统一 `owner_id` 过滤；`task_service._require_owned_inputs`
  在**扣额之前**校验项目与版本归属；`documents` 的 404 不泄露文件名。
- **全文分块**：800—1200 码点目标、重叠 ≤100；`document_parser.build_chunks`
  1200 窗口 / 1100 步长；`text[start:end] == block.text` 的 Unicode 码点偏移。
- **诚实失败**：`contracts.completion_errors(kind, result, artifact_kinds)` 是
  `succeeded` 的唯一判据；空成果 → `partial`/`failed`，绝不包装成成功。
- **幂等**：`Idempotency-Key` 强制（8—128 ASCII）；同键等价请求返回原结果，
  同键不同请求 → **409 `IDEMPOTENCY_CONFLICT`**（PRD §8.2）。
- **账本**：`(billing_group_id, operation)` 唯一 → 结算至多一次；释放幂等；
  权益映射 review→external_review、revision→modification、draft→generation。
- **派发**：任务行 + 额度预留 + `task.accepted` + outbox 同事务提交；
  `dispatcher.py` 在提交后消费 outbox，按 PRD §9 预算（系统 3 / 单用户 1）执行。

## 4. 验证方式（可复核）

```powershell
# 研究域验收测试（R0 主证据）
.venv\Scripts\python.exe -m pytest src/backend/tests/test_research -q

# 代码质量
.venv\Scripts\python.exe -m ruff check src/backend/research src/backend/routers/research.py src/backend/app.py

# 应用装配（22 条路由 + 错误处理器）
.venv\Scripts\python.exe -c "from src.backend.app import create_app; a=create_app(); print([r.path for r in a.routes if r.path.startswith('/api/v1/research')])"

# 既有 182 用例回归（约 10 分钟，慢因 sentence-transformers 联网超时，非失败）
.venv\Scripts\python.exe -m pytest src/backend/tests -q
```

## 5. 与 PRD 的偏差（需产品确认）

1. **R0 未接外部来源与向量索引**：`search_sources` 默认走同范围词法并显式标注
   `retrieval_method=lexical`、`degraded=true`；注入 provider 才走向量。
   接口返回扁平 list（空 `[]`），另有 `external_source_status()`。
2. **Document 删除是硬删**（无 `deleted_at` 软删）；删除后版本/块/分块级联清理。
3. **分块末块可能 <800 码点**（尾部短块），属分块算法边界，不影响偏移一致性。
4. **revision 仅接受 `finding_ids`**：无有效补丁时返回 422，由 runner 收敛。
5. **SSE 直接读事件表**并持有请求会话；长连接期间占用一个 DB 会话。
6. **`GET /projects` 走 ORM 直查**（`project_service` 暂无 `list_projects`），
   分页与过滤在路由层完成。

## 6. 集成层修正（Lead 收口，回应 verifier 偏差 ①②与错误外壳）

verifier 在报告里点出三处"看起来生效、实际没生效"的问题。Lead 已逐条修掉并用
独立用例锁住：

| 问题 | 处置 | 回归 |
| --- | --- | --- |
| `FastAPI(request_body_max_size=...)` 不是合法参数，被静默忽略，22MiB 上限从未执行 | 新增 `src/backend/middleware/request_size_limit.py`（ASGI 中间件，仅覆盖 `/api/v1/research`，`Content-Length` 预判 + 分块计数），`app.py` 移除无效 kwarg 并在 CORS 内层注册 | `test_integration_wiring.py::test_research_body_limit_rejects_oversized_request` |
| `config.py` 未声明 SSE 字段，`routers/research.py:764` 只能 getattr 兜底 | 在 `config.py` 声明 `RESEARCH_SSE_MAX_SECONDS=60.0`、`RESEARCH_SSE_POLL_SECONDS=0.5`，测试不再靠 `settings.__dict__` 注入 | 既有 SSE 用例 |
| 研究域鉴权失败走全局处理器，返回 `{"success": false}` 外壳，与 §8.2 不一致 | `routers/research.py` 新增 `require_research_user` 依赖（基于 `get_optional_user_id`），替换 23 处 `Depends(get_current_user)`，统一 `{"error": {code, message, details, retryable, request_id}}` | `test_integration_wiring.py::test_research_auth_error_uses_unified_envelope` |

附带的协议一致性：413 也带 `request_id`（中间件在 `RequestIDMiddleware` 外层，
因此回落读 `X-Request-ID`，最后兜底 UUIDv4），满足 PRD §8.2 错误体要求。

新增用例合计 3 条（`src/backend/tests/test_research/test_integration_wiring.py`），
研究域用例总数 287 → 290。

## 7. 明确不属于 R0 的项（R1/R2）

- R1：真实全文诊断质量（多轮重试、质量评分 `quality_score` 分布）、修改建议的
  领域深度、前端 `ResearchWorkspace` 工作台、来源检索接入、按项目容量策略细化。
- R2：质量验证（AT-044 — AT-056）、埋点指标看板、灰度发布链。

## 8. 未提交改动提醒

工作区包含用户原有未提交改动与本轮新增文件；本轮**未执行** `git reset`/`git checkout`，
也未改写历史。提交前请按团队规范分组提交（研究域、装配、测试、文档）。
