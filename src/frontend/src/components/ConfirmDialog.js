import { createElement } from '../utils/dom.js';
import { iconAlert, iconCheck, iconInfo } from '../utils/icons.js';

// Focus trap helper
function trapFocus(container) {
  const focusable = container.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (!first) return () => {};

  function handler(e) {
    if (e.key !== 'Tab') return;
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }
  container.addEventListener('keydown', handler);
  return () => container.removeEventListener('keydown', handler);
}

// Lock body scroll
const scrollLocks = [];
function lockBodyScroll() {
  if (scrollLocks.length === 0) {
    document.body.style.overflow = 'hidden';
  }
  scrollLocks.push(true);
}
function unlockBodyScroll() {
  scrollLocks.pop();
  if (scrollLocks.length === 0) {
    document.body.style.overflow = '';
  }
}

// 通用确认对话框组件
// options: { title, message, confirmText, cancelText, variant }
// 返回 Promise<boolean>
export function showConfirmDialog(options = {}) {
  const {
    title = '确认操作',
    message = '',
    confirmText = '确认',
    cancelText = '取消',
    variant = 'danger',
  } = options;

  return new Promise(resolve => {
    const overlay = createElement('div', { className: 'confirm-overlay' });
    const dialog = createElement('div', { className: 'confirm-dialog', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'confirm-title' });

    const iconFn = variant === 'info' ? iconInfo : variant === 'success' ? iconCheck : iconAlert;
    const iconColor = variant === 'danger' ? 'var(--accent-red)' : variant === 'success' ? 'var(--accent-green)' : 'var(--accent-amber)';

    const titleEl = createElement('div', { className: 'confirm-dialog-title', id: 'confirm-title' });
    titleEl.innerHTML = `<span class="confirm-dialog-icon" style="color:${iconColor};display:inline-flex;vertical-align:middle;margin-right:8px;">${iconFn(20)}</span>${title}`;
    dialog.appendChild(titleEl);

    const msgEl = createElement('div', { className: 'confirm-dialog-message' }, message);
    dialog.appendChild(msgEl);

    const actions = createElement('div', { className: 'confirm-dialog-actions' });
    const cancelBtn = createElement('button', { className: 'btn btn-outline' }, cancelText);
    const confirmBtn = createElement('button', { className: 'btn ' + (variant === 'danger' ? 'btn-danger' : 'btn-primary') }, confirmText);
    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    dialog.appendChild(actions);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    lockBodyScroll();
    confirmBtn.focus();

    // Focus trap
    const releaseTrap = trapFocus(dialog);
    let closed = false;

    function close(result) {
      if (closed) return;
      closed = true;
      releaseTrap();
      unlockBodyScroll();
      overlay.style.animation = 'fadeIn 0.15s ease reverse';
      setTimeout(() => {
        overlay.remove();
        resolve(result);
      }, 150);
    }

    cancelBtn.addEventListener('click', () => close(false));
    confirmBtn.addEventListener('click', () => close(true));
    overlay.addEventListener('click', e => { if (e.target === overlay) close(false); });

    // ESC 关闭 + Enter on confirm
    const escHandler = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); close(false); }
    };
    document.addEventListener('keydown', escHandler);
    // Auto-cleanup event listener on close
    const origClose = close;
    close = (result) => {
      document.removeEventListener('keydown', escHandler);
      origClose(result);
    };
  });
}

// Toast 通知
export function showToast(message, type = 'info', duration = 3000) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = createElement('div', { className: 'toast-container', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(container);
  }
  const toast = createElement('div', { className: 'toast toast-' + type, role: 'alert' });
  const iconFn = type === 'success' ? iconCheck : type === 'error' ? iconAlert : iconInfo;
  toast.innerHTML = `<span class="toast-icon">${iconFn(18)}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-removing');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}