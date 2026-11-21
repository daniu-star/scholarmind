# R0 独立验证报告（Research R0）

- 验证对象：ScholarMind R0 研究域后端（`src/backend/research/` + `src/backend/routers/research.py` + `app.py` 挂载 + `db/session.py` 建表）
- 验证角色：独立验证子代理 verifier（只写测试与报告，不改生产代码）
- 验证时间：2026-11-20 00:35（Asia/Shanghai）
- 环境：Windows，Python 3.14（项目 `.venv`），pydantic 2.13.4 / fastapi 0.136.3 / httpx 0.28.1 / sqlalchemy 2.0.50 / pytest 9.0.3 / pytest-asyncio 1.4.0；真实 `create_app()` + `httpx.ASGITransport` + 每用例独立临时 SQLite
- 执行命令（只跑研究目录，未跑全量旧用例）：

```
.venv/Scripts/python.exe -m pytest src/backend/tests/test_research -q
```

## 1. 最终结果

| 项 | 数值 |
| --- | --- |
| 测试文件 | 8 个（contracts / documents / ownership / capabilities / billing / tasks_api / revision / honesty） |
| 用例总数 | **287** |
| 通过 | **287** |
| 失败 | **0** |
| 错误/警告 | 0 / 0（PytestWarning 已消除） |
| 总耗时 | 256.75s（约 4 分 17 秒） |

单模块基线（同一命令的组成部分，供对照）：

| 模块 | 用例数 | 结果 | 覆盖主题 |
| --- | --- | --- | --- |
| `test_contracts.py` | 133 | pass | 枚举/状态机/常量/全部 DTO 校验器/`completion_errors` |
| `test_documents.py` | 39 | pass | 解析器偏移与状态诚实性、分块 800–1200/重叠≤100、上限、上传/复用/版本/删除、HTTP 20 MiB/413/415、跨用户 404 |
| `test_ownership.py` | 10 | pass | 7 个归属守卫统一 404、存在性不泄露 |
| `test_capabilities.py` | 17 | pass | 能力如实上报（不得谎报 ready）+ 管道独立包（AT-021） |
| `test_billing.py` | 14 | pass | 预留/结算/释放、幂等、账本行、并发 429、billing_group 冲突 |
| `test_tasks_api.py` | 35 | pass | REST 鉴权/伪造身份/幂等键/Skill 契约/事件 SSE/取消/归属隔离 |
| `test_revision.py` | 30 | pass | `validate_hunks` 纯函数 + `apply_proposal` 409/422/幂等/成果 |
| `test_honesty.py` | 9 | pass | 导出诚实交付、模型不可用/垃圾输出不假成功、终态重入、成果底线 |

## 2. AT 映射表（R0 范围）

结论口径：`pass` = 行为已被真实运行断言；`partial` = 主路径通过但矩阵要求的部分场景未覆盖；`not_covered` = 本 R0 后端测试范围未覆盖（附原因）。**不把“函数存在/HTTP 200”当通过。**

| AT | 结论 | 证据（测试文件::用例） | 说明 / 缺口 |
| --- | --- | --- | --- |
| AT-004 Skill 契约 | partial | `test_tasks_api.py::test_absent_skill_ids_means_no_skill_selected`、`test_explicit_empty_skill_ids_loads_nothing`、`test_enabled_skill_is_recorded_in_snapshot`、`test_unknown_or_disabled_skill_rejected_before_billing`；`test_contracts.py`（skill_ids ≤8/去重/显式空） | 缺席 vs 显式空 vs 未知/禁用/超量/重复均按契约；**缺口**：“选中规则真正进入 prompt 且哈希可追溯”未断言（无 prompt 快照链路测试），legacy 字段同值/冲突未覆盖（R0 路由无 legacy 字段） |
| AT-006 伪造身份 | pass | `test_tasks_api.py::test_every_endpoint_requires_authentication`（16 端点 401/`AUTHENTICATION_FAILED`）、`test_forged_owner_id_in_task_body_is_rejected`、`test_forged_user_id_in_project_body_is_rejected`；`test_ownership.py`（owner 过滤 + DB 行归属） | 伪造 owner_id/user_id 被 `extra="forbid"` 422 且不落任何行；显式 owner 不授予权限 |
| AT-007 跨用户统一 404 | partial | `test_tasks_api.py::test_cross_user_reads_return_unified_404`（项目/文档/块/任务/诊断/成果/下载/取消/恢复/重试/事件）、`test_lists_do_not_leak_other_users_content`、`test_findings_are_owner_scoped`；`test_documents.py::test_http_document_reads_are_owner_scoped`、`test_other_user_cannot_read_document`；`test_revision.py::test_apply_other_users_proposal_is_404` | 缺口：evidence（来源/证据行）跨用户与搜索/replay 泄露未覆盖（本轮 R0 未测 evidence 检索链路） |
| AT-009 容量按 owner | pass | `test_documents.py::test_project_file_limit_is_per_owner` | A 塞满 50 个文件后 B 首次上传成功（422 `RESOURCE_LIMIT` 只作用于 A） |
| AT-010 同哈希复用不泄露 | pass | `test_documents.py`（同项目同 owner 复用 `reused=True` 单行；不同用户同哈希各自建文档、不返回对方文件名/正文/归属） | 复用仅限 owner+project 命中；他人同内容按新文件处理 |
| AT-011 20 MiB/413/415 | pass | `test_documents.py::test_http_upload_accepts_twenty_mib_document`（>19 MiB 且 >10 MiB 的合法 DOCX 201）、`test_http_upload_over_limit_returns_413`、`test_http_upload_unsupported_type_returns_415`、service 层 `MAX_FILE_BYTES+1` 无残留行 | ASGI 层通过；**风险**：真实反向代理/网关的 10 MiB 限制不在本测试范围（见 §4.3） |
| AT-021 管道独立包 | partial | `test_capabilities.py::test_pipelines_package_does_not_import_web_or_db_stack`（子进程独立导入 `pipelines`，断言未加载 fastapi/starlette/sqlalchemy/pydantic_settings）、`test_generation_and_review_are_separate_packages` | 缺口：两个合成流程并行、模型快照绑定与初始化顺序变化的运行期验证未覆盖 |
| AT-022 模型失败不假成功 | partial | `test_honesty.py::test_review_with_unavailable_model_is_recoverable_not_success`（recoverable、无成果、无 verdict、预留保持）、`test_review_with_garbage_model_output_does_not_succeed`（partial 且成果非空、无 verdict、有明确 error） | 缺口：限流重试耗尽、流中断、长度截断的精确分支未逐一模拟；未撤销“客户端断开不得退款”场景 |
| AT-023 Skill 字段适配 | not_covered | — | 属前端/适配层字段（paper_content、review_score、score_history、round_number），R0 后端测试范围外；建议由 T02/T05 的适配器测试补齐 |
| AT-024 提纲/字数实际入参 | partial | `test_contracts.py`（draft 必须带 outline 版本、target_word_count 仅 draft/revision、范围 1..1_000_000）；`test_tasks_api.py` 受理快照含 `request_fingerprint` | 缺口：两份不同提纲/不同字数的执行输入快照对比未覆盖（需要执行链路 prompt 快照） |
| AT-025 子量表/总分诚实 | not_covered | — | R0 后端未承载该评分量表逻辑（属评审/前端展示契约），本目录无对应断言 |
| AT-026 严重缺陷 vs 最大轮次 | partial | `test_contracts.py::completion_errors`（review 成功必须有 coverage 且 ratio=1.0 + quality_verdict；缺成果即失败）；`test_honesty.py`（失败不得 succeeded） | 缺口：真实/桩模型跑完整 review 到 `issues_found` 的端到端未做；“最大轮次无有效结果 → failed/partial”未覆盖 |
| AT-034 空交付/空修改不算成功 | pass | `test_honesty.py::test_export_with_empty_body_fails_and_releases_quota`、`test_create_artifact_rejects_empty_body_and_unknown_kind`、`test_export_task_succeeds_only_with_non_empty_artifact`；`test_revision.py::test_validate_rejects_no_op_replacement`；`test_contracts.py::completion_errors`（失败/部分不得声称成功） | 空正文导出 → failed 且释放额度；空成果 422；原文回填不算修改 |
| AT-038 重复投递/并发/旧租约 | partial | `test_tasks_api.py::test_same_key_same_request_replays_the_same_task`、`test_same_key_different_request_is_rejected`（409 `IDEMPOTENCY_CONFLICT`）；`test_billing.py::test_same_idempotency_key_replays_without_second_reservation`、`test_active_reservation_blocks_second_task_in_same_group`；`test_honesty.py::test_terminal_task_is_not_executed_twice`；事件 sequence 连续 | 缺口：两个 worker 真并发抢租约、旧租约迟到写入被 fencing 拒绝未做并发测试 |
| AT-039 取消幂等与额度释放 | pass | `test_tasks_api.py::test_cancel_is_idempotent_and_emits_single_terminal_event`（重复取消 state_revision 不推进、单终态事件、终态不可恢复）；`test_billing.py::test_release_refunds_once_and_is_idempotent` | 取消后事件序列 `task.accepted → task.cancelled`；释放只退一次 |
| AT-040 额度不被超用 | partial | `test_billing.py::test_concurrent_second_task_rejected_without_extra_reservation`（429 `CONCURRENCY_LIMIT` scope=user）、幂等重放不多扣、`test_billing_group_*` | 缺口：“最后 1 额度 + 两个不同任务真并发”与免费 greeting 伪造场景未覆盖（后者属对话入口，不在研究域） |
| AT-041 模型快照隔离 | not_covered | — | 需 `runtime.capture_snapshot` + 会员过期/默认模型变更后的执行链测试，R0 本目录未覆盖；建议 T04/T07 补 |
| AT-042 失败释放/持有/幂等 | partial | `test_billing.py::test_free_user_review_rejected_402_before_any_row`（402 前零任务/事件/outbox/账本行）、`test_release_*`、`test_settle_is_idempotent_and_marks_reservation`；`test_honesty.py` recoverable 保持 reserved | 缺口：客户端断开（健康任务不得退款）、auto-recovery 24h 超时释放未做假时钟测试 |
| AT-043 支付/权益回归 | not_covered | — | 研究域测试未跑既有支付/权益用例（任务要求只跑 `test_research` 目录）；SKU 499/1999/3990/5990 与重复回调由既有支付测试负责 |

补充（非 R0 主清单，但本目录已提供证据的能力诚实性）：AT-005/AT-018/AT-048/AT-049 的“能力不得谎报”由 `test_capabilities.py` 17 条覆盖（每条 checked_at/reason/真实前置条件；未配置凭证只能 disabled/degraded；未开放能力 disabled）。

## 3. 每条用例一行结果

287 条全部 `PASS`。按模块给出结果与对应主题（逐条明细可用 `pytest -q` 复现，失败时为 0 条）：

- `test_contracts.py`（133 PASS）：schema 版本、TaskKind/Status/EventType、17 条合法 + 11 条非法迁移、`EVENT_TERMINAL_STATUS`、`QUALITY_VERDICT_KINDS`、`Actor`/`new_id`/NFC/`text_hash`/`content_hash`、Idempotency-Key 边界（7/8/128/129/非法字符）、R0 常量（20 MiB、8 Skill、200 页、200000 码点、维度/保留项/导出格式/期刊样式）、`TaskInputRefs`/`TaskScope`/`TaskConstraints`/`ResearchTaskInput` 全部校验器、`ResumeInput`、`Coverage` 比例与 `full_coverage`、`TaskResult` 仅 succeeded 可带 verdict、`Finding` 局部必须有定位+引用、`RevisionHunk` 哈希不匹配、`TaskSnapshot`、`TaskEventDTO`、`ArtifactRef`、`completion_errors`。
- `test_documents.py`（39 PASS）：解析偏移可切片、文本规范化、空/二进制/不支持 MIME 的状态诚实性、DOCX 标题/表格/损坏包、PDF 页数上限 PARTIAL、`validate_limits` 422、分块尺寸/偏移/重叠/超长块拆分、上传落库三表、同内容复用、版本递增、空文件 422、超限 413 无残留、20 MiB 成功、415、非法 UTF-8 422、码点超限 422、文件名去路径、跨用户 404/删除/块排序、50 文件上限按 owner、HTTP 20 MiB/413/415/跨用户 404。
- `test_ownership.py`（10 PASS）：project/document/version/task/artifact/proposal 本人可取、他人 404、缺失 id 与越权返回完全一致的 `(404, NOT_FOUND)`、`owned()` 真值。
- `test_capabilities.py`（17 PASS）：能力名完整唯一、每条带 checked_at/reason/合法状态、database 真实探测、解析器依赖探测、模型无凭证 disabled/假 key 未探测 unknown/探测失败 degraded/可达 ready、未开放能力 disabled、免费用户 task.* unauthorized → 会员后 ready、ready 条目必须有证据、vector 不掩盖回退、管道包独立导入。
- `test_billing.py`（14 PASS）：CAPABILITY_BY_KIND 固定映射、402 前零行、冻结生成额度恰好一次预留、settle/release 幂等、membership/external_subscription 记录、chart/export 免费不写账本、幂等重放不二次预留、409 `IDEMPOTENCY_CONFLICT`、并发 429、billing_group 活跃冲突、快照含 billing_group/指纹。
- `test_tasks_api.py`（35 PASS）：16 端点鉴权、伪造字段 422、缺键/短键/非法字符 422、同键重放、409 冲突、202 受理快照、SSE 帧/游标/Last-Event-ID/不匹配 422/终态空流、取消幂等、恢复与重试守卫（409 `STATE_CONFLICT` / `STATE_REVISION_MISMATCH`）、跨用户 404、列表隔离、findings owner 作用域、Skill 契约、任务 ID/事件序号。
- `test_revision.py`（30 PASS）：`validate_hunks` 合法/非字符串/None/非数组/非对象/缺字段/负区间/越界/原文不符/哈希不符/NFC 等价/无差异/重叠/受保护数字与日期/显式关闭保留项/超 6000 码点；`apply_proposal` 成功创建新版本+块+变更说明+推进 state_revision、错误基准 409、文档已前进 409、正文哈希不符 409、同键重放同结果、异键二次采纳 409、invalid 提案 422、`HUNK_NOT_FOUND`/`NO_HUNKS`/`HUNK_VALIDATION_FAILED`/`MISSING_EXPECTED_VERSION`/非法幂等键、他人提案 404。
- `test_honesty.py`（9 PASS）：导出成功必须有非空成果且终态事件带 artifact_ids、空正文导出 failed+释放、模型不可用 recoverable 不假成功、垃圾输出 partial 不 succeeded 且无 verdict、终态重入无副作用、排队快照无成果、空成果/未知类型 422、未知期刊样式/格式 422、导出 owner 隔离。

## 4. 偏差与风险（需 Lead 决策/后续跟踪）

### 4.1 已验证并已修复的缺陷

1. **preset Skill 全部被误判不可用（AT-004 阻断）**
   - 现象：空库无 Skill ORM 行时，`task_service._skill_enabled` 的 `PRESET_SKILLS` 兜底用 `item.get("skill_id")` 匹配，而 `services/skills_service.py` 的预设条目主键字段是 `"id"` → `academic-researcher` 等 enabled 技能也返回 `422 SKILL_UNAVAILABLE`。
   - 处理：已在 `send_message` 中报告 file+symbol+期望键，Lead 修复为 `item.get("id") or item.get("skill_id")`。
   - 回归保护：`test_tasks_api.py::test_enabled_skill_is_recorded_in_snapshot`，修复后整目录 287 passed。

### 4.2 与契约/文档的偏差（不阻断，但建议对齐）

2. **`TaskAccepted` 无 `schema_version`**：其他 DTO（TaskResult/TaskEventDTO/CapabilityResponse）都带版本，受理响应只有 `task_id/status/state_revision/billing_state/snapshot_summary`。若前端依赖 schema_version 会缺字段；R0 契约测试按现状断言。
3. **任务 ID 前缀为 `task_`**（非早期文档示例的 `rtask_`）：实现已统一为 `new_id("task")`；测试按实际断言，文档示例若引用 `rtask_` 需同步。
4. **SSE 配置项未在 `Settings` 声明**：路由用 `getattr(settings, "RESEARCH_SSE_MAX_SECONDS", 60)` / `RESEARCH_SSE_POLL_SECONDS`（默认 0.5），但 `config.py` 无这两个字段，环境变量无法生效。测试通过写 `settings.__dict__` 压到 1s/0.05s；**生产上排队任务的事件流会等 60s**，建议正式声明配置字段并给默认值。
5. **`create_task` 新增强制归属校验**：现在要求 project 属于当前用户（404）、正文版本存在且属于该项目（否则 422 `PROJECT_DOCUMENT_MISMATCH`）、大纲/审阅版本与 source_ids 同样校验，且发生在扣额之前。行为正确但属对旧调用的破坏性收紧，旧客户端传“任意版本 id 也能受理”的用法会 404。
6. **幂等键冲突语义**：已按 PRD §8.2 为 `409 IDEMPOTENCY_CONFLICT`（不同请求同键），422 仅保留给键缺失/格式非法；测试已同步。

### 4.3 环境/部署风险（测试无法完全覆盖）

7. **`create_app(request_body_max_size=10*1024*1024)` 不是 FastAPI/Starlette 参数**，`inspect.signature` 中不存在，实测被静默忽略（ASGI 下 20 MiB 请求可进入路由）。因此 20 MiB 用例通过**不能**证明真实反向代理（Nginx/网关）的 10 MiB 限制已解除；需要在部署层验证 `client_max_body_size` 与网关限额。
8. 测试使用真实 `create_app()`（每会话一次）+ 每用例独立临时 SQLite；无 lifespan（ASGITransport 不触发 startup），因此**dispatcher 后台任务未在测试中启动**。任务执行用例直接调用 `task_runner.execute_task(..., client=替身)`，覆盖执行器语义但不覆盖 outbox 消费者轮询本身。

### 4.4 未覆盖清单（按 AT）

- AT-023（Skill 字段适配）、AT-025（子量表/总分诚实）、AT-041（模型快照隔离）、AT-043（支付 SKU 回归）：R0 本目录范围外或需专门链路/既有支付测试。
- AT-004 的 prompt 哈希可追溯、AT-007 的 evidence/search 泄露、AT-021 的并行流程与快照绑定、AT-022 的限流/流中断/截断分支、AT-024 的执行输入快照对比、AT-026 的完整 review 端到端、AT-038 的真并发租约、AT-040 的真并发最后额度、AT-042 的客户端断开/24h 超时释放：均已在上表标 `partial` 并注明缺口，建议在 R1 或对应 T0x 用例补齐。

## 5. R0 放行结论

**研究域后端可放行（有保留条件）**：

- 287 条研究域测试全绿，R0 主清单中 AT-006/009/010/011/034/039 已 `pass`；AT-004/007/021/022/024/026/038/040/042 为 `partial`（主路径真实通过，缺口见 §2/§4.4）；AT-023/025/041/043 未覆盖且有明确归属。
- 保留条件：① §4.2 第 4/5/6 条需在发布说明中告知（SSE 配置字段、归属收紧、409 语义）；② 真实部署需验证代理层 20 MiB 限制（§4.3 第 7 条）；③ R0 整体放行仍需 T09 所述“真实交付页面 + 既有权限/支付/上传回归 + 能力关闭一致性”证据，本报告只覆盖研究域后端与接口契约，不等同于产品级 R0 放行。

## 6. 复现

```bash
# 项目根目录
.venv/Scripts/python.exe -m pytest src/backend/tests/test_research -q
```

期望：`287 passed`（无 failed/error/warning）。测试文件位于 `src/backend/tests/test_research/`，均为本次验证新增，未修改任何生产代码。

---

## 附录：Lead 复核补记（2026-11-20，报告提交后）

本附录记录 Lead 针对本报告 §4 偏差所做的修复与复测，原正文保留未改动（保留"提出 → 修复 → 复测"的可追溯链）。

| 报告中的偏差 | 修复 | 复测 |
| --- | --- | --- |
| §4.2 第 4 条：`config.py` 未声明 SSE 字段 | 在 `Settings` 声明 `RESEARCH_SSE_MAX_SECONDS=60.0` / `RESEARCH_SSE_POLL_SECONDS=0.5` | 既有 SSE 用例 |
| §4.2 第 5 条：`create_task` 归属收紧是破坏性变更 | 保留该收紧（这是 FR-03 的要求），在 `R0_DELIVERY.md` §5 与发布说明中显式告知 | `test_tasks_api.py` 35 条 |
| §4.3 第 7 条：`request_body_max_size` 非法参数被忽略 | 新增 `src/backend/middleware/request_size_limit.py`（仅覆盖 `/api/v1/research`），`app.py` 移除无效 kwarg | 新增 `test_integration_wiring.py` 3 条 |
| 额外发现：研究域 401 外壳与 §8.2 不一致（全局处理器返回 `{"success": false}`） | `routers/research.py` 改用 `require_research_user` 依赖（23 处），统一 `{"error": {...}}`；错误码沿用 `AUTHENTICATION_FAILED` | 同上文件 `test_research_auth_error_uses_unified_envelope` |

复测结果：`pytest src/backend/tests/test_research -q` → **290 passed / 0 failed**（4 分 12 秒，较原 287 增加 3 条集成层用例）。
