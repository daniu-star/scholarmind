import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';

const disciplineLabels = {
  engineering: '工科',
  science: '理科',
  humanities: '人文社科',
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
};

export function ResearchTypePage({ discipline } = {}) {
  const page = createElement('div', { className: 'page active' });

  const header = createElement('div', { className: 'hero-section', style: 'padding-top:30px;padding-bottom:10px;' },
    createElement('h2', { className: 'hero-title', style: 'font-size:1.6rem;' },
      disciplineLabels[discipline] || '选择学科'),
    createElement('p', { className: 'hero-subtitle' }, '选择你的研究类型，以便ScholarMind提供更精准的引导'),
  );
  page.appendChild(header);

  const types = researchTypes[discipline] || [];
  const grid = createElement('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill, minmax(220px, 1fr));gap:12px;justify-content:center;padding:0 24px;max-width:960px;margin:0 auto;' });

  types.forEach(t => {
    const card = createElement('div', { className: 'card', style: 'text-align:left;' },
      createElement('div', { className: 'card-title' }, t.name),
      createElement('div', { className: 'card-desc' }, t.desc),
    );
    card.addEventListener('click', () => {
      state.researchType = t.id;
      navigateTo('readiness');
    });
    grid.appendChild(card);
  });

  page.appendChild(grid);

  const backLink = createElement('div', { style: 'text-align:center;padding:20px 24px 40px;' },
    createElement('button', {
      className: 'btn btn-outline',
      style: 'font-size:0.85rem;',
    }, '← 返回首页'),
  );
  backLink.querySelector('button').addEventListener('click', () => navigateTo('homepage'));
  page.appendChild(backLink);

  return page;
}