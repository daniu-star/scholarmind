import { state, watch } from './store.js';
import { HomePage } from '../pages/HomePage.js';
import { ResearchTypePage } from '../pages/ResearchTypePage.js';
import { ReadinessPage } from '../pages/ReadinessPage.js';
import { AgentPage } from '../pages/AgentPage.js';
import { SettingsPage } from '../pages/SettingsPage.js';

const routes = {
  'homepage':       { title: 'ScholarMind',           render: HomePage },
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
  state.currentPage = pageId;
  Object.assign(state, extraState);
  window.location.hash = pageId;
}

export function initRouter(container) {
  const renderCurrent = () => {
    const pageId = state.currentPage;
    const route = routes[pageId] || routes['homepage'];
    document.title = route.title + ' · ScholarMind';
    container.innerHTML = '';
    container.appendChild(route.render(route.props || {}));
  };

  renderCurrent();

  window.addEventListener('hashchange', () => {
    const pageId = window.location.hash.slice(1) || 'homepage';
    state.currentPage = pageId;
    renderCurrent();
  });

  watch('currentPage', () => renderCurrent());
}