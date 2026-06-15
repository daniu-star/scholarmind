import { createElement } from '../utils/dom.js';
import { state, watch } from '../app/store.js';
import { navigateTo } from '../app/router.js';

const AGENT_NAMES = {
  researcher: '研究员', reviewer: '审查员', architect: '架构师',
  synthesizer: '综述员', polisher: '润色员', 'custom-agent': '自定义Agent',
};

const DISCIPLINE_NAMES = {
  engineering: '工科',
  science: '理科',
  humanities: '人文社科',
};

function getBreadcrumbs() {
  const page = state.currentPage;
  const crumbs = [{ label: '首页', page: 'homepage' }];

  if (['engineering', 'science', 'humanities'].includes(page)) {
    crumbs.push({ label: DISCIPLINE_NAMES[state.discipline] || state.discipline || '学科', page });
  } else if (page === 'readiness') {
    crumbs.push({ label: DISCIPLINE_NAMES[state.discipline] || state.discipline || '学科', page: state.discipline || 'homepage' });
    crumbs.push({ label: '研究准备度', page });
  } else if (['researcher', 'reviewer', 'architect', 'synthesizer', 'polisher', 'custom-agent'].includes(page)) {
    if (state.discipline) {
      crumbs.push({ label: DISCIPLINE_NAMES[state.discipline] || state.discipline, page: state.discipline });
    }
    crumbs.push({ label: '研究准备度', page: 'readiness' });
    crumbs.push({ label: AGENT_NAMES[page] || 'Agent', page });
  } else if (page === 'settings') {
    crumbs.push({ label: '设置', page });
  }

  return crumbs;
}

function renderBreadcrumbs() {
  const crumbs = getBreadcrumbs();
  return crumbs.flatMap((c, i) => {
    const isLast = i === crumbs.length - 1;
    const el = createElement(
      isLast ? 'span' : 'a',
      isLast
        ? { className: 'current' }
        : { onClick: () => navigateTo(c.page) },
      c.label
    );
    if (i > 0) return [createElement('span', { className: 'sep' }, '›'), el];
    return [el];
  });
}

export function TopNav() {
  const nav = createElement('nav', { className: 'top-nav' });

  const logo = createElement('div', { className: 'nav-logo' },
    createElement('span', { className: 'nav-logo-icon' }, 'S'),
    createElement('span', {}, 'ScholarMind'),
  );
  logo.addEventListener('click', () => navigateTo('homepage'));
  nav.appendChild(logo);

  // Breadcrumb
  const breadcrumb = createElement('div', { className: 'breadcrumb' },
    ...renderBreadcrumbs()
  );
  nav.appendChild(breadcrumb);

  // Re-render breadcrumb on page change
  watch('currentPage', () => {
    breadcrumb.innerHTML = '';
    renderBreadcrumbs().forEach(el => breadcrumb.appendChild(el));
  });

  const actions = createElement('div', { className: 'nav-actions' },
    createElement('button', {
      className: 'btn btn-outline',
      'data-action': 'settings',
      style: 'font-size:0.8rem;padding:4px 12px;',
    }, '设置'),
  );
  actions.querySelector('button[data-action="settings"]').addEventListener('click', () => navigateTo('settings'));
  nav.appendChild(actions);

  return nav;
}