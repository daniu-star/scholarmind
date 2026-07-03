import { createElement } from '../utils/dom.js';
import { initRouter } from './router.js';
import { state, watch } from './store.js';
import { TopNav } from '../components/TopNav.js';
import { initOnboarding } from '../components/Onboarding.js';

// Inject ambient glow orbs that float behind all content
function createAmbientGlow() {
  const container = document.createElement('div');
  container.className = 'ambient-glow';
  // 3 floating orbs
  for (let i = 0; i < 3; i++) {
    const orb = document.createElement('div');
    orb.className = 'ambient-orb ambient-orb-' + (i + 1);
    container.appendChild(orb);
  }
  document.body.appendChild(container);
}

export function App() {
  const el = createElement('div', { className: 'app-root' });
  el.appendChild(TopNav());

  const pageContainer = createElement('div', { className: 'page-container', id: 'main-content', tabindex: '-1' });
  el.appendChild(pageContainer);

  // Inject ambient glow orbs
  createAmbientGlow();

  // Apply theme on load and watch for changes
  document.documentElement.setAttribute('data-theme', state.settings.theme || 'dark');
  watch('settings', (settings) => {
    document.documentElement.setAttribute('data-theme', settings?.theme || 'dark');
  });

  initRouter(pageContainer);

  // 首次访问时延迟弹出新手引导
  setTimeout(() => initOnboarding(), 500);

  return el;
}