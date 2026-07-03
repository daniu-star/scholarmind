import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { AGENTS } from '../utils/constants.js';
import { renderIcon, iconArrowLeft } from '../utils/icons.js';

const levels = [
  { id: 'exploring', icon: 'search', label: '探索阶段', desc: '刚确定研究方向，正在寻找选题' },
  { id: 'planning', icon: 'edit', label: '规划阶段', desc: '已有研究方向，正在设计研究方案' },
  { id: 'writing', icon: 'pen', label: '写作阶段', desc: '已完成研究，正在撰写论文' },
  { id: 'revising', icon: 'refresh', label: '修改阶段', desc: '论文初稿完成，需要进行修改润色' },
];

const agentShortDescs = {
  researcher: '选题与问题建构',
  reviewer: '研究思路审查',
  architect: '论文架构优化',
  synthesizer: '文献综述撰写',
  polisher: '学术语言润色',
};

export function ReadinessPage() {
  const page = createElement('div', { className: 'page active' });

  // 返回按钮移至 header 左侧
  const backBtn = createElement('button', { className: 'btn btn-outline btn-back', 'aria-label': '返回选择研究类型' });
  backBtn.innerHTML = iconArrowLeft(16) + ' 返回选择研究类型';
  backBtn.addEventListener('click', () => {
    navigateTo(state.discipline || 'homepage');
  });

  const header = createElement('div', { className: 'page-header' },
    backBtn,
    createElement('h2', { className: 'page-header-title' }, '研究准备度'),
    createElement('p', { className: 'page-header-subtitle' }, '你目前处于研究的哪个阶段？'),
  );
  // P1-2: 步骤进度指示器
  const steps = createElement('div', { className: 'step-progress' },
    createElement('span', { className: 'step-progress-item done' }, '① 学科'),
    createElement('span', { className: 'step-progress-sep' }, '▸'),
    createElement('span', { className: 'step-progress-item done' }, '② 研究类型'),
    createElement('span', { className: 'step-progress-sep' }, '▸'),
    createElement('span', { className: 'step-progress-item current' }, '③ 准备度'),
    createElement('span', { className: 'step-progress-sep' }, '▸'),
    createElement('span', { className: 'step-progress-item' }, '④ 开始研究'),
  );
  page.appendChild(header);
  page.appendChild(steps);

  const levelCards = createElement('div', { className: 'level-cards-grid' });
  levels.forEach(l => {
    const card = createElement('div', { className: 'radio-card level-card', role: 'button', tabindex: '0', 'aria-label': l.label },
      createElement('div', { className: 'level-card-icon', innerHTML: renderIcon(l.icon, 28) }),
      createElement('div', { className: 'memory-title' }, l.label),
      createElement('div', { className: 'memory-meta' }, l.desc),
    );
    const select = () => {
      state.readiness = l.id;
      if (state.researchType) {
        navigateTo('researcher');
      } else {
        navigateTo(state.discipline || 'homepage');
      }
    };
    card.addEventListener('click', select);
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); } });
    levelCards.appendChild(card);
  });
  page.appendChild(levelCards);

  // 过渡分隔区
  const agentSection = createElement('div', { className: 'agent-quick-section' },
    createElement('div', { className: 'agent-quick-divider' }),
    createElement('p', { className: 'agent-quick-hint' }, '或直接选择一位AI助手开始对话'),
  );
  const agentGrid = createElement('div', { className: 'agent-quick-grid' });
  AGENTS.forEach(a => {
    const btn = createElement('button', { className: 'btn btn-outline agent-quick-btn', 'aria-label': a.name },
      createElement('div', { className: 'agent-quick-name' }, a.name),
      createElement('div', { className: 'agent-quick-desc' }, agentShortDescs[a.id] || a.desc),
    );
    btn.addEventListener('click', () => navigateTo(a.id));
    agentGrid.appendChild(btn);
  });
  agentSection.appendChild(agentGrid);
  page.appendChild(agentSection);

  return page;
}
