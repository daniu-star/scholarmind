# ScholarMind 产品与技术系统诊断

日期：2026-11-19。范围：当前工作区，包含检查开始前已有的未提交改动。本次未修改产品实现。

**核心判断：产品的承诺范围已经超过能够稳定交付的范围。任务闭环、研究证据、项目状态和质量验收没有同时成立，导致入口很多、用户承担的组织工作很多、可验证的成果很少。**

这不是对模型智力的测评结论。本次梳理整个目录，并重点追踪主界面、工程化前端、聊天、检索、上传、图表、代码执行、生成/审稿流水线、项目存储、账号权益、支付和测试部署链路；结合本地浏览器观察、隔离测试和无外部模型调用的契约探针进行判断。没有进行真实付费、外发消息、在线模型质量盲评，也没有把本地现象直接当作线上故障率。

优先级定义：P0 为交付失效、研究可信度或数据隔离问题，应在继续对外承诺或收费前处理；P1 为影响核心价值、留存和可持续运营的结构问题。产品定位与主线收敛应立即决策，与修复 P0 并行推进。

## 已验证的关键现象

| 检查 | 结果与解释 |
|---|---|
| 后端既有测试 | 在隔离数据目录并建立日志目录后，182 passed，4 warnings，111.39 秒。测试通过不能证明完整研究任务可交付。首轮从没有 logs 的目录启动测试时，暴露了日志目录前置条件问题，不能把由此造成的 77 个 setup error 解释成 77 个业务故障。 |
| 浏览器意图判断 | “帮我润色这篇论文”“请审查我的论文架构”“检索10篇文献并写综述”均被识别为文献搜索。 |
| 主界面 Skill 请求 | 前端在 context.selected_skill_ids 中选择的技能，被路由用默认空的顶层 skill_ids 覆盖。工程化前端已另传顶层字段，说明两套前端行为分叉。 |
| 流水线模块身份 | 生成流程函数来自 generation，但其绑定的 llm_exec 来自 review；这个对象缺少生成评分所需的 execute_reviewer_scoring。sys.modules 中另一个 generation 执行器又没有 bridge。安装日志仍报告成功。 |
| 审稿输出适配 | 将技能实际定义的 paper_content、review_score=91、score_history=[81,91]、round_number=2 交给服务适配器，得到 revised_paper 为空、final_score 为 null、历史为空、轮数为 7，状态却是 completed。此项为局部契约探针，不代表真实模型运行结果。 |
| 工具结果回传 | 使用本地模型/工具替身，图表工具成功返回结果，但对话流的 done.chart_info 仍为 null，之后没有结果事件。 |
| 单文件上传容量 | 一个测试用户上传 15 个很小的文本文件后，另一测试用户的首次单文件上传收到 413。 |
| 上传所有权 | 两个测试用户向相同 session_id 上传均成功；上下文加载器读到双方文件。利用前提是知道同一个 session_id，不等于可枚举所有会话。 |
| 长附件读取 | 3000 多字的测试附件尾部证据未进入聊天上下文，出现“内容已截断”。 |
| 本地知识库只读统计 | 当前资源表 1530 条，来源集中在本地传播学、民族学、人类学、社会学及学者分析资料；1220 条有非空 abstract。该表没有全文或 discipline 列。这反映本地数据结构与覆盖面，不能推断线上全部数据。 |

证据输出：[契约探针结果](C:/Users/13067/Desktop/全能研究Agent/tmp/product-audit-20261119/contract-probe-results.json)、[模块身份核查](C:/Users/13067/Desktop/全能研究Agent/tmp/product-audit-20261119/bridge-module-identity.json)、[浏览器观察](C:/Users/13067/Desktop/全能研究Agent/tmp/product-audit-20261119/ui-probe-results.json)、[后端测试记录](C:/Users/13067/Desktop/全能研究Agent/tmp/product-audit-20261119/baseline-tests-with-logs.txt)。

## 逐项问题、属性与优化方向

### 01. 服务对象和专业边界过宽

**属性：产品战略、能力边界；P1；依据为代码与本地资料覆盖。** 首页并列工科、理科、人文社科和交叉学科，生成流程实际可选的期刊格式只有三本新闻传播期刊与《社会学研究》，研究类型和知识资产也明显偏向社科。博士、硕士、教师、不同学科的方法与交付标准没有分别兑现。

影响：用户会按“全能研究”的承诺提出问题，系统却只能在部分领域给出相对熟悉的回答；跨学科菜单增加了期待与维护成本。优化：先选定一类用户、一个学科群、一项高价值任务；其他能力按已验证范围展示。验收：针对目标人群有清楚的输入、交付物、适用边界和真实任务评测集。

证据：[学科入口](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:5526)、[实际学科及期刊枚举](C:/Users/13067/Desktop/全能研究Agent/src/backend/models/schemas/paper_pipeline.py:15)、[期刊映射](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/pipeline_utils.py:37)。

### 02. 卖点围绕技术和角色数量，用户成果定义不足

**属性：价值定位、市场表达；P1；产品推断。** 首页反复强调 RAG、LangGraph、7/13 Agent、GAN 和九维评分，直接承诺“顶刊发表水平”。这些词没有回答用户最关心的：这次能指出哪几处实质问题、能否核对依据、能节省哪一段工作。

影响：增加角色或技能时，价值感不会自动增长；期待越高，普通聊天输出越显得弱。优化：把卖点改为具体成果，例如“定位全文关键论证缺口、给出依据与修改稿”；技术名词进入说明或任务详情。验收：新用户能在短时间复述产品交付什么，并看到可检查的样例。

证据：[首页承诺](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:5317)、[快捷功能描述](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:5553)。

### 03. 用户在获得价值前承担过多分类和填写工作

**属性：信息架构、首次体验；P1；代码确认。** 常规路径要求选学科、研究类型、阶段与角色。前端审查员有 16 步引导，其中要求用户先判断理论适配度、数据质量、结论可靠性；这些本来就是用户希望助手协助判断的内容。前后端提示词还各自维护引导流程。

影响：熟练用户被迫重复陈述资料，初学者又未必能作专业判断；成果出现前已消耗注意力和对话次数。优化：默认从上传材料或一句任务开始，先读材料并展示初步发现；仅追问会改变结论的缺失信息，并允许跳过与修正。验收：记录首次有用结果耗时、追问次数和中途退出位置。

证据：[研究阶段入口](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:5868)、[16 步引导](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:13201)、[后端另有引导协议](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent/prompt_templates/synthesizer.j2:29)。

### 04. 聊天角色之间缺少实际交接机制

**属性：Agent 架构、任务编排；P1；代码确认。** 普通聊天主要是按 agent_id 选择提示词后进行一次模型调用，各角色建议用户自行转接。系统确实有独立的 LangGraph 论文流水线，但它没有成为常规聊天中的统一任务控制层。

影响：用户需要记住上一步结论、切换角色并再次描述上下文；专业分工给用户增加了协调负担。优化：前台提供一个研究助手，后台按任务调用检索、审查、修改等能力；角色共享项目事实、证据与交付物，交接传递结构化结果。验收：一个复合任务能在同一上下文中完成，并能说明各步骤的输入和产出。

证据：[聊天主调用](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:238)、[提示词中的转接建议](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent/prompt_templates/custom.j2:23)。

### 05. 关键词拦截使正常任务进入错误功能

**属性：路由错误、核心交互；P0；浏览器复现。** detectCNKIIntent 把“论文”“文献”等泛词作为搜索意图，sendMessage 在模型调用和聊天持久化之前直接转去搜索并返回。因此“润色这篇论文”也可能只得到检索行为，复合任务“检索并写综述”无法按原任务继续执行。

优化：把明确搜索指令与包含论文对象的普通指令分开；复合意图应形成任务计划并携带结果继续处理。验收：润色、架构审查、外审、检索后综述各有实际浏览器回归案例；提及“论文”不能单独触发搜索。

证据：[泛关键词](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:12543)、[提前返回](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:13778)。

### 06. 项目尚未成为研究状态的统一容器

**属性：领域模型、长期记忆；P1；代码确认。** “我的研究项目”保存于固定 localStorage 键中，进入项目实际只跳转学科页；未见统一的服务端 Project—Document—Evidence—Task—Version 关联。工作台标题又来自全局议题键。聊天上下文主要读取最近 40 条消息，缺少明确的长期项目事实和已确认决策。

影响：切设备、换账号、切角色、继续旧研究时难以保证同一研究状态；项目数量增加后价值不会积累。优化：以研究项目为数据主线，关联资料、任务、版本、待核实事实与用户已确认的决定。验收：两个项目交替工作互不串题，跨设备可恢复完整材料与进度。

证据：[本地项目存储与进入动作](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:11155)、[标题来源](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:19181)、[历史窗口](C:/Users/13067/Desktop/全能研究Agent/src/backend/db/repository/conversation.py:27)、[当前 ORM](C:/Users/13067/Desktop/全能研究Agent/src/backend/models/orm.py:35)。

### 07. 部分配置显示成功，实际上没有改变执行行为

**属性：功能完整性、产品诚信；P0；代码确认。** 自定义 Agent 的“保存”只有成功提示，“保存并开始对话”直接进入研究员；没有读取并保存配置。LangGraph 启停、并行度、超时和重试只写入本地存储并改变文字，没有对应后端配置更新。

影响：用户无法分辨自己真的设置了能力，还是只改变了页面。优化：未接通的配置撤出正式功能；配置生效后返回服务端版本和实际参数。验收：保存后刷新、重新登录和发起任务均能确认使用了所保存的配置。

证据：[自定义 Agent 保存按钮](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:7533)、[本地工作流配置](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:10930)。

### 08. 主界面选择的 Skill 被请求契约覆盖

**属性：前后端集成；P0；契约探针复现。** 主界面仅发送 context.selected_skill_ids，ChatRequest 的顶层 skill_ids 默认为空，路由随后用该空列表覆盖 context。工程化前端已同时传顶层字段，但当前主界面和构建入口仍然使用单文件版本。

优化：统一请求契约并建立主界面的真实请求回归；显示本次实际载入的规则版本。验收：用户显式选择一项测试技能后，服务端提示词确实包含该技能规则，取消后不再包含。

证据：[当前主界面请求](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:13865)、[路由覆盖](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/agent.py:148)、[默认字段](C:/Users/13067/Desktop/全能研究Agent/src/backend/models/schemas/agent.py:45)。

### 09. Skill 目录数量超过实际可执行能力

**属性：能力平台、工具执行；P1；代码确认。** 外部技能主要读取 SKILL.md 并拼入提示词；其引用的脚本、辅助资料、需要的工具及完成条件没有统一执行机制。当前 /skills 路由只有两个 GET，主界面创建与更新却使用 POST/PUT。独立 Browser Agent 命令入口也没有形成模型规划—工具执行—结果反馈的统一闭环。

影响：安装与展示一项技能，并不代表产品能够完成该技能描述的工作。优化：区分写作规则、可执行工具与完整工作流；每项能力声明输入、权限、工具、输出和失败处理。验收：技能清单按真实可运行能力展示，新增技能经过至少一个完整任务验收。

证据：[规则注入](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:588)、[技能接口](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/skills.py:11)、[创建请求](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:15475)、[浏览器入口](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/browser_agent.py:37)。

### 10. 两个论文流水线发生模块串用和连接状态不一致

**属性：运行时架构、核心交付；P0；隔离导入复现。** 两套技能使用相同的 pipeline.* 模块名，并通过 sys.path、sys.modules 临时清理和重导入拼装。按 bridge 安装后导入生成服务的顺序，生成 loop_controller 绑定的 llm_exec 实际来自审稿技能，缺少 execute_reviewer_scoring；注册表中的生成执行器又没有模型 bridge。

影响：日志中的“已安装”“已加载”不足以说明实际节点可运行；问题随初始化顺序改变，可能出现在长流程中途。优化：使用独立包命名空间和显式依赖注入，取消运行时改写全局模块缓存；对实际绑定的执行器进行启动自检。验收：两套流水线以任意启动顺序并行工作，实际节点身份正确，缺失模型连接时拒绝启动。

证据：[bridge 安装顺序](C:/Users/13067/Desktop/全能研究Agent/src/backend/utils/pipeline_llm_bridge.py:150)、[生成模块重载](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_pipeline_service.py:115)、[审稿模块重载](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_review_service.py:86)、[实测模块身份](C:/Users/13067/Desktop/全能研究Agent/tmp/product-audit-20261119/bridge-module-identity.json)。

### 11. 论文生成没有使用关键用户输入

**属性：输入契约、任务正确性；P0；代码与探针确认。** 主界面强制上传提纲，上传成功后只把 outline_file_id 和文件名传入 guidance_data；后端 _build_initial_paper 没有查找或读取这个文件，只使用 topic/angle/subject/method 等少数字段生成带“待生成”的骨架。user_target_words 也没有传给实际 PipelineConfig。研究员表单使用 phenomenon/perspective/object，与该构建器的 topic/angle/subject 还存在命名分叉。

影响：产品看似收集了很多资料，生成过程却缺少用户最重要的约束和已有研究成果。优化：建立统一研究输入对象，文件正文/结构、研究问题、已有数据、禁改内容与目标长度必须明确进入任务。验收：相同主题、两份结构显著不同的提纲，应产生可说明其依据的不同结构；字数选项可观察地生效。

证据：[提纲上传后传参](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:16803)、[骨架构建器](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_pipeline_service.py:640)、[实际配置组装](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_pipeline_service.py:549)。

### 12. 审稿结果在服务适配时丢失

**属性：输出契约、结果交付；P0；局部契约探针复现。** 技能定义并输出 paper_content、review_score、score_history、round_number；服务却读取 revised_paper/final_paper、final_score/scores、round。使用技能定义的合法字段作为输入时，服务会将空正文、空分数、空历史和错误轮数标记为 completed。

优化：统一强类型结果协议，并在 completed 前校验成果正文、状态、评分和轮数的一致性。验收：技能产生的正文逐字可从 API 取回；字段不兼容时明确失败，不显示完成。

证据：[服务输出映射](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_review_service.py:484)、[技能状态字段](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-review/pipeline/loop_controller.py:1243)。

### 13. 完整论文任务受到固定截断和输出上限限制

**属性：文档理解、长文可靠性；P0；代码与截断探针确认。** 常规聊天每个附件只取前 2000 字；生成与审稿评分都只把论文前 8000 字交给模型；多轮修改节点默认要求输出整篇论文，但默认上限为 4096 tokens。部分流式截断会作为正常完成结束，前端还依赖并未稳定返回的 truncated 字段。

影响：结论、参考文献、方法附录或后半篇论证可能未被检查；长文逐轮整体改写又可能删失内容。优化：按文档结构分章阅读和修改，记录全文覆盖范围与未读部分；维护章节预算和跨章一致性检查。验收：放在论文尾部的特定错误必须能被发现；章节数量、引文和已确认事实在修改后保持可核查。

证据：[附件截断](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:717)、[生成评分截断](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/llm_executor.py:241)、[审稿评分截断](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-review/pipeline/llm_executor.py:226)、[修改输出上限](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/llm_executor.py:74)。

### 14. 私有全文知识库承诺尚未形成完整实现

**属性：RAG、资料管理；P0；代码确认，部分影响为推断。** 上传接口保存文件并抽取文本，没有把私有全文分块、建立用户/项目索引；聊天从会话目录读截断文本。向量库主要索引标题和 abstract，注入时最多三条、每条摘要 200 字。重建索引的数据库记录又没有 discipline 列，而聊天按 discipline 过滤；这一构建路径会给索引写入空学科，增加空召回与关键词回退的可能。

影响：“上传即自动向量化”“引用可回原文”与实现不一致；提高模型档位不能补齐证据缺失。优化：建立解析—分块—页码/段落定位—权限索引—检索—证据引用的完整链，并向用户显示哪些文件可检索。验收：能检索指定文档尾部内容，引用可打开相应原文位置，跨用户无法命中。

证据：[私有知识库宣传](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:19396)、[上传实际行为](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/upload.py:373)、[向量索引文本](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/vector_service.py:123)、[摘要上下文](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/rag_service.py:170)、[学科过滤](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:613)。

### 15. 模拟内容与静态状态进入真实产品体验

**属性：可信度、能力披露；P0；代码确认。** 审查员检索为空或出错时，仍生成带张三、李四及固定引用量的模拟文献，并放入高引用/高相关推荐区；需要点击预览才提示模拟。首页和设置静态显示 WoS、Scopus 已连接，实际聚合服务列出的来源没有这两者。工作台的部分任务数、版本数、知识库数与权限文字也是静态值。

优化：正式研究输出禁止使用虚构文献补空；空结果、故障、演示样例明确分开。所有连接状态绑定实际健康与权限检查。验收：断开某来源后界面真实变化；空检索保持空结果，不自动补入虚构作者和引用量。

证据：[模拟文献回退](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:17342)、[固定文献数据](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:17492)、[静态连接状态](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:5587)、[实际数据源](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/academic_search_service.py:35)、[静态工作台指标](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:19230)。

### 16. 文献存在、文献内容支持观点、引用格式正确三件事没有分别验证

**属性：学术证据、引用可信度；P0；代码确认。** “文献策展人”主要把文本交给 LLM 修改，再写“文献验证完成”日志，没有在该节点形成文献标识解析和原文论据核验。聊天搜索结果的前端映射还丢掉 DOI、URL、来源标识和摘要等信息；文献详情在部分路径只显示“加载中”。

影响：格式整齐、模型认为合理的引用，仍可能不存在、错引或不能支持相关论断。优化：每条引用保存可验证标识、真实来源、原文位置和支持的具体论断；无法核实的条目显式列出。验收：抽样检查真实存在率与“引用确实支持论断”的比例，不能只检查引用标记格式。

证据：[文献策展人节点](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/loop_controller.py:1209)、[聊天检索结果映射](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:12593)。

### 17. 图表能力同时存在路由缺失、示例数据和结果回传断点

**属性：工具交付、研究数据真实性；P0；代码与本地替身复现。** 主界面请求 /api/v1/chart/generate，但当前路由没有注册该接口；聊天自动图表路径明确调用 _generate_sample_data，而非解析用户数据；流式聊天先发送 chart_info=null 的 done，后台生成结果没有再交付。已有图表绘制函数是真实资产，但调用链并不等于可用产品能力。

优化：统一图表接口；显式绑定用户数据、列定义和统计处理过程；异步结果必须回到任务与对话。示例数据只用于用户明确选择的演示。验收：输入一份已知数据后，图中数值可逐项核对，下载文件真实可访问。

证据：[前端图表请求](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:11685)、[路由注册](C:/Users/13067/Desktop/全能研究Agent/src/backend/app.py:208)、[生成示例数据](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:802)、[结果未回传](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:462)。

### 18. 计算研究入口超过普通用户可用的执行范围

**属性：功能范围、能力兑现；P1；配置与代码确认。** 产品提供代码编辑器、运行按钮和“直接写码跑给你看”的开场白；当前代码执行默认关闭，启用后仍要求管理员。关闭高风险执行入口本身有合理性，问题在于普通用户仍会把该入口理解为已交付的分析能力。

优化：当前按真实能力展示“生成代码/导出分析脚本”；若要服务普通用户，再建设隔离执行环境、依赖版本、数据权限和结果复现。验收：以普通账号测试完整路径；生成的代码、实际运行环境和结果来源一致。

证据：[执行开关](C:/Users/13067/Desktop/全能研究Agent/src/backend/app.py:215)、[管理员权限](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/code_execution.py:33)、[能力开场白](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent/prompt_builder.py:109)。

### 19. 评分体系无法支撑“顶刊水平”的结论

**属性：评估有效性、研究质量；P0；代码确认与评估方法判断。** 生成流程无 bridge 时存在固定 85 分回退；评分提示词列出的分项上限合计 90，却称总分 100。GAN 模块实际是两个提示角色的分数融合，没有形成能证明发表质量的独立校准。部分规则把问号标题、高级图表、避免柱状图/饼图作为质量检查点，学术正确性与特定风格偏好混在一起。

优化：将事实、方法、论证、引用、格式分别验收；移除固定合格分和缺失评分的正常化处理；使用人工专家盲评与真实问题集校准。验收：评分能发现预置的严重缺陷，修改后关键问题确实减少；模型分数只作为过程辅助指标。

证据：[固定分数](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/loop_controller.py:1638)、[评分提示词](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/llm_executor.py:226)、[分数融合](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/gan_scorer.py:25)、[风格检查点](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/config.py:154)。

### 20. 任务执行结束与成果验收通过没有清晰区分

**属性：状态机、错误处理；P0；代码确认。** 节点调用失败后可回退为原文；生成流程不论达到阈值还是耗尽轮数，只要返回结果就由服务标记 completed；审稿适配器也可能把空输出标记 completed。界面以完成图标和分数展示，用户难以知道究竟做了多少有效工作。

优化：统一 running、partial、needs_input、failed、completed 等结果状态；completed 必须有最小交付物和验证记录。把可保留的部分成果、未执行步骤和缺失证据展示出来。验收：模型失败、评分缺失、全文未读或成果为空时都不能显示“已完成且达标”。

证据：[节点失败回退原文](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/llm_executor.py:128)、[生成服务统一完成](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_pipeline_service.py:610)、[前端完成展示](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:14891)。

### 21. 长任务的持久化、恢复与长期资产保存不足

**属性：可靠性、后台任务；P1；代码确认。** 生成/审稿主要由进程内 asyncio.create_task 启动；状态存于 TTL 24 小时的 Redis，断开时降级内存；任务句柄与执行上下文不持久。系统有 Celery 设施，但这两个核心长任务没有因此自动获得持久化执行、断点恢复和重试能力。查询旧状态也不等于恢复旧任务。

优化：将任务登记、排队、执行、章节检查点、成果文件及额度结算持久化；支持安全重试和用户主动继续。验收：执行中重启服务，任务能恢复或给出清楚的可继续状态；历史成果在约定保留期内持续可访问。

证据：[进程内任务](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_pipeline_service.py:298)、[状态 TTL](C:/Users/13067/Desktop/全能研究Agent/src/backend/db/pipeline_state_repo.py:33)、[内存任务引用](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/paper_pipeline_service.py:214)。

### 22. 上传和本地研究资料的用户隔离不完整

**属性：数据隔离、容量管理；P0；本地合成资料复现。** 单文件上传共用 single_uploads 目录，并套用每会话 15 个文件限制；某用户用满后会阻塞其他用户。会话附件按 session_id 存储和读取，没有校验该会话归属 user_id；已认证用户知道同一 session_id 时可混入资料。项目、文献库等多个浏览器键也未按账号分区，退出登录仅清除认证相关键。

优化：文档与会话建立服务端所有权关系，以 user_id/project_id/document_id 隔离对象、容量和检索；增加删除与保留机制，本地缓存按账号分区。验收：跨用户同 session_id 读写被拒绝；一个用户容量耗尽不会影响另一个；退出切账号后不显示上个账号的项目和文献。

证据：[全局单文件目录与数量检查](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/upload.py:347)、[会话目录未校验归属](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/upload.py:253)、[上下文读取无 user_id](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:694)、[退出行为](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:8730)、[固定文献库键](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:12286)。

### 23. 流水线复杂度没有对应可证明的质量增益

**属性：效率、成本、工作流设计；P1；架构判断。** 生成图大部分节点串行，多名角色反复处理整篇论文，默认多轮执行；前端主要展示角色和轮数。尚未见每新增一个节点带来的质量增益、增量成本和等待时间的对照评测。不能仅凭节点多断言成本一定不可接受，但当前代码不足以证明它们值得。

优化：先用“读全文—诊断—定向修改—复核”的短链做基线，按缺陷类型触发必要角色，按章节处理并限制任务预算。验收：比较相同任务的质量、成功率、耗时和模型调用消耗，以增益决定是否保留节点。

证据：[串行节点边](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/loop_controller.py:2248)、[全文改写协议](C:/Users/13067/Desktop/全能研究Agent/skills/cyclical-paper-generation/pipeline/llm_executor.py:363)、[任务超时](C:/Users/13067/Desktop/全能研究Agent/src/backend/config.py:195)。

### 24. 成果主要停留在聊天与抽屉，缺少可审阅的修改资产

**属性：核心工作区、交付物；P1；代码与领域模型观察。** 当前同时有角色聊天、写作工作台、论文工作台和流水线抽屉。写作内容以本地保存和整体文本为主，未见统一的论文段落版本、修改依据、引用关联和逐项采纳记录；“版本追溯”的宣传超过当前统一资产模型。

影响：用户仍需自己判断、复制、整理和比对，难以把产品输出直接转成研究进展。优化：围绕同一篇文档展示“原文位置—问题—依据—修改建议—可采纳改动”，支持逐项接受、拒绝、恢复和导出。验收：用户能解释某段为什么修改，撤回单个改动而不丢其他修改，并导出一致的稿件。

证据：[论文工作台独立聊天请求](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:18728)、[本地写作保存](C:/Users/13067/Desktop/全能研究Agent/src/frontend/src/pages/WritingWorkspace.js:438)、[现有领域对象](C:/Users/13067/Desktop/全能研究Agent/src/backend/models/orm.py:35)。

### 25. 套餐、计价说明和模型权益存在多套口径

**属性：商业化、权益一致性；P0/P1；代码确认。** 服务端有 4.99、19.99、39.90、59.90 四项商品，关于页仍写 Pro 39 元/月、年付八折、按 token 计费与企业套餐。聊天会按用户权益选择 Flash/Pro，但论文流水线配置没有绑定该用户模型策略，bridge 仍走全局默认模型；本地默认是 Flash。

优化：价格与权益从服务端唯一目录渲染；同一任务贯穿使用已确认的模型档位，写入任务账单。先核算真实任务成本，再确定“不限次数”等承诺的范围。验收：商品页、购买页、账号权益和任务实际使用模型一致；过期后的权益也一致。

证据：[商品目录](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/entitlement_service.py:17)、[旧套餐介绍](C:/Users/13067/Desktop/全能研究Agent/prototypes/interactive-prototype.html:7791)、[聊天模型策略](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/model_policy.py:79)、[流水线模型调用](C:/Users/13067/Desktop/全能研究Agent/src/backend/utils/pipeline_llm_bridge.py:98)。

### 26. 免费体验和失败扣额没有围绕有效交付设计

**属性：激活转化、额度结算；P1，涉及错误扣额的路径应按 P0 处理；代码确认。** 免费 20 次对话包含正常问候和长引导消耗，三个醒目的核心快捷任务都需要额外权益。聊天内部把模型失败转成离线引导后正常返回，外层基于异常退额的逻辑不会触发；流水线仅在启动阶段异常退额，后台执行失败缺少对应的结算闭环。

影响：用户可能在看到最强成果前耗尽试用，或为失败、占位结果承担额度。优化：提供一项完整、可验证的核心体验；将额度预留、任务验收和结算分开，失败与取消按明确规则处理，支持幂等重试。验收：在模型断连、队列超时、后台失败和重复点击场景下，账单与有效交付一致。

证据：[问候仍正常扣额](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/agent.py:39)、[失败转正常回复](C:/Users/13067/Desktop/全能研究Agent/src/backend/services/agent_service.py:278)、[仅启动异常退额](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/paper_pipeline.py:64)、[流异常才退额](C:/Users/13067/Desktop/全能研究Agent/src/backend/routers/agent.py:173)。

### 27. 原型承担生产职责，工程投入难以持续改善真实体验

**属性：工程维护、发布可靠性；P1；代码确认。** 当前生产构建复制约 1.03 MB、约 1.97 万物理行的单 HTML；另一套模块化前端同时存在。账号、请求字段、UI 和功能在两套前端分别维护，已出现 Skill 修复只落在工程化版的情况。CI 的主前端构建主要是复制文件，没有证明主界面脚本与完整用户流程正确。另有本地路径、两套 Celery 实例、运行时模块拼装和日志目录前置条件增加部署变量。

优化：确定唯一产品前端与发布链，按任务模块迁移，优先统一 API 契约、状态和缓存边界；用真实主界面流程保障迁移。验收：一次能力变更只需要修改唯一实现，测试、预览和线上使用相同入口与构建产物。

证据：[构建复制原型](C:/Users/13067/Desktop/全能研究Agent/scripts/build-frontend.js:28)、[当前界面约定](C:/Users/13067/Desktop/全能研究Agent/README.md:179)、[CI](C:/Users/13067/Desktop/全能研究Agent/.github/workflows/ci.yml:50)、[日志文件初始化](C:/Users/13067/Desktop/全能研究Agent/src/backend/core/logging_config.py:46)。

### 28. 验证体系侧重接口与页面，缺少真实研究任务质量和用户结果指标

**属性：质量管理、产品发现、运营；P1；仓库观察。** 既有测试覆盖权限、套餐、安全和若干工具函数，182 项通过；仍未拦住提纲未使用、结果映射丢失、关键词误路由等完整任务缺陷。ab_testing 是 LLM 扮演 Persona 对 UI 的模拟评价，不能作为真实用户使用效果。现有 Prometheus 主要记录请求、错误、连接和生成时长，未见把研究任务成功、引用准确、修改采纳与用户回访串联的产品指标。

优化：建立一组授权真实论文任务，包含后半篇错误、虚构引用、无数据要求、方法不一致和服务故障；用人工盲评校准，并追踪首次有效成果、成果采纳、独立完成率及回访。验收：每次上线同时报告技术稳定性、任务质量和用户收益；新增角色需证明有额外收益。

证据：[既有聊天测试](C:/Users/13067/Desktop/全能研究Agent/src/backend/tests/test_services/test_agent_service.py:23)、[Persona 模拟](C:/Users/13067/Desktop/全能研究Agent/src/backend/ab_testing/personas.py:1)、[运行指标](C:/Users/13067/Desktop/全能研究Agent/src/backend/core/metrics.py:1)、[测试记录](C:/Users/13067/Desktop/全能研究Agent/tmp/product-audit-20261119/baseline-tests-with-logs.txt)。

## 产品重构建议

**先聚焦一个可验证的任务：新闻传播及相近社科研究者的投稿前诊断与定向修改。** 这是依据现有期刊格式、知识资产和审稿实现提出的待验证方向，仍需真实目标用户任务验证。

建议的主流程：上传论文和投稿目标 → 阅读全文并展示覆盖情况 → 定位关键问题与依据 → 用户选择本轮修改目标 → 生成带对照的修改稿 → 检查引用和内容守恒 → 导出稿件与修改说明。

前台保留一个主助手、一个项目资料区、一个文档与修改区、一个任务记录区。后台角色按缺陷和需要调用。论文生成先明确为基于已有提纲、材料与证据的辅助起草；缺少真实研究数据时标示待研究内容，不生成已经完成实证研究的假象。跨学科扩展、自定义 Agent 平台、普通用户代码执行和泛化技能市场应等待主任务验证后再扩展。

| 顺序 | 工作包 | 交付验收 |
|---|---|---|
| 第一批，恢复交付可信度 | 修复误路由、Skill 契约、流水线模块身份、提纲输入、审稿输出、工具结果回传、上传隔离；撤下模拟文献和未实现的成功提示；统一价格与实际能力。 | 一份固定论文能从上传到结果与导出完整走通；失败可见且不以合格成果结算。 |
| 第二批，建立任务主线 | 服务端项目/文档/证据模型、全文读取、可定位引用、定向修改、可采纳差异与持久任务。 | 同一项目跨会话/设备可继续，关键修改有依据，用户能控制每次改动。 |
| 第三批，证明价值再扩展 | 基线任务评测、专家盲评、真实用户观察、单任务成本与回访分析。 | 新能力在质量、节省时间或成功率上有可证明增益，再增加角色、学科与收费范围。 |

可先采用的验收目标（均为建议目标，不是本次测得的现状）：目标任务技术完成率至少 95%；所有展示的引用均有可验证来源；所有完成任务均交付可打开的成果；故障任务不按成功任务结算；至少用一组覆盖不同长度和研究方法的授权论文做人工抽检。具体时间、成本和采纳率目标应在真实用户基线测量后确定。

## 值得保留的资产

已有的期刊导出与格式处理、多源搜索适配、图表绘制函数、账号权益原子更新、安全测试、提示词与学科资料均可继续使用。现阶段主要需要把这些资产放进同一个能验证输入、证据、执行和交付结果的任务中，而非继续用入口数量体现进展。

本诊断未声称所有用户都无法完成任务，也未给出未经测量的留存、收入、模型能力或线上故障率。策略判断与已复现故障分别标明，便于后续逐项验证。
