// R1-T18 · 研究组件共享的小工具（无第三方依赖，全部返回原生 DOM）
import { createElement } from '../../utils/dom.js';

export const TONE_CLASS = {
  green: 'rw-tone-green',
  amber: 'rw-tone-amber',
  red: 'rw-tone-red',
  blue: 'rw-tone-blue',
  gray: 'rw-tone-gray',
  purple: 'rw-tone-purple',
};

export function pill(text, tone = 'gray') {
  return createElement(
    'span',
    { className: `rw-pill ${TONE_CLASS[tone] || TONE_CLASS.gray}` },
    String(text)
  );
}

export function iconBox(iconFn, size = 16) {
  const span = createElement('span', { className: 'rw-icon', 'aria-hidden': 'true' });
  span.innerHTML = iconFn(size);
  return span;
}

export function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

export function formatWhen(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatClock(iso) {
  const date = iso ? new Date(iso) : new Date();
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function shortId(id, size = 10) {
  const text = String(id || '');
  if (text.length <= size) return text || '—';
  return `${text.slice(0, size)}…`;
}

export function capabilityIndex(capabilities) {
  const map = new Map();
  (capabilities || []).forEach((cap) => {
    if (cap && cap.name) map.set(cap.name, cap);
  });
  return map;
}

export function capabilityMeta(status) {
  switch (status) {
    case 'ready':
      return { label: '可用', tone: 'green' };
    case 'degraded':
      return { label: '降级可用', tone: 'amber' };
    case 'disabled':
      return { label: '不可用', tone: 'red' };
    case 'unauthorized':
      return { label: '无权限', tone: 'red' };
    default:
      return { label: '未上报', tone: 'gray' };
  }
}

// 只有 ready/degraded 可以继续；未知能力视为「后端未上报」，由服务端兜底校验。
export function gateCapabilities(index, names) {
  const blocked = [];
  const unknown = [];
  names.forEach((name) => {
    const cap = index.get(name);
    if (!cap) {
      unknown.push(name);
      return;
    }
    if (cap.status !== 'ready' && cap.status !== 'degraded') {
      blocked.push(cap);
    }
  });
  return { ok: blocked.length === 0, blocked, unknown };
}

export function blockedReason(blocked) {
  return blocked
    .map((cap) => `${cap.name}：${cap.reason || capabilityMeta(cap.status).label}`)
    .join('；');
}

export function severityMeta(severity) {
  switch (severity) {
    case 'critical':
      return { label: '严重', tone: 'red' };
    case 'major':
      return { label: '重要', tone: 'amber' };
    default:
      return { label: '轻微', tone: 'blue' };
  }
}

export const DIMENSION_LABELS = {
  argument: '论证',
  method: '方法',
  evidence: '证据',
  expression: '表达',
  format: '格式',
};

export function dimensionLabel(key) {
  return DIMENSION_LABELS[key] || key;
}

export function taskStatusMeta(status) {
  switch (status) {
    case 'queued':
      return { label: '排队中', tone: 'gray' };
    case 'running':
      return { label: '执行中', tone: 'blue' };
    case 'needs_input':
      return { label: '待补充输入', tone: 'amber' };
    case 'recoverable':
      return { label: '可恢复', tone: 'amber' };
    case 'partial':
      return { label: '部分完成', tone: 'amber' };
    case 'succeeded':
      return { label: '已完成', tone: 'green' };
    case 'failed':
      return { label: '失败', tone: 'red' };
    case 'cancelled':
      return { label: '已取消', tone: 'gray' };
    default:
      return { label: status || '未知', tone: 'gray' };
  }
}

export function verdictMeta(verdict) {
  switch (verdict) {
    case 'issues_found':
      return { label: '发现问题', tone: 'amber' };
    case 'no_major_issues_found':
      return { label: '未发现重大问题', tone: 'green' };
    case 'insufficient_evidence':
      return { label: '证据不足', tone: 'red' };
    default:
      return { label: '尚未评估', tone: 'gray' };
  }
}

export const TERMINAL_STATUSES = new Set(['succeeded', 'partial', 'failed', 'cancelled']);

export function isTerminal(status) {
  return TERMINAL_STATUSES.has(status);
}

export function keyValue(rows) {
  const wrap = createElement('div', { className: 'rw-kv' });
  rows.forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    const row = createElement('div', { className: 'rw-kv-row' });
    row.appendChild(createElement('span', { className: 'rw-kv-key' }, key));
    const valEl = createElement('span', { className: 'rw-kv-val' });
    if (value instanceof Node) valEl.appendChild(value);
    else valEl.textContent = String(value);
    row.appendChild(valEl);
    wrap.appendChild(row);
  });
  return wrap;
}

export function notice({ tone = 'blue', title = '', text = '', actions = [] } = {}) {
  const box = createElement('div', {
    className: `rw-banner ${TONE_CLASS[tone] || TONE_CLASS.blue}`,
    role: tone === 'red' ? 'alert' : 'status',
  });
  if (title) box.appendChild(createElement('div', { className: 'rw-banner-title' }, title));
  if (text) box.appendChild(createElement('div', { className: 'rw-banner-text' }, text));
  if (actions.length) {
    const row = createElement('div', { className: 'rw-banner-actions' });
    actions.forEach((btn) => row.appendChild(btn));
    box.appendChild(row);
  }
  return box;
}

export function button(label, { tone = 'ghost', onClick, disabled = false, title = '', type = 'button', className = '' } = {}) {
  const cls = tone === 'primary'
    ? 'btn btn-primary btn-sm'
    : tone === 'danger'
      ? 'btn btn-outline btn-sm rw-btn-danger'
      : 'btn btn-ghost btn-sm';
  const el = createElement('button', {
    className: `${cls} rw-btn ${className}`.trim(),
    type,
    title,
    'aria-label': title || label,
  }, label);
  if (disabled) {
    el.disabled = true;
    el.setAttribute('aria-disabled', 'true');
  }
  if (onClick && !disabled) el.addEventListener('click', onClick);
  return el;
}

export function sectionHead(title, subtitle, actions = []) {
  const head = createElement('div', { className: 'rw-card-head' });
  const left = createElement('div');
  left.appendChild(createElement('h2', { className: 'rw-card-title' }, title));
  if (subtitle) left.appendChild(createElement('p', { className: 'rw-card-sub' }, subtitle));
  head.appendChild(left);
  if (actions.length) {
    const row = createElement('div', { className: 'rw-card-actions' });
    actions.forEach((el) => row.appendChild(el));
    head.appendChild(row);
  }
  return head;
}

export function card(title, subtitle, body, actions = []) {
  const el = createElement('section', { className: 'rw-card' });
  el.appendChild(sectionHead(title, subtitle, actions));
  const content = createElement('div', { className: 'rw-card-body' });
  if (body) content.appendChild(body);
  el.appendChild(content);
  return el;
}

export function labeledField(label, control, hint = '') {
  const wrap = createElement('label', { className: 'rw-field' });
  wrap.appendChild(createElement('span', { className: 'rw-label' }, label));
  wrap.appendChild(control);
  if (hint) wrap.appendChild(createElement('span', { className: 'rw-hint' }, hint));
  return wrap;
}
