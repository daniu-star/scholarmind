import { createElement } from '../utils/dom.js';
import { initRouter } from './router.js';
import { state, watch } from './store.js';
import { TopNav } from '../components/TopNav.js';

export function App() {
  const el = createElement('div', { className: 'app-root' });
  el.appendChild(TopNav());

  const pageContainer = createElement('div', { className: 'page-container', id: 'page-container' });
  el.appendChild(pageContainer);

  // Apply theme on load and watch for changes
  document.documentElement.setAttribute('data-theme', state.settings.theme || 'dark');
  watch('settings', (settings) => {
    document.documentElement.setAttribute('data-theme', settings?.theme || 'dark');
  });

  initRouter(pageContainer);
  return el;
}