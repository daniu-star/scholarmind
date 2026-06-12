import { App } from './app/App.js';

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('app');
  root.appendChild(App());
});