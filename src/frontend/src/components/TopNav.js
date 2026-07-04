import { createElement } from '../utils/dom.js';
import { state, watch } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { showToast } from '../components/ConfirmDialog.js';
import { iconChevronRight, iconSun, iconMoon, iconHelp, iconSettings, iconLogOut, iconLogIn, iconUser, iconCrown, iconClock, iconEdit, iconSearch } from '../utils/icons.js';

const AGENT_NAMES = {
  researcher: '研究员', reviewer: '审查员', architect: '架构师',
  synthesizer: '综述员', polisher: '润色员', 'custom-agent': '自定义Agent',
};

const DISCIPLINE_NAMES = {
  engineering: '工科',
  science: '理科',
  humanities: '人文社科',
  interdisciplinary: '交叉学科',
};

function getBreadcrumbs() {
  const page = state.currentPage;
  const crumbs = [{ label: '首页', page: 'homepage' }];

  if (['engineering', 'science', 'humanities', 'interdisciplinary'].includes(page)) {
    crumbs.push({ label: DISCIPLINE_NAMES[page] || page, page });
  } else if (page === 'readiness') {
    const disc = state.discipline;
    if (disc) crumbs.push({ label: DISCIPLINE_NAMES[disc] || disc, page: disc });
    crumbs.push({ label: '研究准备度', page });
  } else if (['researcher', 'reviewer', 'architect', 'synthesizer', 'polisher', 'custom-agent', 'external-reviewer'].includes(page)) {
    const disc = state.discipline;
    if (disc) crumbs.push({ label: DISCIPLINE_NAMES[disc] || disc, page: disc });
    crumbs.push({ label: '研究准备度', page: 'readiness' });
    crumbs.push({ label: AGENT_NAMES[page] || 'Agent', page });
  } else if (page === 'computational') {
    const disc = state.discipline;
    if (disc) crumbs.push({ label: DISCIPLINE_NAMES[disc] || disc, page: disc });
    crumbs.push({ label: '计算社会科学', page });
  } else if (page === 'writing') {
    const disc = state.discipline;
    if (disc) crumbs.push({ label: DISCIPLINE_NAMES[disc] || disc, page: disc });
    if (state.currentAgent) crumbs.push({ label: AGENT_NAMES[state.currentAgent] || state.currentAgent, page: state.currentAgent });
    crumbs.push({ label: '写作工作台', page });
  } else if (page === 'settings') {
    crumbs.push({ label: '设置', page });
  } else if (page === 'pricing') {
    crumbs.push({ label: '套餐', page });
  } else if (page === 'auth') {
    crumbs.push({ label: '登录', page });
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
    if (i > 0) {
      const sep = createElement('span', { className: 'sep' });
      sep.innerHTML = iconChevronRight(12);
      return [sep, el];
    }
    return [el];
  });
}

export function TopNav() {
  const nav = createElement('nav', { className: 'top-nav' });

  // 在 Landing Page 上隐藏工作区导航（Landing 有自己的全局导航）
  const updateVisibility = () => {
    if (state.currentPage === 'landing') {
      nav.style.display = 'none';
    } else {
      nav.style.display = '';
    }
  };
  updateVisibility();
  watch('currentPage', updateVisibility);

  // BC-20: skip-to-content 无障碍链接
  const skipLink = createElement('a', {
    className: 'skip-link',
    href: '#main-content',
  }, '跳转到主要内容');
  skipLink.addEventListener('click', (e) => {
    e.preventDefault();
    const main = document.getElementById('main-content') || document.querySelector('.page.active');
    if (main) main.focus();
  });
  nav.appendChild(skipLink);

  const logo = createElement('div', { className: 'nav-logo' },
    createElement('span', { className: 'nav-logo-icon' }, 'SM'),
    createElement('span', {}, 'ScholarMind'),
  );
  logo.addEventListener('click', () => navigateTo('landing'));
  nav.appendChild(logo);

  // Breadcrumb
  const breadcrumb = createElement('div', { className: 'breadcrumb' },
    ...renderBreadcrumbs()
  );
  nav.appendChild(breadcrumb);

  // Re-render breadcrumb on page change via targeted replacement
  watch('currentPage', () => {
    const newCrumbs = renderBreadcrumbs();
    // Replace only differing children — avoids innerHTML wipe & preserves focus
    const oldChildren = Array.from(breadcrumb.children);
    const maxLen = Math.max(oldChildren.length, newCrumbs.length);
    for (let i = 0; i < maxLen; i++) {
      if (i >= newCrumbs.length) {
        oldChildren[i].remove();
      } else if (i >= oldChildren.length) {
        breadcrumb.appendChild(newCrumbs[i]);
      } else if (oldChildren[i].outerHTML !== newCrumbs[i].outerHTML) {
        oldChildren[i].replaceWith(newCrumbs[i]);
      }
    }
  });

  // nav-actions: 主题切换 + 帮助 + 设置
  const actions = createElement('div', { className: 'nav-actions' });

  const newBtn = createElement('button', {
    className: 'btn btn-primary btn-sm nav-new-btn',
    'aria-label': '新建研究任务',
  });
  newBtn.innerHTML = iconEdit(14) + '<span>新建</span>';
  newBtn.addEventListener('click', () => navigateTo('homepage'));
  actions.appendChild(newBtn);

  const taskBtn = createElement('button', {
    className: 'nav-task-btn',
    'aria-label': '打开任务中心',
    title: '任务中心',
  });
  const taskCount = (state.skills && state.skills.length) || 0;
  taskBtn.innerHTML = iconClock(16) + '<span>任务</span>' + (taskCount > 0 ? '<span class="nav-task-count">' + taskCount + '</span>' : '');
  taskBtn.addEventListener('click', () => {
    const panel = document.querySelector('.agent-insight-panel');
    if (panel) {
      panel.classList.toggle('mobile-panel-open');
      const taskTab = panel.querySelector('[data-tab="tasks"]');
      if (taskTab) taskTab.click();
    } else {
      showToast('进入任一研究项目后，可在这里查看运行中的任务', 'info');
    }
  });
  actions.appendChild(taskBtn);

  // P1-5: 全局搜索按钮 (⌘K 风格入口)
  const searchBtn = createElement('button', {
    className: 'nav-icon-btn nav-search-btn',
    'aria-label': '搜索研究、Agent、功能',
    title: '搜索 (Ctrl+K)',
  });
  searchBtn.innerHTML = iconSearch(18);
  searchBtn.addEventListener('click', () => {
    showToast('全局搜索功能即将上线', 'info');
  });
  actions.appendChild(searchBtn);

  // 主题切换下拉菜单 — 支持5种主题快速切换
  const THEME_OPTIONS = [
    { id: 'dark', label: '学术暖暗色' },
    { id: 'light', label: '学术暖浅色' },
    { id: 'zen', label: '温润新禅意' },
    { id: 'pure', label: '纯白极简' },
    { id: 'warm', label: '暖米橙红' },
    { id: 'eye-care', label: '护眼绿' },
    { id: 'volcano-academic', label: '火山学术' },
  ];
  const themeMenuWrap = createElement('div', { className: 'theme-dropdown' });
  const themeBtn = createElement('button', {
    className: 'nav-icon-btn',
    'aria-label': '切换主题',
    'aria-haspopup': 'true',
    'aria-expanded': 'false',
    'title': '切换主题',
  });
  const updateThemeIcon = () => {
    const currentTheme = state.settings?.theme || 'dark';
    themeBtn.innerHTML = currentTheme === 'dark' ? iconMoon(18) : iconSun(18);
  };
  updateThemeIcon();
  // 下拉菜单
  const themeMenu = createElement('div', { className: 'theme-dropdown-menu', 'role': 'menu' });
  THEME_OPTIONS.forEach(opt => {
    const isActive = (state.settings?.theme || 'dark') === opt.id;
    const item = createElement('button', {
      className: 'theme-dropdown-item' + (isActive ? ' theme-dropdown-item-active' : ''),
      'role': 'menuitem',
      'aria-label': '切换到' + opt.label + '主题',
    }, opt.label);
    item.addEventListener('click', () => {
      state.settings = { ...state.settings, theme: opt.id };
      showToast('主题已切换为' + opt.label, 'success');
      themeMenu.classList.remove('theme-dropdown-open');
      themeBtn.setAttribute('aria-expanded', 'false');
    });
    themeMenu.appendChild(item);
  });
  themeMenuWrap.appendChild(themeBtn);
  themeMenuWrap.appendChild(themeMenu);
  themeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = themeMenu.classList.toggle('theme-dropdown-open');
    themeBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  });
  // 点击外部关闭下拉
  document.addEventListener('click', (e) => {
    if (!themeMenuWrap.contains(e.target)) {
      themeMenu.classList.remove('theme-dropdown-open');
      themeBtn.setAttribute('aria-expanded', 'false');
    }
  });
  // 主题变化时更新图标与激活态
  watch('settings', (settings) => {
    updateThemeIcon();
    const currentTheme = settings?.theme || 'dark';
    themeMenu.querySelectorAll('.theme-dropdown-item').forEach((item, i) => {
      item.classList.toggle('theme-dropdown-item-active', THEME_OPTIONS[i].id === currentTheme);
    });
  });
  actions.appendChild(themeMenuWrap);

  // 帮助按钮
  const helpBtn = createElement('button', {
    className: 'nav-icon-btn nav-help-btn',
    'aria-label': '使用帮助',
    'title': '使用帮助',
  });
  helpBtn.innerHTML = iconHelp(18);
  helpBtn.addEventListener('click', () => {
    showToast('选择学科 → 研究类型 → 准备度 → AI助手，开始你的学术研究之旅', 'info');
  });
  actions.appendChild(helpBtn);

  // 设置按钮
  const settingsBtn = createElement('button', {
    className: 'nav-icon-btn nav-settings-btn',
    'aria-label': '设置',
    'title': '设置',
  });
  settingsBtn.innerHTML = iconSettings(18);
  settingsBtn.addEventListener('click', () => navigateTo('settings'));
  actions.appendChild(settingsBtn);

  // ── 用户认证按钮 ──
  function getStoredUser() {
    try {
      const raw = localStorage.getItem('sm_user');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  const authWrap = createElement('div', { className: 'nav-auth' });

  function renderAuthButtons() {
    authWrap.innerHTML = '';
    const storedUser = getStoredUser();
    if (storedUser) {
      const userBadge = createElement('span', { className: 'nav-user-badge' });
      let entitlements = null;
      try { entitlements = JSON.parse(localStorage.getItem('sm_entitlements') || 'null'); } catch {}
      const quotaText = entitlements?.unlimited_chat
        ? '不限对话'
        : `${entitlements?.free_chats_remaining ?? '—'} 次`;
      userBadge.innerHTML = iconUser(14) + ' ' + (storedUser.nickname || storedUser.phone || '用户') + ` · ${quotaText}`;
      authWrap.appendChild(userBadge);

      if (!entitlements?.membership_active) {
        const upgradeBtn = createElement('button', {
          className: 'btn btn-primary btn-sm nav-btn-upgrade',
          'aria-label': '升级 Pro',
        });
        upgradeBtn.innerHTML = iconCrown(14) + ' Pro';
        upgradeBtn.addEventListener('click', () => navigateTo('pricing'));
        authWrap.appendChild(upgradeBtn);
      }

      const logoutBtn = createElement('button', {
        className: 'nav-icon-btn',
        'aria-label': '退出登录',
        'title': '退出登录',
      });
      logoutBtn.innerHTML = iconLogOut(18);
      logoutBtn.addEventListener('click', () => {
        localStorage.removeItem('sm_token');
        localStorage.removeItem('sm_user');
        localStorage.removeItem('sm_entitlements');
        state.auth = { user: null, token: null, isAuthenticated: false, entitlements: null };
        navigateTo('homepage');
      });
      authWrap.appendChild(logoutBtn);
    } else {
      const loginBtn = createElement('button', {
        className: 'btn btn-primary btn-sm nav-login-btn',
        'aria-label': '登录',
      });
      loginBtn.innerHTML = iconLogIn(14) + '<span>登录</span>';
      loginBtn.addEventListener('click', () => navigateTo('auth'));
      authWrap.appendChild(loginBtn);

      const registerBtn = createElement('button', {
        className: 'btn btn-outline btn-sm nav-register-btn',
        'aria-label': '注册',
      }, '注册');
      registerBtn.addEventListener('click', () => navigateTo('auth'));
      authWrap.appendChild(registerBtn);
    }
  }
  renderAuthButtons();
  actions.appendChild(authWrap);

  nav.appendChild(actions);

  return nav;
}
