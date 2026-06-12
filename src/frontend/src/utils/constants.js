export const AGENTS = {
  researcher: { id: 'researcher', name: '研究员', icon: '🔬', desc: '学术选题与问题建构专家' },
  reviewer: { id: 'reviewer', name: '审查员', icon: '📋', desc: '研究思路审查与优化专家' },
  architect: { id: 'architect', name: '架构师', icon: '🏗️', desc: '论文架构审查与优化专家' },
  synthesizer: { id: 'synthesizer', name: '综述员', icon: '📚', desc: '文献综述撰写专家' },
  polisher: { id: 'polisher', name: '润色员', icon: '✨', desc: '学术语言润色与AIGC降重专家' },
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