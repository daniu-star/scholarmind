import { createElement } from '../utils/dom.js';
import { state, watch } from '../app/store.js';
import { navigateTo } from '../app/router.js';

export function SettingsPage() {
  const page = createElement('div', { className: 'page active' });

  const header = createElement('div', { className: 'hero-section', style: 'padding-bottom:20px;' },
    createElement('h2', { className: 'hero-title', style: 'font-size:1.6rem;' }, '设置'),
    createElement('p', { className: 'hero-subtitle' }, '管理应用配置'),
  );
  page.appendChild(header);

  const content = createElement('div', { style: 'max-width:480px;margin:0 auto;padding:0 24px;' });

  // API Base URL
  const apiSection = createElement('div', { style: 'margin-bottom:20px;' },
    createElement('label', {
      style: 'display:block;font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;',
    }, 'API 基础地址'),
    createElement('input', {
      type: 'text',
      value: state.settings.apiBase || '',
      placeholder: '留空使用相对路径（推荐）',
      style: 'width:100%;background:var(--bg-input);border:1px solid var(--border);border-radius:6px;padding:8px 12px;color:var(--text-primary);font-size:0.85rem;outline:none;',
      oninput: function(e) {
        state.settings = { ...state.settings, apiBase: e.target.value };
      },
    }),
    createElement('p', { style: 'font-size:0.75rem;color:var(--text-tertiary);margin-top:4px;' },
      '留空时使用 Vite 代理转发到后端（推荐）。修改后用于自定义后端地址。'),
  );
  content.appendChild(apiSection);

  // Theme section
  const themeSection = createElement('div', { style: 'margin-bottom:20px;' },
    createElement('label', {
      style: 'display:block;font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;',
    }, '主题'),
  );
  const themeSelect = createElement('div', { style: 'display:flex;gap:8px;' });
  // Watch subscriptions for cleanup
  const unsubscribers = [];
  ['dark', 'light'].forEach(t => {
    const btn = createElement('button', {
      className: 'btn ' + (state.settings.theme === t ? '' : 'btn-outline'),
      style: (state.settings.theme === t ? 'background:var(--gradient-accent);color:#0D1117;' : '') + 'padding:6px 16px;font-size:0.82rem;',
    }, t === 'dark' ? '深色' : '浅色');
    btn.addEventListener('click', () => {
      state.settings = { ...state.settings, theme: t };
    });
    themeSelect.appendChild(btn);
    // Watch for theme changes to update button style
    const unsub = watch('settings', (settings) => {
      const currentTheme = settings?.theme || 'dark';
      if (currentTheme === t) {
        btn.className = 'btn';
        btn.style.cssText = 'background:var(--gradient-accent);color:#0D1117;padding:6px 16px;font-size:0.82rem;';
      } else {
        btn.className = 'btn btn-outline';
        btn.style.cssText = 'padding:6px 16px;font-size:0.82rem;';
      }
    });
    unsubscribers.push(unsub);
  });
  themeSection.appendChild(themeSelect);
  content.appendChild(themeSection);

  // Clear history
  const clearSection = createElement('div', { style: 'margin-bottom:20px;' },
    createElement('label', {
      style: 'display:block;font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;',
    }, '数据管理'),
    createElement('button', {
      className: 'btn btn-outline',
      style: 'font-size:0.82rem;color:var(--accent-red);border-color:rgba(208,90,82,0.3);',
      onclick: function() {
        if (confirm('确定要清除所有对话历史吗？此操作不可撤销。')) {
          state.messages = {};
          alert('对话历史已清除');
        }
      },
    }, '清除所有对话历史'),
  );
  content.appendChild(clearSection);

  // About
  const aboutSection = createElement('div', { style: 'margin-bottom:20px;' },
    createElement('label', {
      style: 'display:block;font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;',
    }, '关于 ScholarMind'),
    createElement('div', {
      style: 'background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:14px 16px;font-size:0.82rem;color:var(--text-secondary);line-height:1.6;',
    },
      createElement('p', {}, 'ScholarMind — 基于 RAG + LangGraph 的智能学术研究助手'),
      createElement('p', { style: 'margin-top:8px;font-size:0.75rem;color:var(--text-tertiary);' }, '版本 3.0.0 · 学术暖暗色主题'),
    ),
  );
  content.appendChild(aboutSection);

  // Back to home
  const backBtn = createElement('button', {
    className: 'btn btn-outline',
    style: 'margin-top:16px;',
  }, '返回首页');
  backBtn.addEventListener('click', () => navigateTo('homepage'));
  content.appendChild(backBtn);

  page.appendChild(content);

  // Attach cleanup for watch subscriptions
  page._cleanup = () => {
    unsubscribers.forEach(fn => { try { fn(); } catch(e) {} });
  };

  return page;
}