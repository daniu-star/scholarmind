# R1 独立验证报告（Research R1 / T10–T20）

- 验证对象：ScholarMind 研究工作区 R1（`src/backend/research/` 增量 + `routers/research.py` metrics 端点 + `src/frontend/src` 研究工作区）
- 验证角色：独立验证子代理 verifier（只写测试与报告，未修改任何生产实现、R0 既有测试或前端源码）
- 验证时间：2026-11-20 11:00（Asia/Shanghai，导出硬化回归补测后更新）
- 环境：Windows 11，Python 3.14.5（项目 `.venv`），pytest 9.0.3 / pytest-asyncio 1.4.0 / SQLAlchemy 2.0.50 / FastAPI 0.136.3 / httpx 0.28.1；真实 `create_app()` + `httpx.ASGITransport` + 每用例独立临时 SQLite，不联网、不调真实模型
- 独占写范围：`src/backend/tests/test_research_r1/**`、本报告；未触碰 `src/backend/research/**`、R0 测试、前端

## 1. 最终结果

执行命令（按任务约束只跑 R1 目录，不跑全量）：

```
.venv/Scripts/python.exe -m pytest src/backend/tests/test_research_r1 -q
```

真实输出（导出硬化与幂等回归补测后的最终运行）：

```
160 passed in 76.11s (0:01:16)
```

（该目录本轮多次完整运行：导出硬化补测前最后一次为 155/155，补入导出幂等与附录回归用例后为 160/160；本次引用最后一次输出。`-q` 未产生 warning/xfail。）

| 项 | 数值 |
| --- | --- |
| 测试文件 | **11 个** |
| 用例总数 | **160** |
| 通过 | **160** |
| 失败 / 错误 | **0 / 0** |
| skip / xfail | **0 / 0** |
| 总耗时 | 76.11s |
| `ruff check src/backend/tests/test_research_r1` | `All checks passed!` |

单模块结果（同一命令的组成部分）：

| 模块 | 用例数 | 结果 | 覆盖主题 |
| --- | --- | --- | --- |
| `test_analytics_metrics.py` | 13 | pass | T19：成功率分母、事件去重、分位/均值、owner/时间窗、metrics 端点鉴权与 self 作用域、free-text 不泄露 |
| `test_checkpoints.py` | 10 | pass | T15：检查点空值/归一化/roundtrip、重试续跑、显式 attempt、按 task_id fencing |
| `test_completeness.py` | 21 | pass | T15：`expected_sections`/`section_coverage` 纯函数、结构缺失 finding、真实已查范围 |
| `test_export_hardening.py` | 8 | pass | T17：partial 标记、空正文拒绝、DOCX 重开校验、未知体例/格式 422、显式版本绑定、附录只来自真实诊断来源 |
| `test_export_idempotency.py` | 4 | pass | T17：同键同请求复用单一成果、同键换请求 409、附章无来源 422（include_report/include_change_log） |
| `test_frontend_contract.py` | 14 | pass | T18：API 导出名、SSE 不用 EventSource、断流不取消服务端、路由注册、状态与禁用文案、无第三方依赖 |
| `test_recovery.py` | 6 | pass | T14：重启派发 outbox、重复投递只执行一次、租约/fencing、取消后迟到写入拒绝、SSE 重放幂等、终态不可再领 |
| `test_review_flow.py` | 10 | pass | T15：续跑只分析剩余块、不重复读入已分析段、跨版本检查点忽略、尾部保证、预算耗尽诚实、结构+模型 finding 分源、严重问题 issues_found、模型不可用不假成功 |
| `test_source_adapters.py` | 40 | pass | T13：DOI/URL 归一化、注册表、Crossref 映射、无元数据不编造、摘要降级、fetch/bytes 兼容 |
| `test_source_fidelity.py` | 29 | pass | T13：来源诚实、URL 安全、用户引文原样保留且 unresolved、材料等级与证据强度一致 |
| `test_workspace_boundaries.py` | 5 | pass | T10/T14：同键重放、异体冲突 409、跨用户 404、未知版本不建任务、匿名拒绝 |

## 2. AT 映射（R1 范围）

结论口径：`pass` = 本轮真实运行断言通过；`partial` = 主路径有断言但矩阵要求的场景未全覆盖；`not_covered` = 本轮 R1 测试范围未覆盖（附原因，不把“函数存在/200”当通过）。标注「R0 继承」的条目证据来自已放行的 R0 测试，本轮未重跑 R0 目录。

| AT | 结论 | 证据（测试::用例） | 说明 / 缺口 |
| --- | --- | --- | --- |
| AT-008 项目隔离 | partial | `test_workspace_boundaries.py::test_other_user_cannot_read_or_cancel_task`、`test_anonymous_create_is_rejected`；R0 `test_documents.py` 项目/文档归属 | 跨用户隔离通过；**缺口**：同一用户两个同题项目的资料不混入未单独构造（R0 复用逻辑按 owner+project 过滤） |
| AT-011 上传边界 | partial | R0 `test_documents.py`（20 MiB、413、415、无半文件）；`test_export_hardening.py`（交付侧 partial 标记） | R1 未改上传链路；上传中断/磁盘失败未模拟 |
| AT-012 DOCX 表格/脚注、PDF 页 | not_covered | — | R1 解析器未变更；R0 已有 DOCX 表格/损坏包与 PDF 用例，但 R1 未重跑、脚注未断言 |
| AT-013 无文本页/加密/不可解析 | not_covered | — | 同上，属解析器范围（R0 `test_documents.py` 覆盖部分状态诚实性） |
| AT-014 尾部错误进入分析 | **pass** | `test_review_flow.py::test_tail_block_is_analyzed_even_when_budget_is_tight`（仅 1 次调用预算仍分析含 TAILMARK 的尾窗，`truncated=True`、覆盖少于总块、未分析原因非空） | 断言的“尾部”是文档最后一段所在窗口；20000 字样本未单独构造，但窗口/预算机制为同一路径 |
| AT-015 按唯一预期块计覆盖 | **pass** | `test_review_flow.py::test_resume_analyzes_only_remaining_blocks`、`test_budget_exhausted_checkpoint_skips_model_and_is_honest`；`test_completeness.py::test_duplicate_ordinals_do_not_double_count`、`test_covered_and_missing_follow_expected_order` | 覆盖 = expected∩analyzed，去重；未分析块逐条给出 `block:N（原因）`；预算耗尽时不调用模型、只给 `insufficient_evidence` 且逐块说明（任务层 succeeded/failed 由 R0 状态机保证） |
| AT-016 尾部事实召回 | not_covered | — | 本轮未写检索/索引集成测试；私有文档尾部事实召回无证据 |
| AT-017 词法回退与降级 | partial | `test_source_fidelity.py::test_search_finds_saved_source_and_marks_degraded`、`test_search_without_match_returns_empty_list`；`test_source_adapters.py::test_reset_makes_registry_unavailable` | 无适配器时搜索标记 `degraded_reason=external_source_unavailable`；**缺口**：向量服务故障注入、索引重建期旧索引可用未测 |
| AT-018 元数据/摘要诚实展示 | **pass** | `test_source_adapters.py`（省略字段保持空、摘要→`abstract`、无标题不造标题）；`test_source_fidelity.py::test_title_only_source_is_unresolved`、`test_abstract_only_source_is_marked_abstract` | 不伪造作者/年份/DOI；空即为空 |
| AT-019 虚构 DOI/错引不写入 | partial | `test_source_fidelity.py::test_unresolved_citations_keep_user_text_verbatim`、`test_without_adapters_everything_is_degraded_and_verbatim`、`test_adapter_failure_degrades_without_fabrication` | 用户疑似错引原样保留并列入 unresolved；**缺口**：模型输出中虚构 DOI 的写入路径未单独构造（当前发布链路不把模型引文直接写 SourceRecord，但无断言） |
| AT-020 可解析但仅摘要 | **pass** | `test_source_fidelity.py::test_abstract_cannot_support_original_claim`（摘要来源 + `supported` → 422 `EVIDENCE_UNSUPPORTED_MATERIAL`）、`test_abstract_only_source_is_marked_abstract`；`test_source_adapters.py::test_abstract_marks_material_level_abstract` | metadata_status 可 resolved 而 material_level=abstract；证据强度不得高于材料等级 |
| AT-026 严重问题 vs 轮次耗尽 | partial | `test_review_flow.py::test_critical_finding_yields_issues_found_without_faking_clean`（critical → `issues_found` 且落库/成果一致）、`test_budget_exhausted_checkpoint_skips_model_and_is_honest`（预算耗尽 → `insufficient_evidence`，不假成功） | “达到最大轮次无有效成果 → failed/partial”属任务状态机，R1 目录未覆盖（R0 `test_honesty.py` 有失败不得 succeeded 的基线） |
| AT-027 局部 + 全篇缺失 | **pass** | `test_completeness.py::test_missing_sections_are_reported_with_document_locator`（document scope、locator、checked_sections 为真实已分析章节）、`test_no_analyzed_blocks_means_no_document_claim`（未分析不出全篇结论）；`test_review_flow.py::test_missing_sections_enter_artifact_with_structural_source`（结构 finding 进成果、来源可区分） | 结构性检查只依据章节结构，不猜内容；局部/全篇来源在成果中分别标注 |
| AT-028 缺数据不得编造结果 | not_covered | — | 本轮无“缺数据/效应量 → 建议或 needs_input”的用例；代码路径未声称实现，不得计入通过 |
| AT-029 受保护内容 | pass（R0 继承） | R0 `test_revision.py`（数字/日期/专名/引用/越界/重叠等保护拒绝） | R1 未改补丁校验；本轮未重跑 |
| AT-030 Unicode 码点 | pass（R0 继承） | R0 `test_revision.py`（NFC 等价、码点区间、emoji/组合字符） | 同上 |
| AT-031 版本冲突 409 | pass（R0 继承） | R0 `test_revision.py`（stale base → 409 `VERSION_CONFLICT`） | 前端静态检查仅确认冲突提示存在 |
| AT-032 采纳幂等 | **pass** | `test_workspace_boundaries.py::test_same_key_same_body_replays_one_task`、`test_same_key_different_body_conflicts_without_second_task`；R0 `test_revision.py`（同键重放同一结果） | 任务受理/采纳两层均有幂等断言 |
| AT-033 未授权写入 | **pass** | `test_workspace_boundaries.py::test_other_user_cannot_read_or_cancel_task`、`test_unknown_version_is_rejected_without_creating_task`、`test_anonymous_create_is_rejected` | 不因越权/未知版本产生任务行 |
| AT-034 空交付不算成功 | **pass** | `test_export_hardening.py::test_empty_version_export_is_rejected_without_artifact`、`test_docx_render_mismatch_aborts_without_artifact`；`test_export_idempotency.py::test_include_sections_without_source_are_rejected`（附章无来源 422 且零成果）；R0 `test_honesty.py` | 空正文/渲染不一致/缺附章来源均不落成功成果，也不生成缺章节却自称完整的文件 |
| AT-035 SSE 重放/去重 | **pass** | `test_recovery.py::test_sse_replay_is_idempotent`（同游标重放帧完全一致、终态后空流）；R0 `test_tasks_api.py`（帧/游标/Last-Event-ID） | 持久事件按 sequence 重放，客户端可去重 |
| AT-036 崩溃后恢复 | partial | `test_recovery.py::test_pending_outbox_is_dispatched_after_restart`（重启后派发、attempt_no=1、事件/outbox 落库）；`test_checkpoints.py::test_retry_without_checkpoint_resumes_from_previous_attempt`、`test_review_flow.py::test_attempt_bound_run_writes_checkpoint` | **缺口**：重启后由 dispatcher 真正“复用检查点继续分析”的端到端未串起来（检查点复用与重启派发分别验证） |
| AT-037 broker 不可用 | partial | `test_recovery.py::test_pending_outbox_is_dispatched_after_restart`（待投递消息保留并重试成功） | **缺口**：broker 不可用时提交 → 503 且无预留；提交后 broker 故障的 outbox 重试期限未测 |
| AT-038 重复投递/旧租约 | **pass** | `test_recovery.py::test_duplicate_outbox_delivery_executes_task_only_once`、`test_lease_prevents_second_worker_and_stale_worker_cannot_write`、`test_terminal_task_is_never_reclaimed` | 重复投递单成果/单终态；并发领取 409 `LEASE_HELD`；旧 worker 被 fencing 拒绝 |
| AT-039 取消幂等/迟到结果 | **pass** | `test_recovery.py::test_cancel_rejects_late_worker_writes`（终态后执行器跳过、无成果、无 attempt、不可回 running）；R0 `test_tasks_api.py`（重复取消） | 取消后迟到写入被拒 |
| AT-040 额度不被超用 | partial | R0 `test_billing.py`（并发 429、幂等不多扣）；`test_analytics_metrics.py` 仅指标口径 | R1 未改计费；本轮未重跑 R0；“仅剩 1 额度两任务并发”未在 R1 复验 |
| AT-041 模型快照隔离 | not_covered | — | 需 runtime 快照 + 会员到期/默认模型变更执行链；R1 目录无 |
| AT-042 失败释放/持有 | partial | `test_recovery.py::test_cancel_rejects_late_worker_writes`（终态后无成果/无 attempt）；R0 `test_billing.py`、`test_honesty.py` | **缺口**：客户端断流不得退款、24h 自动恢复超时未做假时钟 |
| AT-043 支付/权益回归 | partial | R0 `test_billing.py`（402 前零行、SKU 相关基线）；`test_analytics_metrics.py::test_metrics_endpoint_requires_authentication` | R1 未改支付；既有支付/权益用例本轮未重跑 |
| AT-044 迁移/回退/dry-run | not_covered | — | 本轮只做代码级验证，未执行迁移两次/回退演练 |
| AT-045 指定版本导出/DOCX 重开 | **pass** | `test_export_hardening.py::test_complete_markdown_export_has_no_partial_markers`（validation 记录 `document_version_id`）、`test_docx_export_reopens_and_records_sha256`（python-docx 可重开、`reopen_ok`、sha256 与解包字节一致、zip/OOXML 头）、`test_http_export_appends_diagnosis_only_from_real_source`（附章来自真实 review 任务）、`test_http_export_rejects_unknown_style_and_format`（422 `UNSUPPORTED_JOURNAL_STYLE`）、`test_export_idempotency.py`（同键重放单成果、异体 409） | 版本由 `document_version_id` 显式指定；“浏览器另有未保存 V3”不适用于无状态后端，前端静态检查不伪造写入 |
| AT-047 浏览器交互/响应式 | partial | `test_frontend_contract.py`（状态、禁用说明、abort 只在本地、无假成功文案） | **缺口**：1440/390px、键盘焦点、真实点击/上传/采纳未跑浏览器 E2E |
| AT-048 root build/路由兼容 | partial | `test_frontend_contract.py::test_router_registers_research_page_and_keeps_old_entry`（`research` 标题「研究工作区」，保留 `researcher`） | **缺口**：正式构建产物与实际页面未验收 |
| AT-049 恶意来源/权限 | partial | `test_source_adapters.py::test_safe_source_url`；`test_source_fidelity.py::test_unsafe_urls_are_rejected`（私网/回环/凭据/`file:`）；`test_workspace_boundaries.py`（越权 404） | **缺口**：日志/事件不含 token/全文/联系方式未断言 |
| AT-050 20 份样本完成率 | not_covered | — | 需版本化合成样本批量执行；本轮仅提供 metrics 口径，不能替代评估报告 |
| AT-051 retry/supplement | partial | R0 `test_tasks_api.py`（retry 守卫）、`test_billing.py`（billing_group 冲突）；`test_checkpoints.py::test_retry_without_checkpoint_resumes_from_previous_attempt` | **缺口**：手动 retry 产生新任务且同 billing_group、supplement_revision 失效依赖检查点未在 R1 串测 |
| AT-052 指标作用域/去重 | **pass** | `test_analytics_metrics.py::test_success_rate_denominator_excludes_cancelled_and_in_flight`、`test_terminal_event_replay_is_counted_once`、`test_owner_and_since_scope_are_applied`、`test_metrics_endpoint_is_self_scoped_and_never_leaks_foreign_tasks`、`test_metrics_never_include_free_text_columns` | 平台失败/partial 留在分母；重放只计一次；未测量返回 `None` 而非 0；无正文/引文泄露 |
| AT-053 共享浏览器旧缓存 | not_covered | — | 需同浏览器双账号 E2E；前端静态检查不覆盖 localStorage/缓存归属 |
| AT-054 删除后撤权 | partial | R0 `test_documents.py`（删除后 404、跨用户 404） | **缺口**：索引/任务/事件重放对已删文档的撤权与迟到 worker 未覆盖 |

## 3. 验证期间发现并已闭环的缺陷

三项均在验证窗口内由实现方修复，现已由普通（非 xfail）用例锁定；本轮不把它们带入放行条件。

| 编号 | 位置 | 现象 | 修复后锁定用例 |
| --- | --- | --- | --- |
| R1-D1 | `src/backend/research/source_adapters.py:345-349`（`_request_json` fetch 分支） | 注入 `fetch(url)` 形态客户端时直接返回 bytes/str，未走 `_response_payload` 解码，`DoiAdapter.lookup` 静默返回 `[]`（看似“没有来源”，实际是解析失败） | `test_source_adapters.py::test_lookup_accepts_fetch_bytes` |
| R1-D2 | `src/backend/research/review_workflow.py:157-201`（`_chunk_text_for_block`） | 索引分块把相邻短块合并后，整块 chunk 文本被当作单块正文，导致检查点中已分析的段落再次进入提示词（重复阅读、重复扣预算） | `test_review_flow.py::test_resumed_paragraph_text_is_not_reanalyzed` |
| R1-D3 | `src/backend/routers/research.py:1023-1035` → `src/backend/research/export_service.py::export` | `POST /exports` 强制要求 `Idempotency-Key`，但路由把它与 `include_report`/`include_change_log` 一起传给 `_service_call`，被 `inspect.signature` 过滤后静默丢弃：同键重放会产生第二份 Artifact 与第二条 export 任务行，勾选附章也不生效（假开关） | `test_export_idempotency.py` 4 条（同键单成果、异体 409、无来源 422）、`test_export_hardening.py::test_http_export_appends_diagnosis_only_from_real_source` |

修复前三者分别表现为“适配器配置了却查不到”“续跑仍在读已分析段”“导出幂等键与附章开关是假开关”；本轮修复后 160 条用例全绿，无跳过、无 xfail。

## 4. 契约（R1_INTERFACE_SPEC）覆盖对照

| 契约 | 覆盖情况 | 用例 |
| --- | --- | --- |
| §2.1 检查点读写/归一化/fencing | 通过 | `test_checkpoints.py` 10 条；`test_review_flow.py::test_attempt_bound_run_writes_checkpoint`、`test_resume_analyzes_only_remaining_blocks` |
| §2.2 completeness 纯函数 | 通过 | `test_completeness.py` 21 条（无 IO、无 DB、未知章节不猜、checked_sections 为真实范围） |
| §2.3 续跑合并/尾部保证/结构 finding | 通过 | `test_review_flow.py` 10 条（含跨版本检查点忽略、预算耗尽诚实、model/structural 分源计数、critical → issues_found） |
| §2.4 适配器/来源诚实/URL 安全 | 通过 | `test_source_adapters.py` 40 条 + `test_source_fidelity.py` 29 条（不编造、摘要降级、用户引文原样保留、材料等级冲突 422） |
| §2.5 指标聚合 | 通过 | `test_analytics_metrics.py` 13 条（分母/去重/分位/owner+since/None 语义/无 free text） |
| §2.6 前端契约 | 静态通过 | `test_frontend_contract.py` 14 条（导出名、fetch+signal、卸载不取消服务端、路由与旧入口、禁用文案、无第三方依赖、无 `insertAdjacentHTML`/`document.write`） |
| §2.7 验证交付 | 完成 | 本报告 + 上述 160 条用例 |
| T17 导出加固（AT-045/AT-034 交付侧） | 通过 | `test_export_hardening.py` 8 条 + `test_export_idempotency.py` 4 条：partial 标记、DOCX 重开校验、幂等键真实生效、附章无来源显式 422 |

## 5. 风险与边界

1. **SQLite ≠ 生产并发**：租约/fencing/重复投递均在单进程临时 SQLite 上验证；PG/Redis 多进程并发、跨进程租约过期、至少一次投递的网络重试仍需生产同构环境复验（`test_recovery.py` 文件头已注明）。
2. **前端只有静态契约**：没有可用的 Node 浏览器测试环境，AT-047/048/053 的布局、焦点、真实上传/采纳、共享浏览器缓存均未验证；静态检查不能代替 E2E。
3. **R0 已复跑，通过**：本轮末尾执行 `.venv/Scripts/python.exe -m pytest src/backend/tests/test_research -q` → `290 passed in 281.41s`，证明 `evidence_service.py` / `review_workflow.py` / `source_adapters.py` / `export_service.py` 的 R1 改动未回归 R0。前端正式构建与浏览器验收仍未执行，需由 Lead 在放行前完成。
4. **未覆盖的 R1 AT**：AT-016/017（检索/索引）、AT-028（缺数据建议）、AT-041（模型快照）、AT-044（迁移回退）、AT-050（20 份样本评估）、AT-053（共享浏览器）、AT-054（删除撤权）没有本轮证据，发布说明中不得宣称通过。
5. **AT-019 的模型引文路径**：当前链路不把模型引用直接写 SourceRecord，但“模型返回虚构 DOI 时被拒绝/记 unresolved”的专门用例未构造，仅覆盖适配器与用户引文侧。

## 6. R1 放行结论（含保留条件）

**结论：有条件放行（R1 后端研究域核心范围）。**

- 放行依据：R1_INTERFACE_SPEC §2.1–§2.5、§2.7 的契约由 160 条真实运行用例覆盖并全绿；R0 回归 290 条全绿；`ruff check src/backend` 通过；验证期间发现的三项缺陷（D1 适配器 fetch、D2 续跑重复读、D3 导出幂等/附章假开关）均已修复且被普通用例锁定；未发现新的阻断缺陷。
- 保留条件（放行前必须由 Lead 完成）：
  1. 执行前端正式构建与真实浏览器验收（至少 AT-047/048/053 的主路径），静态契约不能替代；
  2. 在发布说明中明确未覆盖项（AT-016/017、AT-028、AT-041、AT-044、AT-050、AT-053、AT-054）与 SQLite 单进程边界；
  3. 若要在生产宣称“崩溃后续跑”“重复投递只执行一次”，需补 PG/Redis 多进程验证。
- 不建议以“R1 全部 AT 通过”对外表述；准确表述为“R1 核心契约与可自动化范围通过，检索/迁移/浏览器/评估类 AT 仍待专项验证”。
