import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { RESEARCH_TYPE_ICONS, iconArrowLeft, iconClipboardCheck } from '../utils/icons.js';
import { showPaperWorkbenchDialog } from '../components/PaperWorkbenchDialog.js';

const disciplineLabels = {
  engineering: '工科',
  science: '理科',
  humanities: '人文社科',
  interdisciplinary: '交叉学科',
};

const researchTypes = {
  engineering: [
    { id: 'algorithm', name: '算法研究', desc: '设计新型算法或优化现有算法' },
    { id: 'system', name: '系统开发', desc: '构建软硬件系统或平台' },
    { id: 'experiment', name: '实验研究', desc: '通过实验验证假设或评估性能' },
    { id: 'application', name: '应用研究', desc: '将技术应用于特定领域场景' },
  ],
  science: [
    { id: 'theoretical', name: '理论研究', desc: '构建数学模型或理论框架' },
    { id: 'experiment', name: '实验研究', desc: '设计并执行科学实验' },
    { id: 'simulation', name: '计算模拟', desc: '通过数值模拟研究复杂系统' },
    { id: 'observational', name: '观测研究', desc: '通过观测数据分析自然现象' },
  ],
  humanities: [
    { id: 'qualitative', name: '质性研究', desc: '深度访谈、文本分析、案例研究' },
    { id: 'quantitative', name: '量化研究', desc: '问卷调查、统计分析、计量模型' },
    { id: 'historical', name: '历史研究', desc: '文献考据、历史比较分析' },
    { id: 'critical', name: '批判研究', desc: '理论批判、话语分析、文化研究' },
  ],
  interdisciplinary: [
    { id: 'computational_social', name: '计算社科', desc: '计算方法研究社会现象' },
    { id: 'multi_method', name: '多方法融合', desc: '整合质性量化与计算方法' },
    { id: 'computational_modeling', name: '计算建模', desc: '构建跨学科计算模型' },
    { id: 'mixed_methods', name: '混合方法', desc: '融合不同学科方法体系' },
  ],
};

export function ResearchTypePage({ discipline } = {}) {
  const page = createElement('div', { className: 'page active' });

  // 返回按钮移至 header 左侧
  const backBtn = createElement('button', { className: 'btn btn-outline btn-back', 'aria-label': '返回首页' });
  backBtn.innerHTML = iconArrowLeft(16) + ' 返回首页';
  backBtn.addEventListener('click', () => navigateTo('homepage'));

  const header = createElement('div', { className: 'page-header' },
    backBtn,
    createElement('h2', { className: 'page-header-title' },
      disciplineLabels[discipline] || '选择学科'),
    createElement('p', { className: 'page-header-subtitle' }, '选择你的研究类型，以便ScholarMind提供更精准的引导'),
  );
  // P1-2: 步骤进度指示器
  const steps = createElement('div', { className: 'step-progress' },
    createElement('span', { className: 'step-progress-item done' }, '① 学科'),
    createElement('span', { className: 'step-progress-sep' }, '▸'),
    createElement('span', { className: 'step-progress-item current' }, '② 研究类型'),
    createElement('span', { className: 'step-progress-sep' }, '▸'),
    createElement('span', { className: 'step-progress-item' }, '③ 准备度'),
    createElement('span', { className: 'step-progress-sep' }, '▸'),
    createElement('span', { className: 'step-progress-item' }, '④ 开始研究'),
  );
  page.appendChild(header);
  page.appendChild(steps);

  const types = researchTypes[discipline] || [];
  const grid = createElement('div', { className: 'research-type-grid' });

  types.forEach(t => {
    const iconFn = RESEARCH_TYPE_ICONS[t.id];
    const iconWrap = createElement('div', { className: 'card-icon', innerHTML: iconFn ? iconFn(24) : '' });
    const card = createElement('div', { className: 'card research-type-card', role: 'button', tabindex: '0', 'aria-label': t.name },
      iconWrap,
      createElement('div', { className: 'card-title' }, t.name),
      createElement('div', { className: 'card-desc' }, t.desc),
    );
    const select = () => {
      state.researchType = t.id;
      navigateTo('readiness');
    };
    card.addEventListener('click', select);
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); } });
    grid.appendChild(card);
  });

  page.appendChild(grid);

  // ── 底部工具栏：论文工作台 ──
  const toolbar = createElement('div', { className: 'home-bottom-toolbar' });
  const wbBtn = createElement('div', { className: 'home-toolbar-btn accent-teal' },
    createElement('div', { className: 'home-toolbar-btn-icon', innerHTML: iconClipboardCheck(24) }),
    createElement('div', { className: 'home-toolbar-btn-body' },
      createElement('div', { className: 'home-toolbar-btn-name' }, '论文工作台'),
      createElement('div', { className: 'home-toolbar-btn-desc' }, '上传审稿 · 一键生成 · Pipeline 驱动'),
    ),
    createElement('div', { className: 'home-toolbar-btn-arrow' }, '→'),
  );
  wbBtn.addEventListener('click', () => showPaperWorkbenchDialog());
  toolbar.appendChild(wbBtn);
  page.appendChild(toolbar);

  return page;
}