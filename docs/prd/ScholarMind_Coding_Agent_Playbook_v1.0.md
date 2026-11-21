# ScholarMind Coding Agent 实施手册 v1.0

日期：2026-11-19。状态：实施任务尚未开始。本文件规定开发顺序和交付证据，不代表产品已经修复。

**目标：先修复现有交付断点，再形成一个能读全文文本、给依据、提出可采纳修改并导出版本的研究工作区。**

产品规格：[优化 PRD](C:/Users/13067/Desktop/全能研究Agent/docs/prd/ScholarMind_Optimization_PRD_v1.0.md)。行为验收：[验收矩阵](C:/Users/13067/Desktop/全能研究Agent/docs/prd/ScholarMind_Acceptance_Matrix_v1.0.md)。历史问题：[诊断报告](C:/Users/13067/Desktop/全能研究Agent/docs/reports/PRODUCT_AUDIT_2026-11-19.md)。

本文件的代码模块名是实施目标，尚未存在的文件不能当作已实现能力。路径表与后续相对代码标识统一以仓库根目录 `C:/Users/13067/Desktop/全能研究Agent` 解析；迁移到其他机器时只替换根目录，不在产品代码硬编码此本机路径。

## 1. 开工约束

1. 先读三份文档及当前 AGENTS.md（如存在），重新检查工作区差异。本次基线包含用户已有未提交修改，不能 reset、覆盖或把它们混入自己的交付。
2. T00—T09 是 R0；T10—T20 是 R1；T21—T23 是 R2。按依赖实施，R0 未验收不要把全部重构混成一个大改动。
3. 复用现有 FastAPI、SQLAlchemy/Alembic、Vite/模块化 JavaScript、Celery/Redis、Chroma、pypdf 和 python-docx。不额外重写前端框架、支付系统、账号系统或检索平台。
4. 所有权限来自服务端认证；代码执行默认关闭和管理员限制不能放宽；外部工具与付费策略变更不因本文件自动获得授权。
5. 故障回归必须先能够复现问题，再修复。新测试以用户行为和契约为依据，不能复制实现逻辑或仅检查 mock 调用。
6. 日常测试使用隔离数据库、上传目录、索引、日志和替身模型，不读取或改写真实用户论文，不默认发起付费模型调用。
7. 原诊断中的临时探针用于理解，不作为长期测试依赖；将最小合成夹具和断言放入版本化测试目录。
8. 每任务形成可独立审阅的改动和验证记录。是否创建提交按当前会话授权执行；若提交，只包含本任务文件，不使用无差别暂存。

## 2. 文件职责与契约归属

以下为建议落点，遵循现有分层并按职责拆分。若某文件因模型定义增多明显膨胀，可在同目录拆成子模块并保留导入接口，但不得借此改变 PRD 的字段、行为与完成门槛。

| 模块目标 | 职责 | 现有集成点 |
|---|---|---|
| `src/backend/research/contracts.py` | TaskInput、TaskResult、覆盖、Finding、Proposal、事件、错误的版本化 DTO | `models/schemas/*` 的兼容适配 |
| `src/backend/research/models.py` | 新研究领域 ORM，使用现有 Base；小型不可变结构可存经过验证的 JSON | `models/orm.py`、`db/session.py`、迁移 env 的模型注册 |
| `src/backend/research/ownership.py` | 认证 Actor 与 owner/project 校验、私有存储定位 | `core/dependencies.py`、upload、下载与索引 |
| `src/backend/research/project_service.py` | 项目与确认上下文 | 新 research router，旧项目导入 |
| `src/backend/research/document_service.py` | 文档/版本/容量/删除与解析调度 | `routers/upload.py` |
| `src/backend/research/document_parser.py` | 结构化文本、表格、脚注和定位，解析报告 | `utils/file_parser.py` 的兼容包装 |
| `src/backend/research/task_repository.py` | 任务、租约、检查点、事件和 outbox 的数据库原子操作 | 取代 Redis-only 核心任务状态 |
| `src/backend/research/task_service.py` | 受理、幂等、状态、恢复、取消、重试的应用服务 | `routers/agent.py`、paper_pipeline、paper_review |
| `src/backend/research/task_runner.py` | 步骤执行、预算、租约、取消与检查点 | `scheduler/research_tasks.py` |
| `src/backend/research/task_events.py` | 持久事件、重放、脱敏和删除撤权 | 新 SSE 与旧 agent stream 适配 |
| `src/backend/research/runtime.py` | 实例化模型运行时、模型快照、类型化失败与使用量 | `utils/llm_client.py`、model_policy |
| `src/backend/research/pipelines/generation/*`、`review/*` | 独立可导入流水线包与薄适配器 | 已入库 skills 中的流程与资源 |
| `src/backend/research/retrieval_service.py` | 用户/项目范围检索、版本化索引与范围一致的降级 | vector_service、rag_service |
| `src/backend/research/evidence_service.py` | 来源、原文与论断关系、核查状态 | academic_search_service、cnki 等适配器 |
| `src/backend/research/review_workflow.py` | 全部分析块的诊断规划、合并、范围验证 | 规范模型运行时，不回退占位评分 |
| `src/backend/research/revision_service.py` | 定向补丁、保护校验、版本冲突与采纳 | 前端修改对照与版本服务 |
| `src/backend/research/artifact_service.py` | 成果校验、持久化、导出与下载 | `routers/export.py`、journal_formatter |
| `src/backend/research/billing_service.py` | 预留、释放、结算与 billing_group 幂等 | 现有 entitlement_service、quota、订单 |
| `src/backend/research/outbox.py` | 待投递派发、重试与数据库恢复 | 单一 Celery app、本地同契约执行器 |
| `src/backend/routers/research.py` | PRD 第 8 节 API 的认证、输入输出与状态码 | `app.py` 注册；不在 router 内写复杂业务 |
| `src/frontend/src/services/researchApi.js` | 新工作区唯一 API、认证、SSE 重放和幂等键 | 现有 api.js 与认证逻辑 |
| `src/frontend/src/pages/ResearchWorkspace.js` | 项目、材料、任务、文档与修改的统一工作区 | router、App 与旧入口迁移 |
| `src/frontend/src/components/research/*` | DocumentPane、FindingList、RevisionDiff、TaskPanel | 现有 DOM 组件方式，组件卸载须取消订阅 |
| `src/backend/tests/test_research/*` | 领域契约、流程、隔离、并发和恢复测试 | 现有测试夹具扩展 |
| `src/frontend/tests/research/*` | 正式构建浏览器回归与交互验收 | CI 中启动实际构建产物与隔离后端 |

新增 runtime 文件不得依赖开发者 `.trae-cn` 目录或运行机器的 IDE。只读外部 Skill 可以继续作为明确选择的规则来源；执行必需的代码和资源需入库并通过版本化清单定位。

## 3. 规范类型和服务接口

类型按依赖定义：T03 在 contracts 中建立最小 `Actor(user_id:int)` 和 `DocumentRef`，Actor 只能由认证层构建；T04 定义 `ExecutionSnapshot/ExecutionContext/RuntimeResult` 与运行时错误；T05 扩展 `ResearchTaskInput/TaskResult/TaskSnapshot/TaskEventDTO/ArtifactRef/ResearchError`。其他字段遵循 PRD，不允许客户端提供实际模型、结算状态或 owner。

T10 扩展 `ProjectDTO/ProjectCreate/DocumentVersionDTO` 和既有最小文档关系；T11 定义 `ParsedDocument/ParseReport`；T12 定义授权召回用的 `RetrievalHit`；T13 定义 `SourceRecordDTO/EvidenceDTO` 并将召回结果转为证据；T15 定义 `Finding/ReviewReport`；T16 定义 `RevisionProposal/ApplyResult`。这些名字和约束保持单一导出位置，可内部拆文件并重导出。

| 服务边界 | 规范接口 | 语义 |
|---|---|---|
| Runtime | `run_step(context: ExecutionContext, step_input: dict) -> RuntimeResult` | 包含真实输出、usage、finish_reason、错误；缺 bridge/截断均可识别 |
| TaskService | `submit(actor: Actor, request: ResearchTaskInput, idempotency_key: str) -> TaskSnapshot` | 事务内验证、预留、登记与 outbox；相同请求返回原任务 |
| TaskService | `get/cancel/resume/retry(actor, task_id, ...) -> TaskSnapshot` | 权限、状态转移与幂等；retry 返回关联新任务 |
| DocumentService | `ingest(actor, project_id, upload, purpose) -> DocumentRef` | 容量和 owner 检查；保存版本和解析状态 |
| Parser | `parse(document_ref: DocumentRef) -> ParsedDocument` | 文本块、来源定位和完整解析报告，不能空文本假成功 |
| Retrieval | `search(actor, project_id, query, document_version_ids, limit) -> list[RetrievalHit]` | 权限过滤在召回前和结果读取时都生效；EvidenceService 再核查并转 EvidenceDTO |
| Review | `run(context: ExecutionContext) -> TaskResult` | 遍历请求范围内的全部分析块，产出有锚点报告 |
| Revision | `propose(context: ExecutionContext) -> RevisionProposal` | 只产生建议，不覆盖正文 |
| Revision | `apply(actor, proposal_id, hunk_ids, expected_version_id, idempotency_key) -> ApplyResult` | 同事务创建新版本与修改说明，冲突 409 |
| Artifact | `validate_and_store(actor, task_id, kind, content, metadata) -> ArtifactRef` | 先校验、持久化，再发 artifact.created |
| Billing | `reserve/settle/release(..., billing_group_id, transaction)` | 与权益更新共享事务；同组最多一次成功结算 |
| Events | `read_events(actor, task_id, after_sequence, limit) -> list[TaskEventDTO]` | 有序、去重、权限与删除撤权校验 |

具体 async 标注、构造器依赖和仓储注入依照现有 FastAPI/SQLAlchemy 风格实现；不得因此改变跨层输入输出含义。JSON 外部响应须使用已定义 DTO 验证，不直接透传模型原文充当结构化结果。

## 4. R0：交付修复任务

推荐串行顺序：T00 → T01 → T02 → T03 → T04 → T05 → T06 → T08 → T07 → T09。T08 先建立任务/事件/成果元数据与账本基础，T07 再完成成果存储和真实事件交付；编号用于追踪，不覆盖依赖关系。

### T00 基线、隔离夹具与可复现检查

**依赖：**无。**需求：**FR-16。**产出：**可复现基线与隔离测试环境。

文件：现有 `tests/conftest.py`、`.github/workflows/ci.yml`、`core/logging_config.py`；新增 `tests/test_research/conftest.py`、`tests/fixtures/research/` 与阶段执行记录。

- [ ] 检查当前差异、运行入口、已有服务端商品和 Celery 注册；记录事实，尤其不要把已有兼容 shim 当成第二个独立实例重做。
- [ ] 建立临时数据库/上传/索引/日志夹具，以及可控制流式失败、截断与使用量的模型替身；默认阻止测试外连。
- [ ] 固化模块串用、Skill 覆盖、结果字段丢失等最小合成复现，不依赖 gitignored 的 tmp 文件。
- [ ] 运行既有后端检查并保存基线；确认空日志目录启动行为，测试数据不落入真实 data。

验收：AT-046；其他任务使用本任务夹具。基线有失败时记录原因，不能宣称业务已修复。

### T01 真实能力与产品承诺收敛

**依赖：**T00。**需求：**FR-01、FR-13、FR-15。**产出：**能力接口与受控入口。

文件：`routers/research.py`、配置与 `app.py`；正式 `prototypes/interactive-prototype.html`；工程化 Landing/About/Settings 对应页面。

- [ ] 为无图表路由、无全文来源、来源故障、关闭代码执行和模拟文献回退建立失败断言。
- [ ] 增加能力响应和真实 checked_at；删除或隔离模拟文献与虚假连接状态，关闭未接通的自定义/执行入口。
- [ ] 前端从能力接口和服务端商品目录渲染，不能保留另一套硬编码连接、价格或成功提示。
- [ ] 在当前正式入口观察断开与空结果行为，验证无虚构成果；本任务不启用普通用户代码执行或 Browser Agent。

验收：AT-005、AT-018、AT-048、AT-049。

### T02 修复意图路由和 Skill 请求契约

**依赖：**T00。**需求：**FR-02、FR-12。**产出：**正确任务语义与明确选择生效。

文件：主 HTML 的 `detectCNKIIntent/sendMessage`；`routers/agent.py`、`models/schemas/agent.py`、`services/agent_service.py`；工程化 AgentPage/agentApi。

- [ ] 参数化覆盖润色论文、审查架构、纯搜索、搜索后综述与含糊指令；检查实际请求链及工具顺序。
- [ ] 去掉泛关键词抢占路径；明确指令直接路由，含糊任务用类型化意图或一次关键追问，保留原始目标和所有任务步骤。
- [ ] 实现顶层 skill_ids 优先与旧字段兼容，区分“未提供”和“显式空”，冲突返回规范错误；任务前验证权限。
- [ ] 验证最终模型提示确实包含所选规则且取消后不含；两个前端使用相同契约。

验收：AT-001—AT-004。不能只测试关键词函数返回值，还要检查用户请求真正到达的后端流程。

### T03 文件归属、容量与旧上传兼容

**依赖：**T00。**需求：**FR-03。**产出：**所有者隔离的上传与文件引用。

文件：`routers/upload.py`、`services/agent_service.py` 的附件读取；新增最小 contracts、ownership、document_service 与 Project/Document/DocumentVersion 元数据迁移；上传安全测试。

- [ ] 覆盖双用户相同 session_id、全局 15 文件限制、项目间串读、大小边界和磁盘写入失败。
- [ ] 新文件建立可信 owner、内容哈希与最小不可变版本，物理存储按 owner/document 分区；R0 解析边界诚实记录，T11 再完善结构块。无 project_id 的旧接口使用该用户独立的历史工作区，不能使用全局公共项目。
- [ ] 附件读取必须接收认证 Actor 并查授权记录；单文件容量和数量按所属资源计算。对未知归属历史文件隔离，不能自动认领。
- [ ] 验证 HTTP、直接服务读取、下载和异常残留清理；不会因另一个用户用满容量而失败。

验收：AT-006—AT-011、AT-053、AT-054 中的撤权基础部分。

### T04 独立流水线包与实例运行时

**依赖：**T00。**需求：**FR-10。**产出：**稳定身份的 generation/review 执行器。

文件：`paper_pipeline_service.py`、`paper_review_service.py`、`pipeline_llm_bridge.py`；新增 research/runtime 与两个独立 pipelines 包；仅对已入库技能做必要迁移/兼容导出。

- [ ] 在独立进程中按先生成/先审稿/先注入客户端三种顺序导入，断言绑定对象来源正确、必要评分方法存在、客户端注入一致。
- [ ] 使用独立包及相对导入，去除全局模块缓存清理与临时 sys.path 选择；资源通过已入库清单定位。
- [ ] 模型依赖随任务实例传递；缺失连接使 preflight 失败，不进入占位执行。不修改机器上的只读外部 Skill 源。
- [ ] 两种流水线并行使用不同模型快照运行合成任务，无串用、无全局客户端切换。

验收：AT-021、AT-041 的运行时隔离部分。

### T05 统一任务输入与成果协议

**依赖：**T03、T04。**需求：**FR-10、FR-15。**产出：**第 3 节规范 DTO 与旧接口适配器。

文件：research/contracts；两个 paper 服务、schema 和路由；提纲上传与生成弹窗。

- [ ] 以真实技能字段输入断言正文、91 分、两轮与历史不丢失；缺字段不得自动完成。构建两份同题不同提纲与不同目标字数的测试。
- [ ] 明确转换旧 `paper_content/review_score/score_history/round_number`；schema_version 固定，校验失败产生明确错误。
- [ ] 上传文件转为受授权的版本引用，提纲正文、目标长度、研究类型和禁改项进入同一输入快照。
- [ ] 通过旧 API、规范 DTO 和当前主界面的集成断言，确保参数变化传到实际执行节点。

验收：AT-023、AT-024、AT-034。

### T06 诚实失败、截断与完成验证

**依赖：**T04、T05。**需求：**FR-04、FR-15。**产出：**类型化 RuntimeResult 与统一完成检查。

文件：research/runtime、task result validator；`llm_client.py`、两套 llm_executor、评分逻辑及前端错误/完成渲染。

- [ ] 故障注入鉴权失败、限流、超时、中途断流、长度截断、原文无变化和空输出。
- [ ] 取消模型失败转正常成功回复、返回原文却声明修改和固定分数回退。保留部分成果时标为 partial，并列出未完成范围。
- [ ] completed/succeeded 只由按 kind 的成果验证决定；评分可为空，保留量表必须校验总分约束。
- [ ] R0 还没有全文覆盖实现时明确披露范围，不能假称已解决长文问题。

验收：AT-022、AT-025、AT-026、AT-034。

### T07 成果文件、工具结果和流式交付闭环

**依赖：**T03、T05、T06、T08。**需求：**FR-09、FR-11、FR-13。**产出：**持久成果引用与可接收工具事件。

文件：artifact_service、task_events 的基础结构；旧 stream/deferred_skills、图表调用与下载路径。

- [ ] 用本地工具替身返回文件，断言文件持久、归属正确且用户能在同一任务收到 artifact ID。
- [ ] 不在 done 之后启动无人接收的工具；即时工具在终态前交付，真正长工具登记任务后用事件/任务详情交付。
- [ ] 图表路由未完成真实数据验证前保持 disabled；不可用时应在调用前返回原因，不能生成示例替代。
- [ ] 验证下载所有权、正确 MIME 和文件存在性；响应不泄露本机路径。

验收：AT-007 的下载、AT-017 的降级基础、AT-035 的事件基础、AT-048 的能力展示。

### T08 任务登记、额度账本与模型快照

**依赖：**T03、T05、T06。**需求：**FR-11、FR-14。**产出：**持久任务与最多一次结算。

文件：research/models（含任务、基础事件、成果元数据、账本和待派发记录）、task_repository/task_service/billing_service；Alembic；旧 agent/paper 路由、entitlement_service、model_policy。

- [ ] 覆盖双击、并发额度最后一次、模型失败、后台失败、重复回调、会员在接收后到期与不同 model 档位。
- [ ] 同事务校验/预留/登记和写入待派发记录，提交后才调用 R0 现有执行器；使用幂等键和请求哈希。节点获得不可变实际模型和权益快照，未验证成果不能结算；完整可恢复 worker 在 T14 完成。
- [ ] 失败/partial/取消释放一次，重试沿 billing_group；系统本地问候不扣研究额度，但客户端不能伪造免费标识。
- [ ] R0 尚未具备检查点恢复时明确 can_resume=false；对进程中断遗留任务由看门记录结束与释放，不宣传自动继续。

验收：AT-022 的结算、AT-038、AT-039—AT-043、AT-051。

### T09 R0 正式入口回归与放行记录

**依赖：**T01—T08。**需求：**FR-16。**产出：**R0 验收记录，不自动发布。

文件：当前构建脚本、CI、正式主界面浏览器测试、阶段结果文档。

- [ ] 用 root build 产生实际交付页面，使用隔离后端走登录、上传、润色、检索、Skill、审稿及失败场景。
- [ ] 跑现有权限/支付/上传测试和所有 R0 用例；检查 capability-off 路径是否在两个前端一致。
- [ ] 保存失败原因和界面证据；只要还有假成功、跨用户读取、错误扣额就不标为 verified。
- [ ] 输出改动与配置、验证结果、未开放功能和回退方式；R1 后续工作单独开始。

验收：验收矩阵全部 R0 条目；不是以测试数量或 HTTP 200 单独放行。

## 5. R1：核心任务版

### T10 项目、不可变版本与确认上下文

**依赖：**T09。**需求：**FR-03、FR-05。**产出：**Project/DocumentVersion/Block 基础领域与项目 API。

文件：research/models、project_service、document_service、contracts、research router；现有 ORM Base 注册与 Alembic env；项目迁移测试。

- [ ] 定义 ProjectDTO 等第 3 节类型，测试跨账号/项目隔离、更新 revision 冲突与历史可读。
- [ ] 增量迁移版本、父版本、内容哈希、确认上下文与来源；对现有文档元数据补关系，不改旧身份与权益。
- [ ] 规范 API 生成真实项目与版本；旧会话映射到可信 owner 的历史工作区；不能依据全局 topic 键覆盖项目题目。
- [ ] 验证迁移 dry-run、可重复执行、未知归属隔离和无破坏的回退读取。

验收：AT-008、AT-044、AT-052、AT-053。

### T11 文档结构、定位和完整解析报告

**依赖：**T10。**需求：**FR-04。**产出：**ParsedDocument/ParseReport 与可定位正文。

文件：document_parser、document_service；file_parser 兼容层；PDF/DOCX/文本合成夹具。

- [ ] 固化 DOCX 表格/脚注、PDF 无文本页、尾部证据、Unicode 字符、超出页数/字符限制和部分解析夹具。
- [ ] 提取段落、表格、脚注与页码/标题路径，NFC 规范化并给块分配稳定 ID/哈希，保留原始定位关系。
- [ ] 提供 complete/partial/unsupported/failed 及未分析对象，不能用空字符串吞掉错误。解析状态不等同全文分析状态。
- [ ] 对解析报告、块顺序与位置做往返核对，超过范围不截断成功。

验收：AT-011—AT-015、AT-030 的定位部分。

### T12 授权全文索引与可靠项目检索

**依赖：**T10、T11。**需求：**FR-05。**产出：**DocumentChunk 与权限内 Evidence 候选。

文件：retrieval_service、vector_service/rag_service 适配、索引迁移与删除清理任务。

- [ ] 测试同题不同用户/项目、尾部块召回、空学科标签、索引故障、版本切换和删除后的拒绝。
- [ ] 按 PRD 分块并记录所有权/版本；检索前过滤，结果再次查数据库权限；降级保留相同范围。
- [ ] 新索引版本构建完成后切换，旧共享集合只有明确公共资料可以进入公共分区；不把旧私有资料直接迁成公共。
- [ ] 测试使用替身嵌入完成确定性验收；另做小规模真实索引集成，不下载大模型来掩盖单元测试问题。

验收：AT-016、AT-017、AT-052、AT-054 的索引撤权。

### T13 来源保真与论断证据

**依赖：**T10—T12。**需求：**FR-06。**产出：**SourceRecordDTO/EvidenceDTO 与核查状态。

文件：evidence_service、academic_search_service 等现有适配器、前端检索映射及项目来源 API。

- [ ] 覆盖 DOI 可解析但无全文、只有摘要、模型虚构引用、用户已有错引、恶意 URL 与附件指令。
- [ ] 保留作者、年份、DOI、URL、来源、权限粒度和获取时间；分别记录出处与支持关系，不能把两者合成 verified=true。
- [ ] 在许可的来源上核查，未核实项明确列出；文献为空不补虚构条目；不擅自替换用户原文引用。
- [ ] 核对报告到来源/原文块的跳转，以及对未知来源、私网地址和已删除文档的拒绝。

验收：AT-018—AT-020、AT-028、AT-049。

### T14 队列、租约、outbox 与事件重放

**依赖：**T08、T10—T13。**需求：**FR-11。**产出：**可恢复 TaskRunner 与规范事件服务。

文件：task_repository/task_runner/task_events/outbox；`scheduler/research_tasks.py` 和现有 celery_app 注册；本地执行器；部署进程与日志配置。

- [ ] 用实际数据库事务与可重启 worker 覆盖投递前崩溃、重复投递、租约失效、Redis 断开、SSE 断线及取消后的迟到写入。
- [ ] 使用 DB outbox 派发、attempt/lease_epoch、可验证步骤检查点和累计预算；worker 每个副作用前验证租约。
- [ ] 持久发布事件并支持 sequence 重放、去重、历史过期读取快照；删除撤权优先于重放。
- [ ] 使用生产同类 PostgreSQL/Redis/Celery 运行一次恢复集成测试；SQLite 测试不能替代生产并发验证。研究任务专用时限不得被现有 300 秒默认配置意外覆盖。

验收：AT-035—AT-039、AT-051、AT-054；内部恢复与终态重试语义严格区分。

### T15 全文诊断与结构化问题报告

**依赖：**T11—T14。**需求：**FR-07、FR-15。**产出：**Finding/ReviewReport 与诊断主流程。

文件：review_workflow、runtime、contracts、artifact_service 的 review validator；模型替身和受控评估样本。

- [ ] 为尾部严重错误、缺失章节、无外部证据、无实证数据和各分析单元失败写结果断言。
- [ ] 建立全文块清单，逐单元分析、保存检查点并合并；局部问题有原文锚点，整体缺失有检查范围。
- [ ] 区分材料事实、模型推断和来源证据；仅完成范围覆盖后交付 succeeded，质量结论不由阈值决定。
- [ ] 通过全服务流程读取报告、定位与未解决项；不能靠提示词要求“检查全文”替代覆盖记录。

验收：AT-014、AT-015、AT-026—AT-028、AT-034。

### T16 定向修改、保护校验与原子采纳

**依赖：**T10、T13、T15。**需求：**FR-08。**产出：**RevisionProposal/ApplyResult 与版本化补丁。

文件：revision_service、contracts、document_service、apply API；前端 RevisionDiff 数据契约。

- [ ] 覆盖受保护数字/日期/专名/引语/引用、范围外块、Unicode 偏移、重叠补丁、旧版本和重复采纳。
- [ ] 以指定 finding/段落生成补丁，校验原文哈希和事实守恒；有风险或需要新数据时请求输入，不自动改写研究结论。
- [ ] 采纳事务检查 expected_version，生成唯一新版本和修改说明；撤回也新增版本；重叠补丁拒绝或要求重新生成。
- [ ] 验证用户未采纳前正文不变、冲突 409、不重复创建版本、所有建议能回到问题依据。

验收：AT-029—AT-033。

### T17 成果库与可验证导出

**依赖：**T07、T15、T16。**需求：**FR-09。**产出：**真实版本导出与成果下载。

文件：artifact_service、research export API、`routers/export.py` 适配、journal_formatter、文件下载授权。

- [ ] 对指定版本、表格脚注、引用标记、空成果、未知期刊和会员到期后的历史读取写检查。
- [ ] 导出绑定已持久化版本与任务；DOCX 重新打开核对内容结构，Markdown 与修改说明保持同一版本。
- [ ] 只列出已验证的格式；未知格式 422，不静默套 generic；partial 成果以明确文件名和说明导出。
- [ ] 通过浏览器真实下载与重新解析校验，导出不二次扣研究额度，不泄露服务器路径。

验收：AT-034、AT-043 的历史权益、AT-045。

### T18 唯一研究工作区与前端迁移

**依赖：**T10—T17。**需求：**FR-01、FR-02、FR-09、FR-16。**产出：**模块化 ResearchWorkspace 与兼容入口。

文件：ResearchWorkspace、researchApi、research 子组件、router/store/api；主 HTML 兼容链接；build-frontend、启动脚本、Vercel 与本地静态路由。

- [ ] 根据真实 API 渲染项目、文档、问题、修改与任务，覆盖登录后恢复、断线、版本冲突、窄屏和键盘操作。
- [ ] 实现统一工作区，不要求用户选内部角色；处理所有规范状态、覆盖与未解决项，保留用户已填输入。
- [ ] 账号缓存隔离、有效 access token 兼容和用户确认的旧本地内容导入；卸载页面移除监听，断流不取消服务端任务。
- [ ] 用同一模块化构建产物完成本地与部署配置预览；切换前验证旧链接与历史成果，保留可回退的安全入口。

验收：AT-031—AT-035 的前端、AT-044、AT-047、AT-048、AT-053。

### T19 产品指标与受控体验

**依赖：**T14—T18。**需求：**FR-14、FR-16。**产出：**结果指标与不改变既有权益的体验入口。

文件：metrics/analytics 聚合、任务/成果事件、授权样例、catalog 渲染、可配置试用开关。

- [ ] 事件计数覆盖重复请求、断线重放、不同版本采纳、partial/平台失败与主动取消，防止成功率分母失真。
- [ ] 记录首次有效发现、采纳、导出、消耗与回访，指标不包含正文或个人联系方式。
- [ ] 授权样例完整演示且显式标记；试用额度实验默认 false，保留原 SKU 和已购买额度，不自动发放新权益。
- [ ] 输出指标口径、样本量和实际数据基线，不能把模拟 Persona 评分写成真实用户满意度。

验收：AT-040、AT-043、AT-050、AT-052 的观测部分。

### T20 R1 整体流程、迁移与 CI 门槛

**依赖：**T10—T19。**需求：**FR-16。**产出：**可审核的 R1 候选版本及发布/回退记录。

文件：后端集成测试、正式产物浏览器测试、迁移 dry-run/恢复脚本、CI、启动/部署配置与操作说明。

- [ ] 完整走通上传—诊断—定位—生成建议—采纳—导出—跨会话继续；同一浏览器换账号再验证。
- [ ] 在 Windows 本地与 Linux CI 检查路径、日志、静态资源和构建入口；生产并发路径使用 PostgreSQL/Redis/Celery。
- [ ] 故障演练重启、索引缺失、来源降级、worker 中断、删除、取消和重复支付事件；验证权益及旧资料无损。
- [ ] 检查所有 R1 用例、格式、类型和既有测试；保存具体命令、结果、未通过项与回退演练。通过后仅标为候选，不自动部署。

验收：全部 R0/R1 用例与 PRD 第 10 节门槛。

## 6. R2：质量与扩展验证

### T21 真实任务与人工盲评

**依赖：**T20。**需求：**FR-07、FR-15、FR-16。**产出：**质量基线与适用边界。

文件：版本化评估规范、授权样本清单、评估工具与结果报告；不将用户真实论文直接提交版本库。

- [ ] 准备至少 10 份不同长度/方法的授权论文，建立主要缺陷和可接受修改的人工参照。
- [ ] 比较短流程与既有多角色流程，记录缺陷识别、误报、依据、修改守恒、人工时间及消耗。
- [ ] 至少两位具备相应领域判断能力的评审独立评价受控样本；报告分歧和样本偏差，不能要求模型代替两位真人。
- [ ] 依据结果收敛适用范围与提示词；未具备真实评审资源时记录质量验收未完成，不能靠模型自评分通过。

验收：AT-050；真实评估资源是本任务的外部依赖，不阻断先前合成与工程验收。

### T22 真实数据图表的独立开放

**依赖：**T13、T14、T17、T20。**需求：**FR-13。**产出：**通过验收后可单独启用的图表能力。

文件：chart schema/router、chart_service/data、研究任务适配、成果下载与前端数据选择。

- [ ] 为已知小表格、缺列、错误类型、缺失值、空数据和越权文件设置确定性数值断言。
- [ ] 只读取受授权数据版本与显式列映射，保存处理过程与数据摘要；去掉研究路径的随机样例回退。
- [ ] 图表产生真实 artifact 并回传任务，下载受控；演示数据仅在独立演示模式使用。
- [ ] 在数据数值、单位和显示范围检查通过后才能开启 ENABLE_VERIFIED_CHARTS；不影响诊断/修改主线放行。

验收：AT-055。

### T23 预算与流程增益优化

**依赖：**T19—T21。**需求：**FR-10、FR-11、FR-16。**产出：**有对照证据的流程优化。

文件：workflow planner、budget、模型使用量统计、性能评估和配置；不默认增加新的 Agent 节点。

- [ ] 对同一任务固定输入、模型和评价标准，记录调用、tokens、时间、覆盖和质量基线。
- [ ] 尝试按问题触发角色、复用检查点和局部补丁，保持输入版本、覆盖与证据要求不变。
- [ ] 对比每项优化的质量与效率；降低质量或遗漏后半篇不能算性能提升。
- [ ] 保存 accepted_budget 配置及实际测量，超预算明确 partial/needs_input，费用未知时不显示为 0。

验收：AT-056；是否开放新的计算/浏览器/全学科能力另立需求，不在本任务扩张。

## 7. 推荐验证方式

以下命令在仓库根目录执行，实施 agent 按实际环境激活隔离配置；不要直接拿生产 .env 和数据库跑迁移测试。

```powershell
.venv\Scripts\python.exe -m pytest src/backend/tests -q
.venv\Scripts\python.exe -m pytest src/backend/tests/test_research -q
.venv\Scripts\python.exe -m ruff check src/backend
.venv\Scripts\python.exe -m mypy src/backend
npm run build:frontend
npm --prefix src/frontend run build
```

新增浏览器验收由 T09/T20 纳入明确脚本，例如 root `test:research:e2e`，脚本须启动隔离后端与**正式构建产物**，不能只测开发服务器。命令名称是新增目标，尚未实现前不可宣称它已运行。R0 仍须检查 root build 当前复制的原型入口，R1 切换后检查模块化产物。

数据库并发与恢复测试须额外注明实际数据库、Redis、worker 配置及故障注入方式；临时目录、替身模型的测试不能被写成真实模型质量或生产可靠性结论。

## 8. 每任务交付记录模板

```text
任务：Txx
需求：FR-xx
状态：not_started / in_progress / implemented / verified / blocked
改动：实际文件与关键行为
数据/配置：新增迁移、默认值、兼容方式
验证：AT 编号、实际命令、结果、运行环境
成果：截图/下载文件校验/事务或恢复证据的位置
限制：尚未覆盖的行为，是否阻断当前阶段
回退：关闭何种开关、如何保留资料与账本
下一项：依赖已满足的后续任务
```

状态初始全部为 not_started。只有存在对应验收证据才可标为 verified；受外部模型/人工评审阻碍时只标明该项依赖，继续完成不依赖它的工程验证，不能借此声称全阶段已经完成。
