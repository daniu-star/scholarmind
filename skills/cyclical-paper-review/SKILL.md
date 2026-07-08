---
name: "cyclical-paper-review"
description: "循环式论文审稿优化Pipeline：7 Agent协作的3-7轮循环审稿与优化，基于9维度量化评分（阈值95）驱动论文至顶刊发表水平。融合waishenyijian专业评审维度与cyclical-paper-generation循环约束机制，新增指令守卫防遗忘、语言自然度检测、逻辑缜密度量化。支持6种研究类型和4种CSSCI期刊格式。v1.1核心优化：声音优先、规则兜底。v1.2核心优化：强制执行协议+强制字数控制。v1.3核心优化：基于真实CSSCI论文语言特征的全面完善——新增正面引导章节、语义衔接质量标准、论证方式约束、4种研究类型范本和句式模板、模仿质量评估标准、句式组合流动范本、风格退化预警规则；FullTextPolisher改为迭代流程、人味特征自适应选择、4章节文风专项要求、润色力度自适应。v1.3核心优化：GAN对抗评分——消除AI自评幻觉。新增AdversarialCritic（D侧挑刺Agent）+gan_scorer评分融合模块，G评分与D评分加权融合（α=0.4偏向D方），对抗信号检测过度自信，动态信任权重调整，过度自信惩罚机制。v1.4核心优化：GAN轮次调整与论文自然化优化——max_rounds从5调整为7（GAN对抗评分加入后需更多轮次达95分阈值），摘要自然化优化（基于真实CSSCI论文摘要特征提取5大结构特征和20条句式模板），断裂式/硬转折修复（新增3个检测函数和5种过渡方式真实示例）。v1.5核心优化：人类语言合规强制检查——基于34篇真实CSSCI论文提取人类语言特征，新增human_language_features.md作为人类语言合规基准，所有Agent输出必须通过人类语言合规检查（微观/中观/宏观/人味四层检查），未通过的论文不得输出。v1.6核心优化：docx脚注验证强制合规——新增5个脚注检测函数（detect_manual_footnotes/check_footnote_completeness/check_footnote_content_quality/validate_footnote_reference_match/check_footnote_format_compliance），脚注-参考文献严格匹配验证，LiteratureAuditor新增脚注验证四步法（存在性→内容完整性→准确性→一致性），FullTextPolisher新增脚注问题报告强制规范与修改边界更新。v1.7核心优化：内参报告按需审稿模块——新增NeicanReviser Agent（内参修订者），仅在用户明确请求时触发，对内参报告进行审稿与优化。新增内参专用9维度评分体系（时新性/重要性/开门见山/言之有物/极简原则/虎气猴气/复杂问题简单化/对策有刻度/不越界代言，阈值95），新增7个内参格式检测函数（detect_neican_title_pattern/opening_pattern/hierarchy/countermeasure_caliber/ending/academic_residue/check_neican_format_compliance），新增neican_standards.md知识库（与生成Pipeline共享）。Invoke when user needs to review and iteratively improve academic papers, or wants cyclical paper polishing to top-journal standards."
---

# 循环式论文审稿优化 Pipeline (cyclical-paper-review) v1.7

## 技能定位

本技能是一个**循环式论文审稿与优化Pipeline**，用于对中文学术论文（新闻传播学领域为主，兼容社会学等相关学科）进行专业化审稿，并基于审稿意见驱动多个专业化Agent循环优化论文（3-7轮），直至论文质量达到外审专家9维度评分≥95分的标准。

**核心目标**：将一篇初稿论文，通过"审稿→修改→再审→再改"的循环，打磨至CSSCI顶刊发表水平。

**★v1.5新增——人类语言合规强制检查**：本Pipeline以 `knowledge_base/human_language_features.md`（基于34篇真实CSSCI论文深度分析提取）为人类语言合规基准，所有Agent输出必须通过人类语言合规检查（微观/中观/宏观/人味四层检查）。人类语言合规检查是pipeline的"最后一道防线"——即使9维度评分≥95，若人类语言合规检查未通过，论文仍不得输出。这确保了pipeline输出不仅在学术质量上达标，更在语言特征上符合人类论文的"指纹性"特征，彻底消除AI生成痕迹。

**★v1.6新增——docx脚注验证强制合规**：本Pipeline新增5个脚注检测函数（`detect_manual_footnotes`/`check_footnote_completeness`/`check_footnote_content_quality`/`validate_footnote_reference_match`/`check_footnote_format_compliance`），对论文脚注进行程序化验证。LiteratureAuditor新增"脚注验证四步法"（存在性→内容完整性→准确性→一致性），强制核验脚注内容是否符合真实已引用文献字段，杜绝脚注乱码、缺漏、错误、占位符、缺斤少两等问题。FullTextPolisher新增"脚注问题报告强制规范"，修改边界明确划分——脚注问题必须报告但不得擅自修改脚注内容本身，需交由LiteratureAuditor处理。本Pipeline与cyclical-paper-generation v7.3协同，确保输出的docx文档包含真实OOXML脚注（`w:footnoteReference`），脚注内容完整准确，符合docx规范。

**★v1.7新增——内参报告按需审稿模块**：本Pipeline新增NeicanReviser Agent（内参修订者），仅在用户明确请求内参审稿时触发，对内参报告进行专业化审稿与优化。新增内参专用9维度评分体系（时新性12分/重要性15分/开门见山10分/言之有物15分/极简原则10分/虎气猴气15分/复杂问题简单化8分/对策有刻度10分/不越界代言5分，阈值95）。新增7个内参格式检测函数（`detect_neican_title_pattern`/`detect_neican_opening_pattern`/`detect_neican_hierarchy`/`detect_neican_countermeasure_caliber`/`detect_neican_ending`/`detect_neican_academic_residue`/`check_neican_format_compliance`）。共享`knowledge_base/neican_standards.md`知识库（基于5篇真实内参报告样本提取的9章节详尽规范）。**核心约束：内参审稿模块仅在用户明确请求时触发，不得在常规论文审稿流程中自动调用，不破坏论文结构。**

**与参考skill的关系**：
- 融合 `waishenyijian-skills` 的专业评审维度与建设性表达策略
- 融合 `cyclical-paper-generation` 的循环约束机制与风格守卫
- **优化升级**：4级评定→9维度量化评分（阈值95）、12 Agent→7核心Agent、新增指令守卫防遗忘、新增语言自然度与逻辑缜密度的量化检测

---

## v1.0 核心特性

- **7核心Agent + 3程序化节点**：外审专家 + 6个章节修改Agent + ConstraintInjector/StyleGuard/InstructionGuard
- **9维度100分制**：阈值95分（比cyclical-paper-generation的90分更严格）
- **4维质量量化标准**：语言自然度 + 逻辑缜密度 + 外审评分 + 指令一致性
- **指令守卫（InstructionGuard）**：★新增，防止多轮循环后遗忘用户初始指令
- **语言自然度量化检测**：★新增，消除断裂式表达、机械过渡句
- **逻辑缜密度量化检测**：★新增，检测句子生硬切换、段落过渡呼吸感
- **6种研究类型支持**：定性/定量/计算社会科学/混合方法/访谈报告/理论论文
- **4种CSSCI期刊格式**：《新闻与传播研究》《国际新闻界》《新闻大学》《社会学研究》

---

## 循环工作流

```
输入：论文初稿 + 用户初始指令 + 研究类型 + 目标期刊
│
▼ N=1（第1轮）
┌─────────────────────────────────────────────────────────┐
│ ConstraintInjector：注入风格约束 + 初始指令快照          │
│         ↓                                               │
│ ExternalReviewer（外审专家）：9维度评审 + 评分           │
│         ↓                                               │
│ ★AdversarialCritic（对抗挑刺者）：D侧9维度挑刺评分     │
│         ↓                                               │
│ ★GANScoreFusion：G评分+D评分融合→最终评分              │
│         ↓                                               │
│ 判断：融合评分 ≥ 95？                                       │
│   ├── 是 → StyleGuard → InstructionGuard → 输出终稿     │
│   └── 否 → OpinionRouter：分发意见至对应Agent           │
│         ↓                                               │
│ 并行修改（按意见路由）：                                │
│   • 摘要问题 → AbstractReviser                          │
│   • 引言问题 → IntroductionReviser                      │
│   • 综述问题 → LiteratureReviewReviser                  │
│   • 发现问题 → FindingsReviser                          │
│   • 文献问题 → LiteratureAuditor                        │
│   • 语言/全局问题 → FullTextPolisher                    │
│         ↓                                               │
│ StyleGuard：风格验证（标点/字数/禁止模式/语言自然度）   │
│         ↓                                               │
│ ★WordCountEnforcer：字数强制执行（v1.2新增）           │
│   · 防线1已在ConstraintInjector注入字数预算             │
│   · 防线2：P1-P5压缩策略                               │
│   · 防线3：硬截断兜底                                  │
│         ↓                                               │
│ InstructionGuard：指令一致性验证（★防遗忘）             │
│         ↓                                               │
│ N++ → 循环                                              │
└─────────────────────────────────────────────────────────┘
│
▼ N=7（最大轮次）
输出：当前最佳版本 + 未解决问题清单 + 改进建议
```

### 循环退出条件

| 条件 | 动作 |
|------|------|
| 外审评分 ≥ 95 且 InstructionGuard通过 | 输出终稿，终止循环 |
| 外审评分 < 95 且 N < 7 | 分发意见，进入下一轮 |
| 外审评分 < 95 且 N = 7 | 输出当前最佳 + 未解决问题清单 |
| 连续3轮总分提升 < 3分 | 触发人工介入提示 |
| InstructionGuard检测到指令严重偏离 | 立即终止，回滚至上一合规版本 |
| 某维度连续2轮满分 | 冻结该维度相关章节 |
| 某维度连续3轮无显著提升 | 冻结该维度，标注"已达当前最优" |
| 某维度出现倒退 | 自动回滚该维度至上一轮版本 |

---

## 9维度评分体系（阈值95）

融合 waishenyijian 的8维度专业评审与 cyclical 的9维度量化评分，重新设计：

| 序号 | 维度 | 满分 | 评估重点 |
|------|------|------|---------|
| 1 | **选题与问题意识** | 12 | 前沿性、理论张力、问题清晰度、边界界定、学术品位 |
| 2 | **理论框架与文献** | 15 | 理论选择合理性、概念界定、文献覆盖面与批判性 |
| 3 | **研究设计与方法** | 15 | 设计逻辑、数据代表性、信效度、方法恰当性 |
| 4 | **研究发现与结果** | 12 | 结果完整性、统计指标、效应量、理论与预期对应 |
| 5 | **讨论与理论对话** | 12 | 文献对话深度、意外发现解释、理论贡献凝练 |
| 6 | **文笔与文风** | 15 | v1.1细化：2a节奏感(5分)+2b多样性(5分)+2c声音一致性(5分) |
| 7 | **逻辑缜密度** | 7 | 句子过渡平滑性、段落逻辑呼吸感、非生硬切换 |
| 8 | **严谨性与规范性** | 7 | 文献引用真实准确、格式标准、学术伦理 |
| 9 | **创新性与启发价值** | 5 | 新概念/框架、理论推进、实践启示 |
| **合计** | | **100** | **通过阈值：95** |

### GAN对抗评分机制（★v1.3新增）
，AI给自己生成的论文打分容易产生"自我肯定偏差"——倾向于给出偏高的评价。本Pipeline引入GAN对抗评分架构：

| 组件 | 角色 | 评分倾向 | 来源 |
|------|------|---------|------|
| **G评分**（Generator） | ExternalReviewer的原始评分 | 偏乐观（建设性评审） | agents/external_reviewer.md |
| **D评分**（Discriminator） | AdversarialCritic的挑刺评分 | 偏严苛（魔鬼代言人） | agents/adversarial_critic.md |
| **融合评分** | G与D的加权融合 | 校正后的最终评分 | pipeline/gan_scorer.py |

**融合公式**：`fused_score = α × G_score + (1 - α) × D_score`
- 默认α=0.4（偏向D挑刺方，因为AI自评幻觉偏向过度自信）
- 动态调整：对抗信号收敛时α↑（信任G更多），信号持续强烈时α保持低位

**对抗信号**：`adversarial_signal = G_score - D_score`
- >10：严重过度自信，D的挑刺高度可信
- 5-10：中度过度自信
- <5：基本一致，评分可靠

**过度自信惩罚**：信号>5时，每超1分扣0.5分

### 评分客观性保障

- 每个维度必须提供≥2个具体证据（引用论文原文片段）
- 每个扣分项必须说明扣分理由和改进方向
- 评分前必须完成全文精读信息提取表
- 引入"学术品位"评估框架（详见 evaluation/academic_taste.md）

---

## 4维质量量化标准

| 维度 | 检测内容 | 量化方法 | 通过标准 |
|------|---------|---------|---------|
| **语言自然度** | 断裂式表达、机械过渡句、公式化辞藻 | style_guard.py 程序化检测 + 外审专家评估 | 0处断裂式表达 + 0处机械过渡（v1.1新增：句长方差8.0-25.0、段落开头多样性≥0.6、机械模式检测） |
| **逻辑缜密度** | 句子生硬切换、段落过渡呼吸感 | quality_metrics.py 过渡平滑度算法 + 外审专家评估 | 过渡平滑度≥0.85 + 外审逻辑维度≥9/10 |
| **外审评分** | 9维度综合评分 | external_reviewer.md 9维度量化 | ≥ 95/100 |
| **指令一致性** | 幻觉检测、初始指令偏离度 | instruction_guard.py 指令快照对比 | 0处幻觉 + 指令偏离度<5% |

---

## Agent角色总览

| # | Agent | 角色 | 参考来源 | 核心职责 |
|---|-------|------|---------|---------|
| 1 | **外审专家** (ExternalReviewer) | 9维度量化评审+学术品位评估 | waishenyijian（优化升级） | 评审、评分、意见路由标签 |
| 1.5 | **对抗挑刺者** (AdversarialCritic) | D侧9维度挑刺评分 | ★v1.3新增（GAN架构D侧） | 假设论文一定有问题，穷尽挑刺 |
| 2 | **摘要修改者** (AbstractReviser) | 摘要结构优化 | cyclical abstract规则 | 350字四段式、禁用分号引号破折号 |
| 3 | **引言修改者** (IntroductionReviser) | 引言五段式结构 | cyclical introduction规则 | 600字五句结构、数据锚点核验 |
| 4 | **研究综述修改者** (LiteratureReviewReviser) | 文献地图重构 | cyclical+waishenyijian维度3 | 2000字三节递进、批判性对话 |
| 5 | **研究发现修改者** (FindingsReviser) | 发现章节结构优化 | cyclical findings规则 | 两大节各三小节、分析性≥70% |
| 6 | **文献审计者** (LiteratureAuditor) | 逐一核对引用真实性 | cyclical literature_curator（强化） | DOI核验、装饰性引用检测 |
| 7 | **全文润色者** (FullTextPolisher) | 语言+叙事融合润色 | cyclical polisher+narrator（融合） | 标点净化、过渡平滑、朗读测试、★v1.1必须模仿目标文风（人味特征≥5项） |
| 7.5 | **内参修订者** (NeicanReviser) | 内参报告审稿与优化 | ★v1.7新增（按需触发） | 内参9维度评分、二十条铁律检查、学术残留清除 |

### 程序化节点

| # | 节点 | 功能 | 参考来源 |
|---|------|------|---------|
| 1 | **ConstraintInjector** | 约束注入器 | cyclical constraint_injector（+指令快照+★v1.2字数预算注入） |
| 2 | **StyleGuard** | 风格守卫 | cyclical style_constraints（+语言自然度检测+★v1.2动态字数目标） |
| 3 | **WordCountEnforcer** | ★v1.2新增：字数强制执行器 | 三层防线（事前约束+事后压缩+硬截断） |
| 4 | **InstructionGuard** | 指令守卫 | ★新增（防指令遗忘） |
| 5 | **GANScoreFusion** | ★v1.3新增：GAN评分融合 | gan_scorer.py（G+D加权融合+对抗信号+过度自信惩罚） |
| 6 | **HumanLanguageGuard** | ★v1.5新增：人类语言守卫 | style_guard.py 的 `check_human_language_compliance()`（基于human_language_features.md，四层合规检查：微观/中观/宏观/人味） |

---

## 研究类型与Agent映射

| 研究类型 | 必执行Agent | 说明 |
|---------|------------|------|
| 定性研究 (qualitative) | 全部7个Agent | 默认配置 |
| 定量研究 (quantitative) | 全部7个Agent | FindingsReviser侧重统计指标 |
| 计算社会科学 (computational) | 全部7个Agent | LiteratureAuditor侧重算法可复现性 |
| 混合方法 (mixed) | 全部7个Agent | FindingsReviser侧重方法整合 |
| 访谈报告 (interview) | 全部7个Agent | FindingsReviser侧重引语处理 |
| 理论论文 (theoretical) | 全部7个Agent | LiteratureReviewReviser权重最高 |

---

## 强制执行协议 (MANDATORY EXECUTION PROTOCOL)

> ⚠️ **本章节为强制约束，AI 助手必须严格遵守，违反任何一条即视为 pipeline 执行失败。**

### 执行主体声明

**AI 助手是本 pipeline 的唯一执行主体**。AI 助手必须按本 SKILL.md 定义的工作流逐轮执行，不得跳过、合并或提前退出。Python 代码（`pipeline/loop_controller.py`）为程序化骨架，节点函数为占位符不调用 LLM，实际 AI 工作（评审、修改、评分）全部由 AI 助手完成。

### 最小/最大轮次约束

| 约束 | 值 | 说明 |
|------|-----|------|
| `min_rounds` | 3 | 必须执行至少 3 轮循环，即使第 1 轮评分已达 95 分阈值，也必须继续执行至第 3 轮 |
| `max_rounds` | 7 | 最多执行 7 轮，第 7 轮后无论评分如何必须输出终稿 |
| `pass_threshold` | 95 | 9 维度评分通过阈值 |

### 轮次回执强制

**每轮结束必须输出"轮次回执"**（模板见下文），回执缺失即视为该轮未执行。轮次回执必须包含：
- 轮次号（第 N / 7 轮）
- 9 维度逐项评分（含 2a/2b/2c 子维度）及本轮总分
- 本轮执行的 Agent 清单（含修改摘要）
- 风格守卫结果、指令守卫结果
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

1. **正常通过**：已执行 ≥ 3 轮（`min_rounds`）且 9 维度评分 ≥ 95（`pass_threshold`）
2. **最大轮次**：已执行 7 轮（`max_rounds`），无论评分如何
3. **人工介入**：连续 3 轮总分提升 < 3 分（`stagnation_threshold`），需在回执中明确标注"触发人工介入"
4. **指令偏离**：InstructionGuard 检测到指令严重偏离，立即终止并回滚至上一合规版本

**禁止行为**：
- ❌ 第 1 轮后直接输出终稿（即使评分 ≥ 95）
- ❌ 跳过中间轮次（如从第 1 轮直接跳到第 5 轮）
- ❌ 合并多轮工作为一轮而不分轮输出回执
- ❌ 省略轮次回执或执行回执

### 反捷径守卫 (Anti-Shortcut Guard)

| 禁止行为 | 检测信号 | 纠正动作 |
|---------|---------|---------|
| 跳过 Agent（未执行 OpinionRouter 分发的 Agent） | 轮次回执中缺失该 Agent 的修改摘要 | 回退执行被跳过的 Agent |
| 伪造评分（评分与论文实际质量明显不符） | 评分轨迹异常（如第 1 轮 95 分但论文明显未达顶刊水平） | 重新按 `agents/external_reviewer.md` 9 维度逐项评估 |
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
1. 选题与问题意识：X/12
2. 理论框架与文献：X/15
3. 研究设计与方法：X/15
4. 研究发现与结果：X/12
5. 讨论与理论对话：X/12
6. 文笔与文风：X/15（2a节奏=X/5, 2b多样性=X/5, 2c声音=X/5）
7. 逻辑缜密度：X/7
8. 严谨性与规范性：X/7
9. 创新性与启发价值：X/5
本轮总分：XX/100（较上轮 +X / -X）

【GAN对抗评分】（★v1.3新增）
G评分：XX/100（ExternalReviewer原始评分）
D评分：XX/100（AdversarialCritic挑刺评分）
融合评分：XX/100（α=0.X，最终决策依据）
对抗信号：XX（G-D差值）
过度自信惩罚：-X分 / 无

【本轮执行 Agent】
✅ ExternalReviewer（已执行）
✅ AbstractReviser（已执行，修改摘要：...）
✅ IntroductionReviser（已执行，修改摘要：...）
✅ LiteratureReviewReviser（已执行，修改摘要：...）
✅ FindingsReviser（已执行，修改摘要：...）
✅ LiteratureAuditor（已执行，修改摘要：...）
✅ FullTextPolisher（已执行，修改摘要：...）

【本轮修改摘要】
- 摘要：...
- 引言：...
- 综述：...
- 发现：...
- 文献：...
- 全文润色：...

【风格守卫结果】违规 X 处（已修复 / 待下轮修复）
【指令守卫结果】偏离度 X%（通过 / 未通过）

【下轮决策】继续 / 退出
【决策依据】评分 < 95 / 已达 min_rounds 且评分 ≥ 95 / 已达 max_rounds / 触发人工介入
═══════════════════════════════════════
```

### Pipeline 执行回执模板（强制）

Pipeline 终止时必须按此模板输出：

```
═══════════════════════════════════════
  Pipeline 执行回执 (Execution Receipt)
═══════════════════════════════════════
【总轮次】N 轮（最小 3 / 最大 7）
【最终评分】XX / 100（阈值：95）
【GAN评分轨迹】
第1轮：G=XX, D=XX, 融合=XX, 信号=XX
第2轮：G=XX, D=XX, 融合=XX, 信号=XX
...
【质量达标】✅ 是 / ❌ 否

【各轮评分轨迹】
第 1 轮：XX 分
第 2 轮：XX 分（+X）
第 3 轮：XX 分（+X）
...

【退出原因】
□ 已达 min_rounds 且评分 ≥ 95（正常通过）
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

## 使用说明

### 执行路径

本 skill 提供两条执行路径：

**路径 A（推荐）：AI 助手手动模拟执行**
- AI 助手按上文"强制执行协议"逐轮执行 pipeline
- 每轮按 `agents/external_reviewer.md` 进行 9 维度评审
- OpinionRouter 分发意见至对应 Agent，AI 助手按各 `agents/*.md` 提示词实际修改论文
- 每轮输出"轮次回执"，Pipeline 终止输出"执行回执"
- 此路径不依赖 Python runtime，是 Trae IDE 上下文中的主要执行方式

**路径 B（可选）：调用 Python `run_pipeline()`**
- 调用 `pipeline/loop_controller.py` 的 `run_pipeline()` 函数
- ⚠️ **注意**：当前 Python 节点函数为占位骨架（不调用 LLM），评分字段返回 `None`
- 若需通过 Python 运行产生实际效果，需先为各节点函数接入 LLM API
- Python 代码作为程序化参考实现，维护状态流转结构

### 执行流程

1. **接收输入**：论文初稿 + 用户初始指令 + 研究类型 + 目标期刊
2. **初始化**：ConstraintInjector 保存初始指令快照，注入风格约束（含 VOICE_SAMPLES/RHYTHM_REQUIREMENTS/HUMAN_VOICE_FEATURES）
3. **循环审稿**（强制 3-7 轮，按强制执行协议）：
   - ExternalReviewer 按 `agents/external_reviewer.md` 进行 9 维度评审+评分（含 2a/2b/2c）
   - 判断是否 ≥ 95 分且已达 `min_rounds=3`
   - 未达标或未达最小轮次则 OpinionRouter 分发意见至对应 Agent
   - Agent 按 `agents/*.md` 提示词实际修改论文（禁止复制占位）
   - StyleGuard 风格验证（标点/字数/禁止模式/节奏/多样性）
   - InstructionGuard 指令一致性验证
   - 输出本轮"轮次回执"
4. **输出终稿**：满足退出条件后输出"Pipeline 执行回执" + 完整优化论文

### 输入要求

```
论文初稿：[完整的论文文本]
用户初始指令：[用户对论文的核心要求，如研究主题、理论框架、方法偏好等]
研究类型：[qualitative/quantitative/computational/mixed/interview_report/theoretical]
目标期刊：[xwycbyj/gjxwj/xwdx/shxyj]
★v1.2新增——用户目标字数：[整数，如15000/12000/20000，默认15000]
★v1.2新增——字数容忍度：[浮点数，默认0.1即±10%]
★v1.2新增——字数执行模式：[strict/compress/warn，默认strict]
```

### 输出格式

```
═══════════════════════════════════════
  循环式论文审稿优化报告 (v1.0)
═══════════════════════════════════════

【循环概览】
总轮次：N轮
最终评分：XX/100
质量达标：✅是 / ❌否

【各轮评分轨迹】
第1轮：XX分
第2轮：XX分（+X）
...

【9维度最终评分】
1. 选题与问题意识：X/12
2. 理论框架与文献：X/15
3. 研究设计与方法：X/15
4. 研究发现与结果：X/12
5. 讨论与理论对话：X/12
6. 文笔与文风：X/15（2a节奏=X/5, 2b多样性=X/5, 2c声音=X/5）
7. 逻辑缜密度：X/7
8. 严谨性与规范性：X/7
9. 创新性与启发价值：X/5

【4维质量量化】
语言自然度：✅通过 / ❌未通过（X处问题）
逻辑缜密度：✅通过 / ❌未通过（平滑度X.XX）
外审评分：✅≥95 / ❌<95（XX分）
指令一致性：✅通过 / ❌未通过（偏离度X%）

【最终输出】
[完整优化后的论文]

【未解决问题清单】（如有）
1. ...
2. ...

═══════════════════════════════════════
```

---

## 文件结构

```
cyclical-paper-review/
├── SKILL.md                          # 本文件
├── agents/                           # 7个核心Agent
│   ├── external_reviewer.md          # 外审专家
│   ├── abstract_reviser.md           # 摘要修改者
│   ├── introduction_reviser.md       # 引言修改者
│   ├── literature_review_reviser.md  # 研究综述修改者
│   ├── findings_reviser.md           # 研究发现修改者
│   ├── literature_auditor.md         # 文献审计者
│   └── full_text_polisher.md         # 全文润色者
│   ├── adversarial_critic.md          # ★v1.3新增：对抗挑刺者（GAN D侧）
├── pipeline/                         # 程序化节点
│   ├── loop_controller.py            # 循环控制器
│   ├── constraint_injector.py        # 约束注入器
│   ├── style_guard.py                # 风格守卫
│   ├── instruction_guard.py          # 指令守卫
│   ├── opinion_router.py             # 意见路由
│   ├── quality_metrics.py            # 质量量化
│   ├── gan_scorer.py                  # ★v1.3新增：GAN评分融合模块
│   └── config.py                     # 配置
├── evaluation/                       # 评分体系
│   ├── scoring_rubric.md             # 9维度评分标准
│   └── academic_taste.md             # 学术品位评估框架
├── journal_formats/                  # 4种CSSCI期刊格式
│   ├── xwycbyj.md
│   ├── gjxwj.md
│   ├── xwdx.md
│   └── shxyj.md
├── knowledge_base/                   # 知识库
│   ├── review_dimensions.md          # 9维度评审标准
│   ├── style_standards.md            # 风格标准
│   ├── style_exemplars.md            # ★v1.6新增：风格范本库（声音锚点）
│   ├── human_language_features.md    # ★v1.5新增：人类语言合规基准
│   └── instruction_consistency.md    # 指令一致性规则
└── voice_library/                    # ★v1.9新增：学者声音锚点库（36个文件，v1.8扩充至人文社科四学科）
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
    │   # ▼v1.8新增：人文社科四学科学者（8位）
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
    │   # ▼v1.8新增：4个新研究类型种子
    ├── ethnic_policy_seed.md         # 民族政策分析种子
    ├── ethnographic_seed.md          # 民族志田野种子
    ├── sociological_theory_seed.md   # 社会学理论种子
    └── concept_genealogy_seed.md     # 概念谱系学种子
```

---

## 版本与维护

- **当前版本**: v1.8.0
- **最后更新**: 2026-06-30

### 主要变更历史

**v1.8 (2026-06-30) 人文社科四学科声音库扩充——深度学习传播学/民族学/人类学/社会学顶刊论文**

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
4. **VOICE_SAMPLES升级至v1.3**：`pipeline/constraint_injector.py`
   - 新增8组声音锚点：theoretical_ethnic、qualitative_rural、theoretical_concept、sociological_theory、chuanboxue_peng、chuanboxue_yu、quantitative_generation（周裕琼·代际比较）、theoretical_indigenous（翟学伟·本土概念建构）
5. **8个Agent学者映射表扩充**：从18行扩展至26行（+44%），覆盖 review 全链（findings_reviser/introduction_reviser/literature_review_reviser/full_text_polisher/abstract_reviser）与 generation（architect/narrator/polisher）
- 数据来源：1204篇人文社科顶刊论文（传播学/民族学/人类学/社会学，4学科×10期刊×~30篇）
- 核心策略：**从15位学者声音扩展到23位，覆盖7大学科全研究类型，实现人文社科全领域风格适配**

**v1.7 (2026-06-23) 内参报告按需审稿模块——新增NeicanReviser Agent与内参格式检测**

**核心变更**：
1. **新增NeicanReviser Agent**：`agents/neican_reviser.md`——内参修订者，仅在用户明确请求时触发
   - 内参9维度评分体系（时新性12/重要性15/开门见山10/言之有物15/极简原则10/虎气猴气15/复杂问题简单化8/对策有刻度10/不越界代言5，阈值95）
   - 核心能力一：内参审稿（二十条铁律逐条检查+9维度评分）
   - 核心能力二：内参修订（标题优化/开篇重构/正文精简/对策刻度化/文风打磨）
   - 核心能力三：学术残留清除（检测并删除文献综述/理论框架/方法论/p值等学术元素）
   - 修改边界：可修改标题/开篇/正文/对策/文风/署名，不可修改研究数据/核心发现

2. **新增内参评分标准**：`evaluation/scoring_rubric.md`新增内参专用9维度评分体系
   - 每维度含评估重点、评分标准（满分/扣分项）、真实样本示例
   - 内参审稿报告格式模板

3. **新增内参格式检测**：`pipeline/style_guard.py`新增7个检测函数
   - `detect_neican_title_pattern`——标题范式检测（5种范式匹配）
   - `detect_neican_opening_pattern`——开篇范式检测（单段式/双段式）
   - `detect_neican_hierarchy`——层级编号检测
   - `detect_neican_countermeasure_caliber`——对策刻度检测（抽象表述检测）
   - `detect_neican_ending`——结尾规范检测（无总结段）
   - `detect_neican_academic_residue`——学术残留检测
   - `check_neican_format_compliance`——综合内参格式合规检查

4. **共享内参知识库**：`knowledge_base/neican_standards.md`（与cyclical-paper-generation共享）
   - 基于5篇真实内参报告样本提取的9章节详尽规范

**涉及文件**：neican_reviser.md（新增）、scoring_rubric.md、style_guard.py、SKILL.md（共4个文件）

**核心约束**：内参审稿模块仅在用户明确请求时触发，不得在常规论文审稿流程中自动调用，不破坏论文结构。

**v1.6 (2026-06-23) docx脚注验证强制合规——新增5个脚注检测函数与Agent脚注验证规范**

**核心变更**：
1. **新增5个脚注检测函数**：`pipeline/style_guard.py` 新增脚注程序化检测能力
   - `detect_manual_footnotes(text)`：检测手动上标伪脚注（如 `[1]`、`[2]` 等非OOXML脚注）
   - `check_footnote_completeness(text)`：检查脚注引用与脚注内容的对应完整性
   - `check_footnote_content_quality(footnote_text)`：验证单条脚注内容质量（非空、无乱码、无占位符、必填字段齐全）
   - `validate_footnote_reference_match(footnotes, references)`：脚注-参考文献严格匹配验证（作者+年份+标题关键词三要素匹配）
   - `check_footnote_format_compliance(text, journal_style)`：综合脚注格式合规检查
   - 新增3个模块级常量：`FOOTNOTE_REFERENCE_PATTERN`、`FOOTNOTE_PLACEHOLDER_PATTERNS`、`FOOTNOTE_REQUIRED_FIELDS`

2. **LiteratureAuditor新增脚注验证强制规范**：`agents/literature_auditor.md` 新增"脚注验证强制规范（★v1.6新增）"章节
   - 脚注验证四步法：存在性（是否有真实OOXML脚注）→内容完整性（必填字段是否齐全）→准确性（脚注内容是否符合真实已引用文献字段）→一致性（脚注-参考文献双向核验）
   - 脚注验证报告格式：包含脚注总数、有效脚注数、无效脚注详情、未匹配参考文献详情
   - 禁止事项：禁止放行含乱码/缺漏/错误/占位符的脚注；禁止仅检查脚注存在性而不验证内容完整性

3. **FullTextPolisher新增脚注问题报告强制规范**：`agents/full_text_polisher.md` 新增"脚注问题报告强制规范（★v1.6新增）"章节
   - 修改边界更新：脚注问题必须报告，但不得擅自修改脚注内容本身（需交由LiteratureAuditor处理）
   - 脚注问题检查清单（6项）：手动伪脚注、脚注缺漏、脚注乱码、脚注占位符、脚注字段缺失、脚注-参考文献不匹配
   - 脚注问题报告格式：包含问题类型、位置、严重程度、建议处理方式
   - 与LiteratureAuditor的协作：FullTextPolisher报告脚注问题→LiteratureAuditor核验并修复

**涉及文件**：style_guard.py、literature_auditor.md、full_text_polisher.md、SKILL.md（共4个文件）

**v1.5 (2026-06-23) 人类语言合规强制检查——基于34篇真实CSSCI论文提取人类语言特征**

**核心变更**：
1. **新增人类语言合规基准**：基于34篇真实CSSCI论文（传播学8篇、经济学8篇、法学6篇、民族学6篇、非遗6篇）深度分析，提取人类论文的"指纹性"语言特征
   - 新增 `knowledge_base/human_language_features.md`：8章节完整文档，包含跨学科共性特征、学科差异化特征、"人味"特征清单、AI论文典型问题清单、话语表述逻辑特征、强制人类语言合规检查标准、跨学科速查表
   - 核心定位：本文件为pipeline的"人类语言合规基准"，所有Agent必须参照执行

2. **新增HumanLanguageGuard节点**：在程序化节点中新增人类语言守卫
   - `pipeline/style_guard.py`：新增 `check_human_language_compliance()` 函数，实现四层合规检查（微观/中观/宏观/人味）
   - 检查项：句长方差（≥10.0）、段落开头多样性（≥5种）、AI高频词检测、短句收束
   - 返回结果字典：passed/failed_checks/suggestions

3. **强制人类语言合规检查机制**：所有Agent输出必须通过人类语言合规检查
   - `SKILL.md`：概述部分新增人类语言合规检查重要性说明，程序化节点表新增HumanLanguageGuard
   - `knowledge_base/style_standards.md`：新增"人类语言合规基准"章节，引用human_language_features.md第六章强制合规检查标准
   - `agents/full_text_polisher.md`：新增"人类语言合规强制检查"章节，列出关键检查项
   - `agents/abstract_reviser.md`：新增"摘要人类语言合规检查"章节，列出摘要相关检查项

**涉及文件**：human_language_features.md（新增）、style_guard.py、style_standards.md、full_text_polisher.md、abstract_reviser.md、SKILL.md（共6个文件）

**v1.4 (2026-06-23) GAN轮次调整与论文自然化优化**

**核心变更**：
1. **轮次阈值调整**：`max_rounds` 从5调整为7，因GAN对抗评分加入后需要更多轮次达到95分阈值
   - `pipeline/config.py`：`max_rounds` 默认值 5→7
   - `pipeline/loop_controller.py`：所有轮次引用更新
   - `SKILL.md`：工作流图、强制执行协议、回执模板、反捷径守卫中的轮次引用全部更新

2. **摘要自然化优化**：基于真实CSSCI论文（黄阳坤/周葆华/刘战伟/雷紫雯）摘要特征提取
   - `agents/abstract_reviser.md`：新增"摘要正面标准"章节，含5大结构特征、"口水话"识别清单、"机械学术腔"识别清单、修复策略
   - `knowledge_base/style_standards.md`：新增"摘要正面标准"章节，含20条精选句式模板和修复策略

3. **断裂式/硬转折修复**：基于真实CSSCI论文过渡模式提取
   - `pipeline/style_guard.py`：新增3个检测函数（`detect_hard_transitions`、`detect_mechanical_connectors`、`detect_concept_disconnect`）
   - `agents/full_text_polisher.md`：新增"断裂修复专项指令"章节，含5种过渡方式真实示例和断裂修复策略

**涉及文件**：config.py、loop_controller.py、style_guard.py、abstract_reviser.md、full_text_polisher.md、style_standards.md、SKILL.md（共7个文件）

**v1.3 (2026-06-22) CSSCI语言特征深度学习——去AI化改造**
- `knowledge_base/style_standards.md` 新增4个章节：正面引导（好语言的5项核心特征）、语义衔接质量判断标准（3种高质量衔接模式+3项判断标准+4种禁止低质量过渡）、论证方式约束（论点-论据-分析比例/概念生成时机/理论对话深度/论证语态多样性）、量化指标汇总
- `knowledge_base/style_exemplars.md` 补充量化/混合/访谈/理论四种研究类型的完整范本和句式模板（每节含风格特征摘要表+15条句式模板+5段真实段落范本）；新增模仿质量评估标准（3项评估维度+4种失败模式+4项过度预警）；新增句式组合流动范本（3个组合范本+4条组合规则）；新增风格退化预警规则（3种退化信号+退化防控协议）
- `agents/full_text_polisher.md` 7步线性流程改为两轮迭代流程（形式修复+声音初调→声音深化+形式微调）；人味特征从"至少5项"改为自适应选择2-5项（按研究类型）；新增4个章节文风专项要求（引言/文献/发现/结语）；新增润色力度自适应机制（微调/中度/大幅三档）；版本号v1.0→v1.3
- 核心策略：**从规则禁止走向正面引导**——以真实CSSCI论文范本为锚点，通过论证语态多样性、语义衔接质量、人味特征自适应三大机制消除AI生成痕迹

**v1.3 (2026-06-22) GAN对抗评分——消除AI自评幻觉**
- 核心问题：AI给自己生成的论文打分容易产生"自我肯定偏差"，倾向于给出偏高的评价
- 新增AdversarialCritic Agent（agents/adversarial_critic.md）：GAN架构中的D侧，扮演"魔鬼代言人"，假设论文一定有问题，穷尽挑刺
- 新增gan_scorer.py（pipeline/gan_scorer.py）：G评分与D评分的加权融合模块，包含对抗信号检测、动态信任权重、过度自信惩罚
- 修改external_reviewer.md：添加G侧角色声明、自信度自评字段、融合评分输出
- 修改loop_controller.py：新增adversarial_critic_node和gan_score_fusion_node，修改图结构（external_reviewer → adversarial_critic → gan_score_fusion → 条件路由）
- 修改config.py：新增gan_enabled/trust_weight_alpha/adversarial_signal_threshold参数
- 融合公式：`fused_score = α × G_score + (1 - α) × D_score`，α默认0.4（偏向D方）
- 核心策略：**一边在生产，另一边在挑刺**——G负责建设性评审，D负责无情挑刺，融合评分校正AI自评幻觉

**v1.2 (2026-06-22) 强制执行协议 + 强制字数控制——修复循环轮次越多字数越膨胀问题**
- 新增 `MANDATORY EXECUTION PROTOCOL` 章节：明确 AI 助手为执行主体、`min_rounds=3`/`max_rounds=5` 约束、轮次回执强制、执行回执强制、4 类退出条件
- 新增 `Anti-Shortcut Guard` 反捷径守卫：6 项禁止行为及检测信号/纠正动作
- 新增"轮次回执模板"和"Pipeline 执行回执模板"两个强制模板
- ★字数控制核心改造：三层防线（事前约束+事后压缩+硬截断兜底）确保无论滚动多少轮，论文字数严格限定在用户指定目标内
  - `pipeline/config.py` 新增 `user_target_words`/`word_count_tolerance`/`word_count_enforcement` 参数，新增 `compute_section_budgets()`/`build_word_budget_constraint()` 函数
  - `pipeline/constraint_injector.py` 在 `inject()` 方法中新增字数预算硬约束注入，向每个修改型Agent注入当前字数状态和章节预算
  - `pipeline/loop_controller.py` 新增 `word_count_enforcer_node` 节点（三层防线），PipelineState新增字数控制字段，`create_pipeline()` 将word_count_enforcer加入节点流（style_guard→word_count_enforcer→instruction_guard）
  - `pipeline/style_guard.py` 新增 `get_dynamic_style_rules()` 动态规则缩放，`run_full_style_audit()` 支持动态字数目标
- 核心策略：**用户提出多少字，无论滚动多少次一定要只限定在这个字数**

**v1.1 (2026-06-19) 声音优先、规则兜底——人味优化**
- 新增 `VOICE_SAMPLES`：基于真实CSSCI核刊论文的声音范本（黄阳坤/刘战伟/雷紫雯），按7种研究类型注入
- 新增 `RHYTHM_REQUIREMENTS`：句长方差(8.0-25.0)、段落开头多样性(≥0.6)、短句占比(≥15%)、长句占比(≤40%)
- 新增 `HUMAN_VOICE_FEATURES`：15项"人味"特征清单，修改Agent必须体现≥5项
- `style_guard.py` 集成 `calculate_sentence_rhythm`/`calculate_paragraph_diversity`/`detect_mechanical_patterns` 到 `run_full_style_audit`
- `quality_metrics.py` 新增节奏与多样性检测函数
- `loop_controller.py` 重构 `constraint_injector_node`（使用ConstraintInjector类）、`style_guard_node`（调用run_full_style_audit）、`external_reviewer_node`（动态2a/2b/2c评分）
- `full_text_polisher.md` 新增"核心能力零：目标文风必须模仿"指令
- `external_reviewer.md` 维度6细化为2a节奏感(5分)+2b多样性(5分)+2c声音一致性(5分)，维度7从10分调整为7分
- 核心策略：**声音优先、规则兜底**——先内化真实顶刊文风，再遵守禁止规则

**v1.0 初始版本**
- 7 Agent + 3程序化节点、9维度100分制（阈值95）、4维质量量化、指令守卫防遗忘

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

> **注**：`update_style_exemplars.py` 与 `scholar_voice_extractor.md` 为两个 pipeline 共享的工具，位于 `cyclical-paper-generation/knowledge_base/` 目录下。

### 步骤2：人工审核提取结果

参考 `scholar_voice_extractor.md` 中的"人工审核要点"，审核：
- 摘录是否为原文
- 摘录是否具有文风代表性
- 摘录是否含违规表达
- VOICE_SAMPLES 子键名是否合规

### 步骤3：合并至 style_exemplars.md

将审核通过的摘录合并至 `knowledge_base/style_exemplars.md` 对应学者章节（如"周葆华文风范本""邓绍根文风范本"）。

### 步骤4：合并至 VOICE_SAMPLES

将审核通过的摘录合并至 `pipeline/constraint_injector.py` 的 `VOICE_SAMPLES` 字典，子键名遵循 `<research_type>_<scholar_pinyin>` 规范。

### 步骤5：验证

运行 `python -c "from pipeline.constraint_injector import VOICE_SAMPLES; print(list(VOICE_SAMPLES.keys()))"` 确认子键已写入。

### 触发条件

参考 `scholar_voice_extractor.md` 的"更新触发条件"小节。
