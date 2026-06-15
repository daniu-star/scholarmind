import { state, watch } from './store.js';
import { createElement } from '../utils/dom.js';
import { HomePage } from '../pages/HomePage.js';
import { ResearchTypePage } from '../pages/ResearchTypePage.js';
import { ReadinessPage } from '../pages/ReadinessPage.js';
import { AgentPage } from '../pages/AgentPage.js';
import { SettingsPage } from '../pages/SettingsPage.js';

function NotFoundPage() {
  const page = createElement('div', { className: 'page active', style: 'text-align:center;padding:60px 20px;' });
  page.appendChild(createElement('h1', { style: 'font-size:4rem;color:var(--text-tertiary);margin-bottom:16px;' }, '404'));
  page.appendChild(createElement('p', { style: 'font-size:1.1rem;color:var(--text-secondary);margin-bottom:8px;' }, '页面未找到'));
  page.appendChild(createElement('p', { style: 'font-size:0.85rem;color:var(--text-tertiary);margin-bottom:24px;' }, '您访问的页面不存在，请检查URL是否正确'));
  const homeBtn = createElement('button', { className: 'btn btn-primary', style: 'font-size:0.9rem;' }, '返回首页');
  homeBtn.addEventListener('click', () => navigateTo('homepage'));
  page.appendChild(homeBtn);
  return page;
}

const routes = {
  'homepage':       { title: 'ScholarMind', render: HomePage },
  'engineering':    { title: '工科',   render: ResearchTypePage, props: { discipline: 'engineering' } },
  'science':        { title: '理科',   render: ResearchTypePage, props: { discipline: 'science' } },
  'humanities':     { title: '人文社科', render: ResearchTypePage, props: { discipline: 'humanities' } },
  'readiness':      { title: '研究准备度',              render: ReadinessPage },
  'researcher':     { title: '研究员对话',              render: AgentPage, props: { agentId: 'researcher' } },
  'reviewer':       { title: '审查员对话',              render: AgentPage, props: { agentId: 'reviewer' } },
  'architect':      { title: '架构师对话',              render: AgentPage, props: { agentId: 'architect' } },
  'synthesizer':    { title: '综述员对话',              render: AgentPage, props: { agentId: 'synthesizer' } },
  'polisher':       { title: '润色员对话',              render: AgentPage, props: { agentId: 'polisher' } },
  'custom-agent':   { title: '自定义Agent',            render: AgentPage, props: { agentId: 'custom' } },
  'settings':       { title: '设置',                  render: SettingsPage },
};

export function navigateTo(pageId, extraState = {}) {
  // 先将额外状态写入 state（不触发页面切换）
  Object.assign(state, extraState);
  // 仅通过 hash 驱动导航，让 hashchange 事件统一驱动渲染
  window.location.hash = pageId;
}

export function initRouter(container) {
  const renderCurrent = () => {
    const pageId = state.currentPage;
    const route = routes[pageId];
    if (!route) {
      document.title = '404 · ScholarMind';
      container.innerHTML = '';
      container.appendChild(NotFoundPage());
      return;
    }
    document.title = route.title === 'ScholarMind' ? 'ScholarMind' : route.title + ' · ScholarMind';

    const currentPage = container.querySelector('.page.active');
    if (currentPage) {
      currentPage.style.opacity = '0';
      currentPage.style.transition = 'opacity 0.15s ease';
      setTimeout(() => {
        container.innerHTML = '';
        const newPage = route.render(route.props || {});
        newPage.style.opacity = '0';
        container.appendChild(newPage);
        requestAnimationFrame(() => {
          newPage.style.transition = 'opacity 0.2s ease';
          newPage.style.opacity = '1';
        });
      }, 150);
    } else {
      container.innerHTML = '';
      container.appendChild(route.render(route.props || {}));
    }
  };

  renderCurrent();

  window.addEventListener('hashchange', () => {
    const pageId = window.location.hash.slice(1) || 'homepage';
    state.currentPage = pageId;  // watch('currentPage') 会自动触发 renderCurrent()
  });

  watch('currentPage', () => renderCurrent());
}