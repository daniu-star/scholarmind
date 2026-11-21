import { state, watch } from './store.js';
import { createElement } from '../utils/dom.js';
import { iconGraduationCap } from '../utils/icons.js';

function NotFoundPage() {
  const page = createElement('div', { className: 'page active not-found-page' });
  const wrap = createElement('div', { className: 'not-found-wrap' });
  wrap.innerHTML =
    '<div class="not-found-icon">' + iconGraduationCap(64) + '</div>' +
    '<h1 class="not-found-code">404</h1>' +
    '<p class="not-found-title">页面未找到</p>' +
    '<p class="not-found-desc">您访问的页面不存在，可能已被移除或链接错误</p>';
  const homeBtn = createElement('button', { className: 'btn btn-primary not-found-btn' }, '返回首页');
  homeBtn.addEventListener('click', () => navigateTo('homepage'));
  wrap.appendChild(homeBtn);
  page.appendChild(wrap);
  return page;
}

// Code-split page loaders — each page dynamically imported
const pageLoaders = {
  'landing':        () => import('../pages/LandingPage.js').then(m => m.LandingPage),
  'homepage':       () => import('../pages/HomePage.js').then(m => m.HomePage),
  'engineering':    () => import('../pages/ResearchTypePage.js').then(m => m.ResearchTypePage),
  'science':        () => import('../pages/ResearchTypePage.js').then(m => m.ResearchTypePage),
  'humanities':     () => import('../pages/ResearchTypePage.js').then(m => m.ResearchTypePage),
  'interdisciplinary': () => import('../pages/ResearchTypePage.js').then(m => m.ResearchTypePage),
  'readiness':      () => import('../pages/ReadinessPage.js').then(m => m.ReadinessPage),
  'researcher':     () => import('../pages/AgentPage.js').then(m => m.AgentPage),
  'reviewer':       () => import('../pages/AgentPage.js').then(m => m.AgentPage),
  'architect':      () => import('../pages/AgentPage.js').then(m => m.AgentPage),
  'synthesizer':    () => import('../pages/AgentPage.js').then(m => m.AgentPage),
  'polisher':       () => import('../pages/AgentPage.js').then(m => m.AgentPage),
  'custom-agent':   () => import('../pages/AgentPage.js').then(m => m.AgentPage),
  'external-reviewer': () => import('../pages/AgentPage.js').then(m => m.AgentPage),
  'settings':       () => import('../pages/SettingsPage.js').then(m => m.SettingsPage),
  'auth':           () => import('../pages/AuthPage.js').then(m => m.AuthPage),
  'pricing':        () => import('../pages/PricingPage.js').then(m => m.PricingPage),
  'writing':        () => import('../pages/WritingWorkspace.js').then(m => m.WritingWorkspace),
  'computational':  () => import('../pages/ComputationalPage.js').then(m => m.ComputationalPage),
  'about':          () => import('../pages/AboutPage.js').then(m => m.AboutPage),
  'research':       () => import('../pages/ResearchWorkspace.js').then(m => m.ResearchWorkspace),
};

const routes = {
  'landing':        { title: 'ScholarMind', props: {} },
  'homepage':       { title: 'ScholarMind · 工作台', props: {} },
  'engineering':    { title: '工科',     props: { discipline: 'engineering' } },
  'science':        { title: '理科',     props: { discipline: 'science' } },
  'humanities':     { title: '人文社科', props: { discipline: 'humanities' } },
  'interdisciplinary': { title: '交叉学科', props: { discipline: 'interdisciplinary' } },
  'readiness':      { title: '研究准备度', props: {} },
  'researcher':     { title: '研究员对话', props: { agentId: 'researcher' } },
  'reviewer':       { title: '审查员对话', props: { agentId: 'reviewer' } },
  'architect':      { title: '架构师对话', props: { agentId: 'architect' } },
  'synthesizer':    { title: '综述员对话', props: { agentId: 'synthesizer' } },
  'polisher':       { title: '润色员对话', props: { agentId: 'polisher' } },
  'custom-agent':   { title: '自定义Agent', props: { agentId: 'custom' } },
  'external-reviewer': { title: '外审专家对话', props: { agentId: 'external_reviewer' } },
  'settings':       { title: '设置', props: {} },
  'auth':           { title: '登录', props: {} },
  'pricing':        { title: '套餐', props: {} },
  'writing':        { title: '写作工作台', props: {} },
  'computational':  { title: '计算社会科学', props: {} },
  'about':          { title: '关于 ScholarMind', props: {} },
  'research':       { title: '研究工作区', props: {} },
};

// Track navigation direction for transitions
let navDirection = 0; // -1=backward, 0=same, 1=forward
let prevPageId = 'landing';

export function navigateTo(pageId, extraState = {}) {
  Object.assign(state, extraState);
  // Determine navigation direction for transition
  const pageOrder = Object.keys(routes);
  const prevIdx = pageOrder.indexOf(prevPageId);
  const newIdx = pageOrder.indexOf(pageId);
  navDirection = (newIdx > prevIdx) ? 1 : (newIdx < prevIdx) ? -1 : 0;
  prevPageId = pageId;
  window.location.hash = pageId;
}

export function initRouter(container) {
  let currentCleanup = null;

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
    // Cleanup previous page
    if (currentCleanup) { try { currentCleanup(); } catch(e) {}; currentCleanup = null; }

    const loader = pageLoaders[pageId];
    if (!loader) {
      container.innerHTML = '';
      container.appendChild(NotFoundPage());
      return;
    }

    // Show loading indicator for slow pages
    let loadingEl = null;
    const loadingTimer = setTimeout(() => {
      loadingEl = createElement('div', { className: 'page-loading' });
      loadingEl.innerHTML = '<div class="page-loading-spinner"></div><p>加载中...</p>';
      container.appendChild(loadingEl);
    }, 150);

    loader().then(renderFn => {
      clearTimeout(loadingTimer);
      if (loadingEl && loadingEl.parentNode) loadingEl.remove();

      const newPage = renderFn(route.props || {});
      newPage.style.opacity = '0';
      newPage.style.transition = 'opacity 0.2s ease, transform 0.25s ease';

      // Directional transition
      if (navDirection !== 0 && currentPage) {
        const slideX = navDirection > 0 ? '24px' : '-24px';
        newPage.style.transform = 'translateX(' + slideX + ')';
      }

      container.appendChild(newPage);

      if (currentPage) {
        currentPage.style.transition = 'opacity 0.18s ease, transform 0.22s ease';
        currentPage.style.opacity = '0';
        if (navDirection !== 0) {
          const slideX = navDirection > 0 ? '-24px' : '24px';
          currentPage.style.transform = 'translateX(' + slideX + ')';
        }

        const onTransitionEnd = (e) => {
          if (e.target !== currentPage) return;
          currentPage.removeEventListener('transitionend', onTransitionEnd);
          if (currentPage.parentNode) currentPage.remove();
        };
        currentPage.addEventListener('transitionend', onTransitionEnd);

        // Safety timeout in case transitionend never fires
        setTimeout(() => {
          currentPage.removeEventListener('transitionend', onTransitionEnd);
          if (currentPage.parentNode) currentPage.remove();
        }, 500);

        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            newPage.style.opacity = '1';
            newPage.style.transform = 'translateX(0)';
          });
        });
      } else {
        requestAnimationFrame(() => {
          newPage.style.opacity = '1';
          newPage.style.transform = 'translateX(0)';
        });
      }

      // Store cleanup function
      if (newPage._cleanup) {
        currentCleanup = newPage._cleanup;
      }
    }).catch(err => {
      clearTimeout(loadingTimer);
      if (loadingEl && loadingEl.parentNode) loadingEl.remove();
      console.error('Page load failed:', pageId, err);
      if (currentPage) currentPage.remove();
      container.innerHTML = '';
      container.appendChild(NotFoundPage());
    });
  };

  renderCurrent();

  window.addEventListener('hashchange', () => {
    const pageId = window.location.hash.slice(1) || 'homepage';
    state.currentPage = pageId;
  });

  watch('currentPage', () => renderCurrent());
}