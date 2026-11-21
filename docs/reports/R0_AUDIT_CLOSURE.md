# 产品审计问题 × R0 闭环对照（2026-11-20）

> 对照基准：`docs/reports/PRODUCT_AUDIT_2026-11-19.md`（问题 01—28）与
> `docs/prd/ScholarMind_Acceptance_Matrix_v1.0.md`（AT-001 — AT-056）。
> 状态定义：**闭环**＝R0 代码+测试同时约束；**部分**＝R0 打了基础但验收在 R1/R2；
> **延后**＝明确不属于 R0。

## 一、R0 已闭环（代码 + 测试双约束）

| # | 问题 | R0 处置 | 证据 |
| --- | --- | --- | --- |
| 06 | 项目不是研究状态的统一容器 | `research_projects` 成为归属根：项目 → 文档 → 版本 → 块/分块 → 任务/成果；一切按项目归属访问 | `ownership.py`、`test_documents.py`、AT-006—AT-011 |
| 08 | 主界面选择的 Skill 被请求契约覆盖 | `agent.py` 改为仅当 `skill_ids is not None` 才覆盖；Schema 区分"未提供"与"显式空"、去重、≤8 | `models/schemas/agent.py`、`routers/agent.py`、AT-004 |
| 09 | Skill 目录数量超过实际可执行能力 | `/capabilities` 对 Skill 目录真实计数并要求 `enabled`；任务受理前按 `enabled` 校验，未知/禁用扣额前 422 | `capabilities.py::_check_skills`、`task_service.validate_skill_ids` |
| 10 | 两条论文流水线模块串用 | 独立 `research/pipelines/` 包，禁止导入 FastAPI/DB/全局配置；模型客户端构造注入 | AT-021、`pipelines/base.py` |
| 15 | 模拟内容/静态状态进入真实体验 | 能力状态五态化（ready/degraded/disabled/unauthorized/unknown），探测异常 → unknown；图表/代码/浏览器在 R0 明确 disabled 并拒绝 | `/capabilities`、`kind=chart` 422 |
| 17 | 图表能力路由缺失/示例数据/回传断点 | R0 收敛为"不可用即说明不可用"（FR-13），不再提供假图表入口 | `capabilities.chart_generation=disabled` |
| 20 | 任务结束 ≠ 成果验收 | `contracts.completion_errors` 是 `succeeded` 唯一判据；空成果 → `partial`/`failed`，事件带 `artifact_ids` | `task_runner.py`、AT-034 |
| 21 | 长任务持久化/恢复/资产保存 | 任务行 + 事件序列 + 租约/fencing + outbox；`resume`/`retry`/`cancel` 幂等；成果落库绑版本 | `task_repository.py`、`task_events.py`、`test_tasks_api.py` |
| 22 | 上传与资料的用户隔离不完整 | 研究域上传按项目归属 + 容量（20MiB/50 文件/1GiB）+ 同哈希复用不泄露；他人资源统一 404 | `document_service.py`、`test_documents.py` |
| 24 | 成果停留在聊天与抽屉 | 成果/导出为独立实体（`research_artifacts`），`/artifacts/{id}` 与 `/download`、导出绑已存版本 | `artifact_service.py`、`export_service.py` |
| 26 | 免费体验与失败扣额没有围绕有效交付 | 额度 `reserved → settled/released`；失败/取消/超时释放；账本唯一约束保证至多一次结算 | `billing_service.py`、`test_billing.py` |
| 28 | 验证体系缺少任务质量指标 | R0 建立任务/事件/覆盖度/失败原因的可观测面（`/capabilities`、事件流、`coverage`、`error.code`），质量指标本身属 R2 | `capabilities.py`、`task_events.py` |

## 二、部分闭环（R0 打基础，验收在 R1/R2）

| # | 问题 | 已做的部分 | 仍缺 |
| --- | --- | --- | --- |
| 01 | 服务对象与边界过宽 | 研究域只有 6 种 `TaskKind`，图表/代码/浏览器在 R0 关闭 | 对外叙事与套餐文案收敛（产品决策，非本轮代码） |
| 02 | 卖点围绕技术，成果定义不足 | 成果实体化 + 导出（md/docx） | R1 的"审阅对照 → 逐项采纳"前端工作台 |
| 03 | 用户获得价值前负担过重 | 单一任务入口 + 结构化 `intent`/`scope` | R1 的任务范围确认与引导 |
| 04 | 角色交接缺机制 | 流水线只做"编排成可核对结果"，不靠角色聊天交接 | R1 多阶段流水线交接 |
| 05 | 关键词拦截导致错误功能 | `/capabilities` + 显式 `kind` 取代猜测路由 | 旧聊天入口的引导改造（R1） |
| 07 | 配置显示成功但未改变执行 | 研究域配置均参与真实探测/预算；`RESEARCH_*` 进 `config.py` | 旧模块（非研究域）配置一致性 R2 收口 |
| 11 | 论文生成没使用关键用户输入 | `draft_from_outline` 读入 `outline_document_version_id` 并做长度/结构校验 | 真实成稿质量（R1） |
| 12 | 审稿结果在适配时丢失 | Finding 稳定 ID + 证据四字段 + 定位/引用保真 | 多维评分的领域权重（R1） |
| 13 | 完整论文任务受固定截断限制 | R0 用"诚实失败/部分完成"替代静默截断（FR-15） | R1 分窗口续跑与预算调整 |
| 14 | 私有全文知识库承诺未实现 | 全文分块 + 全量遍历诊断（不 top-k）+ 先授权后检索 | 向量索引持久化与来源接入（R1） |
| 16 | 文献存在/支持观点/格式正确未分开验证 | Evidence 四字段（metadata/material/support/verification） | 真实外部来源元数据（R1） |
| 19 | 评分体系无法支撑"顶刊水平" | `quality_score` 可空、结论三选一、`insufficient_evidence` 诚实输出 | R2 质量验证与评分校准 |
| 23 | 流水线复杂度无质量增益证据 | 双流水线隔离 + FakeClient 可测 | R2 A/B 质量对比 |
| 25 | 套餐/计价/权益多套口径 | 研究域权益映射单一来源（review→external_review 等） | 价格与权益授权变更（PRD D-10：需产品书面授权） |
| 27 | 原型承担生产职责 | 研究域独立服务层/路由层，原型不参与 | 前端工程化（R1） |

## 三、延后（R1/R2 明确项）

- R1：全文诊断质量深度、修改建议领域深度、前端 `ResearchWorkspace`、来源检索接入。
- R2：质量验证（AT-044—AT-056）、埋点与指标看板、灰度发布链。

## 四、产品判断（PM 视角）

1. **R0 的价值不是"功能更多"，而是"承诺可核对"**：能力状态、归属、容量、
   完成校验、账本这五件事从"口头承诺"变成"代码 + 测试"。
2. **下一步最该投入的是 R1 的"审阅对照 + 逐项采纳"**：审计问题 12/24 的根因是
   用户看不到"为什么改、改成什么、改了什么"，只堆后端诊断无法解决。
3. **不要提前开放图表/代码/浏览器**：R0 的 `disabled` 是产品诚实度的一部分，
   一旦为了演示打开，问题 15/17/18 会原样复发。
4. **价格与权益不在本轮**：PRD D-10 已把该决策留给产品书面授权，工程侧只保证
   映射单一、结算至多一次。
