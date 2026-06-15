import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { AGENTS } from '../utils/constants.js';

const levels = [
  { id: 'exploring', emoji: '🔍', label: '探索阶段', desc: '刚确定研究方向，正在寻找选题' },
  { id: 'planning', emoji: '✍️', label: '规划阶段', desc: '已有研究方向，正在设计研究方案' },
  { id: 'writing', emoji: '📝', label: '写作阶段', desc: '已完成研究，正在撰写论文' },
  { id: 'revising', emoji: '🔄', label: '修改阶段', desc: '论文初稿完成，需要进行修改润色' },
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

  const header = createElement('div', { className: 'hero-section', style: 'padding-top:30px;padding-bottom:10px;' },
    createElement('h2', { className: 'hero-title', style: 'font-size:1.6rem;' }, '研究准备度'),
    createElement('p', { className: 'hero-subtitle' }, '你目前处于研究的哪个阶段？'),
  );
  page.appendChild(header);

  // Back to research type selection
  const backLink = createElement('div', { style: 'text-align:center;padding-bottom:16px;' },
    createElement('button', {
      className: 'btn btn-outline',
      style: 'font-size:0.82rem;',
    }, '← 返回选择研究类型'),
  );
  backLink.querySelector('button').addEventListener('click', () => {
    navigateTo(state.discipline || 'homepage');
  });
  page.appendChild(backLink);

  const levelCards = createElement('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:420px;margin:0 auto;padding:0 24px;' });
  levels.forEach(l => {
    const card = createElement('div', { className: 'theme-card' },
      createElement('div', { style: 'font-size:1.4rem;margin-bottom:8px;' }, l.emoji),
      createElement('div', { className: 'memory-title' }, l.label),
      createElement('div', { className: 'memory-meta' }, l.desc),
    );
    card.addEventListener('click', () => {
      state.readiness = l.id;
      if (state.researchType) {
        navigateTo('researcher');
      } else {
        navigateTo(state.discipline || 'homepage');
      }
    });
    levelCards.appendChild(card);
  });
  page.appendChild(levelCards);

  const agentSection = createElement('div', { style: 'text-align:center;padding:16px 24px 30px;' },
    createElement('p', { style: 'color:var(--text-secondary);font-size:0.85rem;margin-bottom:16px;' },
      '或直接选择一位AI助手开始对话'),
  );
  const agentGrid = createElement('div', { style: 'display:flex;gap:10px;justify-content:center;flex-wrap:wrap;' });
  AGENTS.forEach(a => {
    const btn = createElement('button', { className: 'btn btn-outline', style: 'font-size:0.8rem;line-height:1.3;text-align:center;' },
      createElement('div', {}, a.name),
      createElement('div', { style: 'font-size:0.7rem;color:var(--text-tertiary);' }, agentShortDescs[a.id] || a.desc),
    );
    btn.addEventListener('click', () => navigateTo(a.id));
    agentGrid.appendChild(btn);
  });
  agentSection.appendChild(agentGrid);
  page.appendChild(agentSection);

  return page;
}