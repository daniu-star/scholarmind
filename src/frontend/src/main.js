import { App } from './app/App.js';
import { healthCheck } from './services/api.js';
import { state } from './app/store.js';

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('app');
  root.appendChild(App());

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