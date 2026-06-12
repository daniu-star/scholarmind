import { createElement } from '../utils/dom.js';
import { initRouter } from './router.js';
import { TopNav } from '../components/TopNav.js';

export function App() {
  const el = createElement('div', { className: 'app-root' });
  el.appendChild(TopNav());

  const pageContainer = createElement('div', { className: 'page-container', id: 'page-container' });
  el.appendChild(pageContainer);

  initRouter(pageContainer);
  return el;
}