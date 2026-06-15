export const AGENTS = {
  researcher: { id: 'researcher', name: '研究员', icon: '🔬', desc: '学术选题与问题建构专家' },
  reviewer: { id: 'reviewer', name: '审查员', icon: '📋', desc: '研究思路审查与优化专家' },
  architect: { id: 'architect', name: '架构师', icon: '🏗️', desc: '论文架构审查与优化专家' },
  synthesizer: { id: 'synthesizer', name: '综述员', icon: '📚', desc: '文献综述撰写专家' },
  polisher: { id: 'polisher', name: '润色员', icon: '✨', desc: '学术语言润色与AIGC降重专家' },
};

export const AGENT_META = {
  researcher: {
    name: '研究员',
    role: '学术选题与问题建构专家，帮助你明确研究方向、建构问题边界、发现研究空白',
    suggestions: [
      { icon: '🔍', title: '明确研究方向', desc: '我在做[领域]的研究，想探索[方向]，帮我明确研究选题' },
      { icon: '📖', title: '文献检索建议', desc: '帮我搜索关于[关键词]的最新文献，分析研究现状' },
      { icon: '✏️', title: '建构研究框架', desc: '我的研究问题是[问题]，请帮我设计研究框架' },
    ],
    placeholder: '描述你的研究方向，或提出一个研究问题...',
  },
  reviewer: {
    name: '审查员',
    role: '研究思路审查与优化专家，从研究问题明确性、理论框架、方法论、创新性四个维度评估',
    suggestions: [
      { icon: '📋', title: '审查研究思路', desc: '以下是我的研究思路：[描述]，请从4个维度评估' },
      { icon: '📊', title: '评估研究方案', desc: '这是我的研究方案，请从方法论和可行性角度评估' },
      { icon: '💡', title: '改进建议', desc: '我的论文初稿已写好，请审查并给出优化建议' },
    ],
    placeholder: '粘贴你的研究思路，我会从4个维度进行评估...',
  },
  architect: {
    name: '架构师',
    role: '论文架构审查与优化专家，评估逻辑连贯性、章节完整性、论证链路',
    suggestions: [
      { icon: '🏗️', title: '审查论文结构', desc: '以下是我的论文大纲：[大纲]，请帮我优化结构' },
      { icon: '🔗', title: '逻辑连贯性检查', desc: '帮我检查论文各章节之间的逻辑连贯性' },
      { icon: '📝', title: '章节完整性评估', desc: '我的论文包含[章节列表]，是否缺少关键部分？' },
    ],
    placeholder: '描述你的论文结构，我会帮你优化架构...',
  },
  synthesizer: {
    name: '综述员',
    role: '文献综述撰写专家，辅助文献检索与筛选，按主题/方法/时间线组织文献',
    suggestions: [
      { icon: '📚', title: '撰写文献综述', desc: '请帮我撰写关于[主题]的文献综述，涵盖近5年研究' },
      { icon: '🔬', title: '分析研究趋势', desc: '分析[领域]的研究趋势和前沿热点' },
      { icon: '📑', title: '构建理论框架', desc: '帮我构建[领域]的理论框架和概念模型' },
    ],
    placeholder: '输入研究主题，我会帮你检索和分析文献...',
  },
  polisher: {
    name: '润色员',
    role: '学术语言润色与AIGC降重专家，变换句式结构、同义替换、保持原意',
    suggestions: [
      { icon: '✨', title: '学术语言润色', desc: '请润色以下文本使其符合Nature期刊风格：[文本]' },
      { icon: '📝', title: 'AIGC降重', desc: '以下文本的AI检测率过高，请帮我改写：[文本]' },
      { icon: '🔤', title: '英文摘要润色', desc: '请将以下摘要润色为地道的学术英文：[摘要]' },
    ],
    placeholder: '粘贴需要润色的文本，或描述降重需求...',
  },
  custom: {
    name: '自定义Agent',
    role: '通用学术助手，可应对各类学术问题和需求',
    suggestions: [
      { icon: '💬', title: '自由对话', desc: '直接提出你的研究问题或需求，我会尽力帮助' },
      { icon: '📄', title: '文档分析', desc: '上传或粘贴研究文档，我会帮你分析核心内容' },
      { icon: '🔍', title: '知识查询', desc: '询问任何学术相关的知识或方法' },
    ],
    placeholder: '输入任何问题，开始对话...',
  },
};

export const DISCIPLINES = [
  { id: 'engineering', name: '工科', icon: '⚙️', desc: '计算机、电子、机械、土木等' },
  { id: 'science', name: '理科', icon: '🔬', desc: '数学、物理、化学、生物等' },
  { id: 'humanities', name: '人文社科', icon: '📖', desc: '文学、历史、哲学、社会学等' },
];

export const HUMANITIES_TYPES = [
  { id: 'survey', name: '调查报告' },
  { id: 'qualitative', name: '质化研究' },
  { id: 'quantitative', name: '量化研究' },
  { id: 'mixed', name: '混合研究' },
  { id: 'literature', name: '文献综述' },
  { id: 'case_study', name: '案例研究' },
];

export const READINESS_OPTIONS = [
  { id: 'no_idea', name: '我暂未有思路', desc: '让AI引导您逐步构建研究方案' },
  { id: 'has_idea', name: '我已经有思路', desc: '与AI一起完善和优化您的研究思路' },
  { id: 'has_structure', name: '我已经写好了论文架构', desc: '让AI审查和优化您的论文结构' },
];

export const CHART_TYPES = {
  ribbon: '丝带图',
  violin: '小提琴图',
  alluvial: '冲积图',
  bubble_kde: '气泡KDE图',
  gradient_area: '渐变面积图',
  surface3d: '3D地形图',
  parallel: '平行坐标图',
  contour: '等高线图',
  swarm: '蜂群图',
  scatter_density: '散点密度图',
  chord: '和弦图',
  heatmap_dendro: '热力图',
};