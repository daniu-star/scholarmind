# ScholarMind R0 实现接口契约（v1.0）

> 本文件是 R0 多代理并行实现的**集成契约**。所有 `src/backend/research/*` 模块必须遵守此处
> 签名；偏离必须在交付记录中说明原因。DTO 定义见 `src/backend/research/contracts.py`，
> ORM 见 `src/backend/research/models.py`，错误与所有权见 `errors.py` / `ownership.py`。
> 上述四个文件由 Lead 维护，子代理**不得修改**。

## 0. 通用约定

- 所有服务层函数都是 `async`，第一个参数为 `db: AsyncSession`，第二个为 `actor: Actor`
  （`Actor` 只能由认证层构造，见 `contracts.Actor`）。
- 抛错只用 `research.errors.ResearchAPIError`（或其工厂函数）。禁止 `HTTPException`
  出现在服务层，禁止返回 `None` 表示“不存在”（应抛 `not_found()`）。
- 时间使用 `contracts.utcnow()`（UTC naive）；文本写入前 `contracts.normalize_text()`。
- 禁止在模块导入期读取全局配置做 I/O；运行期依赖通过参数注入（FR-10）。
- 每个模块无副作用导入：不得在建表、连库、下载模型。
- 查询必须带 `owner_id == actor.user_id` 过滤（见 `ownership.py`）。
- 数值/能力声明必须来自真实检查或显式 `unknown`，不得写死 `ready`（FR-01/FR-15）。

## 1. 任务与账本（T1 负责）

### `task_repository.py`
```python
async def create_task(db, actor: Actor, payload: ResearchTaskInput, *,
                      idempotency_key: str | None, request_fingerprint: str,
                      billing_group_id: str) -> ResearchTask
async def find_by_idempotency(db, owner_id: int, key: str) -> ResearchTask | None
async def next_sequence(db, task_id: str) -> int
async def append_event(db, task: ResearchTask, event_type: str, *,
                       payload: dict | None = None) -> TaskEvent
async def transition(db, task: ResearchTask, status: TaskStatus, *,
                     error: dict | None = None, result: dict | None = None,
                     coverage: dict | None = None,
                     quality_verdict: str | None = None,
                     snapshot_summary: dict | None = None) -> ResearchTask
async def open_attempt(db, task: ResearchTask, *, lease_holder: str,
                       lease_seconds: int = 1200) -> TaskAttempt
async def close_attempt(db, attempt: TaskAttempt, status: str, *, error: dict | None = None) -> None
async def list_events(db, task_id: str, *, after_sequence: int = 0) -> list[TaskEvent]
```
要求：`transition` 校验 `contracts.can_transition`，非法迁移抛
`conflict("INVALID_TRANSITION", ...)`；每次迁移 `state_revision += 1`；
终态写 `ended_at`；`append_event` 序列严格单调且 `(task_id, sequence)` 唯一，
并发冲突时重试一次。

### `billing_service.py`
```python
CAPABILITY_BY_KIND: dict[TaskKind, PipelineCapability | None]
async def reserve(db, actor: Actor, task: ResearchTask, kind: TaskKind) -> dict
async def settle(db, task: ResearchTask, reservation: dict) -> None
async def release(db, task: ResearchTask, reservation: dict) -> None
```
映射固定为 `review→external_review`、`revision→modification`、
`draft_from_outline→generation`、`literature_review→external_review`；
`chart/export` 不消耗论文额度（`None`）。额度操作写 `BillingOperation`
（`billing_group_id` + `operation` 唯一 → 同一组最多一次结算），
`EntitlementError` 映射为 `payment_required`（402，`details.capability`）。
`settle/release` 必须幂等：重复调用不改变账本。

### `outbox.py`
```python
def enqueue(db, topic: str, payload: dict, *, task_id: str | None = None) -> OutboxMessage
async def pending(db, *, limit: int = 50) -> list[OutboxMessage]
async def mark_published(db, message: OutboxMessage) -> None
async def mark_failed(db, message: OutboxMessage, error: str) -> None
```
`enqueue` 与任务登记、额度预留**同一事务**（由 `task_service.create_task` 保证）。

### `task_service.py`
```python
async def create_task(db, actor, payload: ResearchTaskInput, *,
                      idempotency_key: str | None) -> TaskAccepted
async def get_task_snapshot(db, actor, task_id: str) -> TaskSnapshot
async def resume_task(db, actor, task_id: str, payload: ResumeInput) -> TaskSnapshot
async def cancel_task(db, actor, task_id: str) -> TaskSnapshot
async def retry_task(db, actor, task_id: str) -> TaskAccepted
async def list_findings(db, actor, task_id: str) -> list[Finding]
async def enqueue_task(db, actor, task_id) -> None  # 可选钩子：投递给执行器
```
`create_task` 顺序（全部在一个事务内，失败整体回滚）：校验 payload →
校验 `skill_ids`（未知/禁用 Skill 在**扣额前**拒绝，422 `SKILL_UNAVAILABLE`；
显式 `[]` 表示不使用 Skill，`None` 表示未提供）→ 并发/排队上限（429）→
额度预留（402）→ 任务行 + 事件 `task.accepted` + outbox → commit。
相同 `Idempotency-Key` 重放返回同一任务（`TaskAccepted`），
`request_fingerprint` 不同则 422 `IDEMPOTENCY_KEY_REUSED`。
`resume_task` 校验 `expected_state_revision`（不匹配 409 `STATE_CONFLICT`），
要求任务处于 `needs_input`/`recoverable`；`cancel_task` 只允许非终态。

### `task_events.py`
```python
def serialize_event(event: TaskEvent) -> dict
async def replay(db, task: ResearchTask, *, after_sequence: int | None,
                 last_event_id: int | None) -> list[dict]
async def stream(db, task: ResearchTask, *, after_sequence: int | None,
                 last_event_id: int | None) -> AsyncIterator[dict]
```
两个游标同时给出且不一致 → 422 `EVENT_SEQUENCE_MISMATCH`；
`after_sequence` 早于保留窗口 → 410 `EVENT_HISTORY_EXPIRED`（R0 用
`MIN_EVENT_SEQUENCE=1` 占位，语义必须保留）。`stream` 首次读取即在
`task` 处于终态且无新事件时立即结束，不得无限挂起。

## 2. 项目、文档、检索与证据（T2 负责）

### `document_parser.py`
```python
@dataclass(frozen=True) class ParsedBlock: ordinal:int; kind:str; text:str; start:int; end:int; section_path:str; eligible:bool
@dataclass(frozen=True) class ParsedDocument: text:str; blocks:list[ParsedBlock]; page_count:int|None; parse_status:ParseStatus; warnings:list[str]
def parse_document(data: bytes, filename: str, mime: str) -> ParsedDocument
@dataclass(frozen=True) class ChunkSpec: ordinal:int; block_ordinal:int; text:str; start:int; end:int
def build_chunks(blocks: Sequence[ParsedBlock]) -> list[ChunkSpec]
def validate_limits(pages: int | None, codepoints: int) -> None
```
- 支持 `text/plain`、`text/markdown`、`application/pdf`、docx
  （docx 用 `zipfile` + `word/document.xml` 正则/XML 解析，不新增依赖；
  PDF 若 `pypdf` 未安装 → `parse_status=ParseStatus.UNSUPPORTED`，
  **不得伪称成功**，由服务层抛 415）。
- 分块：每块 800–1200 码点，块间重叠 ≤100，块边界落在块内，
  单块超 1200 码点必须切分；分块偏移是规范化全文的码点偏移。
- 上限：200 页 / 200000 码点，超限抛 `invalid("DOCUMENT_TOO_LARGE")`（422）。

### `document_service.py`
```python
async def upload_document(db, actor, project_id: str, *, filename: str,
                          mime: str, data: bytes) -> dict   # {document, version}
async def get_document(db, actor, document_id: str) -> dict
async def delete_document(db, actor, document_id: str) -> None
async def list_blocks(db, actor, document_id: str, *,
                      version_id: str | None = None) -> list[dict]
```
上传：空文件 422；`len(data) > MAX_FILE_BYTES` → 413；解析失败/不支持 → 415/422；
同项目内 `content_hash` 相同则复用既有文档（**仅当 owner 相同**），
复用不得泄露他人内容（他人命中时按新建处理）。
版本号自增，`Document.current_version_id` 指向最新版本。

### `project_service.py`
```python
async def create_project(db, actor, title: str) -> dict
async def get_project(db, actor, project_id: str) -> dict     # 含文档摘要
async def update_project(db, actor, project_id: str, *, title: str | None, status: str | None) -> dict
```
项目上限：每用户 1GiB、每项目 50 文件（R1 容量；R0 至少实现常量与 422 校验）。

### `retrieval_service.py`
```python
async def ensure_index(db, actor, version_id: str) -> int
async def iter_chunks(db, actor, version_id: str) -> list[DocumentChunk]
async def search(db, actor, version_id: str, query: str, *, limit: int = 8) -> list[dict]
```
检索必须先授权（owner 过滤）后检索；向量不可用时**同范围**降级为词法检索，
结果带 `retrieval_method`（`vector` / `lexical`）。全文诊断必须用 `iter_chunks`
遍历全部块，禁止用 top-k 代替全文。

### `evidence_service.py`
```python
async def create_source(db, actor, project_id: str, payload: dict) -> dict
async def search_sources(db, actor, project_id: str, query: str) -> list[dict]
async def create_evidence(db, actor, task_id: str, payload: dict) -> dict
def validate_evidence(payload: dict) -> None
```
证据必须四字段齐全：`metadata_status` / `material_level` / `support_status` /
`verification_method`；缺失或非法 → 422 `EVIDENCE_INCOMPLETE`。
外部来源不可用时返回 `degraded` 标记与空结果，不得伪造来源。

## 3. 运行时、流水线、修改与成果（T3 负责）

### `runtime.py`
```python
@dataclass(frozen=True) class ModelSnapshot: provider:str; model:str; mode:str; captured_at:datetime
def capture_snapshot(*, mode: str | None) -> ModelSnapshot
def get_client(snapshot: ModelSnapshot) -> ModelClient   # Protocol: async complete(system, user, json_schema=None) -> str
class UnavailableClient: ...  # 无凭证/不可达时抛 unavailable("MODEL_UNAVAILABLE")
```
任务开始时捕获快照一次，后续调用复用（同一任务不换模型）。

### `pipelines/`（独立包，禁止依赖 FastAPI / DB 会话）
```python
# pipelines/review/pipeline.py
class ReviewPipeline:
    def __init__(self, client: ModelClient, *, max_calls: int = 160, max_tokens: int = 100_000)
    async def run(self, request: ReviewRequest) -> ReviewOutcome
```
`pipelines/base.py` 定义 `ModelClient`、`Literal` 结果类型；`pipelines/__init__.py`
导出 `ReviewPipeline`、`GenerationPipeline`。流水线**不**读写数据库、不读取全局配置。

### `review_workflow.py`
```python
async def run_review(db, task: ResearchTask, *, client: ModelClient) -> dict
```
读取版本 → 遍历全部 eligible 块 → 逐块（或合并到 ≤1200 码点窗口）诊断 →
持久化 `FindingRow` → 计算 `Coverage`（`expected_eligible_blocks` /
`analyzed_eligible_blocks`）→ 结论只能是三种之一；
模型不可用 → 抛 `unavailable`（由 runner 落 `recoverable`/`failed`，不得伪造 `no_major_issues_found`）。

### `revision_service.py`
```python
async def create_proposal(db, actor, task_id: str, *, selected_findings: list[str]) -> dict
async def apply_proposal(db, actor, proposal_id: str, *, expected_version_id: str,
                         idempotency_key: str | None) -> ApplyResult
def validate_hunks(base_text: str, hunks: list[dict]) -> list[str]
```
`apply_proposal`：`base_version_id` 与 `expected_version_id` 不一致 → 409
`VERSION_CONFLICT`；同一 `Idempotency-Key` 重放返回同一结果；补丁按 Unicode
码点偏移应用，倒序应用避免漂移；成功创建新版本 + 变更日志成果。

### `artifact_service.py` / `export_service.py`
```python
async def create_artifact(db, *, owner_id: int, task_id: str, kind: str, body: str,
                          mime: str, filename: str, validation: dict | None = None) -> Artifact
async def list_artifacts(db, actor, task_id: str) -> list[dict]
async def read_artifact(db, actor, artifact_id: str) -> Artifact
async def export(db, actor, *, project_id: str, document_version_id: str,
                 fmt: str, journal_style: str) -> Artifact
```
导出必须绑定**已存版本**；未知 `journal_style` → 422 `UNSUPPORTED_JOURNAL_STYLE`；
未知格式 → 422 `UNSUPPORTED_EXPORT_FORMAT`；空成果不得算成功。

### `task_runner.py`
```python
async def execute_task(db, task: ResearchTask, *, holder: str) -> None
```
加租约（fencing）→ `task.started` → 按 `kind` 分派（review/revision/
draft_from_outline/literature_review/chart/export）→ 用
`contracts.completion_errors` 做最小交付检查 → 结算/释放额度 →
终态事件（`task.completed` 必须带 `artifact_ids`）。

## 4. 能力与路由（T4 负责）

### `capabilities.py`
```python
async def build_capabilities(db, user_id: int) -> CapabilityResponse
```
每项能力都必须来自真实检查：DB 可查询性、模型凭证与近期可达性、解析器可用性、
向量检索可用性、外部来源配置、浏览器/代码执行开关、Skill 目录。
状态只能是 `ready/degraded/disabled/unauthorized/unknown`；`unauthorized` 仅用于
“当前用户权益不覆盖”，不得用来掩盖未实现。

### `routers/research.py`
前缀 `/api/v1/research`，全部端点强制 `get_current_user`；按 PRD §8.1 实现：
```
GET  /capabilities
POST /projects                        GET /projects
GET  /projects/{project_id}          PATCH /projects/{project_id}
POST /projects/{project_id}/documents
GET  /documents/{document_id}        DELETE /documents/{document_id}
GET  /documents/{document_id}/blocks
POST /projects/{project_id}/sources/search
POST /tasks                          GET /tasks/{task_id}
GET  /tasks/{task_id}/events         (SSE)
POST /tasks/{task_id}/resume|/cancel|/retry
GET  /tasks/{task_id}/findings
GET  /artifacts/{artifact_id}        GET /artifacts/{artifact_id}/download
POST /revision-proposals/{proposal_id}/apply
POST /exports
```
统一异常处理：`ResearchAPIError` → 对应状态码 + `{"error": {...}}`；
`Idempotency-Key` 头 8–128 ASCII，非法 → 422 `INVALID_IDEMPOTENCY_KEY`。
`POST /tasks` 成功返回 202 `{task_id, status, state_revision, snapshot_summary}`。

## 5. 测试与验收（T5 负责）

测试目录 `src/backend/tests/test_research/`，使用 conftest 的 `authed_async_client`
与 `test_db`。覆盖 R0 关键验收：AT-004、AT-006—AT-011、AT-021、AT-022/025/026、
AT-023/024、AT-034、AT-038—AT-043。断言必须证明**行为**（状态码、错误码、DB 行、
事件序列），不接受只断言“函数存在”。

**不要运行全量 `pytest src/backend/tests`**（现有 182 个用例每次建表，单次 >10 分钟）。
只跑 `pytest src/backend/tests/test_research -q` 与单文件。
