# R1 实施接口契约（T10 — T20 增量）

> 基线：R0 已交付（见 R0_DELIVERY.md / R0_VERIFICATION.md，研究域 290 用例全绿）。
> 本文件只写 **R1 增量**：谁写哪个文件、对外函数签名、必须满足的不变量。
> 所有模块仍遵循 R0 的 `contracts.py` DTO 与 `errors.py` 错误码，不得新增平行类型。

## 0. 通用约束

- 只读共享地基：`research/contracts.py`、`research/models.py`、`research/errors.py`、
  `research/ownership.py`。需要新增字段时**先找 Lead**，不要自行改。
- 禁止 `import` FastAPI/DB 全局配置到 `research/pipelines/**`（AT-021 隔离）。
- 禁止调用真实外部网络/模型：模型走注入的 `ModelClient`，检索走注入的 provider。
- 报告"完成"必须能给出可复核命令与真实输出，不许写"应该通过"。

## 1. 模块归属与写范围（互不重叠）

| 代理 | 独占文件 |
| --- | --- |
| review-depth | `research/review_workflow.py`、`research/completeness.py`(新)、`research/checkpoints.py`(新)、`research/pipelines/review/**`、`research/pipelines/base.py` |
| sources | `research/evidence_service.py`、`research/source_adapters.py`(新)、`research/retrieval_service.py` |
| workspace-ui | `src/frontend/src/services/researchApi.js`(新)、`src/frontend/src/pages/ResearchWorkspace.js`(新)、`src/frontend/src/components/research/**`(新)、`src/frontend/src/app/router.js` |
| metrics | `research/analytics.py`(新) |
| verifier | `src/backend/tests/test_research_r1/**`、`docs/reports/R1_VERIFICATION.md` |
| Lead | `models.py`、`config.py`、`app.py`、`db/migrations/**`、`routers/research.py`、`export_service.py`、`docs/reports/R1_*` |

## 2. 各模块契约

### 2.1 `research/checkpoints.py`（review-depth）

```python
async def load_checkpoint(db: AsyncSession, task_id: str, attempt_no: int | None = None) -> dict:
    """返回 {'analyzed_ordinals': list[int], 'cursor': int, 'model_calls': int, 'tokens': int}；
    无记录时返回空结构（不抛异常）。"""

async def save_checkpoint(db: AsyncSession, attempt_no: int, payload: dict) -> None: ...
```

- 存在 `research_task_attempts.checkpoint_json`（Lead 已加列 + 迁移 m6）。
- 只做读写，不做业务判断；调用方（review_workflow）决定合并语义。
- 写入必须与当前 attempt 的 lease/fencing 一致：若 attempt 行不存在则静默跳过（不报错）。

### 2.2 `research/completeness.py`（review-depth）

```python
def expected_sections(blocks: Sequence[Any]) -> list[str]:
    """根据 section_path 返回可核对的章节清单（去重、保序）。"""

def section_coverage(blocks: Sequence[Any], analyzed_ordinals: Iterable[int]) -> dict:
    """返回 {'expected': [...], 'covered': [...], 'missing': [...]}。"""

def document_level_findings(
    *, title: str, blocks: Sequence[Any], analyzed_ordinals: Iterable[int],
) -> list[dict]:
    """不依赖模型的"整体缺失"检查：返回 [{'category','severity','problem','reason',
    'locator','checked_sections'}]；每条必须带 locator（至少 {'scope':'document'}）
    与 checked_sections（真实分析范围），不得凭猜。"""
```

- 纯函数、无 IO、无 DB，便于单测。
- 只报告"可核对的结构性缺失"（如标题层级缺引言/方法/结论、正文无参考文献节），
  不得输出"应该更好"这类主观断言。

### 2.3 `review_workflow.run_review` 增量（review-depth）

- 启动时 `load_checkpoint`；若检查点里有已分析块且与当前 `review_blocks` 一致，
  只分析剩余块（模型调用预算按剩余计算），最后合并 findings 与 coverage。
- 每个窗口成功后 `save_checkpoint`（已分析序号、游标、累计 calls/tokens）。
- 新增"尾部保证"：无论窗口如何切分，**最后一个块必须被分析**（末块常含结论/利益冲突声明）。
- 新 findings 来源两类：`pipeline`（模型）与 `doclevel`（completeness 纯函数，
  `verification_method="structural"`）；两类都必须进 artifacts 报告。
- `coverage.unassessed_objects` 必须能解释"哪些没分析、为什么"。

### 2.4 `research/source_adapters.py` + `evidence_service` 增量（sources）

```python
class SourceAdapter(Protocol):
    name: str
    async def lookup(self, query: str, *, limit: int = 10) -> list[dict]: ...
# lookup 返回统一结构：{title, authors, year, doi, url, provider, metadata_status,
#   material_level, license, retrieved_at, abstract}
```

- 新增 `register_adapter(adapter)` / `reset_adapters()`；默认零 adapter → 走 DB 词法并标 degraded。
- 内置 `DoiAdapter`：从用户输入 DOI 解析元数据（离线可测试：注入 HTTP 客户端替身，
  不真实联网；替身返回交叉引用风格 JSON）。
- 不变量：
  1. 未解析到元数据 → `metadata_status="unresolved"`，绝不编造作者/年份/DOI；
  2. 只有摘要 → `material_level="abstract"`，不得声称支持了原文观点；
  3. 用户原文里有但来源里查不到的引用 → 明确列入 unresolved，不替换用户原文；
  4. URL 只接受 http(s)、阻断私网/回环/`file:`；已删除文档的 source 拒绝关联。
- `create_source` / `create_evidence` 保持 R0 签名，仅在内部接 adapter。

### 2.5 `research/analytics.py`（metrics，T19）

```python
async def task_metrics(db: AsyncSession, *, owner_id: int | None = None,
                      since: datetime | None = None) -> dict: ...
async def funnel_metrics(db: AsyncSession, *, owner_id: int | None = None,
                        since: datetime | None = None) -> dict: ...
```

- `task_metrics` 返回：`total`、`succeeded`、`partial`、`failed`、`cancelled`、
  `needs_input`、`success_rate`（= succeeded / (succeeded+partial+failed)，**分母不含**
  cancelled 与仍在途任务）、`retried_tasks`、`replay_events_deduped`、`p50_duration_seconds`、
  `p95_duration_seconds`、`avg_model_calls`、`avg_tokens`。
- `funnel_metrics` 返回：`projects`、`documents`、`tasks_by_kind`、`tasks_with_findings`、
  `findings_total`、`proposals_created`、`proposals_applied`、`artifacts_created`、
  `exports`、`first_finding_rate`、`apply_rate`。
- 只做聚合，不返回正文/引用原文/联系方式；同一任务多次重放只计一次；所有除法分母为 0
  时返回 `None` 而不是 0 或 NaN。
- 不新增表：全部从 `research_tasks / research_task_events / research_findings /
  research_revision_proposals / research_artifacts / research_billing_operations` 聚合。

### 2.6 前端 `researchApi.js` + `ResearchWorkspace.js`（T18）

- 复用 `services/api.js` 的 `request`/鉴权与 `ApiError` 约定（先读该文件再写）。
- 导出：`getCapabilities()`、`listProjects()`、`createProject(payload)`、
  `getProject(id)`、`uploadDocument(projectId, file)`、`getDocumentBlocks(id)`、
  `searchSources(projectId, query)`、`createTask(payload, idempotencyKey)`、
  `getTask(id)`、`streamTaskEvents(id, { onEvent, signal })`、`cancelTask`、`resumeTask`、
  `retryTask`、`getFindings(taskId)`、`createProposal`（如需）、`applyProposal(id, payload)`、
  `getExportUrl` / `exportArtifact`。
- 页面状态必须覆盖：`loading / empty / degraded / unauthorized / error / ready`；
  能力为 disabled 的入口要**显式说明不可用**，不得静默隐藏或假成功。
- 退出页面时 `AbortController.abort()` 断流，但**不得**调用 cancel 取消服务端任务。
- 在 `router.js` 注册 `'research'` 页面（title「研究工作区」），保留旧入口可回退。
- 不引第三方依赖，保持模块化 JS + `createElement` 既有风格。

### 2.7 测试（verifier）

- 目录 `src/backend/tests/test_research_r1/`，与 R0 用例并存互不影响。
- 覆盖：completeness 纯函数、checkpoint 合并/重试、尾部块必被分析、
  adapter 不编造元数据/摘要降级/私网拒绝、analytics 分母与去重、前端契约静态检查
  （导出函数名存在、router 注册、无假成功文案）。
- 报告 `docs/reports/R1_VERIFICATION.md`：AT 映射、命令、真实输出、缺口。
