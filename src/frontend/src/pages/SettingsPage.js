import { createElement } from '../utils/dom.js';
import { state, watch } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { showConfirmDialog, showToast } from '../components/ConfirmDialog.js';
import { resetOnboarding } from '../components/Onboarding.js';
import { APP_VERSION } from '../utils/constants.js';
import { iconHome, iconArrowLeft } from '../utils/icons.js';

function isValidUrlOrEmpty(val) {
  if (!val) return true;
  try {
    new URL(val);
    return true;
  } catch {
    return false;
  }
}

export function SettingsPage() {
  const page = createElement('div', { className: 'page active' });

  // Header 增加返回首页按钮（左侧）
  const backBtn = createElement('button', { className: 'btn btn-outline btn-back', 'aria-label': '返回首页' });
  backBtn.innerHTML = iconArrowLeft(16) + ' 返回首页';
  backBtn.addEventListener('click', () => navigateTo('homepage'));

  const header = createElement('div', { className: 'page-header' },
    backBtn,
    createElement('h2', { className: 'page-header-title' }, '设置'),
    createElement('p', { className: 'page-header-subtitle' }, '管理应用配置'),
  );
  page.appendChild(header);

  const content = createElement('div', { className: 'settings-content-wrap' });
  const grid = createElement('div', { className: 'settings-grid' });

  const unsubscribers = [];

  // ========== 左栏：主题 + 数据管理 ==========
  const leftCol = createElement('div', {});

  // 主题区 — 卡片式预览
  const themeSection = createElement('div', { className: 'settings-section' },
    createElement('label', { className: 'settings-label' }, '主题'),
  );
  const themeSelect = createElement('div', { className: 'theme-select-group' });
  const themeMeta = [
    { id: 'dark', label: '深色风', desc: '学术暖暗色', swatchClass: 'dark' },
    { id: 'light', label: '浅色风', desc: '学术暖浅色', swatchClass: 'light' },
    { id: 'pure', label: '洁白风', desc: '纯白极简', swatchClass: 'pure' },
    { id: 'warm', label: '温暖风', desc: '暖米橙红', swatchClass: 'warm' },
  ];
  themeMeta.forEach(t => {
    const card = createElement('div', {
      className: 'theme-preview-card ' + (state.settings.theme === t.id ? 'theme-active' : ''),
      'role': 'button',
      'tabindex': '0',
      'aria-label': '切换到' + t.label + '主题',
      'aria-pressed': state.settings.theme === t.id ? 'true' : 'false',
    },
      createElement('div', { className: 'theme-preview-swatch ' + t.swatchClass }),
      createElement('div', { className: 'theme-preview-label' }, t.label),
      createElement('div', { className: 'theme-preview-desc' }, t.desc),
    );
    const activate = () => {
      state.settings = { ...state.settings, theme: t.id };
      showToast('主题已切换为' + t.label, 'success');
    };
    card.addEventListener('click', activate);
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); } });
    themeSelect.appendChild(card);
    const unsub = watch('settings', (settings) => {
      const currentTheme = settings?.theme || 'dark';
      const isActive = currentTheme === t.id;
      card.className = 'theme-preview-card ' + (isActive ? 'theme-active' : '');
      card.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    unsubscribers.push(unsub);
  });
  themeSection.appendChild(themeSelect);
  leftCol.appendChild(themeSection);

  // 数据管理区 — 危险样式
  const clearSection = createElement('div', { className: 'settings-section settings-section-danger' },
    createElement('label', { className: 'settings-label' }, '数据管理'),
    createElement('p', { className: 'settings-hint', style: 'margin-bottom: 12px;' }, '清除所有 Agent 对话历史，此操作不可撤销'),
    createElement('button', {
      className: 'btn btn-danger-outline',
      'aria-label': '清除所有对话历史',
    }, '清除所有对话历史'),
  );
  clearSection.querySelector('button').addEventListener('click', async () => {
    const confirmed = await showConfirmDialog({
      title: '清除对话历史',
      message: '确定要清除所有对话历史吗？此操作不可撤销。',
      confirmText: '清除',
      cancelText: '取消',
      variant: 'danger',
    });
    if (confirmed) {
      state.messages = {};
      showToast('对话历史已清除', 'success');
    }
  });
  leftCol.appendChild(clearSection);

  // 新手引导区
  const onboardingSection = createElement('div', { className: 'settings-section' },
    createElement('label', { className: 'settings-label' }, '新手引导'),
    createElement('p', { className: 'settings-hint', style: 'margin-bottom: 12px;' }, '重新查看 ScholarMind 功能介绍与使用指引'),
    createElement('button', {
      className: 'btn btn-outline',
      'aria-label': '重新查看新手引导',
    }, '重新查看新手引导'),
  );
  onboardingSection.querySelector('button').addEventListener('click', () => {
    resetOnboarding();
    showToast('已重新启动新手引导', 'info');
  });
  leftCol.appendChild(onboardingSection);

  grid.appendChild(leftCol);

  // ========== 右栏：API + About ==========
  const rightCol = createElement('div', {});

  // API Base URL
  const apiSection = createElement('div', { className: 'settings-section' },
    createElement('label', { className: 'settings-label' }, 'API 基础地址'),
  );
  const apiInput = createElement('input', {
    type: 'text',
    className: 'form-input',
    value: state.settings.apiBase || '',
    placeholder: '留空使用相对路径（推荐）',
  });
  const apiHint = createElement('p', { className: 'settings-hint' },
    '留空时使用 Vite 代理转发到后端（推荐）。修改后用于自定义后端地址。');
  const apiError = createElement('p', { className: 'settings-error' }, '');
  let apiDebounceTimer = null;
  apiInput.addEventListener('input', function(e) {
    const val = e.target.value;
    if (!isValidUrlOrEmpty(val)) {
      apiError.textContent = '请输入有效的 URL 地址（如 http://localhost:8000）';
      apiError.style.display = 'block';
    } else {
      apiError.style.display = 'none';
      clearTimeout(apiDebounceTimer);
      apiDebounceTimer = setTimeout(() => {
        state.settings = { ...state.settings, apiBase: val };
      }, 400);
    }
  });
  apiSection.appendChild(apiInput);
  apiSection.appendChild(apiError);
  apiSection.appendChild(apiHint);
  rightCol.appendChild(apiSection);

  // About 区 — 丰富列表
  const themeLabelMap = { dark: '学术暖暗色', light: '学术暖浅色', pure: '纯白极简', warm: '暖米橙红' };
  const themeValueEl = createElement('span', { className: 'about-list-value' }, themeLabelMap[state.settings.theme] || '学术暖暗色');
  const aboutSection = createElement('div', { className: 'settings-section' },
    createElement('label', { className: 'settings-label' }, '关于 ScholarMind'),
    createElement('div', { className: 'about-card' },
      createElement('p', {}, 'ScholarMind — 基于 RAG + LangGraph 的智能学术研究助手'),
      createElement('div', { className: 'about-list' },
        createElement('div', { className: 'about-list-item' },
          createElement('span', { className: 'about-list-key' }, '版本'),
          createElement('span', { className: 'about-list-value' }, APP_VERSION),
        ),
        createElement('div', { className: 'about-list-item' },
          createElement('span', { className: 'about-list-key' }, '技术栈'),
          createElement('span', { className: 'about-list-value' }, 'RAG + LangGraph'),
        ),
        createElement('div', { className: 'about-list-item' },
          createElement('span', { className: 'about-list-key' }, '前端'),
          createElement('span', { className: 'about-list-value' }, 'Vite + Vanilla JS'),
        ),
        createElement('div', { className: 'about-list-item' },
          createElement('span', { className: 'about-list-key' }, '主题'),
          themeValueEl,
        ),
      ),
    ),
  );
  rightCol.appendChild(aboutSection);
  const unsubThemeAbout = watch('settings', (s) => {
    themeValueEl.textContent = themeLabelMap[s?.theme] || '学术暖暗色';
  });
  unsubscribers.push(unsubThemeAbout);

  grid.appendChild(rightCol);

  content.appendChild(grid);
  page.appendChild(content);

  page._cleanup = () => {
    unsubscribers.forEach(fn => { try { fn(); } catch(e) {} });
  };

  return page;
}
