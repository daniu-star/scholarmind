---
name: "cyclical-paper-generation"
description: "循环式论文生成技能v7.3：13 Agent协作的循环式论文精炼Pipeline，基于LangGraph的Loop机制+约束注入+风格守卫，通过13个专业化Agent多轮迭代打磨学术论文至顶刊发表水平。v7.3核心优化：docx脚注强制合规——修复Word文档脚注生成机制，确保自动生成真实OOXML脚注（w:footnoteReference），脚注内容完整准确（不缺斤少两），脚注内容符合真实已引用文献字段，强制docx规范合规。新增脚注内容完整性验证（validate_footnote_content_completeness）、脚注编号格式验证（validate_footnote_number_format）、脚注-参考文献严格匹配（阈值≥3分）、脚注内容安全生成（add_footnote_with_validation）、结构化引用数据生成脚注（add_footnote_from_reference）；修复回滚机制Bug（detect_manual_footnotes传入Document对象而非字符串路径）；废弃手动上标伪脚注（add_footnote_marker）。v7.4核心优化：内参报告按需生成模块——新增NeicanWriter Agent（内参撰写者），仅在用户明确请求时触发，将学术论文转化为内参报告或直接生成内参。新增neican_standards.md知识库（基于5篇真实内参报告样本提取的9章节详尽规范），新增内参格式验证（validate_neican_title/opening/hierarchy/countermeasure/ending/signature/academic_residue），新增内参Word模板（generate_neican_document），新增output_mode配置（paper/neican/both，默认paper不破坏论文结构）。v7.2核心优化：人类语言合规强制检查——基于34篇真实CSSCI论文提取人类语言特征，新增human_language_features.md作为人类语言合规基准，所有Agent输出必须通过人类语言合规检查（微观/中观/宏观/人味四层检查），未通过的论文不得输出。v7.1核心优化：GAN轮次调整与论文自然化优化。v7.0核心优化：GAN对抗评分——消除AI自评幻觉。支持量化/质化/计算社会科学/混合方法/访谈报告/理论论文六种研究类型。支持多CSSCI期刊格式输出。"
---

# 循环式论文生成 (Cyclical Paper Generation) v7.4

## 概述

本Skill封装了一个基于LangGraph的**13 Agent循环式论文精炼Pipeline**，通过多轮迭代（目标7轮）将学术论文初稿打磨至顶刊发表水平。最终评分目标≥90分（满分100分，涵盖9个维度）。支持《新闻与传播研究》《国际新闻界》《新闻大学》《社会学研究》四种CSSCI期刊格式输出。

**v7.3核心优化：docx脚注强制合规**——修复Word文档脚注生成机制，确保输出的docx文档包含真实OOXML脚注（`w:footnoteReference`），脚注内容完整准确（不缺斤少两、不乱码、不占位符），脚注内容符合真实已引用文献字段。新增脚注内容完整性验证（`validate_footnote_content_completeness`）、脚注编号格式验证（`validate_footnote_number_format`）、脚注-参考文献严格匹配（阈值从≥2提高到≥3分）、脚注内容安全生成（`add_footnote_with_validation`）、结构化引用数据生成脚注（`add_footnote_from_reference`）、脚注内容格式化（`format_footnote_text`）。修复回滚机制Bug（`detect_manual_footnotes`传入Document对象而非字符串路径，返回值字段名错误）。废弃手动上标伪脚注（`add_footnote_marker`）。修复`enforce_all_fonts()`不检查footnotes.xml中run的字体问题。所有Agent新增脚注生成强制规范。

**v7.4核心优化：内参报告按需生成模块**——新增NeicanWriter Agent（内参撰写者），仅在用户明确请求时触发（output_mode=neican或both），将学术论文转化为内参报告或直接生成内参。新增`knowledge_base/neican_standards.md`知识库（基于5篇真实内参报告样本提取的9章节详尽规范：基础规范/标题范式/开篇范式/正文结构/对策刻度/文风特征/转化对照表/结尾署名/字数指导）。新增内参格式验证函数（`validate_neican_title`/`validate_neican_opening`/`validate_neican_hierarchy`/`validate_neican_countermeasure`/`validate_neican_ending`/`validate_neican_signature`/`validate_neican_academic_residue`/`run_neican_validation`）。新增内参Word模板生成函数（`generate_neican_document`）。新增`output_mode`配置（`paper`默认/`neican`/`both`），默认为`paper`不破坏论文结构。新增`NEICAN_CONFIG`配置字典。**核心约束：内参模块仅在用户明确请求时触发，不得在常规论文流程中自动调用。**

**v7.2核心优化：人类语言合规强制检查**——基于34篇真实CSSCI论文（传播学8篇、经济学8篇、法学6篇、民族学/历史学6篇、非遗/文化研究6篇）的深度分析，提取人类论文的语言特征（跨学科共性特征、学科差异化特征、"人味"特征清单、AI典型问题、话语表述逻辑），新增 `knowledge_base/human_language_features.md` 作为人类语言合规基准。所有Agent在生成/润色时必须参照该文件，确保输出符合人类论文的语言逻辑、习惯、规范。新增HumanLanguageGuard（人类语言守卫）程序化节点，执行微观（句式/词汇/标点）、中观（章节风格）、宏观（论证/过渡/声音）、人味（≥3项）四层合规检查，未通过的论文不得输出。

**v6.3核心优化：强制字数控制**——三层防线（事前约束+事后压缩+硬截断兜底）确保无论滚动多少轮，论文字数严格限定在用户指定目标内。用户提出多少字，无论滚动多少次一定要只限定在这个字数。

**v6.1核心策略：声音优先、规则兜底**——先内化目标文风（范本锚点），再遵守禁止规则（规则兜底），解决"生成论文要么僵硬机械化、要么散文化口水化"的核心问题。

**v6.0核心特性：**
- **12 Agent 架构**（从5 Agent扩展）：新增Methodologist、LiteratureCurator、WordCountController、Narrator、Orchestrator、WordFormatValidator、StyleGuard
- **ConstraintInjector**（约束注入器）：每次Agent执行前注入中央风格约束，确保规则不随循环增加而漂移
- **StyleGuard**（风格守卫）：每次Agent输出后程序化验证标点/字数/禁止模式合规，形成"违规→注入→修复→再验证"闭环
- **WordFormatValidator**（格式验证）：验证脚注真实性和连续性、中文引号字体一致性、图表编号连续性、文档可打开性
- **字数控制器**：精确逐节字数检查（±10%容差），超标自动生成压缩指令
- **叙事连贯性主编**：整体叙事弧线审计、段落间过渡检查、"朗读测试"统一论文声音
- **编排者**：管理多Agent执行策略，监控得分趋势，检测停滞/倒退
- **共享学习档案**：所有Agent共享用户风格偏好，消除"各自学习互不知道"
- **单一真实来源**：`style_constraints.py` 集中管理所有风格约束，消除三处重复维护风险
- **OOXML真实脚注**：替代手动上标方案，真正的Word脚注（w:footnoteReference）
- **中文引号字体修复**：强制w:eastAsia=宋体，防止引号回退到Times New Roman/等线/Calibri
- **六种研究类型**：定性研究、定量研究、计算社会科学、混合方法、访谈报告、理论论文
- **LangGraph Checkpointer**：启用 MemorySaver 实现状态持久化与恢复

**v6.1 风格系统增强：**
- **风格范本库** `knowledge_base/style_exemplars.md`：周葆华计算社会科学风格（5段落范本+15句式模板）+ 刘战伟质化研究风格（5段落范本+15句式模板）+ 20组通用改写示例 + 30种段落开头多样性库
- **正向句式模式** `RECOMMENDED_PATTERNS`：按研究类型提供推荐句式（概念辨析/理论升华/过渡），替代纯禁止性规则
- **声音锚点** `VOICE_SAMPLES`：按研究类型提供目标文风范本段落，供Polisher和Narrator内化
- **节奏检测** `RHYTHM_METRICS`：句长方差（8.0-25.0）、段落开头多样性（≥0.6）、机械模式检测，程序化识别"僵硬化"和"散文化"
- **Polisher 声音驱动重构**：从849行规则驱动重构为~462行声音驱动，新增声音锚点、改写原则、节奏与多样性、研究类型适配
- **Narrator 扩展**：新增声音锚点、8个声音统一改写示例、朗读测试四步操作规范、6种研究类型声音守护策略
- **Reviewer 维度2细化**：15分拆分为2a节奏感(5分)+2b多样性(5分)+2c声音一致性(5分)
- **ConstraintInjector 增强**：注入VOICE_SAMPLES和RHYTHM_METRICS到Polisher和Narrator
- **StyleValidator 增强**：记录节奏诊断（僵硬化/散文化信号）到error_log

## Pipeline架构

### 整体流程（LangGraph图结构 — v7.0 13 Agent版 + 守卫节点 + 编排器 + GAN对抗评分）

```
                     ┌──────────────────────────┐
                     │    ConstraintInjector     │  ← v6.0 新增：约束注入器
                     │  (注入中央风格规则)       │
                     │  v6.1: 注入范本+节奏要求  │
                     └───────────┬──────────────┘
                                 │
                                 ▼
              ┌────────────────────────────────────┐
              │  润色者 (Polisher) v6.1             │
              │  · 声音锚点 · 改写原则             │
              │  · 标点净化 · 辞藻削薄            │
              │  · 节奏与多样性 · 研究类型适配    │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  StyleGuard (风格守卫)              │  ← v6.0 新增
              │  · 标点计数 · 字数检查            │
              │  · 禁止模式检测 · 违规记录        │
              │  · v6.1: 节奏/多样性/机械模式检测  │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  可视化者 (Visualizer)              │
              │  · Origin级图表 · 三线表           │
              │  · 英文摘要 · 配色规范             │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  方法论专家 (Methodologist) v6.0     │  ← 新增
              │  · 抽样审核 · 编码策略             │
              │  · 统计方法 · 研究伦理             │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  文献策展人 (LiteratureCurator)       │  ← 新增（从Expert拆分）
              │  · 文献验证 · 中文补充             │
              │  · 装饰性引用检测 · 脚注核验       │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  内容专家 (Expert) v6.1              │
              │  · 论证逻辑 · 理论对话             │
              │  · 概念定义 · 学术规范             │
              │  · v6.1: 研究类型内容差异          │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  StyleGuard (风格守卫)              │  ← 再次验证
              │  · 检查Expert是否引入新违规        │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  字数控制器 (WordCountController)    │  ← 新增
              │  · 逐节字数审计 · 超标压缩指令    │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  叙事连贯性主编 (Narrator) v6.1      │  ← 新增
              │  · 声音锚点 · 叙事弧线             │
              │  · 改写示例 · 朗读测试             │
              │  · 研究类型声音差异                │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  编排者 (Orchestrator)               │  ← 新增（元Agent）
              │  · 执行策略 · 趋势监控             │
              │  · 资源分配 · 人工介入决策         │
              └───────────┬────────────────────────┘
                          │
                          ▼
              ┌────────────────────────────────────┐
              │  审稿人 (Reviewer) v6.1              │
              │  · 9维度评分 · 否思 · 编码优化    │
              │  · 图表批判 · 框架建议             │
              │  · v6.1: 维度2细化(2a/2b/2c)       │
              │  PASS/REVISE 信号                    │
              └───────────┬────────────────────────┘
                          │
              ┌────────────┴────────────────────────┐
              │              │                       │
              ▼              ▼                       ▼
        ┌──────────┐  ┌──────────┐           ┌──────────────┐
        │ ≥90分?  │  │ <90分?  │           │ 防死锁触发   │
        │  PASS   │  │  REVISE  │           │ 人工介入     │
        └────┬─────┘  └────┬──────┘           └──────┬───────┘
             │              │                        │
             ▼              │                        ▼
    ┌────────────────┐      │                   ┌──────────┐
    │ WordFormatValidator│    │                   │   END    │
    │ (v6.0 新增)    │      │                   └──────────┘
    │ · 可打开性     │      │
    │ · 脚注格式     │      │
    │ · 引号字体     │      │
    │ · 图表编号     │      │
    └───────┬────────┘      │
            │               │
            ▼               │
    ┌────────────────┐      │
    │ 格式化为Word    │      │
    │ (目标期刊格式)  │      │
    └────────────────┘      │
                             │
                             ▼
                   ┌────────────────────────────────────┐
                   │  HumanLanguageGuard (人类语言守卫)    │  ← ★v7.2 新增
                   │  · 微观检查（句式/词汇/标点）        │
                   │  · 中观检查（章节风格）              │
                   │  · 宏观检查（论证/过渡/声音）        │
                   │  · 人味检查（≥3项人类特征）         │
                   │  · 参照 human_language_features.md  │
                   │  · 未通过→注入修复指令→循环         │
                   └─────────┬──────────────────────────┘
                             │
                             ▼
                   ┌─────────┴──────────┐
                   │  意见路由分发        │
                   │  OpinionRouter      │
                   │  (六路分发v6.0)     │
                   │  语言→润色者        │
                   │  图表→可视化者      │
                   │  内容→专家          │
                   │  方法→Methodologist │
                   │  文献→LiteratureCur.│
                   │  叙事→Narrator     │
                   └─────────┬──────────┘
                             │
                             ▼
                   ┌────────────────────┐
                   │ 增量修改控制        │
                   │ IncrementalControl │
                   │ (冻结已通过章节)    │
                   └─────────┬──────────┘
                             │
                             ▼
                   ┌────────────────────┐
                   │ ConstraintInjector  │  ← 循环回到起点
                   │ (注入违规记录)      │
                   └────────────────────┘
```

### 循环退出条件

| 条件 | 动作 |
|------|------|
| 审稿人评分 ≥ 90 | 输出最终定稿Word，终止循环 |
| 审稿人评分 < 90 且 N < 7 | 分发修改意见至对应Agent，进入下一轮 |
| 审稿人评分 < 90 且 N = 7 | 输出当前最佳版本 + 未解决问题清单 |
| 连续3轮总分提升 < 3分 | 触发人工介入提示 |
| 某维度连续2轮满分 | 冻结该维度相关章节 |
| 某维度连续3轮无显著提升 | 冻结该维度，标注"已达当前最优" |
| 某维度出现倒退 | 自动回滚该维度至上一轮版本 |

### 评分维度与权重（总分100分）

| 序号 | 维度 | 满分 | 评估重点 |
|------|------|------|---------|
| 1 | 标题冲击力 | 10 | 主标题反问式张力、小节标题信息密度 |
| 2 | 文笔与文风 | 15 | v6.1细化：2a节奏感(5分)+2b多样性(5分)+2c声音一致性(5分) |
| 3 | 学术深度 | 15 | 核心概念定义清晰、论证层层递进、理论对话充分 |
| 4 | 学理性 | 15 | 分析性（非描述性）、编码数据支撑、反直觉发现展开 |
| 5 | 图表美观度与专业性 | 10 | 三线表规范、高级图表类型、学术配色 |
| 6 | 格式标准性 | 10 | 符合目标期刊投稿格式、脚注真实、字体合规 |
| 7 | 严谨性 | 10 | 文献引用真实准确、编码数据与论点一致 |
| 8 | 专业性 | 10 | 学科理论深入理解、术语恰当、研究设计合理 |
| 9 | 创新性与启发价值 | 5 | 新概念/分析框架、理论推进、实践启示 |
### GAN对抗评分机制（★v7.0新增）

| 组件 | 角色 | 评分倾向 | 来源 |
|------|------|---------|------|
| **G评分**（Generator） | Reviewer的原始评分 | 偏乐观 | agents/reviewer.md |
| **D评分**（Discriminator） | AdversarialCritic的挑刺评分 | 偏严苛 | agents/adversarial_critic.md |
| **融合评分** | G与D的加权融合 | 校正后最终评分 | pipeline/gan_scorer.py |

融合公式：`fused_score = α × G_score + (1 - α) × D_score`，α默认0.4
对抗信号：`adversarial_signal = G_score - D_score`，>10为严重过度自信
过度自信惩罚：信号>5时每超1分扣0.5分

---

## 13 Agent 角色总览

| # | Agent | 角色 | v6.1 变更 |
|---|-------|------|-----------|
| 0 | **论文架构师** (Architect) v6.1 | 研究框架设计，五阶段问题引导 | v6.1: 阶段五新增研究类型框架差异化 |
| 1 | **润色者** (Polisher) v6.1 | 语言编辑：声音锚点/改写原则/节奏多样性 | v6.1: 规则驱动→声音驱动重构（849行→462行） |
| 2 | **可视化者** (Visualizer) | 学术图表设计：4表+4图+英文摘要 | 接入中央风格约束 |
| 3 | **方法论专家** (Methodologist) | v6.0新增：方法论审核（量/质/计算） | 无（新建） |
| 4 | **文献策展人** (LiteratureCurator) | v6.0新增：文献验证/中文补充/格式统一 | 无（从Expert拆分） |
| 5 | **内容专家** (Expert) v6.1 | 论证逻辑/理论对话/概念定义/学术规范 | v6.1: 新增研究类型内容差异+范本库引用 |
| 6 | **字数控制器** (WordCountController) | v6.0新增：逐节字数审计+超标压缩 | 无（新建） |
| 7 | **叙事连贯性主编** (Narrator) v6.1 | v6.0新增：叙事弧线/段落过渡/朗读测试 | v6.1: 新增声音锚点+8个改写示例+朗读测试规范+研究类型声音差异（153行→366行） |
| 8 | **编排者** (Orchestrator) | v6.0新增：执行策略/趋势监控/资源分配 | 无（新建，元Agent） |
| 9 | **审稿人** (Reviewer) v6.1 | 9维度评分+否思+编码优化+图表批判+框架建议 | v6.1: 维度2细化为2a节奏感/2b多样性/2c声音一致性+研究类型风格适配检查 |
| 9.5 | **对抗挑刺者** (AdversarialCritic) | v7.0新增：GAN D侧，假设论文有问题穷尽挑刺 | 无（新建） |
| 10 | **风格守卫** (StyleGuard) | v6.0新增：程序化风格约束验证节点 | v6.1: 新增节奏/多样性/机械模式检测+error_log诊断记录 |
| 11 | **Word格式验证** (WordFormatValidator) | v6.0新增：脚注/引号字体/文档完整性 | 无（新建） |
| 12 | **内参撰写者** (NeicanWriter) | v7.4新增：论文→内参转化/内参直接生成 | 无（新建，按需触发） |

---

## v6.0 新增 Pipeline 机制

### ConstraintInjector（约束注入器）

在 LangGraph 图中，于每个核心 Agent node 之前插入 `constraint_injector` 节点。从 `pipeline/style_constraints.py` 读取中央风格约束，写入对应 Agent 的 `*_instruction` 字段。同时携带上一轮的风格违规记录（error_log 中的违规项），形成"违规→注入→修复→再验证"闭环。

**v6.1 增强**：额外注入 `VOICE_SAMPLES`（声音锚点段落）和 `RHYTHM_METRICS`（节奏要求）到 Polisher 和 Narrator 的 instruction 字段。

### StyleGuard（风格守卫）

在每个核心 Agent node 之后插入 `style_validator` 节点。运行程序化检查（标点符号计数、全文字数、禁止模式检测），输出违规列表。违规列表被注入到下一轮的 instruction 中。

**v6.1 增强**：新增节奏诊断（句长方差过低=僵硬化信号，过高=散文化信号）、段落开头多样性检测、机械模式检测，所有诊断记录到 error_log。

### WordFormatValidator（文档验证）

仅当论文通过评审（PASS）后触发，进入最终输出阶段前执行：
1. 验证 docx 文件可打开
2. 验证脚注为真实 Word 脚注（w:footnote 元素）
3. 验证脚注与参考文献一致性
4. 验证中文引号字体为宋体（w:eastAsia设置）
5. 验证图表编号连续性

### 共享学习档案

`pipeline/shared_learning.py` 管理所有 Agent 共享的用户风格偏好档案。每次 Pipeline 完成后，Orchestrator 从各 Agent 的学习日志中提取共性模式更新共享档案，下一轮 ConstraintInjector 据此生成个性化指令。

---

## v6.1 风格系统架构（声音优先、规则兜底）

```
┌─────────────────────────────────────────────────────────┐
│ Layer 4: Pipeline 控制器 (loop_controller.py)           │
│  · constraint_injector 注入范本段落+节奏要求            │
│  · style_validator 新增节奏/多样性/机械模式检测         │
└────────────────────────┬────────────────────────────────┘
                         │ 注入
┌────────────────────────▼────────────────────────────────┐
│ Layer 3: Agent 系统提示 (.md 文件)                      │
│  · polisher.md v6.1: 规则驱动→声音驱动（849行→462行）  │
│  · narrator.md v6.1: 扩展改写示例（153行→366行）       │
│  · expert.md v6.1: 引用范本库+研究类型内容差异          │
│  · architect.md v6.1: 阶段五研究类型框架差异化          │
│  · reviewer.md v6.1: 维度2细化(2a/2b/2c)               │
└────────────────────────┬────────────────────────────────┘
                         │ 引用
┌────────────────────────▼────────────────────────────────┐
│ Layer 2: 中央约束 (style_constraints.py)                │
│  · RECOMMENDED_PATTERNS（正向句式模式，按研究类型）     │
│  · VOICE_SAMPLES（声音锚点段落，按研究类型）            │
│  · RHYTHM_METRICS（节奏检测指标）                       │
│  · check_rhythm / check_paragraph_diversity 等          │
│  · get_agent_constraints 注入范本+节奏要求              │
└────────────────────────┬────────────────────────────────┘
                         │ 加载
┌────────────────────────▼────────────────────────────────┐
│ Layer 1: 风格范本库 (knowledge_base/style_exemplars.md) │
│  · 计算社会科学风格（基于周葆华）：5段落范本+15句式模板 │
│  · 质化研究风格（基于刘战伟）：5段落范本+15句式模板     │
│  · 通用风格：20组 before/after 改写示例                 │
│  · 30种段落开头多样性库                                  │
└─────────────────────────────────────────────────────────┘
```

---

## Agent System Prompt 三维结构（v6.0）

每个 Agent 的 System Prompt 具备三个维度：

| 维度 | 说明 | 示例 |
|------|------|------|
| **水平（广度）** | 覆盖所有职责范围 | 每个 Agent 500-800 行 |
| **垂直（深度）** | 优先级体系（P0-P3） | P0=绝对红线, P1=高优先级, P2=中, P3=低 |
| **时间（学习）** | 循环反馈融合 | 每轮注入上轮评分 + 违规 + 重点方向 |

---

## 支持的研究类型与 Agent 映射

| 研究类型 | 必执行 Agent | 可选 |
|---------|------------|------|
| 定性研究 (qualitative) | ConstraintInjector, Polisher, Visualizer, Methodologist(q), LiteratureCurator, Expert, WordCountController, Narrator, Orchestrator, Reviewer, AdversarialCritic, WordFormatValidator | - |
| 定量研究 (quantitative) | 同上（Methodologist 启用定量模式） | 如需编码验证，加 LiteratureCurator |
| 计算社会科学 (computational) | 同上（Methodologist 启用计算模式） | - |
| 混合方法 (mixed) | 全部 13 Agent | - |
| 访谈报告 (interview) | ConstraintInjector, Polisher, Methodologist, Expert, WordCountController, Narrator, Orchestrator, Reviewer, AdversarialCritic, WordFormatValidator | Visualizer |
| 理论论文 (theoretical) | ConstraintInjector, Expert, LiteratureCurator, Narrator, Orchestrator, Reviewer, AdversarialCritic, WordFormatValidator | Polisher, Visualizer, Methodologist |

---

## 强制执行协议 (MANDATORY EXECUTION PROTOCOL)

> ⚠️ **本章节为强制约束，AI 助手必须严格遵守，违反任何一条即视为 pipeline 执行失败。**

### 执行主体声明

**AI 助手是本 pipeline 的唯一执行主体**。AI 助手必须按本 SKILL.md 定义的工作流逐轮执行，不得跳过、合并或提前退出。Python 代码（`pipeline/loop_controller.py`）为程序化骨架，节点函数为占位符不调用 LLM，实际 AI 工作（润色、评审、修改、评分）全部由 AI 助手完成。

### 最小/最大轮次约束

| 约束 | 值 | 说明 |
|------|-----|------|
| `min_rounds` | 3 | 必须执行至少 3 轮循环，即使第 1 轮评分已达 90 分阈值，也必须继续执行至第 3 轮 |
| `max_rounds` | 7 | 最多执行 7 轮，第 7 轮后无论评分如何必须输出终稿 |
| `pass_threshold` | 90 | 9 维度评分通过阈值 |

### 轮次回执强制

**每轮结束必须输出"轮次回执"**（模板见下文），回执缺失即视为该轮未执行。轮次回执必须包含：
- 轮次号（第 N / 7 轮）
- 9 维度逐项评分（含 2a/2b/2c 子维度）及本轮总分
- 本轮执行的 Agent 清单（含修改摘要）
- 风格守卫结果
- 下轮决策（继续/退出）及决策依据

### 执行回执强制

**Pipeline 终止时必须输出"Pipeline 执行回执"**（模板见下文），回执缺失即视为 pipeline 未完成。执行回执必须包含：
- 总轮次、最终评分、质量达标状态
- 各轮评分轨迹
- 退出原因（四选一）
- 反捷径守卫自检（4 项全 ✅）
- 未解决问题清单
- 完整优化后的论文

### 退出条件

仅当以下条件之一满足时方可退出 pipeline：

1. **正常通过**：已执行 ≥ 3 轮（`min_rounds`）且 9 维度评分 ≥ 90（`pass_threshold`）
2. **最大轮次**：已执行 7 轮（`max_rounds`），无论评分如何
3. **人工介入**：连续 3 轮总分提升 < 3 分（`stagnation_threshold`），需在回执中明确标注"触发人工介入"
4. **指令偏离**：检测到用户初始指令严重偏离，立即终止并回滚至上一合规版本

**禁止行为**：
- ❌ 第 1 轮后直接输出终稿（即使评分 ≥ 90）
- ❌ 跳过中间轮次（如从第 1 轮直接跳到第 7 轮）
- ❌ 合并多轮工作为一轮而不分轮输出回执
- ❌ 省略轮次回执或执行回执

### 反捷径守卫 (Anti-Shortcut Guard)

| 禁止行为 | 检测信号 | 纠正动作 |
|---------|---------|---------|
| 跳过 Agent（未执行 OpinionRouter 分发的 Agent） | 轮次回执中缺失该 Agent 的修改摘要 | 回退执行被跳过的 Agent |
| 伪造评分（评分与论文实际质量明显不符） | 评分轨迹异常（如第 1 轮 90 分但论文明显未达顶刊水平） | 重新按 `agents/reviewer.md` 9 维度逐项评估 |
| 提前退出（未达 `min_rounds` 或未满足退出条件） | 执行回执显示总轮次 < 3 或退出条件未满足 | 继续执行至 `min_rounds` |
| 合并轮次（一轮内完成多轮工作却不分轮输出） | 轮次回执数量 < `min_rounds` | 拆分为多轮并分别输出回执 |
| 省略回执（未输出轮次回执或执行回执） | 回执缺失 | 补输出回执 |
| 复制论文占位（直接复制初稿作为修改输出） | 修改摘要为空或与初稿完全相同 | 按对应 `agents/*.md` 实际修改 |

### 轮次回执模板（强制）

每轮结束必须按此模板输出：

```
═══════════════════════════════════════
  第 N 轮回执 (Round N Receipt)
═══════════════════════════════════════
【轮次】第 N / 7 轮
【9维度评分】
1. 标题冲击力：X/10
2. 文笔与文风：X/15（2a节奏=X/5, 2b多样性=X/5, 2c声音=X/5）
3. 学术深度：X/15
4. 学理性：X/15
5. 图表美观度与专业性：X/10
6. 格式标准性：X/10
7. 严谨性：X/10
8. 专业性：X/10
9. 创新性与启发价值：X/5
本轮总分：XX/100（较上轮 +X / -X）
【GAN对抗评分】（★v7.0新增）
G评分：XX/100（Reviewer原始评分）
D评分：XX/100（AdversarialCritic挑刺评分）
融合评分：XX/100（α=0.X，最终决策依据）
对抗信号：XX（G-D差值）
过度自信惩罚：-X分 / 无

【本轮执行 Agent】
✅ ConstraintInjector（已执行）
✅ Polisher（已执行，修改摘要：...）
✅ Visualizer（已执行，修改摘要：...）
✅ Methodologist（已执行，修改摘要：...）
✅ LiteratureCurator（已执行，修改摘要：...）
✅ Expert（已执行，修改摘要：...）
✅ WordCountController（已执行，修改摘要：...）
✅ Narrator（已执行，修改摘要：...）
✅ Orchestrator（已执行，修改摘要：...）
✅ Reviewer（已执行，9维度评分）
✅ AdversarialCritic（已执行，9维度挑刺评分）

【本轮修改摘要】
- 标题：...
- 摘要：...
- 引言：...
- 综述：...
- 发现：...
- 结语：...
- 图表：...
- 语言润色：...
- 叙事连贯：...

【风格守卫结果】违规 X 处（已修复 / 待下轮修复）

【下轮决策】继续 / 退出
【决策依据】评分 < 90 / 已达 min_rounds 且评分 ≥ 90 / 已达 max_rounds / 触发人工介入
═══════════════════════════════════════
```

### Pipeline 执行回执模板（强制）

Pipeline 终止时必须按此模板输出：

```
═══════════════════════════════════════
  Pipeline 执行回执 (Execution Receipt)
═══════════════════════════════════════
【总轮次】N 轮（最小 3 / 最大 7）
【最终评分】XX / 100（阈值：90）
【GAN评分轨迹】
第1轮：G=XX, D=XX, 融合=XX, 信号=XX
第2轮：G=XX, D=XX, 融合=XX, 信号=XX
...【质量达标】✅ 是 / ❌ 否

【各轮评分轨迹】
第 1 轮：XX 分
第 2 轮：XX 分（+X）
第 3 轮：XX 分（+X）
...

【退出原因】
□ 已达 min_rounds 且评分 ≥ 90（正常通过）
□ 已达 max_rounds（最大轮次上限）
□ 连续 3 轮提升 < 3 分（人工介入）
□ 指令严重偏离（回滚终止）

【反捷径守卫自检】
✅ 所有轮次回执已输出（N/N）
✅ 所有 Agent 已执行（无跳过）
✅ 评分非硬编码（已按 9 维度逐项评估）
✅ 修改非占位（每轮有实际修改摘要）

【未解决问题清单】
1. ...
2. ...

【最终输出】
[完整优化后的论文]
═══════════════════════════════════════
```

---

## 使用方法

### 执行路径

本 skill 提供两条执行路径：

**路径 A（推荐）：AI 助手手动模拟执行**
- AI 助手按上文"强制执行协议"逐轮执行 pipeline
- 每轮按 `agents/reviewer.md` 进行 9 维度评审
- OpinionRouter 分发意见至对应 Agent，AI 助手按各 `agents/*.md` 提示词实际修改论文
- 每轮输出"轮次回执"，Pipeline 终止输出"执行回执"
- 此路径不依赖 Python runtime，是 Trae IDE 上下文中的主要执行方式

**路径 B（可选）：调用 Python `run_pipeline()`**
- 调用 `pipeline/loop_controller.py` 的 `run_pipeline()` 函数
- ⚠️ **注意**：当前 Python 节点函数为占位骨架（不调用 LLM），评分字段返回 `None`
- 若需通过 Python 运行产生实际效果，需先为各节点函数接入 LLM API
- Python 代码作为程序化参考实现，维护状态流转结构

### 启动 Pipeline
1. 确保论文初稿文件存在
2. 确保编码数据文件存在（如适用）
3. 调用本 Skill，指定论文文件路径
4. AI 助手按强制执行协议逐轮执行（路径 A），或调用 Python `run_pipeline()`（路径 B，需先接入 LLM）
5. Pipeline 自动执行第 1 轮循环，并按强制执行协议继续至满足退出条件

### 配置参数
- `max_rounds`: 最大循环次数（默认7）
- `pass_threshold`: 通过分数阈值（默认90）
- `style_enforcement`: 是否启用风格约束强制（默认true，v6.0新增）
- `word_count_enforcement`: 字数执行模式（"strict"/"compress"/"warn"，默认"strict"，v6.3重构）
- `user_target_words`: 用户指定的全文字数目标（默认15000，v6.3新增）
- `word_count_tolerance`: 字数容忍度（默认0.1即±10%，v6.3新增）
- `word_validation_enabled`: 是否启用Word格式验证（默认true，v6.0新增）
- `gan_enabled`: 是否启用GAN对抗评分（默认true，v7.0新增）
- `trust_weight_alpha`: G评分信任权重（默认0.4，v7.0新增）
- `adversarial_signal_threshold`: 对抗信号阈值（默认10.0，v7.0新增）
- `output_format`: 输出格式（"word"/"markdown"，默认"word"）
- `journal_style`: 目标期刊格式
- `research_type`: 研究类型（"qualitative"/"quantitative"/"computational"/"mixed"/"interview_report"/"theoretical"）

### 执行 v6.2 Pipeline（路径 B — 需先接入 LLM）

> ⚠️ **注意**：以下 Python 代码为路径 B 的示例。当前 `loop_controller.py` 的节点函数为占位骨架（不调用 LLM），评分字段返回 `None`。若需通过 Python 运行产生实际效果，需先为各节点函数接入 LLM API。推荐使用路径 A（AI 助手手动模拟）。

```python
from pipeline.loop_controller import create_pipeline, PipelineConfig

config = PipelineConfig(
    max_rounds=7, pass_threshold=90, journal_style="xwycbyj",
    research_type="qualitative", style_enforcement=True,
    word_validation_enabled=True,
    user_target_words=15000,  # v6.3: 用户指定全文字数目标
    word_count_tolerance=0.1,  # v6.3: 字数容忍度±10%
    word_count_enforcement="strict",  # v6.3: strict=硬截断, compress=仅压缩, warn=仅警告
    gan_enabled=True,  # v7.0: 启用GAN对抗评分
    trust_weight_alpha=0.4,  # v7.0: G评分信任权重
    adversarial_signal_threshold=10.0,  # v7.0: 对抗信号阈值
)
app = create_pipeline(config)
result = app.invoke({"paper_content": paper_text})
```

---

## 支持的文件结构

```
cyclical-paper-generation/
├── SKILL.md                          # 主Skill定义（v7.3，本文件）
├── agents/
│   ├── architect.md                  # Agent 0：论文架构师（v6.1，阶段五研究类型差异化）
│   ├── polisher.md                   # Agent 1：润色者（v6.1，声音驱动重构）
│   ├── visualizer.md                 # Agent 2：可视化者（v6.0）
│   ├── methodologist.md              # Agent 3：方法论专家（v6.0 新增）
│   ├── literature_curator.md         # Agent 4：文献策展人（v6.0 新增）
│   ├── expert.md                     # Agent 5：内容专家（v6.1，研究类型内容差异+范本引用）
│   ├── word_count_controller.md      # Agent 6：字数控制器（v6.0 新增）
│   ├── narrator.md                   # Agent 7：叙事连贯性主编（v6.1，声音锚点+改写示例+朗读测试）
│   ├── orchestrator.md               # Agent 8：编排者（v6.0 新增）
│   ├── reviewer.md                   # Agent 9：审稿人（v6.1，维度2细化2a/2b/2c）
│   ├── adversarial_critic.md          # Agent 9.5：对抗挑刺者（v7.0新增，GAN D侧）
│   ├── word_format_validator.md      # Agent 10：Word格式验证（v6.0 新增）
│   └── ...（style_guard 为程序化节点，无 .md 文件）
├── pipeline/
│   ├── style_constraints.py          # 中央风格约束定义（v6.1，新增范本/节奏/正向模式）
│   ├── shared_learning.py            # 共享学习档案管理（v6.0 新增）
│   ├── word_validation.py            # Word文档质量验证模块（v7.3，脚注内容完整性+编号格式验证）
│   ├── loop_controller.py            # LangGraph循环控制器（v7.0，新增GAN对抗评分节点）
│   ├── state_manager.py              # 状态管理器（v6.0，新增约束/学习/验证字段）
│   ├── gan_scorer.py                  # v7.0新增：GAN评分融合模块
│   ├── config.py                     # 配置文件（v7.0，13 Agent+研究类型映射+Word配置+GAN参数）
│   ├── incremental_revision.md       # 增量修改机制
│   └── opinion_router.md             # 意见自动分发规则
├── journal_formats/
│   ├── xwycbyj.md                    # 《新闻与传播研究》格式规范
│   ├── gjxwj.md                      # 《国际新闻界》格式规范
│   ├── xwdx.md                       # 《新闻大学》格式规范
│   └── shxyj.md                      # 《社会学研究》格式规范
├── knowledge_base/
│   ├── style_exemplars.md            # 风格范本库（v6.1 新增，声音锚点）
│   ├── human_language_features.md    # 人类语言特征详尽总结（★v7.2 新增，人类语言合规基准）
│   ├── communication_theories.md     # 新闻传播学理论库（由 ConstraintInjector 动态加载）
│   ├── sociology_theories.md         # 社会学理论库（同上）
│   └── methodology_standards.md      # 方法论标准库（由 Methodologist 加载）
├── templates/
│   ├── paper_template.md             # 通用论文模板
│   └── word_template.py              # Word生成模板（v7.3，真实OOXML脚注+脚注内容验证+字体修复）
└── voice_library/                    # ★v8.0新增：学者声音锚点库（36个文件，v7.5扩充至人文社科四学科）
    ├── scholar_huangyangkun.md       # 黄阳坤：可见性理论+算法审计
    ├── scholar_zhoubaohua.md         # 周葆华：多模态计算+舆论特征
    ├── scholar_liuzhanwei.md         # 刘战伟：田野叙事+劳动控制
    ├── scholar_leiziwen.md           # 雷紫雯：知识中介+角色命名
    ├── scholar_dengshaogen.md        # 邓绍根：年度综述+历史溯源
    ├── scholar_tongbing.md           # 童兵：理论贡献分类
    ├── scholar_zhengbaowei.md        # 郑保卫：百年叙事+实践基础
    ├── scholar_chenlidan.md          # 陈力丹：概念考辨+语源追溯
    ├── scholar_zhouyong.md           # 周勇：元问题+对话沟通
    ├── scholar_yuweihua.md           # 余建华：跨平台传播
    ├── scholar_buyumei.md            # 卜玉梅：网络民族志
    ├── scholar_zhitingrong.md        # 支庭荣：嵌入性视角
    ├── scholar_shenzhengfu.md        # 沈正赋：时空脉络
    ├── scholar_yangbaojun.md         # 杨保军：实践转向+真实观
    ├── scholar_lixingbo.md           # 李兴博：理论阐释
    │   # ▼v7.5新增：人文社科四学科学者（8位）
    ├── scholar_yuguoming.md          # 喻国明：判断式宣言开篇+技术赋权
    ├── scholar_penglan.md            # 彭兰：主体性追问+多重互动分析
    ├── scholar_zhouyuqiong.md        # 周裕琼：生命周期视角+代际比较
    ├── scholar_maguoging.md          # 麻国庆：跨体系社会+文明互动
    ├── scholar_hexuefeng.md          # 贺雪峰：村庄本位+经验质感
    ├── scholar_haoshiyuan.md         # 郝时远：概念考古+族性溯源
    ├── scholar_qujingdong.md         # 渠敬东：制度逻辑+技术治理
    ├── scholar_zhaixuewei.md         # 翟学伟：本土概念+关系向度
    ├── computational_seed.md         # 计算社会科学种子
    ├── computational_zhou_seed.md    # 计算传播（周）种子
    ├── qualitative_seed.md           # 质化研究种子
    ├── quantitative_seed.md          # 量化研究种子
    ├── mixed_seed.md                 # 混合方法种子
    ├── interview_report_seed.md      # 访谈报告种子
    ├── digital_sociology_seed.md     # 数字社会学种子
    ├── theoretical_seed.md           # 理论论文种子
    ├── theoretical_deng_seed.md      # 马克思主义新闻观种子
    │   # ▼v7.5新增：4个新研究类型种子
    ├── ethnic_policy_seed.md         # 民族政策分析种子
    ├── ethnographic_seed.md          # 民族志田野种子
    ├── sociological_theory_seed.md   # 社会学理论种子
    └── concept_genealogy_seed.md     # 概念谱系学种子
```

---

## 版本与维护

- **当前版本**: v7.5.0
- **最后更新**: 2026-06-30
- **维护者**: 用户项目
- **许可证**: 项目内部使用
- **进化标记**: 本Skill支持持续进化，每次重大更新需更新版本号和evolution_notes

### 主要变更历史

**v7.5 (2026-06-30) 人文社科四学科声音库扩充——深度学习传播学/民族学/人类学/社会学顶刊论文**

**核心变更**：
1. **声音库大规模扩充**：`voice_library/` 从24个文件扩充至36个文件（+50%）
   - 新增8位学者声音锚点：喻国明（传播学·判断式宣言开篇）、彭兰（传播学·主体性追问）、周裕琼（传播学·生命周期代际比较）、麻国庆（民族学·跨体系社会）、贺雪峰（社会学·村庄本位经验质感）、郝时远（民族学·概念考古族性溯源）、渠敬东（社会学·制度逻辑技术治理）、翟学伟（社会学·本土概念关系向度）
   - 新增4个研究类型种子文件：ethnic_policy_seed.md、ethnographic_seed.md、sociological_theory_seed.md、concept_genealogy_seed.md
   - 双库同步：`cyclical-paper-generation/voice_library/` 与 `cyclical-paper-review/voice_library/` 36个文件完全一致（SHA256验证通过）
2. **人类语言合规基准升级至v3.0**：`knowledge_base/human_language_features.md`
   - 新增第十三章（民族学/人类学文风特征）、第十四章（社会学文风特征）、第十五章（新学者声音指纹扩充8位）
   - 论文覆盖量从195篇扩展至1399篇（+618%），学科从5个扩展至7个
3. **风格范本库升级至v4.0**：`knowledge_base/style_exemplars.md`
   - 新增4位学者完整范本：渠敬东（政治经济学制度分析）、翟学伟（本土概念建构）、麻国庆（田野多层次分析）、喻国明（判断式宣言开篇）
   - 每位学者含完整范本段落+5组before/after改写示例+5条句式模板+研究类型映射
4. **VOICE_SAMPLES升级至v7.1**：`pipeline/style_constraints.py`
   - 新增8组声音锚点：theoretical_ethnic、qualitative_rural、theoretical_concept、sociological_theory、chuanboxue_peng、chuanboxue_yu、quantitative_generation（周裕琼·代际比较）、theoretical_indigenous（翟学伟·本土概念建构）
5. **8个Agent学者映射表扩充**：从18行扩展至26行（+44%），覆盖 generation（architect/narrator/polisher）与 review（findings_reviser/introduction_reviser/literature_review_reviser/full_text_polisher/abstract_reviser）
- 数据来源：1204篇人文社科顶刊论文（传播学/民族学/人类学/社会学，4学科×10期刊×~30篇）
- 核心策略：**从15位学者声音扩展到23位，覆盖7大学科全研究类型，实现人文社科全领域风格适配**

**v7.4 (2026-06-23) 内参报告按需生成模块——新增NeicanWriter Agent与内参格式验证**

**核心变更**：
1. **新增NeicanWriter Agent**：`agents/neican_writer.md`——内参撰写者，仅在用户明确请求时触发
   - 核心能力一：论文→内参转化（剥离学术外壳→重构骨架→填充血肉→打磨文风）
   - 核心能力二：内参直接生成（从研究数据/发现直接生成内参报告）
   - 核心能力三：内参格式规范（5种标题范式、单段式/双段式开篇、3-5板块结构、对策刻度化）
   - 核心能力四：内参文风内化（虎气猴气、复杂问题简单化、静中见动异中见同）
   - 转化诊断清单（6步）+ 质量自检清单（32项）

2. **新增内参知识库**：`knowledge_base/neican_standards.md`——基于5篇真实内参报告样本提取的9章节详尽规范
   - 第一章：内参报告基础规范（二十条铁律+检验标准+样本实证）
   - 第二章：标题范式库（5种范式+真实样本示例）
   - 第三章：开篇范式库（单段式+双段式+真实样本示例）
   - 第四章：正文结构范式（3-5板块+层级编号+现状→问题→建议循环+关系处理板块）
   - 第五章：对策建议刻度库（15组抽象vs具体对照表+责任主体规范）
   - 第六章：文风特征库（虎气判断句15例+猴气比喻句10例+反差句10例）
   - 第七章：论文→内参转化对照表（10组转化示例+剥离学术外壳操作清单）
   - 第八章：结尾与署名规范（不写总结段+统一署名格式）
   - 第九章：字数指导（短报告/标准报告/长报告/综合规划报告）

3. **新增内参配置**：`pipeline/config.py`
   - 新增`NEICAN_CONFIG`配置字典（字数范围/标题范式/板块数量/层级编号/署名格式）
   - `PipelineConfig`新增`output_mode`字段（默认`paper`，支持`neican`/`both`）
   - `AGENT_DEFINITIONS`新增`neican_writer`条目（enabled默认False）
   - `OPINION_ROUTING_RULES`新增10条内参相关路由

4. **新增内参验证**：`pipeline/word_validation.py`
   - 新增`validate_neican_title`——验证标题范式（5种范式匹配）
   - 新增`validate_neican_opening`——验证开篇范式（单段式/双段式）
   - 新增`validate_neican_hierarchy`——验证层级编号
   - 新增`validate_neican_countermeasure`——验证对策刻度（检测抽象表述、验证责任主体）
   - 新增`validate_neican_ending`——验证结尾规范（无总结段）
   - 新增`validate_neican_signature`——验证署名格式
   - 新增`validate_neican_academic_residue`——检测学术残留
   - 新增`run_neican_validation`——整合所有内参验证项

5. **新增内参Word模板**：`templates/word_template.py`
   - 新增`add_neican_title`——内参标题（居中、黑体、16pt）
   - 新增`add_neican_section`——内参板块（三级层级编号）
   - 新增`add_neican_body`——内参正文段落
   - 新增`add_neican_signature`——内参署名
   - 新增`generate_neican_document`——完整内参文档生成

6. **更新循环控制器**：`pipeline/loop_controller.py`
   - 新增`neican_writer_node`——NeicanWriter节点函数
   - 新增内参输出分支（output_mode=neican/both时触发）
   - 新增内参格式验证回滚触发（neican_format_invalid）

**涉及文件**：neican_writer.md（新增）、neican_standards.md（新增）、config.py、word_validation.py、word_template.py、loop_controller.py、SKILL.md（共7个文件）

**核心约束**：内参报告模块仅在用户明确请求时触发（output_mode默认为paper），不得在常规论文流程中自动调用，不破坏论文结构。

**v7.3 (2026-06-23) docx脚注强制合规**

**核心变更**：
1. **脚注生成机制修复**：确保输出的docx文档包含真实OOXML脚注（`w:footnoteReference`），禁止使用手动上标`[1]`等伪脚注方式
   - `templates/word_template.py`：修复`generate_sample_document()`使用真实OOXML脚注替代手动上标；废弃`add_footnote_marker()`（添加DeprecationWarning）；修复`enforce_all_fonts()`增加对footnotes.xml中run的字体检查和表格中run的字体检查；新增DOI字段到`add_reference_english_journal()`
   - 新增8个脚注验证和安全生成函数：`detect_footnote_type()`、`extract_footnote_fields()`、`validate_footnote_content()`、`add_footnote_with_validation()`、`get_all_footnote_texts()`、`validate_all_footnotes()`、`format_footnote_text()`、`add_footnote_from_reference()`

2. **脚注验证增强**：新增脚注内容完整性验证和编号格式验证
   - `pipeline/word_validation.py`：新增`validate_footnote_content_completeness()`（检查必填字段、占位符、乱码）、`validate_footnote_number_format()`（检查上标、字号、字体）、`_extract_footnote_texts()`辅助函数；增强`validate_footnote_refs()`匹配阈值从≥2提高到≥3并增加标题关键词匹配；更新`run_full_validation()`和`format_report()`包含新检查项

3. **回滚机制Bug修复**：修复`check_and_rollback()`中脚注检测失效问题
   - `pipeline/loop_controller.py`：修复`detect_manual_footnotes()`传入Document对象而非字符串路径；修复返回值字段名错误（`manual_footnotes_count`不存在，实际返回`List[Dict]`）；新增脚注内容完整性和无真实脚注的回滚触发；增强`word_format_validator_node()`记录详细脚注问题

4. **Agent脚注生成强制规范**：所有生成型Agent新增脚注生成强制要求
   - `agents/architect.md`：新增"脚注生成强制规范"章节（框架预留、内容完整性、禁止事项、脚注规划）
   - `agents/literature_curator.md`：新增"脚注生成强制规范"章节（内容完整性验证清单、格式规范、双向核验、禁止事项）
   - `agents/expert.md`：新增"脚注生成强制规范"章节（引用与脚注对应关系、完整性检查、禁止事项）

**涉及文件**：word_template.py、word_validation.py、loop_controller.py、architect.md、literature_curator.md、expert.md、SKILL.md（共7个文件）

**v7.2 (2026-06-23) 人类语言合规强制检查**

**核心变更**：
1. **人类语言特征总结文档**：基于34篇真实CSSCI论文（传播学8篇、经济学8篇、法学6篇、民族学/历史学6篇、非遗/文化研究6篇）的深度分析，提取人类论文的语言特征
   - `knowledge_base/human_language_features.md`：新增《人类论文语言特征详尽总结 v1.0》，包含8章节（跨学科共性特征、学科差异化特征、"人味"特征清单、AI典型问题、话语表述逻辑、强制合规检查标准、跨学科速查表、版本维护）

2. **强制人类语言合规检查机制**：新增HumanLanguageGuard（人类语言守卫）程序化节点，执行四层合规检查
   - 微观检查：句长方差≥10.0、段落开头多样性≥5种、AI高频词检测、短句收束、标点功能
   - 中观检查：摘要结构、引言风格、文献综述对话性、结论批判性关怀
   - 宏观检查：论证结构、过渡方式、作者声音、隐喻体系化、概念命名
   - 人味检查：≥3项人类写作特有特征
   - 未通过的论文不得输出，触发修复指令注入循环

3. **Agent强制参照要求**：所有Agent在生成/润色时必须参照human_language_features.md
   - `agents/architect.md`：新增"人类语言合规参照"章节
   - `agents/polisher.md`：新增"人类语言合规强制检查"章节
   - `agents/narrator.md`：新增"人类语言合规检查"章节
   - `pipeline/style_constraints.py`：新增HUMAN_LANGUAGE_THRESHOLDS配置

**涉及文件**：human_language_features.md、SKILL.md、architect.md、polisher.md、narrator.md、style_constraints.py（共6个文件）

**v7.1 (2026-06-23) GAN轮次调整与论文自然化优化**

**核心变更**：
1. **轮次阈值调整**：`max_rounds` 从5调整为7，因GAN对抗评分加入后需要更多轮次达到95分阈值
   - `pipeline/config.py`：`max_rounds` 默认值 5→7
   - `pipeline/loop_controller.py`：所有轮次引用更新
   - `SKILL.md`：工作流图、强制执行协议、回执模板、反捷径守卫中的轮次引用全部更新

2. **摘要自然化优化**：基于真实CSSCI论文（黄阳坤/周葆华/刘战伟/雷紫雯）摘要特征提取
   - `knowledge_base/style_exemplars.md`：新增"摘要范本库"章节，含5大结构特征、25条高质量句式模板、避免"口水话"和"学术机械语言"的策略、研究发现呈现方式
   - `agents/architect.md`：新增"摘要自然化要求"章节，含5大结构特征强制要求、正面范本、禁止清单、生成检查清单

3. **断裂式/硬转折修复**：基于真实CSSCI论文过渡模式提取
   - `pipeline/style_constraints.py`：新增 `TRANSITION_EXEMPLARS`（56条真实示例，按5种类型分类）、`HARD_TRANSITION_ANTIPATTERNS`（5条反面案例）、`TRANSITION_QUALITY_STANDARDS`（5大过渡质量标准）
   - `agents/polisher.md`：新增"断裂修复专项指令"章节，含5种过渡方式真实示例和断裂修复策略
   - `agents/narrator.md`：新增"硬转折检测清单"章节，含段落间逻辑衔接检查项、机械连接词检测、硬转折识别、修复指引

**涉及文件**：config.py、loop_controller.py、style_constraints.py、style_exemplars.md、architect.md、polisher.md、narrator.md、SKILL.md（共8个文件）

**v7.0 (2026-06-22) GAN对抗评分——消除AI自评幻觉**
- 核心问题：AI给自己生成的论文打分容易产生"自我肯定偏差"，倾向于给出偏高的评价
- 新增AdversarialCritic Agent（agents/adversarial_critic.md）：GAN架构中的D侧，扮演"魔鬼代言人"，侧重AI生成论文的典型缺陷（幻觉、模式化、伪创新、表面化论证）
- 新增gan_scorer.py（pipeline/gan_scorer.py）：G评分与D评分的加权融合模块，包含对抗信号检测、动态信任权重、过度自信惩罚
- 修改reviewer.md：添加G侧角色声明、自信度自评字段、GAN融合评分规则
- 修改loop_controller.py：新增adversarial_critic_node和gan_score_fusion_node，修改图结构（reviewer → adversarial_critic → gan_score_fusion → 条件路由）
- 修改config.py：新增gan_enabled/trust_weight_alpha/adversarial_signal_threshold参数
- 融合公式：`fused_score = α × G_score + (1 - α) × D_score`，α默认0.4（偏向D方）
- 核心策略：**一边在生产，另一边在挑刺**——G负责建设性评审，D负责无情挑刺，融合评分校正AI自评幻觉
**v6.4 (2026-06-22) 基于真实CSSCI论文语言特征的全面完善**
- 核心问题：现有规则偏重"禁止模式"，缺乏"正面引导"；句式模板数量有限且格式化；过渡方式仅停留在检测层面；论证方式约束几乎空白；研究类型覆盖不均衡
- 深度阅读9篇真实CSSCI论文（张洪忠、刘战伟、黄阳坤、俞雅芸、周葆华、雷紫雯），提取8个维度的语言特征
- `pipeline/style_constraints.py` 新增 `ARGUMENTATION_VOICE_PATTERNS`（6种论证语态）、`TRANSITION_QUALITY_RULES`（3种高质量过渡正面标准）、`ORAL_ACADEMIC_TONE`（5项学术口语感特征）、`ARGUMENTATION_DENSITY`（论证密度指标）、`STYLE_DEGRADATION_SIGNALS`（风格退化闭环防控）；扩充 `RECOMMENDED_PATTERNS` 至每类15-20条
- `knowledge_base/style_exemplars.md` 计算社会科学范本替换为黄阳坤真实论文摘录；为量化/混合/访谈/理论四种研究类型补充风格特征摘要表和15条句式模板；新增微观论证流动范本、人味特征章节分布指南和堆砌预警规则、10组渐进式改写示例
- `agents/polisher.md` 为4种研究类型补充声音锚点；增加改写程度控制指南；段落内部结构模板从刚性5层改为弹性组合；定义8个核心能力的优先级和交互逻辑
- `agents/narrator.md` 增加段落级叙事推进检查；增加叙事声音与论证内容的协调指导；为6种研究类型补充守护检查清单
- 核心策略：**从"禁止模式"转向"正面引导"，让Agent知道"应该写成什么样"**

**v6.3 (2026-06-22) 强制字数控制——修复循环轮次越多字数越膨胀问题**
- 核心问题：随着滚动轮次增加，各Agent修改论文时倾向于增加内容而非精简，导致论文字数逐轮膨胀
- 新增三层防线机制：防线1事前约束（ConstraintInjector向每个Agent注入字数预算硬约束）、防线2事后压缩（WordCountController执行P1-P5五级压缩策略）、防线3硬截断兜底（从末尾删除段落直到字数达标）
- `pipeline/style_constraints.py` 新增 `compute_section_budgets()` 动态字数预算计算（按user_target_words/15000等比缩放）、`build_word_budget_constraint()` 字数硬约束文本生成
- `pipeline/config.py` 新增 `user_target_words`/`word_count_tolerance`/`word_count_enforcement` 参数，新增 `get_effective_hard_limit()`/`get_section_budgets()` 方法
- `pipeline/loop_controller.py` 重构 `constraint_injector_node`（注入字数预算硬约束）、重构 `word_count_controller_node`（三层防线）、新增 `_hard_truncate_paper()` 硬截断函数、PipelineState新增字数控制字段
- `agents/word_count_controller.md` 从v6.0升级到v6.3，新增三层防线机制说明、动态字数目标、缩放示例
- 核心策略：**用户提出多少字，无论滚动多少次一定要只限定在这个字数**

**v6.2 (2026-06-20) 强制执行协议——修复 pipeline 不严格执行问题**
- 新增 `MANDATORY EXECUTION PROTOCOL` 章节：明确 AI 助手为执行主体、`min_rounds=3`/`max_rounds=5` 约束、轮次回执强制、执行回执强制、4 类退出条件
- 新增 `Anti-Shortcut Guard` 反捷径守卫：6 项禁止行为（跳过 Agent/伪造评分/提前退出/合并轮次/省略回执/复制占位）及检测信号/纠正动作
- 新增"轮次回执模板"和"Pipeline 执行回执模板"两个强制模板（9 维度按 generation 维度表）
- 改写"使用方法"章节：明确路径 A（AI 助手手动模拟，推荐）和路径 B（Python run_pipeline，需 LLM 接入），声明 Python 代码为占位骨架
- `pipeline/loop_controller.py` 移除 `reviewer_node` 硬编码评分（`review_score = 85`），改为 `review_score = None`，所有 Agent 节点 docstring 注明占位性质
- 核心策略：**强制执行协议**——以回执驱动多轮循环，以反捷径守卫禁止走捷径，彻底修复"运行一次就输出"问题

**v6.1 (2026-06-19) 风格系统优化：声音优先、规则兜底**
- 新增风格范本库 `knowledge_base/style_exemplars.md`（周葆华计算社会科学风格 + 刘战伟质化研究风格 + 20组改写示例 + 30种段落开头）
- `style_constraints.py` 新增 RECOMMENDED_PATTERNS（正向句式模式）、VOICE_SAMPLES（声音锚点）、RHYTHM_METRICS（节奏检测指标）、check_rhythm/check_paragraph_opening_diversity/check_mechanical_patterns 检测函数
- Polisher 从规则驱动（849行）重构为声音驱动（~462行），新增声音锚点、改写原则、节奏与多样性、研究类型适配
- Narrator 扩展声音锚点、8个改写示例、朗读测试操作规范、研究类型声音差异（153行→366行）
- Expert/Architect/Reviewer 增量修改：引用范本库、研究类型差异化、维度2子维度细化（2a节奏感/2b多样性/2c声音一致性）
- ConstraintInjector 注入 VOICE_SAMPLES 和 RHYTHM_METRICS，StyleValidator 记录节奏诊断
- 核心策略：**声音优先、规则兜底**——先内化目标文风，再遵守禁止规则

**v6.0 (2026-06-18) 12 Agent 架构重构**
- 5 Agent → 12 Agent、新增 ConstraintInjector/StyleGuard/WordFormatValidator、新增中央风格约束单一真实来源、新增共享学习档案、新增 Word 模板字体安全修复和 OOXML 真实脚注、Agent System Prompt 三维结构优化

---

## 数据库学者文风更新流程（v5.1 新增）

当数据库新增学者论文或需补充学者文风范本时，按以下流程操作：

### 步骤1：提取学者文风特征

```bash
cd c:\Users\13067\.trae-cn\skills\cyclical-paper-generation\knowledge_base
python update_style_exemplars.py --scholar 周葆华
```

或输出到文件：

```bash
python update_style_exemplars.py --scholar 邓绍根 --output deng_voice.md
```

### 步骤2：人工审核提取结果

参考 `scholar_voice_extractor.md` 中的"人工审核要点"，审核：
- 摘录是否为原文
- 摘录是否具有文风代表性
- 摘录是否含违规表达
- VOICE_SAMPLES 子键名是否合规

### 步骤3：合并至 style_exemplars.md

将审核通过的摘录合并至 `style_exemplars.md` 对应学者章节（如"周葆华文风范本""邓绍根文风范本"）。

### 步骤4：合并至 VOICE_SAMPLES

将审核通过的摘录合并至 `pipeline/style_constraints.py` 的 `VOICE_SAMPLES` 字典，子键名遵循 `<research_type>_<scholar_pinyin>` 规范。

### 步骤5：验证

运行 `python -c "from pipeline.style_constraints import VOICE_SAMPLES; print(list(VOICE_SAMPLES.keys()))"` 确认子键已写入。

### 触发条件

参考 `scholar_voice_extractor.md` 的"更新触发条件"小节。
