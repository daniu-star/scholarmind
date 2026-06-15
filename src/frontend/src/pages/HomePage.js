import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { DISCIPLINES } from '../utils/constants.js';

export function HomePage() {
  const page = createElement('div', { className: 'page active' });

  const hero = createElement('div', { className: 'hero-section' },
    createElement('h1', { className: 'hero-title' }, 'ScholarMind'),
    createElement('p', { className: 'hero-subtitle' }, '基于RAG + LangGraph的智能学术研究助手'),
    createElement('p', { style: 'color:var(--text-tertiary);font-size:0.82rem;padding-top:8px;margin-bottom:30px;' }, '选择学科开始'),
  );
  page.appendChild(hero);

  const cards = createElement('div', { className: 'discipline-cards' });
  DISCIPLINES.forEach(d => {
    const card = createElement('div', { className: 'discipline-card' },
      createElement('div',
        { className: 'discipline-icon', style: 'background:var(--accent-amber-dim);' },
        d.icon),
      createElement('div', { className: 'discipline-card-title' }, d.name),
      createElement('div', { className: 'discipline-card-desc' }, d.desc),
    );
    card.addEventListener('click', () => {
      state.discipline = d.id;
      navigateTo(d.id);
    });
    cards.appendChild(card);
  });
  page.appendChild(cards);

  const footer = createElement('div', { className: 'version-footer', style: 'margin-top:auto;' }, 'ScholarMind v3.0.0 · 智能学术研究助手');
  page.appendChild(footer);

  return page;
}