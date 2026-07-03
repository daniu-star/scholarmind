import { App } from './app/App.js';
import { healthCheck, onGlobalError } from './services/api.js';
import { state } from './app/store.js';

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('app');
  root.appendChild(App());

  // P0-3: 全局错误监听 — 统一的 API 错误 UI 反馈
  onGlobalError((error) => {
    // 仅对未被页面捕获的全局错误显示 toast
    if (error.name === 'NetworkError') {
      const banner = document.getElementById('global-error-banner');
      if (!banner) {
        const el = document.createElement('div');
        el.id = 'global-error-banner';
        el.className = 'backend-offline-banner';
        el.innerHTML = '后端服务连接失败，请检查服务是否启动 · <button class="close-btn" style="background:none;border:none;color:inherit;cursor:pointer;font-size:1rem;margin-left:8px;">✕</button>';
        el.querySelector('.close-btn').addEventListener('click', () => el.remove());
        document.body.insertBefore(el, document.body.firstChild);
        setTimeout(() => { if (el.parentNode) el.remove(); }, 10000);
      }
    }
    if (error.name === 'ApiError' && error.status === 401) {
      // 401 由 401 处理 — 已在各页面单独处理，全局仅记录
      console.warn('[GlobalError] 401 Unauthorized — 页面应处理重新登录');
    }
  });

  const apiBase = state.settings?.apiBase || '';
  healthCheck(apiBase)
    .then(() => {
      console.log('Backend connected');
    })
    .catch(() => {
      const banner = document.createElement('div');
      banner.className = 'backend-offline-banner';
      banner.innerHTML =
        '后端服务未启动，请在终端执行 <code>cd src/backend &amp;&amp; uvicorn app:app --reload</code>';
      const closeBtn = document.createElement('button');
      closeBtn.className = 'close-btn';
      closeBtn.textContent = '✕';
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        banner.remove();
      });
      banner.appendChild(closeBtn);
      banner.addEventListener('click', () => banner.remove());
      document.body.insertBefore(banner, document.body.firstChild);
    });
});