"""
循环式论文审稿优化 Pipeline v1.2 - 约束注入器（ConstraintInjector）

在每轮循环开始时，从 config.py 读取风格约束，注入到各 Agent 的 instruction 字段。
同时注入用户初始指令快照（防止多轮后遗忘）、上一轮违规记录、评分反馈、共享学习档案。

v1.0 核心新增（相对于 cyclical-paper-generation 的 constraint_injector_node）：
- ★新增：注入用户初始指令快照（initial_instruction_snapshot），防止多轮循环后遗忘
- 适配 7 Agent 架构（external_reviewer / abstract_reviser / introduction_reviser /
  literature_review_reviser / findings_reviser / literature_auditor / full_text_polisher）
- 注入上一轮 style_violations 与 review_feedback
- 注入共享学习档案（用户风格偏好）
- 完整 error_log 记录

Author: Cyclical Paper Review Pipeline
Version: 1.0.0
"""

from typing import TypedDict, List, Dict, Optional, Any
from datetime import datetime


# ============================================================================
# PipelineState 定义（与 cyclical-paper-review 主流程兼容）
# ============================================================================

class PipelineState(TypedDict, total=False):
    """循环式论文审稿优化 Pipeline 状态定义"""

    # ========== 论文状态 ==========
    paper_content: str                              # 当前论文全文
    paper_version: int                              # 版本号
    paper_title: str                                # 当前标题
    round_number: int                               # 当前循环轮次

    # ========== 用户初始指令（★v1.0新增） ==========
    initial_instruction: str                        # 用户初始指令原文
    initial_instruction_snapshot: Optional[str]     # 初始指令快照（首轮固化，防遗忘）

    # ========== 7 Agent 输出/指令 ==========
    external_reviewer_output: Optional[str]
    external_reviewer_instruction: Optional[str]
    abstract_reviser_output: Optional[str]
    abstract_reviser_instruction: Optional[str]
    introduction_reviser_output: Optional[str]
    introduction_reviser_instruction: Optional[str]
    literature_review_reviser_output: Optional[str]
    literature_review_reviser_instruction: Optional[str]
    findings_reviser_output: Optional[str]
    findings_reviser_instruction: Optional[str]
    literature_auditor_output: Optional[str]
    literature_auditor_instruction: Optional[str]
    full_text_polisher_output: Optional[str]
    full_text_polisher_instruction: Optional[str]

    # ========== 风格约束与违规 ==========
    style_violations: List[str]                     # 上一轮风格违规记录
    active_constraints: Optional[Dict]              # 当前活跃的风格约束
    review_feedback: Optional[Dict]                 # 上一轮评审反馈
    instruction_consistency_report: Optional[Dict]  # 指令一致性报告

    # ========== 共享学习档案 ==========
    user_style_profile: Optional[Dict]              # 用户风格偏好档案
    shared_learning_update: Optional[Dict]          # 共享学习更新

    # ========== 评审状态 ==========
    review_report: Optional[str]
    review_score: Optional[int]
    review_pass: Optional[bool]
    dimension_scores: Optional[Dict[str, int]]
    score_history: List[int]

    # ========== 循环控制 ==========
    max_rounds: int
    pass_threshold: int
    frozen_sections: List[str]
    section_states: Dict[str, Dict]
    human_intervention_required: bool

    # ========== 元信息 ==========
    research_type: str
    journal_style: str
    error_log: List[str]
    version_history: List[Dict]
    pipeline_start_time: Optional[str]


# ============================================================================
# 7 Agent 名称常量
# ============================================================================

AGENT_NAMES = [
    "external_reviewer",
    "abstract_reviser",
    "introduction_reviser",
    "literature_review_reviser",
    "findings_reviser",
    "literature_auditor",
    "full_text_polisher",
]

# Agent 中文名映射（用于日志可读性）
AGENT_CN_NAMES = {
    "external_reviewer": "外审专家",
    "abstract_reviser": "摘要修改者",
    "introduction_reviser": "引言修改者",
    "literature_review_reviser": "研究综述修改者",
    "findings_reviser": "研究发现修改者",
    "literature_auditor": "文献审计者",
    "full_text_polisher": "全文润色者",
}


# ============================================================================
# v1.2 扩展：正向声音范本（VOICE_SAMPLES）——基于真实CSSCI核刊论文
#   - 新增声音锚点：quantitative_generation（周裕琼定量代际研究）、
#                     theoretical_indigenous（翟学伟本土化理论）
# 核心策略：声音优先、规则兜底——先内化目标文风，再遵守禁止规则
# ============================================================================

VOICE_SAMPLES: Dict[str, List[str]] = {
    "computational": [
        '作为"集体注意力的授权管理者"，新闻媒体长期承担着可见性创建与管理的功能，协调和影响的范围涵盖事件、人物、群体及各类辩论、争议、叙事。正如马特·卡尔森所言，可见性作为新闻机构与公众互动的属性，是新闻机构的常态价值目标，也是其合法性与生命力的重要来源。换言之，对新闻媒体而言，可见性的创建与管理不仅是静态功能，更是动态追求，新闻机构由此构筑权威与社会信任。（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
        '学界虽已关注到算法作为"转义者"对可见性的再赋，但对推荐算法在削弱新闻机构可见性控制的同时、又将其置于可见性管理之下的机制，仍缺乏细致的实证检验。这一问题关涉智媒时代新闻传播的公共性与公正性，亟须探索可行的可见性管理之策。基于此，论文通过虚拟代理测试驱动的算法审计，回应以下核心问题：算法平台如何塑造新闻机构的可见性？这一机制在何种情境与因素作用下会出现弹性变化？（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
        '二者共同的局限在于，无法解释可见性如何随着情境变化和时间推移而诞生、演变或消亡。也就是说，关于情境与过程的研究视角相对缺乏。作为可见性研究的代表性人物，布里根蒂在理论化"可见性"时，先以制度为其定位，将其界定为"或多或少固定的互动模式"，并强调其"高度依赖情境及社会、技术、政治的复杂安排"，突显其动态性和情境化特点。（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
    ],
    "qualitative": [
        '数据是一种权力，谁拥有了数据，谁就掌握了权力。站在劳动技术控制的视角，本文聚焦N企业的算法实验与中央大脑系统，研究算法系统的前端数据采集与末端指令执行的人类劳动过程。在算法实验中，作为幽灵劳动的"人类工蜂"，与物联传感器类的"机器工蜂"，展开大规模的数据采集，补足人工智能的"最后一公里"。技术升级并未带来人的解放，反而出现电子圆形监狱式的全景监控，引发"技术升级"与"劳动降级"的悖论。从"铁锹实验"到"算法实验"，算法成为控制王座上的"蜂王"，人则沦为算法系统抽象化的"工蜂"性工具人。（刘战伟，《"蜂王"统令"工蜂"》）',
        '三大日系便利店巨头7-11、全家、罗森，在中国开出2000家店，分别用了15年、16年和23年，N企业只用了3年。有人提问："N企业和7－11有什么区别？"其答复："表面上看，我们是一家连锁便利店，其实我们是一家数据科技公司。"迥异于传统便利店，N企业依托人工贴拍信息采集员、监控摄像头与智能传感器大规模采集数据，训练算法模型，开展了一项让中央大脑全面接管人类决策的算法实验，引发了人与技术的劳动控制冲突。（刘战伟，《"蜂王"统令"工蜂"》）',
        '我们不禁要反思追问，中央大脑的人工智能算法系统是否能够脱离人类劳动？算法技术为何经常错漏百出，不仅没能解放人，反而给人带来更严密的技术控制？当人成为中央大脑算法系统的人肉义肢时，人的主体性尊严在哪里？从个案上升至公共议题：上述问题不仅仅是N企业面对的困境，更是人工智能时代人与技术关系的核心命题。（刘战伟，《"蜂王"统令"工蜂"》）',
    ],
    "digital_sociology": [
        '数字化、智能化技术深度嵌入社会，使社会技术系统内的知识流转与传播网络更加复杂。已有研究多关注平台、技术在知识传播中的中介作用，忽视了人类在知识传播网络中的知识转译和传播功能。通过参与式观察和访谈，本研究以医疗职业陪诊师在医疗健康系统的知识中介和转译实践为切入点进一步拓展了相关讨论。研究发现，陪诊师在摆渡患者疾患经验和医疗专业知识、医疗组织系统的隐性知识，以及数字医疗技术系统知识中扮演"知识专家""知识领航人"和"知识修补师"的角色。他们通过对医疗系统相关知识的中介和转译，成为嵌入医疗健康系统的人类补丁。（雷紫雯，《"知识摆渡人"》）',
        '在老龄化加剧、独居人群增多、异地就医需求增大等背景下，社会对陪诊服务的需求不断攀升，"陪诊师"这一新兴职业应运而生。当前社会层面对职业陪诊师的讨论主要聚焦老龄社会背景下，陪诊师扮演"临时家人""孤独就诊的帮手"等情感劳动方面的角色，而忽视了陪诊师事实上承担着复杂医疗健康系统与普通个体病患间的"知识中介"角色。（雷紫雯，《"知识摆渡人"》）',
        '迥异于传播学过往对知识的研究主要强调大众媒体和社交媒体等在知识传播与扩散方面的影响，本研究则"回归人类"，从知识传播与中介的角度切入，通过对职业陪诊师工作的田野观察与深度访谈，探究陪诊师如何中介和转译医疗健康领域的相关知识，以及他们如何通过"摆渡知识"的陪诊实践嵌入医疗健康系统，发挥认知层面的知识桥接与补足作用。（雷紫雯，《"知识摆渡人"》）',
    ],
    "quantitative": [
        '作为"集体注意力的授权管理者"，新闻媒体长期承担着可见性创建与管理的功能，协调和影响的范围涵盖事件、人物、群体及各类辩论、争议、叙事。正如马特·卡尔森所言，可见性作为新闻机构与公众互动的属性，是新闻机构的常态价值目标，也是其合法性与生命力的重要来源。换言之，对新闻媒体而言，可见性的创建与管理不仅是静态功能，更是动态追求，新闻机构由此构筑权威与社会信任。（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
        '学界虽已关注到算法作为"转义者"对可见性的再赋，但对推荐算法在削弱新闻机构可见性控制的同时、又将其置于可见性管理之下的机制，仍缺乏细致的实证检验。这一问题关涉智媒时代新闻传播的公共性与公正性，亟须探索可行的可见性管理之策。基于此，论文通过虚拟代理测试驱动的算法审计，回应以下核心问题：算法平台如何塑造新闻机构的可见性？这一机制在何种情境与因素作用下会出现弹性变化？（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
    ],
    "mixed": [
        '数据是一种权力，谁拥有了数据，谁就掌握了权力。站在劳动技术控制的视角，本文聚焦N企业的算法实验与中央大脑系统，研究算法系统的前端数据采集与末端指令执行的人类劳动过程。技术升级并未带来人的解放，反而出现电子圆形监狱式的全景监控，引发"技术升级"与"劳动降级"的悖论。（刘战伟，《"蜂王"统令"工蜂"》）',
        '作为"集体注意力的授权管理者"，新闻媒体长期承担着可见性创建与管理的功能。学界虽已关注到算法作为"转义者"对可见性的再赋，但对推荐算法在削弱新闻机构可见性控制的同时、又将其置于可见性管理之下的机制，仍缺乏细致的实证检验。这一问题关涉智媒时代新闻传播的公共性与公正性，亟须探索可行的可见性管理之策。（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
    ],
    "interview_report": [
        '三大日系便利店巨头7-11、全家、罗森，在中国开出2000家店，分别用了15年、16年和23年，N企业只用了3年。有人提问："N企业和7－11有什么区别？"其答复："表面上看，我们是一家连锁便利店，其实我们是一家数据科技公司。"迥异于传统便利店，N企业依托人工贴拍信息采集员、监控摄像头与智能传感器大规模采集数据，训练算法模型，开展了一项让中央大脑全面接管人类决策的算法实验。（刘战伟，《"蜂王"统令"工蜂"》）',
        '一个店二三十个摄像头，监控时时刻刻在监视你，要是离开监控区域3分钟以上后台就会语音喊你，问你在干嘛！马上回到监控区域。晚上夜班即使没人也不能休息，每15分钟没有动静，员工就要面临罚款（N2，2022年3月26日）。你刚查完库存，明知道没货了，但没有找货的动作是需要扣钱的，还有咖啡机的问题，机器人喊三声没加奶或者清洗咖啡机就扣钱。N企业所有的钱都用来买监控了，他不仅是为了监督顾客，更是监督员工（N4，2022年3月30日）。（刘战伟，《"蜂王"统令"工蜂"》）',
    ],
    "theoretical": [
        '尽管"可见性"并未以高度理论化的形式密集出现于中国新闻传播学教材和专著中，但回顾其在传播学的建构与发展，不难发现其基础性作用。在人际传播情境下，早如齐美尔已探讨了凝视所产生的互视可见性；在大众传播情境下，约翰·汤普森转向关注印刷媒体、电视等媒介对社会行动者可见性的影响；在网络传播情境中，杰弗里·特里姆等人又提出了"传播可见性"的三重维度，强调用户管理可见性的可供性与可能性。（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
        '二者共同的局限在于，无法解释可见性如何随着情境变化和时间推移而诞生、演变或消亡。也就是说，关于情境与过程的研究视角相对缺乏。作为可见性研究的代表性人物，布里根蒂在理论化"可见性"时，先以制度为其定位，将其界定为"或多或少固定的互动模式"，并强调其"高度依赖情境及社会、技术、政治的复杂安排"，突显其动态性和情境化特点。（黄阳坤，《平台算法如何形塑新闻机构的可见性？》）',
    ],

    # ===== v6.5 同步新增：12个学者/细分声音锚点（从 generation 同步，Dict->List 格式转换）=====
    "computational_zhou": [
        '随着计算方法的快速发展，超越文本的视觉计算传播研究开始兴起，但是仍主要体现为单一模态研究（只是从文本转向视觉）。本文强调，在媒体内容消费多模态化的时代背景下，我们应当高度重视多模态计算传播研究的发展。通过对SSCI、A&HCI等核心数据库中的31篇多模态计算传播研究的内容分析，我们梳理了现有研究概况、理论概念、研究模式与操作方法。研究发现：多模态计算传播研究发展较晚，亟待加强；研究模式呈现多模态关系（独立/组合）×研究目的（描述/解释）的四个分类。（周葆华，《超越单一模态：多模态计算传播研究的进展与前瞻》）',
        '时间自然流逝，但被赋予意义。2020年是历史切片中的一年，但置于社交与智能媒介的新传播语境下，年度网络热点事件也折射出时代性的舆论特征。本文以2020年网络热点事件为例，阐释两个值得重视的舆论特征维度——"出圈"与"折叠"，分析其背后的传播逻辑，并探讨其对于媒体内容生产的意义与启示。（周葆华，《出圈与折叠：2020年网络热点事件的舆论特征及对内容生产的意义》）',
        '在体现"意见气候感知"的不同维度上，与社会上多数人意见、与身边多数同学意见、以及与多数网友意见的一致程度对网络意见表达并无显著影响；与此同时，与家长意见的不一致、以及与主流媒体意见的不一致不仅不会抑制大学生的网络意见表达，反而具有显著的促进作用，其对大学生网络意见表达的独立正向影响达到统计检验上的显著程度。（周葆华，《大学生网络意见表达及其影响因素的实证研究》）',
    ],
    "theoretical_deng": [
        '2022年中国的马克思主义新闻观研究主要表现为对马克思主义新闻观经典论述的时代化阐释、对中国共产党新闻事业的多样化解读、对新时代马克思主义新闻观研究的中国化探索，呈现出继承与创新、理论与实践、总结与展望三大鲜明特征。与此同时，新时代十年间的习近平新闻舆论思想得到凝练与深化；党的二十大精神、中国新闻传播学自主知识体系建设成为研究新热点，进一步巩固了马克思主义新闻观在中国新闻事业的核心地位，开辟了新时代马克思主义新闻观新境界。（邓绍根，《立足中国、回应时代：2022年中国的马克思主义新闻观研究》）',
        '2019年是中国具有重要历史纪念意义的一年，它不仅是中华人民共和国诞生70周年，而且是改革开放40年后再出发的新起点。在这一重要的历史节点上，中国的马克思主义新闻观沿着历史溯源、理论创新和实践指导三种研究路径，进行了新探索，取得了新突破，获得了新成果。以"马克思主义新闻观"为关键词，通过中国人民大学中文学术资源发现平台检索，截止到2020年1月1日，共检索到615条结果，发表在中文核心期刊上的论文达到127篇。（邓绍根，《新起点、新探索：2019年中国的马克思主义新闻观研究综述》）',
        '2022年马克思主义新闻观经典研究呈现出"继承"与"突破"两大鲜明特征。前者详细梳理马克思、恩格斯、列宁等马克思主义经典作家的报刊活动及其新闻宣传思想，解读马克思主义新闻观的历史价值、思想内涵；后者以马克思主义新闻观认识论为出发点，突破原有范式，对马克思主义新闻观的核心概念进行创造性阐释。如唐荣堂著作《马克思主义新闻观核心概念（宣传篇）》，从马克思主义有关宣传的核心概念入手，以马克思主义经典作家的文献、言论等为依据，梳理和阐释马克思主义的宣传理论。（邓绍根，《立足中国、回应时代：2022年中国的马克思主义新闻观研究》）',
        '综上所述，2019年中国的马克思主义新闻观研究成果丰硕，形势喜人，体现了学界以马克思主义新闻观为指导构建中国特色社会主义新闻理论体系的高度自觉，马克思主义新闻观研究不断追求历史逻辑、理论逻辑与现实逻辑的有机统一，既反映了马克思主义新闻观在坚守中创新，在继承中发展的历史脉络，也体现了马克思主义新闻观关照现实、指导实践的价值追求，是马克思主义理论与时俱进理论品质的生动写照。（邓绍根，《新起点、新探索：2019年中国的马克思主义新闻观研究综述》）',
    ],
    "theoretical_tong": [
        "习近平把哲学社会科学分为马克思主义学科、支撑学科、优秀重点学科、新兴学科和交叉学科、具有重要文化价值和传承意义的'绝学'以及冷门学科等几类。他把新闻学列为支撑学科之一，并且对这门学科借以依存的新闻传播事业巨大的社会功能给予充分的肯定和评价。（童兵，《试论习近平新时代新闻舆论工作论述对马克思主义新闻观的发展》）",
        '习近平在讲话中列举当前严重影响网络安全、妨碍网络空间清朗的一些表现，比如，利用网络鼓吹推翻国家政权，煽动宗教极端主义，宣扬民族分裂思想，教唆暴力恐怖活动。这些表现构成了新时代新闻舆论工作必须直面的问题情境。（童兵，《试论习近平新时代新闻舆论工作论述对马克思主义新闻观的发展》）',
        '这些重要论述对马克思主义新闻观的发展有六个方面的理论贡献：其一，关于新闻舆论工作地位作用的新概括；其二，关于新闻舆论工作职责使命的新定位；其三，关于新闻舆论工作方针原则的新阐述；其四，关于新闻舆论工作创新发展新要求；其五，关于新闻舆论工作队伍建设新论述；其六，关于党管媒体原则的新发展。（童兵，《试论习近平新时代新闻舆论工作论述对马克思主义新闻观的发展》）',
    ],
    "theoretical_zheng": [
        "回顾和总结中国共产党百年新闻思想形成与发展的历史可以发现，党在创办新闻事业的过程中所关注和解决的核心问题，集中在'为什么办报''为谁办报''办什么样的报纸'和'怎样办好报纸'等几个方面。（郑保卫，《马克思主义新闻观中国化时代化的发展进程、基本特点及思想启示》）",
        '回顾党的百年奋斗历史可以发现，中国共产党人办报的宗旨和目的都是为了革命，为了党和人民的事业。这一办报传统自党诞生之初便已确立，并贯穿于百年新闻实践的全过程。（郑保卫，《论党的十八大以来习近平创新发展马克思主义新闻观的理论贡献》）',
        '综观习近平在地方上的从政经历，从梁家河到中南海，从大队党支部书记到党的总书记，他的新闻宣传舆论观的形成有着深厚的实践基础和思想渊源。正是在此基础上形成了习近平新时代新闻观，为马克思主义新闻观的当代发展贡献了思想智慧和理论成果。（郑保卫，《习近平新闻宣传舆论观的形成背景及理论创新》）',
    ],
    "theoretical_chen": [
        "由于历史原因，中国共产党的一些政治概念来自俄国的列宁而不是德国的马克思。典型的概念如'党性'，它直接译自斯拉夫语族的俄文'партийность'，即党的意识、党的观念。这是一个性质形容词词干+ость的名词结构，是一种表示性质的抽象概念。（陈力丹，《党性和人民性的提出、争论和归结》）",
        "由于德文、英文等日耳曼语族文字的构词法与斯拉夫语族俄文的差异，马克思恩格斯的著作中没有使用过列宁和中国意义的'党性'概念，但他们在论证党的出版物时，各使用过一次'党的精神'的概念。（陈力丹，《党性和人民性的提出、争论和归结》）",
        "俄文名词партия翻译为'党'；形容词партийный翻译为'党的'；名词化的形容词партийность被翻译为'党性'。这一概念演变历经从马克思到列宁再到中国共产党历史实践的长时段演进，其内涵在不同历史时期呈现出差异化特征，体现了概念迁移中的语义重构。（陈力丹，《党性和人民性的提出、争论和归结》）",
    ],
    "theoretical_zhouyong": [
        '新闻传播学的元问题是什么？对这个问题的探讨首先要回到本体论层面。顾名思义，新闻传播研究的对象是信息传播，这也是作为实践层面的新闻传播事业的主体特征。（周勇，《从元问题出发：中国特色新闻传播学知识体系的建构逻辑与实践进路》）',
        "新闻传播学的一个重要特质就是关注'对话与沟通'及由此对'共识与秩序'的促成，进而推进人类文明和文化的理解与融合。然而，长期跑马圈地扩张而以添砖加瓦方式累积形成的知识碎片，难以回应数字时代的学科根本命题。（周勇，《从元问题出发：中国特色新闻传播学知识体系的建构逻辑与实践进路》）",
        '有组织的信息传播的根本意义不在于信息内容本身，而是以对话、交流促进社会的沟通。新闻传播学的元问题可表述为：新闻传播作为一种以体系化的信息传播为取向的实践活动，如何通过影响人的个体发展以及人与社会关系的构建，促进人与社会的良性发展以及信息传播体系自身的进化。（周勇，《从元问题出发：中国特色新闻传播学知识体系的建构逻辑与实践进路》）',
    ],
    "computational_yu": [
        '学术期刊跨平台传播指的是学术期刊提供的内容在纸本、网站、数据库以及社交媒体平台上的发布与传播。学术期刊跨平台传播可分为四个层次：第一层次是知识传播源头，主要是纸质期刊原版内容；第二层次是呈现在学术期刊自有网站上的内容；第三层次指的是知识传播的图谱化，即期刊内容进入各类期刊文献数据库；第四层次是基于社交媒体平台的跨圈层、跨学科知识的扩散与引流。（禹卫华，《融媒体背景下学术期刊跨平台传播：态势、问题与进路》）',
        '31个省级卫健委政务新媒体对疫情的响应时间不一，其中，1月19日是重要的响应节点之一。重大突发公共卫生事件中政务传播的响应机制亟待系统检视，其议题分布与功能定位亦需实证考察。（禹卫华，《重大突发公共卫生事件的政务传播：响应、议题与定位》）',
        "研究发现，政务传播呈现'响应-议题-定位'三维度框架：响应维度关注时效性与平台差异，议题维度关注内容聚焦与议程设置，定位维度关注功能角色与传播策略。数据进一步显示，跨平台传播的四个层次之间存在显著的非均衡性特征，知识传播的图谱化层次承载了主要的学术影响力。（禹卫华，《重大突发公共卫生事件的政务传播：响应、议题与定位》）",
    ],
    "qualitative_bu": [
        "田野关涉人类学家该在'哪里'从事研究。人类学发展百余年来，'田野'概念已历经多次解构与重构。然则，面对互联网与数字技术的快速发展和网络民族志的兴起，'虚拟田野'的合法性悬而未决。（卜玉梅，《网络民族志的'虚拟田野'诠证》）",
        "建基于'原型'的现实田野逐渐与'地点'脱钩，并在人与物日益流动的背景下，逐步与经典社区形态相分离。这一变迁为网络民族志的兴起提供了学科史背景，亦使'虚拟田野'的合法性成为亟待论证的方法论命题。（卜玉梅，《网络民族志的'虚拟田野'诠证》）",
        "建基于原型，田野首先与特定空间工作的精神想象关联起来，田野工作应该包括一系列的旅行，一种空间上的移动和转换。从'摇椅上的人类学家'到'走向田野的人类学家'，马林诺夫斯基范式革命确立了'原型田野'的学科地位。然则，'虚拟田野'的合法性依然悬而未决，以适应社会政治变迁、关怀人类文明和人类生存境遇为导向的田野实践正在经历深刻变革。（卜玉梅，《网络民族志的'虚拟田野'诠证》）",
    ],
    "theoretical_zhi": [
        "马克思主义新闻观以'嵌入性视角'来诠释新闻与人民的关系，与西方新闻观存在根本的区别。马克思主义新闻观从源头开始，其价值立场一直是人民群众的立场。（支庭荣，《马克思主义新闻观：理论视角、内在逻辑和价值关怀》）",
        "通过宣传与组织的复合机制、政党与群众的有机联系、鼓动与引导的正向性、事实与价值的统一性，马克思主义成功实现了新闻与人民力量的嵌合。这一'嵌入性视角'构成了马克思主义新闻观的核心理论视角，亦是其区别于西方新闻观的根本所在。（支庭荣，《马克思主义新闻观：理论视角、内在逻辑和价值关怀》）",
        "与西方传播学'认知-情感-社会整合-文化传承'功能论不同，马克思主义新闻观强调新闻传播的'能动作用'。其内在逻辑体现为四机制：宣传与组织的复合机制、政党与群众的有机联系、鼓动与引导的正向性、事实与价值的统一性。其价值关怀则以人民为中心，并致力于构建人类命运共同体。（支庭荣，《马克思主义新闻观：理论视角、内在逻辑和价值关怀》）",
    ],
    "theoretical_shen": [
        '纵观习近平的成长环境、生活阅历与奋斗历程，我们可以梳理出这样一条非常明晰的思想发展轨迹，那就是从梁家河的早期萌芽，到西子湖畔的理论实践，再到中南海的全面发展。（沈正赋，《习近平关于新闻舆论工作重要论述：逻辑起点·发展脉络·理论内核》）',
        '习近平新时代中国特色社会主义思想形成和发展的时空脉络十分明晰，理论与实践的有机结合水乳交融、相得益彰，从感性到理性的升华和腾挪浑然天成、相映生辉。（沈正赋，《习近平关于新闻舆论工作重要论述：逻辑起点·发展脉络·理论内核》）',
        "沿着从有形之'河'（梁家河）、有形之'湖'（西湖）到无形之'海'（中南海），从形而下之'河''湖'到形而上之'海'的发展轨迹，习近平关于新闻舆论工作重要论述的逻辑起点奠基于马恩列新闻观与中国共产党历代领导人新闻观，其发展脉络贯穿中国革命建设改革实践，其理论内核聚焦于新时代新闻舆论工作的使命任务。（沈正赋，《习近平关于新闻舆论工作重要论述：逻辑起点·发展脉络·理论内核》）",
    ],
    "theoretical_yang": [
        "马克思主义新闻观是从马克思主义视角形成的关于'新闻是什么、应该是什么、应该如何做新闻'的系统看法，'如何做新闻'就是关于实践的问题。（杨保军，《马克思主义新闻观研究的'转向'：从'史论偏重'到'史论与实践并重'》）",
        "马克思主义是实践的哲学。马新观源于实践，又以解决实践问题为目标。尽管史论研究具有基础地位，但马新观本身拥有强烈的实践指向性和开放性。（杨保军，《马克思主义新闻观研究的'转向'》）",
        "任何一件具体的新闻事实，都是由部分构成的整体，因而，关于新闻事实的反映和报道，就涉及到部分真实与整体真实的关系问题。当代中国主导性新闻真实观的特征表现为：事实真实、过程真实、统一真实三点。统一真实观的主要内涵包含三个层次：既要关注'坏'的新闻事实，也要关注'好'的新闻事实，既要关注新闻价值突出的事实，也要关注新闻价值不那么明显的事实。（杨保军，《统一性：当代中国马克思主义新闻真实观的典型特征》）",
        "必须真诚说明的是，本文对'转向'问题的讨论仍然属于'纸上谈兵'，发出的主要是呼吁。马新观研究应从'史论偏重'转向'史论与实践并重'，这一转向的实质、根据与途径构成了一个完整的研究议程。（杨保军，《马克思主义新闻观研究的'转向'》）",
    ],
    "theoretical_li": [
        '2022年中国的马克思主义新闻观研究主要表现为对马克思主义新闻观经典论述的时代化阐释、对中国共产党新闻事业的多样化解读、对新时代马克思主义新闻观研究的中国化探索，呈现出继承与创新、理论与实践、总结与展望三大鲜明特征。（李兴博，《立足中国、回应时代：2022年中国的马克思主义新闻观研究》）',
        '新时代十年间的习近平新闻舆论思想得到凝练与深化；党的二十大精神、中国新闻传播学自主知识体系建设成为研究新热点，进一步巩固了马克思主义新闻观在中国新闻事业的核心地位，开辟了新时代马克思主义新闻观新境界。（李兴博，《立足中国、回应时代：2022年中国的马克思主义新闻观研究》）',
        "2022年马克思主义新闻观经典研究呈现出'继承'与'突破'两大鲜明特征。前者详细梳理马克思、恩格斯、列宁等马克思主义经典作家的报刊活动及其新闻宣传思想，解读马克思主义新闻观的历史价值、思想内涵；后者以马克思主义新闻观认识论为出发点，突破原有范式，对马克思主义新闻观的核心概念进行创造性阐释。（李兴博，《立足中国、回应时代：2022年中国的马克思主义新闻观研究》）",
    ],
    "theoretical_ethnic": [
        '费孝通先生提出的"中华民族多元一体格局"，为我们理解中华民族共同体认同提供了一个经典框架。但已有研究多聚焦于制度层面的共同体建构，较少关注"记忆"在共同体认同中的多层整合功能。本文基于对知青群体、抗震救灾、国庆阅兵三种不同类型的集体记忆事件的田野调查，提出"记忆的多层性"这一概念——中华民族共同体认同并非在单一层面上形成，而是在个体记忆、社区记忆、区域记忆、国家记忆乃至跨国记忆的多层次互动中不断建构与整合。（麻国庆，《记忆的多层性与中华民族共同体认同》）',
        '中国是一个统一的多民族国家，费孝通曾用"多元一体"概括中华民族的结构特征。但"一体"如何从"多元"中生成？已有研究多从制度安排、政策实践、经济发展等层面回应这一追问，较少从记忆与情感的维度加以阐释。本文尝试提出"记忆的多层性"概念，以补充和推进既有讨论。（麻国庆，《记忆的多层性与中华民族共同体认同》）',
        "研究发现，在个体记忆的层面上，知青群体的'上山下乡'记忆作为创伤性共同经验，形成了一种跨越地域和代际的情感纽带；在社区记忆层面，抗震救灾中的邻里互助和社区重建被叙事化为'一家人'的共同体隐喻；在国家记忆层面，国庆阅兵等仪式通过媒介传播将个体体验转化为国家认同的集体表象。这三种记忆类型并非孤立运作，而是在'个体—社区—区域—国家'的多层次互动中不断建构和整合，由此形成中华民族共同体的记忆基础。（麻国庆，《记忆的多层性与中华民族共同体认同》）",
    ],
    "qualitative_rural": [
        '如何理解乡村治理的内卷化？本文从资源输入的视角出发，分析了取消农业税以后国家向农村转移支付大幅增加背景下，乡村治理出现的"内卷化"困境——即国家资源输入越多，基层治理能力反而越弱。这种悖论的产生，源于乡村利益共同体的解体与基层组织的悬浮化。要走出内卷化困境，资源下乡需要与组织下乡、制度下乡同步进行。（贺雪峰，《论乡村治理内卷化》）',
        '取消农业税以前，乡村治理的基本格局是"收粮派款、刮宫引产"；取消农业税以后，国家向农村转移支付大幅增加。一个看似矛盾的现象随之出现：资源输入增加了，但基层组织的治理能力反而下降了。村干部从"要钱要粮"变成"送钱送物"，村民从"被索取"变成"被给予"——表面上看是好事，但深层看却是乡村治理"内卷化"的开始。（贺雪峰，《论乡村治理内卷化》）',
        "研究发现，乡村治理内卷化表现为三重矛盾：资源输入增加与治理效率下降之间的'资源悖论'、项目下乡与村级负债之间的'项目陷阱'、考核压力增大与公共服务弱化之间的'考核困境'。这三重矛盾的根源在于：取消农业税以后，村干部'悬浮'于村庄社会之上，不再需要与村民打交道就能完成上级交办的任务；村民则'原子化'为分散的利益个体，缺乏组织化参与的渠道和能力。由此，资源输入越多，村庄内部的利益分配冲突越剧烈，治理内卷化越严重。（贺雪峰，《论乡村治理内卷化》）",
    ],
    "theoretical_concept": [
        '"民族"一词在中国古代汉语中并非舶来品。通过对《南齐书》《太白阴经》《三朝北盟会编》等古代文献的考证，本文证明"民族"一词在19世纪末之前已多次出现于中文典籍之中，推翻了"汉语民族一词最早见于1899年"的成说。对这一概念源流的考辨，不仅关涉词源学的问题，更关涉中国多民族国家的历史认知与当代建构。（郝时远，《中文"民族"一词源流考辨》）',
        '学界长期认为，中文"民族"一词最早见于1899年梁启超的《东籍月旦》，是从日文"民族"（みんぞく）借入的近代汉字词。这一成说被广泛征引，几乎成为民族学界的常识。然而，本文通过对《南齐书》《太白阴经》《三朝北盟会编》等古代文献的梳理，发现"民族"作为一个双音节名词在中文典籍中出现的时间远远早于19世纪末——这提示我们有必要重新审视"民族"一词的语源与语义变迁。（郝时远，《中文"民族"一词源流考辨》）',
        "考证表明：其一，《南齐书》卷五十四《高逸传·顾欢传》中已出现'民族'一词，时为公元5世纪末，早于日本明治时期约1400年；其二，唐代《太白阴经》序言中'民族'一词再次出现，指称特定的人类群体；其三，宋代《三朝北盟会编》中'民族'多次使用，已具备'具有共同语言、共同地域、共同经济生活和共同文化心理的人们共同体'的基本语义。这些证据表明，'民族'一词确属中国古代汉语的名词，而非近代日文汉字词的借入。（郝时远，《中文'民族'一词源流考辨》）",
    ],
    "sociological_theory": [
        '改革开放以来，中国的国家治理经历了从"总体支配"到"技术治理"的深刻转型。本文基于30年改革经验的社会学分析，考察了这一转型的制度逻辑与意外后果。研究发现，从双轨制下的模糊产权运行到分税制后的项目制治理，国家权力在从总体性支配撤退的过程中，通过技术化的方式重新渗透进经济与社会领域，形成了新的治理格局——但这一格局同样面临着社会公平危机与系统性风险。（渠敬东、周飞舟、应星，《从总体支配到技术治理》）',
        '改革开放以来的30年，是中国的国家治理从"总体支配"向"技术治理"转型的30年。这一转型并非简单的制度替代，而是在新旧体制的衔接与博弈中展开的复杂过程：从1980年代的双轨制到1990年代的市场化，再到2000年代以来的项目制，每一次制度变革都夹带着多重的意图、产生了复杂的意外后果。本文将这一过程作为理解中国国家治理演变的核心线索。（渠敬东、周飞舟、应星，《从总体支配到技术治理》）',
        "分析表明，改革开放30年的国家治理转型呈现三阶段的演变逻辑：第一阶段（1980年代），双轨制以集体制为核心，在模糊产权中创造了经济增长的空间，但也埋下了权力寻租的隐患；第二阶段（1990年代），市场化改革确立了'经济增长至上'的发展策略，但同时使社会公平在后期陷入危机；第三阶段（2000年代至今），项目制以技术治理的方式突破了单位制的束缚，却在原行政体制之外形成了新的'项目权力'，将基层社会裹挟进庞大的金融资本链条之中。（渠敬东、周飞舟、应星，《从总体支配到技术治理》）",
    ],
    "chuanboxue_peng": [
        '互联网发展的一个重要线索，是人与人的连接的演变，连接也已成为互联网的一个内在法则。但今天人们也在面临着过度连接的重负，例如强互动下的倦怠与压迫感、圈层化对个体的约束及对社会的割裂、线上过度连接对线下连接的挤占、人与内容过度连接的重压等。过度连接的背景下，适度的反连接或许将成为互联网的一种新法则，它是用户在必要情境下的一种新选择。（彭兰，《连接与反连接：互联网法则的摇摆》）',
        '纵观以往的历史，互联网的运动更像是一种钟摆式的运动，从它的运行法则到具体的产品，都在不断摇摆。不同时期的不同连接模式，在不同方向上满足了人们的社会关系需求，在连接模式的演变中，也存在着远距离与近距离、匿名与实名、弱关系与强关系等关系属性的摇摆。但今天人们在享受连接便利的同时，也面临着过度连接的重负。（彭兰，《连接与反连接：互联网法则的摇摆》）',
        "研究表明，过度连接表现为五个维度：强互动下的倦怠与压迫感、圈层化对个体的约束及对社会的割裂、线上过度连接对线下连接的挤占、人与内容过度连接的重压、对'外存'的过度依赖。反连接并不是无条件切断所有连接，而是在一定的情境下断开那些可能对个体产生过分压力与负担的连接链条，使个体恢复必要的私人空间、时间与个人自由——这也意味着，未来的产品需要适度的减法和克制思维。（彭兰，《连接与反连接：互联网法则的摇摆》）",
    ],
    "quantitative_generation": [
        '本文厘清了数字反哺的理论渊源和概念维度，并在家庭传播视域下考察其现状及影响因素。以全国54座城市954个家庭3291位祖孙三代样本的问卷调查数据为基础，我们在数字接入反哺、技能反哺和素养反哺的三大维度上进行了不同世代的分析与对比。就反哺现状而言，年轻世代"给出去的反哺"与年长世代"接受到的反哺"大体能达成共识，但仍有三成左右互相矛盾。（周裕琼，《中国家庭三代数字反哺现状及影响因素研究》）',
        '通过配对比较同一个家庭内父母与子女所采纳的新媒体数量，我们发现了一条横亘在亲子两代之间显著的数字代沟。平均而言，父母采纳了4.46种新媒体，而子女采纳了5.73种新媒体，两者相差1.26，使用paired samples t-test进行统计检验，两者之间的差距具有统计显著性（t=8.44，p=.000）。有趣的是，文化反哺程度越深的家庭，亲子关系越和谐，子女在父母眼中的地位也越高。（周裕琼，《数字代沟与文化反哺》）',
        '笔者初次关注数字代沟与数字反哺时，借用了美国学者弗瑞尔"数字难民"的比喻来形容被新媒体浪潮边缘化的老年人。随着研究的不断深入，笔者越来越认识到老年人是"数字弱势群体"而非"数字难民"。弱势并不意味着"可怜"，而是蕴藏希望与力量。（周裕琼，《中国家庭三代数字反哺现状及影响因素研究》）',
    ],
    "theoretical_indigenous": [
        '在本研究展开之前，我首先将中国社会预设为一种情理合一的社会，从而使此种社会中发生的人情面子全然不同于西方人的类似心理和行为。在中国社会，我们在经验中便可以发现大多数人的办事和处世原则既不会偏向理性，也不会偏向非理性，而是希望在两者之间做出平衡和调和。（翟学伟，《人情、面子与权力的再生产》）',
        '于是，这样的社会对做人、做事及其判断不是单从理性的、逻辑的思维和条文制度规定的角度来考虑，还从具体的、情境的和个别性来考虑。所谓"合情合理""入情入理""通情达理""酌情处理"和"情理交融"，或"于情于理如何如何"的意思都是希望人们做人做事时兼顾情和理。（翟学伟，《人情、面子与权力的再生产》）',
        '总之，人情偏向的是交换上的一对一的关系，因此它的回报方式就不是正面评价的问题，而是实惠和实质性的帮助；而面子偏向的是赋予交往关系以价值判断。或者说，平时多做人情，就会得到较大的面子，平时不讲人情，就得不到面子。（翟学伟，《人情、面子与权力的再生产》）',
    ],
    "chuanboxue_yu": [
        '互联网已成为标识这个时代的关键词，但它不仅仅是一个媒介，更本质的意义就在于它是一种重新构造世界的结构性力量。互联网比我们过去所面对的那些传统媒介都多出一个维度，生长出一个新的社会空间、运作空间、价值空间。"高维"媒介是不可能用传统媒介的运作和管理方式去管理和运作的——用"低维"的方式去管"高维"是没有用的。（喻国明，《互联网是一种"高维"媒介》）',
        "迄今为止，我们对于互联网本身的理解可能还处在一种肤浅的水平上。用马克思的话来说，还处在'必然王国'的状态，远还没有进入'自由王国'的境地。事实上，互联网不仅仅是一个媒介，更本质的意义就在于它是一种重新构造世界的结构性力量，这是它真正的意义。解决战略问题远比解决战术问题更重要——'提领而顿，百毛皆顺'。（喻国明，《互联网是一种'高维'媒介》）",
        "一部媒介发展史，就是人类凭借媒介的升级迭代不断地突破现实世界的限制走向更大自由度的过程。正如麦克卢汉所言，'任何的新媒介都是一个进化的过程，一个生物裂变的过程，它为人类打开了通向感知和新型活动领域的大门'。新媒介之'新'，本质上是看它是否为人类社会的连接提供新的方式、新的尺度和新的标准——从'场景时代'到'元宇宙'再到'心世界'，未来媒介的进化方向是从'向外'扩张到'向内'深化，再到'升维'重构。（喻国明，《未来媒介的进化逻辑》）",
    ],
}

# v1.1 新增：节奏要求——基于真实论文实测值校准
RHYTHM_REQUIREMENTS: Dict[str, Any] = {
    "sentence_length_variance": {"min": 8.0, "max": 25.0, "ideal": 15.0},
    "paragraph_opening_diversity_min": 0.6,
    "max_consecutive_same_opening": 2,
    "short_sentence_ratio_min": 0.15,  # 短句（≤15字）占比≥15%
    "long_sentence_ratio_max": 0.40,   # 长句（>50字）占比≤40%
}

# v1.1 新增："人味"特征清单——修改Agent必须体现至少5项
HUMAN_VOICE_FEATURES: List[str] = [
    "戏剧性经验开篇——用具体数据/案例/引语开篇，不用'随着...的发展'",
    "格言式判断——用短句收束核心判断（如'数据是一种权力。'）",
    "悖论揭示——揭示'技术升级却带来劳动降级'式的反直觉发现",
    "反思追问——用'我们不禁要反思追问...'建立认知期待",
    "从个案到公共议题——'从个案上升至公共议题...'",
    "理论谦逊——'本研究从...出发'，而非'本研究创新性地...'",
    "自然缺口陈述——'然而，关于...我们知之甚少'",
    "批判性理论评估——'二者共同的局限在于...'",
    "高密度隐喻概念——如'蜂王/工蜂''幽灵劳动''电子圆形监狱'",
    "学者递进对话——'Dayan→Carlson→Thompson'式理论脉络",
    "历史演进判断——'在X时代，权力来源于Y'式排比",
    "俗语嵌入——'巧妇难为无米之炊'等中国俗语自然嵌入",
    "差异化定位——'迥异于X过往对Y的研究...'",
    "三重角色命名——'知识专家''知识领航人''知识修补师'",
    "中国语境强调——'在中国，随着X的深入推进...'",
]


# ============================================================================
# 约束注入器核心实现
# ============================================================================

class ConstraintInjector:
    """
    约束注入器：在每轮循环开始时为各 Agent 注入上下文。

    注入内容包括：
    1. 风格约束（从 config.py 的 STYLE_RULES 读取）
    2. ★用户初始指令快照（防止多轮后遗忘）
    3. 上一轮违规记录（style_violations）
    4. 上一轮评审反馈（review_feedback）
    5. 共享学习档案（user_style_profile）
    """

    def __init__(self, style_rules: Optional[Dict] = None):
        """
        初始化约束注入器。

        参数:
            style_rules: 风格规则字典。若为 None，则从 config.py 动态加载。
        """
        self.style_rules = style_rules or self._load_style_rules()
        self._snapshot_fixed: bool = False  # 标记初始指令快照是否已固化

    @staticmethod
    def _load_style_rules() -> Dict:
        """从 config.py 加载 STYLE_RULES（容错处理）"""
        try:
            # 尝试相对导入（作为包内模块运行时）
            try:
                from .config import STYLE_RULES
                return STYLE_RULES
            except ImportError:
                pass
            # 尝试绝对导入（作为独立模块运行时）
            try:
                from config import STYLE_RULES
                return STYLE_RULES
            except ImportError:
                pass
            # 兜底：使用内置默认规则
            return _DEFAULT_STYLE_RULES
        except Exception as e:
            # 严重错误：返回最小可用规则集
            return {
                "global": {
                    "total_words": 15000,
                    "tolerance": 0.10,
                    "max_dash_count": 15,
                    "max_semicolon_count": 10,
                    "max_colon_per_1000_words": 2,
                }
            }

    def _build_snapshot(self, state: PipelineState) -> str:
        """
        ★新增：构建用户初始指令快照。
        首轮调用时固化快照，后续轮次直接复用，防止多轮循环后指令漂移。

        参数:
            state: 当前 Pipeline 状态

        返回:
            固化后的初始指令快照文本
        """
        # 若已固化，直接返回 state 中的快照
        if self._snapshot_fixed and state.get("initial_instruction_snapshot"):
            return state["initial_instruction_snapshot"]

        initial_instruction = state.get("initial_instruction", "").strip()
        if not initial_instruction:
            # 没有初始指令时返回空快照
            return ""

        # 构建结构化快照（包含原始指令 + 提取的关键要素）
        snapshot_parts = [
            "【用户初始指令快照（请严格遵守，禁止偏离）】",
            f"快照固化时间：{datetime.now().isoformat()}",
            f"研究类型：{state.get('research_type', 'qualitative')}",
            f"目标期刊：{state.get('journal_style', 'xwycbyj')}",
            "",
            "=== 初始指令原文 ===",
            initial_instruction,
            "",
            "=== 关键要素提取 ===",
        ]

        # 简单的关键要素提取（关键词、主题）
        keywords = self._extract_keywords(initial_instruction)
        if keywords:
            snapshot_parts.append(f"核心关键词：{', '.join(keywords[:10])}")

        # 标记已固化
        self._snapshot_fixed = True
        return "\n".join(snapshot_parts)

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """
        从文本中提取关键词（简化版，基于停用词过滤）。

        参数:
            text: 输入文本

        返回:
            关键词列表
        """
        if not text:
            return []
        # 简化实现：按标点切分后过滤过短 token
        import re
        # 去除常见标点
        cleaned = re.sub(r'[，。、；：！？""''（）()\[\]【】《》\s]+', ' ', text)
        tokens = [t.strip() for t in cleaned.split() if len(t.strip()) >= 2]
        # 去重保序
        seen = set()
        keywords = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                keywords.append(t)
        return keywords

    def _build_style_context(self, agent_name: str) -> str:
        """
        为指定 Agent 生成风格约束上下文。

        参数:
            agent_name: Agent 名称（见 AGENT_NAMES）

        返回:
            风格约束文本
        """
        g = self.style_rules.get("global", {})
        parts = [f"【写作风格约束 - {AGENT_CN_NAMES.get(agent_name, agent_name)}】"]

        # 全局约束
        parts.append(
            f"全文字数上限 {g.get('total_words', 15000)} 字"
            f"（±{int(g.get('tolerance', 0.10) * 100)}% 容差）"
        )
        parts.append(
            f"破折号 ≤ {g.get('max_dash_count', 15)} 处，"
            f"分号 ≤ {g.get('max_semicolon_count', 10)} 处"
        )
        parts.append(
            f"冒号密度 ≤ {g.get('max_colon_per_1000_words', 2)} 处/千字"
        )
        parts.append("禁止断裂式表达，禁止空洞修饰语")

        # 章节级约束（按 Agent 职责匹配）
        section_map = {
            "abstract_reviser": "abstract",
            "introduction_reviser": "introduction",
            "literature_review_reviser": "literature_review",
            "findings_reviser": "findings",
        }
        section_key = section_map.get(agent_name)
        if section_key and section_key in self.style_rules:
            section_rules = self.style_rules[section_key]
            if isinstance(section_rules, dict):
                if "words" in section_rules:
                    parts.append(f"本章字数：{section_rules['words']} 字")
                if "forbidden" in section_rules:
                    parts.append(f"本章禁止：{', '.join(section_rules['forbidden'])}")

        # 全文润色者：注入所有章节约束
        if agent_name == "full_text_polisher":
            for section, rules in self.style_rules.items():
                if section in ("global", "title"):
                    continue
                if isinstance(rules, dict) and "words" in rules:
                    parts.append(f"  {section}: {rules['words']} 字")

        # 文献审计者：补充文献相关约束
        if agent_name == "literature_auditor":
            parts.append("中文 CSSCI 期刊文献 ≥ 8 条")
            parts.append("禁止装饰性引用、张冠李戴、DOI 不实")

        # 外审专家：注入评分维度提示
        if agent_name == "external_reviewer":
            parts.append("9 维度评分（阈值 95），每维度需 ≥2 个原文证据")
            parts.append("每条意见必须标注目标 Agent 与修改优先级")

        return "\n".join(parts)

    def _build_voice_context(self, research_type: str) -> str:
        """
        ★v1.1新增：构建声音范本上下文——必须模仿，而非参考。

        核心策略：声音优先、规则兜底。先内化目标文风，再遵守禁止规则。
        将 VOICE_SAMPLES、RHYTHM_REQUIREMENTS、HUMAN_VOICE_FEATURES 注入到
        Agent 指令中，使 Agent 在修改时始终以真实顶刊论文为目标文风。

        参数:
            research_type: 研究类型（computational/qualitative/digital_sociology/
                          quantitative/mixed/interview_report/theoretical）

        返回:
            声音范本上下文文本
        """
        samples = VOICE_SAMPLES.get(
            research_type, VOICE_SAMPLES.get("qualitative", [])
        )
        rhythm = RHYTHM_REQUIREMENTS

        parts = [
            "【目标文风——你必须模仿，而非参考】",
            "以下是你必须模仿的目标文风。你的输出应在句式结构、句长节奏",
            "（长句30-50字铺陈+短句10-20字收束）、概念密度、段落推进方式上",
            "与范本一致。这不是'参考'，而是'目标'——如果你的输出读起来不像",
            "范本那样'一个思维清晰的人在说话'，就是失败。",
            "",
            "=== 范本段落 ===",
        ]

        # 注入前3个范本（避免指令过长）
        for i, sample in enumerate(samples[:3], 1):
            parts.append(f"【范本{i}】\n{sample}\n")

        # 节奏要求
        parts.append("\n=== 节奏要求 ===")
        parts.append(
            f"- 句长方差: {rhythm['sentence_length_variance']['min']}-"
            f"{rhythm['sentence_length_variance']['max']}"
            f"（理想{rhythm['sentence_length_variance']['ideal']}）"
        )
        parts.append(
            f"- 段落开头多样性: ≥{rhythm['paragraph_opening_diversity_min']}"
        )
        parts.append(
            f"- 短句（≤15字）占比: ≥{rhythm['short_sentence_ratio_min']}"
        )
        parts.append(
            f"- 长句（>50字）占比: ≤{rhythm['long_sentence_ratio_max']}"
        )

        # 人味特征清单
        parts.append("\n=== 人味特征清单（修改后至少体现5项）===")
        for i, feat in enumerate(HUMAN_VOICE_FEATURES, 1):
            parts.append(f"{i}. {feat}")

        return "\n".join(parts)

    def _build_violation_context(self, state: PipelineState) -> str:
        """
        构建上一轮违规记录上下文。

        参数:
            state: 当前 Pipeline 状态

        返回:
            违规记录文本（无违规时返回空字符串）
        """
        violations = state.get("style_violations", [])
        if not violations:
            return ""

        parts = ["【上一轮风格违规记录（本轮必须修复）】"]
        for i, v in enumerate(violations, 1):
            parts.append(f"{i}. {v}")
        return "\n".join(parts)

    def _build_review_feedback_context(self, state: PipelineState) -> str:
        """
        构建上一轮评审反馈上下文。

        参数:
            state: 当前 Pipeline 状态

        返回:
            评审反馈文本（无反馈时返回空字符串）
        """
        feedback = state.get("review_feedback")
        if not feedback:
            return ""

        parts = ["【上一轮评审反馈】"]
        if isinstance(feedback, dict):
            score = feedback.get("review_score")
            if score is not None:
                parts.append(f"上一轮总分：{score}")
            dim_scores = feedback.get("dimension_scores", {})
            if dim_scores:
                parts.append("各维度得分：")
                for dim, s in dim_scores.items():
                    parts.append(f"  - {dim}: {s}")
            suggestions = feedback.get("suggestions", [])
            for i, s in enumerate(suggestions, 1):
                parts.append(f"{i}. {s}")
        else:
            parts.append(str(feedback))

        return "\n".join(parts)

    def _build_learning_context(self, state: PipelineState, agent_name: str) -> str:
        """
        构建共享学习档案上下文（用户风格偏好）。

        参数:
            state: 当前 Pipeline 状态
            agent_name: Agent 名称

        返回:
            学习档案文本（无档案时返回空字符串）
        """
        profile = state.get("user_style_profile")
        if not profile or not isinstance(profile, dict):
            return ""

        parts = [f"【共享学习档案 - {AGENT_CN_NAMES.get(agent_name, agent_name)}】"]
        pref = profile.get("user_style_preferences", {})

        if pref.get("hates_colon_in_body"):
            parts.append("⚠ 用户厌恶正文句中冒号，请严格避免")
        if pref.get("prefers_short_paragraphs") is True:
            parts.append("⚠ 用户偏好短段落（150-250 字）")
        forbidden = pref.get("forbidden_phrases", [])
        if forbidden:
            parts.append(f"⚠ 用户反感用语：{', '.join(forbidden)}")
        max_dash = pref.get("max_dash_tolerance", 15)
        if max_dash < 15:
            parts.append(f"⚠ 用户破折号容忍度低：≤ {max_dash} 处")

        theories = profile.get("theoretical_preferences", {}).get("preferred_theories", [])
        if theories:
            parts.append(f"💡 用户偏好理论：{', '.join(theories[-3:])}")

        # 仅当有内容时返回
        if len(parts) > 1:
            return "\n".join(parts)
        return ""

    def inject(self, state: PipelineState) -> PipelineState:
        """
        执行约束注入主流程。

        参数:
            state: 当前 Pipeline 状态

        返回:
            更新后的 Pipeline 状态
        """
        round_num = state.get("round_number", 1)
        error_log = state.get("error_log", [])

        try:
            # ===== Step 1: 固化初始指令快照（★v1.0新增） =====
            snapshot = self._build_snapshot(state)
            if snapshot:
                state["initial_instruction_snapshot"] = snapshot
                error_log.append(
                    f"[第{round_num}轮] ConstraintInjector: 已注入初始指令快照"
                )

            # ★v1.1新增：构建声音范本上下文（声音优先、规则兜底）
            research_type = state.get("research_type", "qualitative")
            voice_context = self._build_voice_context(research_type)

            # ★v1.9新增：将 voice_context 存入 state，供评分节点（ExternalReviewer/AdversarialCritic）使用
            state["voice_context"] = voice_context

            # ★v1.2新增：构建字数预算硬约束（事前约束，防止字数膨胀）
            paper = self._get_current_paper(state)
            current_words = self._count_chinese_words(paper)
            target_words = state.get("user_target_words", 15000)
            tolerance = state.get("word_count_tolerance", 0.1)
            section_words = self._count_section_words(paper)

            # 动态导入 build_word_budget_constraint（避免循环导入）
            try:
                from .config import build_word_budget_constraint as _build_constraint
            except ImportError:
                from config import build_word_budget_constraint as _build_constraint

            word_budget_constraint = _build_constraint(
                target_words=target_words,
                current_words=current_words,
                section_words=section_words,
                tolerance=tolerance,
            )

            # ===== Step 2: 为每个 Agent 生成并注入约束上下文 =====
            for agent_name in AGENT_NAMES:
                instruction_key = f"{agent_name}_instruction"
                # 基础风格约束
                context_parts = [self._build_style_context(agent_name)]

                # ★v1.1新增：注入声音范本（声音优先、规则兜底）
                # 文献审计者不涉及文风修改，跳过声音注入
                if agent_name != "literature_auditor" and voice_context:
                    context_parts.append("")
                    context_parts.append(voice_context)

                # ★v1.2新增：注入字数预算硬约束（每个修改型Agent都需要）
                if agent_name != "literature_auditor" and word_budget_constraint:
                    context_parts.append("")
                    context_parts.append(word_budget_constraint)

                # 注入初始指令快照（每个 Agent 都需要看到，防止遗忘）
                if snapshot:
                    context_parts.append("")
                    context_parts.append(snapshot)

                # 注入上一轮违规记录
                violation_ctx = self._build_violation_context(state)
                if violation_ctx:
                    context_parts.append("")
                    context_parts.append(violation_ctx)

                # 注入上一轮评审反馈
                feedback_ctx = self._build_review_feedback_context(state)
                if feedback_ctx:
                    context_parts.append("")
                    context_parts.append(feedback_ctx)

                # 注入共享学习档案
                learning_ctx = self._build_learning_context(state, agent_name)
                if learning_ctx:
                    context_parts.append("")
                    context_parts.append(learning_ctx)

                # 写入 instruction 字段
                state[instruction_key] = "\n".join(context_parts)

            # ===== Step 3: 记录活跃约束（供 StyleGuard 引用） =====
            state["active_constraints"] = {
                "style_rules": self.style_rules,
                "injected_at_round": round_num,
                "injected_at": datetime.now().isoformat(),
                "agents_injected": list(AGENT_NAMES),
                "voice_samples_injected": research_type,  # ★v1.1新增
                "word_budget_injected": True,  # ★v1.2新增
                "target_words": target_words,
                "current_words": current_words,
            }

            error_log.append(
                f"[第{round_num}轮] ConstraintInjector: 已为 {len(AGENT_NAMES)} 个 Agent 注入约束"
                f"（含声音范本: {research_type}, 字数预算: {target_words}字）"
            )
            state["error_log"] = error_log

        except Exception as e:
            error_log.append(
                f"[第{round_num}轮] ConstraintInjector 异常: {type(e).__name__}: {e}"
            )
            state["error_log"] = error_log

        return state

    @staticmethod
    def _get_current_paper(state: PipelineState) -> str:
        """获取当前论文内容（v1.2新增：辅助字数预算注入）"""
        for key in [
            "full_text_polisher_output",
            "findings_reviser_output",
            "literature_review_reviser_output",
            "introduction_reviser_output",
            "abstract_reviser_output",
            "paper_content",
        ]:
            val = state.get(key)
            if val:
                return val
        return state.get("paper_content", "")

    @staticmethod
    def _count_chinese_words(text: str) -> int:
        """计算中文字数（v1.2新增）"""
        if not text:
            return 0
        import re
        chinese_chars = re.findall(r'[一-鿿]', text)
        return len(chinese_chars)

    @staticmethod
    def _count_section_words(paper: str) -> Dict[str, int]:
        """计算论文各章节的当前字数（v1.2新增）"""
        import re
        section_words = {}

        section_patterns = [
            ("abstract", r"(?:摘\s*要|Abstract)[：:\n]"),
            ("introduction", r"(?:一\s*[、.．]|引\s*言|绪\s*论)[：:\n]"),
            ("literature_review", r"(?:二\s*[、.．]|文献回顾|文献综述|研究综述)[：:\n]"),
            ("method", r"(?:三\s*[、.．]|研究方法|研究设计)[：:\n]"),
            ("findings", r"(?:四\s*[、.．]|研究发现|研究结果|分析与发现)[：:\n]"),
            ("conclusion", r"(?:五\s*[、.．]|结语|结论|讨论与结论)[：:\n]"),
        ]

        positions = []
        for section_name, pattern in section_patterns:
            match = re.search(pattern, paper, re.IGNORECASE)
            if match:
                positions.append((match.start(), section_name))

        positions.sort(key=lambda x: x[0])

        for i, (start, section_name) in enumerate(positions):
            if i + 1 < len(positions):
                end = positions[i + 1][0]
            else:
                end = len(paper)
            section_text = paper[start:end]
            chinese_chars = re.findall(r'[一-鿿]', section_text)
            section_words[section_name] = len(chinese_chars)

        return section_words


# ============================================================================
# 默认风格规则（兜底，当 config.py 不可用时使用）
# ============================================================================

_DEFAULT_STYLE_RULES: Dict[str, Any] = {
    "global": {
        "total_words": 15000,
        "tolerance": 0.10,
        "max_dash_count": 15,
        "max_colon_per_1000_words": 2,
        "max_semicolon_count": 10,
        "max_ellipsis_in_body": 0,
        "forbidden_patterns": [
            "第一，.*第二，.*第三",
            "首先，.*其次，.*再次",
            "一方面，.*另一方面",
        ],
        "forbidden_phrases": [
            "深刻", "极具", "丰富而多元", "复杂而深刻",
            "不可或缺", "至关重要", "众所周知", "不言而喻", "毋庸置疑",
        ],
        "max_words_per_sentence": 60,
        "max_words_per_paragraph": 400,
        "min_words_per_paragraph": 100,
    },
    "abstract": {"words": 350, "forbidden": ["分号", "引号", "破折号", "第一", "第二", "第三"]},
    "introduction": {"words": 600},
    "literature_review": {"words": 2000},
    "method": {"words": 800},
    "findings": {"words": 3750, "min_words": 3500, "max_words": 4000},
    "conclusion": {"words": 1750, "min_words": 1500, "max_words": 2000},
}


# ============================================================================
# Pipeline 节点入口函数
# ============================================================================

def constraint_injector_node(state: PipelineState) -> PipelineState:
    """
    在核心 agent 执行前注入风格约束和初始指令快照。

    作为 LangGraph 节点入口函数，与 Pipeline 主流程兼容。
    每轮循环开始时调用，确保各 Agent 始终在最新约束下工作，
    且不会因多轮迭代而遗忘用户初始指令。

    参数:
        state: 当前 Pipeline 状态

    返回:
        注入约束后的 Pipeline 状态
    """
    injector = ConstraintInjector()
    return injector.inject(state)


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    # 模拟一个初始状态
    demo_state: PipelineState = {
        "paper_content": "（论文初稿内容）",
        "paper_version": 1,
        "round_number": 2,
        "initial_instruction": "请围绕'短视频算法推荐对青少年价值观塑造的影响'展开，"
                               "采用定性研究方法，目标期刊为《新闻与传播研究》。",
        "research_type": "qualitative",
        "journal_style": "xwycbyj",
        "style_violations": ["破折号超限: 18/15", "禁止用语 '至关重要': 2 处"],
        "review_feedback": {
            "review_score": 88,
            "dimension_scores": {"writing_style": 10, "academic_depth": 13},
            "suggestions": ["摘要需删除所有分号", "引言需补充数据锚点"],
        },
        "user_style_profile": {
            "user_style_preferences": {
                "hates_colon_in_body": True,
                "forbidden_phrases": ["在新时代背景下"],
                "max_dash_tolerance": 10,
            },
            "theoretical_preferences": {"preferred_theories": ["议程设置", "框架理论"]},
        },
        "error_log": [],
    }

    result = constraint_injector_node(demo_state)
    print("=== 注入完成 ===")
    print(f"已注入 Agent 数：{len(AGENT_NAMES)}")
    print(f"错误日志条数：{len(result.get('error_log', []))}")
    print("\n=== external_reviewer_instruction 预览 ===")
    print(result.get("external_reviewer_instruction", "")[:500])
