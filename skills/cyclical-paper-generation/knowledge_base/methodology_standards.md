# 方法论标准库 v1.0

> 面向新闻传播学/社会学论文写作的方法论标准体系，覆盖量化研究、质化研究与计算社会科学三类范式。

---

## 一、量化研究标准

### 1.1 问卷设计规范

**核心文献**：
- Dillman, D. A., Smyth, J. D., & Christian, L. M. (2014). *Internet, Phone, Mail, and Mixed-Mode Surveys: The Tailored Design Method* (4th ed.). Wiley.
- 风笑天. (2013). 《社会调查研究方法》. 中国人民大学出版社.

**关键步骤**：
1. 概念操作化：将抽象概念转化为可测量的具体指标
2. 量表选择：优先使用成熟量表（已发表文献中检验过信效度），避免自行开发
3. 题项设计原则：
   - 一个题项只测一个概念
   - 避免引导性问题、双重否定、行话
   - 选项设置互斥且穷尽
4. 量表类型：Likert 5点或7点量表为社会科学主流
5. 预测试（pilot test）：至少30份有效问卷，检验题项理解度和完成时间

**质量检查清单**：
- [ ] 每个概念至少3个题项测量
- [ ] 量表来源标注清晰
- [ ] 包含注意力检测题（attention check）
- [ ] 人口学变量置于问卷末尾
- [ ] 问卷完成时间控制在15分钟内

### 1.2 抽样方法

**核心文献**：
- Fowler, F. J., Jr. (2013). *Survey Research Methods* (5th ed.). Sage.
- Groves, R. M., Fowler, F. J., Couper, M. P., Lepkowski, J. M., Singer, E., & Tourangeau, R. (2009). *Survey Methodology* (2nd ed.). Wiley.

**常用抽样方法**：

| 方法 | 适用场景 | 优势 | 局限 |
|------|----------|------|------|
| 简单随机抽样 | 有完整抽样框 | 无偏、可推断总体 | 需完整名单 |
| 分层抽样 | 已知群体异质性大 | 提高精度 | 需事前分层信息 |
| 配额抽样 | 快速调查 | 操作简便 | 无法推断抽样误差 |
| 便利抽样 | 探索性研究 | 低成本 | 外部效度低 |
| 滚雪球抽样 | 隐藏群体/特殊人群 | 可触及难接触群体 | 样本偏差大 |

**质量检查清单**：
- [ ] 明确抽样框和抽样方法
- [ ] 报告样本量计算依据（功效分析/Power Analysis）
- [ ] 报告回收率和无应答偏差分析
- [ ] 样本与总体的人口学比较
- [ ] 讨论抽样策略的局限

### 1.3 信效度检验

**核心文献**：
- DeVellis, R. F. (2016). *Scale Development: Theory and Applications* (4th ed.). Sage.
- Fornell, C., & Larcker, D. F. (1981). Evaluating structural equation models with unobservable variables and measurement error. *Journal of Marketing Research*, 18(1), 39-50.

**信度检验**：
- Cronbach's α > 0.70（探索性研究可放宽至0.60）
- 组合信度（CR）> 0.70
- 重测信度：间隔2-4周，r > 0.70

**效度检验**：
- 内容效度：专家评审
- 构念效度：
  - 收敛效度：AVE > 0.50（Fornell-Larcker标准）
  - 区分效度：AVE平方根 > 构念间相关系数
- 标准关联效度：与同类成熟量表的相关性

**质量检查清单**：
- [ ] 报告每个量表的Cronbach's α
- [ ] 报告EFA/KMO和Barlett球形检验结果
- [ ] 如做CFA，报告模型拟合指数（χ²/df, CFI, TLI, RMSEA, SRMR）
- [ ] 报告AVE和CR（如适用）

### 1.4 统计方法选择

**核心文献**：
- Field, A. (2017). *Discovering Statistics Using IBM SPSS Statistics* (5th ed.). Sage.
- Hayes, A. F. (2017). *Introduction to Mediation, Moderation, and Conditional Process Analysis* (2nd ed.). Guilford Press.

**常用方法选择指南**：

| 研究目的 | 推荐方法 | 软件 |
|----------|----------|------|
| 组间差异比较 | t检验/ANOVA | SPSS/R |
| 变量间关系 | Pearson/Spearman相关 | SPSS/R |
| 预测模型 | 多元线性回归 | SPSS/R |
| 中介效应 | Bootstrap中介分析（Hayes PROCESS） | SPSS/R |
| 调节效应 | 交互项回归 | SPSS/R |
| 潜变量建模 | SEM（结构方程模型） | AMOS/Mplus/R(lavaan) |
| 分类/聚类 | 潜在类别分析（LCA） | Mplus/R |

**质量检查清单**：
- [ ] 报告效应量（Cohen's d, η², R²等）
- [ ] 报告置信区间（95% CI）
- [ ] 检查统计假设（正态性、方差齐性、多重共线性）
- [ ] 报告多重比较校正（如Bonferroni）
- [ ] 不滥用"显著"一词（p值只是概率指标）

### 1.5 效应量报告

**核心文献**：
- Cohen, J. (1992). A power primer. *Psychological Bulletin*, 112(1), 155-159.
- Sullivan, G. M., & Feinn, R. (2012). Using effect size—or why the p value is not enough. *Journal of Graduate Medical Education*, 4(3), 279-282.

**常用效应量指标**：
- d = 0.2（小）、0.5（中）、0.8（大）
- r = 0.1（小）、0.3（中）、0.5（大）
- η²/ω² = 0.01（小）、0.06（中）、0.14（大）
- R² = 0.02（小）、0.13（中）、0.26（大）

**质量检查清单**：
- [ ] 所有p值旁报告效应量
- [ ] 解释效应量实际意义（不仅仅是大小）
- [ ] 报告样本量功效分析

---

## 二、质化研究标准

### 2.1 扎根理论三级编码

**核心文献**：
- Strauss, A., & Corbin, J. (1998). *Basics of Qualitative Research: Techniques and Procedures for Developing Grounded Theory* (2nd ed.). Sage.
- Charmaz, K. (2014). *Constructing Grounded Theory* (2nd ed.). Sage.

**三级编码流程**：

**一级编码（Open Coding）**：
- 逐行/逐段阅读数据
- 给每个意义单元赋予概念标签
- 保持编码贴近数据（使用in vivo编码）
- 产出：初始编码列表（>100个编码典型）

**二级编码（Axial Coding）**：
- 发现编码之间的关系
- 按照"条件→现象→脉络→中介条件→行动/互动策略→结果"的典范模型组织
- 将一级编码归纳为子类别和类别
- 产出：类别体系（10-30个类别典型）

**三级编码（Selective Coding）**：
- 识别核心范畴（core category）
- 将其他类别与核心范畴连接
- 发展"故事线"（storyline）
- 产出：理论框架/理论模型

**质量检查清单**：
- [ ] 理论饱和判断清晰（新增数据不再产生新类别）
- [ ] 编码过程有审计追踪（编码簿、备忘录）
- [ ] 提供编码示例（原始数据→一级编码→二级编码→三级编码）
- [ ] 报告编码一致性（如多人编码）

### 2.2 深度访谈法

**核心文献**：
- Kvale, S., & Brinkmann, S. (2009). *InterViews: Learning the Craft of Qualitative Research Interviewing* (2nd ed.). Sage.
- Rubin, H. J., & Rubin, I. S. (2011). *Qualitative Interviewing: The Art of Hearing Data* (3rd ed.). Sage.

**关键步骤**：
1. 访谈提纲设计：从开放式问题开始，逐步聚焦
2. 样本选择：目的性抽样（purposive sampling），非概率抽样
3. 样本量依据：信息饱和（通常15-30人）
4. 访谈录制与转录：逐字转录，标注非语言信息
5. 访谈质量控制：追问技巧、避免引导、建立信任

**质量检查清单**：
- [ ] 访谈提纲经预访谈检验
- [ ] 报告样本选择逻辑（最大差异/典型/关键案例抽样）
- [ ] 报告拒绝率和样本人口学特征表
- [ ] 单次访谈时长和总数据量
- [ ] 转录规则说明
- [ ] 提供访谈环境描述

### 2.3 案例研究法

**核心文献**：
- Yin, R. K. (2017). *Case Study Research and Applications: Design and Methods* (6th ed.). Sage.
- Stake, R. E. (1995). *The Art of Case Study Research*. Sage.

**关键步骤**：
1. 案例选择：基于理论目的而非统计目的
2. 多案例设计：通常4-10个案例（Yin建议）
3. 数据三角验证：访谈+观察+文档+实物
4. 案例内分析→跨案例分析→理论构建
5. 分析策略：模式匹配、解释构建、时序分析

**质量检查清单**：
- [ ] 案例选择理由明确（关键/极端/典型/揭示性案例）
- [ ] 详述案例情境（context）
- [ ] 多证据来源（至少3种）
- [ ] 证据链完整（从研究问题到结论可追溯）
- [ ] 讨论竞争性解释（rival explanations）

### 2.4 理论饱和判断

**核心文献**：
- Guest, G., Bunce, A., & Johnson, L. (2006). How many interviews are enough? An experiment with data saturation and variability. *Field Methods*, 18(1), 59-82.
- Hennink, M. M., Kaiser, B. N., & Marconi, V. C. (2017). Code saturation versus meaning saturation: How many interviews are enough? *Qualitative Health Research*, 27(4), 591-608.

**饱和判断标准**：
- **编码饱和**（code saturation）：12-16个访谈后不再出现新编码
- **意义饱和**（meaning saturation）：需要更多访谈（20-24个）才能完全理解所有编码的维度和细微差异
- 实践标准：当连续3位新受访者不再贡献新的类别时

**质量检查清单**：
- [ ] 描述饱和判断的具体方法
- [ ] 报告追加的验证性访谈数量
- [ ] 报告最后一轮访谈的新增编码数

### 2.5 反身性（Reflexivity）

**核心文献**：
- Berger, R. (2015). Now I see it, now I don't: Researcher's position and reflexivity in qualitative research. *Qualitative Research*, 15(2), 219-234.
- Finlay, L. (2002). Negotiating the swamp: The opportunity and challenge of reflexivity in research practice. *Qualitative Research*, 2(2), 209-230.

**反身性实践**：
- 研究日志/备忘录：记录研究过程中的决策、情绪、偏见
- 研究者立场声明：年龄、性别、教育背景、与研究主题的关系
- 与研究对象的权力关系反思

**质量检查清单**：
- [ ] 研究方法部分包含研究者立场声明
- [ ] 讨论研究者特征对数据收集和分析的潜在影响
- [ ] 提供一个反身性实例

### 2.6 可信性框架 (Trustworthiness)

**核心文献**：
- Lincoln, Y. S., & Guba, E. G. (1985). *Naturalistic Inquiry*. Sage.

**四个可信性标准**（替代量化研究的效度）：

| 标准 | 定义 | 策略 |
|------|------|------|
| 可信性（Credibility） | 研究真实反映了参与者经验 | 长时间投入、三角验证、成员核查 |
| 可转移性（Transferability） | 研究发现可应用于其他情境 | 厚描述（thick description） |
| 可靠性（Dependability） | 研究发现是可重复的 | 审计追踪、编码簿公开 |
| 可确认性（Confirmability） | 发现来自数据而非研究者偏见 | 反身性日志、外部审计 |

**质量检查清单**：
- [ ] 明确报告如何满足四项标准
- [ ] 提供审计追踪记录
- [ ] 报告成员核查（member checking）结果
- [ ] 情境描述充分"厚"

### 2.7 Gioia 方法论

**核心文献**：
- Gioia, D. A., Corley, K. G., & Hamilton, A. L. (2013). Seeking qualitative rigor in inductive research: Notes on the Gioia methodology. *Organizational Research Methods*, 16(1), 15-31.

**Gioia方法论的核心特征**：
- 一阶概念（1st-order concepts）：使用受访者的语言（informant-centric）
- 二阶主题（2nd-order themes）：使用研究者的理论语言（researcher-centric）
- 聚合维度（aggregate dimensions）：将二阶主题进一步抽象为理论维度
- 产出：数据结构的可视化（data structure diagram）

**质量检查清单**：
- [ ] 提供数据结构图
- [ ] 一阶概念直接引用受访者语言
- [ ] 二阶主题的命名体现理论抽象
- [ ] 报告编码过程（从原始数据到理论模型的完整路径）

---

## 三、计算社会科学标准

### 3.1 计算方法论

**核心文献**：
- Lazer, D., Pentland, A., Adamic, L., Aral, S., Barabási, A. L., Brewer, D., ... & Van Alstyne, M. (2009). Computational social science. *Science*, 323(5915), 721-723.
- Salganik, M. J. (2019). *Bit by Bit: Social Research in the Digital Age*. Princeton University Press.

**关键方法**：
1. **自然语言处理（NLP）**：主题建模（LDA）、情感分析、文本分类
2. **社会网络分析（SNA）**：网络密度、中心性、社区检测
3. **计算实验**：ABM（Agent-Based Modeling）、模拟仿真
4. **机器学习**：有监督/无监督学习、预测建模

**质量检查清单**：
- [ ] 数据来源和采集方法透明
- [ ] 算法选择和参数设置合理
- [ ] 报告模型性能指标（准确率、召回率、F1等）
- [ ] 人类标注作为ground truth
- [ ] 报告标注一致性（Cohen's κ > 0.70）

### 3.2 大数据分析

**关键步骤**：
1. 数据采集：API获取、爬虫、数据捐赠
2. 数据清洗：去重、缺失值处理、异常值检测
3. 数据预处理：分词、去停用词、标准化
4. 探索性分析：可视化、描述统计
5. 建模与分析
6. 结果解读与理论化

**质量检查清单**：
- [ ] 数据规模和特征描述
- [ ] 数据清洗步骤透明
- [ ] 缺失数据处理策略报告
- [ ] 数据代表性讨论（平台数据≠全人口数据）

### 3.3 计算可复现性

**核心文献**：
- Peng, R. D. (2011). Reproducible research in computational science. *Science*, 334(6060), 1226-1227.
- Hardwicke, T. E., et al. (2018). Data availability, reusability, and analytic reproducibility. *Royal Society Open Science*, 5(8), 180448.

**可复现性标准**：
- 开放数据（尽可能脱敏后公开）
- 开放代码（GitHub/OSF仓库）
- 环境文档化（Docker/requirements.txt）
- 分析管道（pipeline）透明化

**质量检查清单**：
- [ ] 提供数据可用性声明
- [ ] 提供可复现代码仓库链接
- [ ] 文档化分析环境（软件版本）
- [ ] README包含完整的复现步骤

### 3.4 数据伦理

**核心文献**：
- Zimmer, M. (2010). "But the data is already public": On the ethics of research in Facebook. *Ethics and Information Technology*, 12(4), 313-325.
- boyd, d., & Crawford, K. (2012). Critical questions for big data. *Information, Communication & Society*, 15(5), 662-679.

**伦理标准**：
1. 知情同意：即使是公开数据，也应考虑使用者期望
2. 数据脱敏：删除或匿名化可识别个人信息
3. 不作恶：不利用数据对弱势群体造成伤害
4. 情境完整性（contextual integrity）：尊重数据产生情境的边界

**质量检查清单**：
- [ ] 伦理审查委员会批准（如适用）
- [ ] 数据脱敏方法描述
- [ ] 重新识别风险评估
- [ ] 数据安全存储措施

### 3.5 算法透明性

**核心文献**：
- Diakopoulos, N. (2016). Accountability in algorithmic decision making. *Communications of the ACM*, 59(2), 56-62.
- Mittelstadt, B. D., Allo, P., Taddeo, M., Wachter, S., & Floridi, L. (2016). The ethics of algorithms: Mapping the debate. *Big Data & Society*, 3(2), 1-21.

**算法透明性标准**：
- 算法逻辑可解释（不一定是黑箱）
- 训练数据和特征公开
- 偏误检测和报告
- 公平性评估（不同群体之间的表现差异）

**质量检查清单**：
- [ ] 报告算法选择的理由
- [ ] 特征工程透明化
- [ ] 讨论算法的潜在偏误
- [ ] 报告不同子群的表现差异