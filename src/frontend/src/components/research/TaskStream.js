// R1-T18 · 任务状态灯 + SSE 事件日志（续订/重连不取消服务端任务）
import { createElement } from '../../utils/dom.js';
import {
  button,
  formatClock,
  pill,
  notice,
  taskStatusMeta,
  iconBox,
} from './shared.js';
import { iconRefresh } from '../../utils/icons.js';

const STREAM_META = {
  idle: { label: '未连接', tone: 'gray' },
  connecting: { label: '连接中', tone: 'amber' },
  open: { label: '已连接', tone: 'green' },
  reconnecting: { label: '重连中', tone: 'amber' },
  closed: { label: '流已结束', tone: 'gray' },
  error: { label: '连接异常', tone: 'red' },
  aborted: { label: '已断开本地流', tone: 'gray' },
};

const KIND_LABELS = {
  review: '全文诊断',
  revision: '修改建议',
  draft_from_outline: '大纲起草',
  literature_review: '文献综述',
  chart: '图表',
  export: '导出',
};

function summarizePayload(type, payload = {}) {
  if (!payload || typeof payload !== 'object') return '';
  switch (type) {
    case 'task.started':
      return [payload.model, payload.provider, payload.mode, payload.pipeline_version]
        .filter(Boolean)
        .join(' · ');
    case 'artifact.created':
      return [payload.kind, payload.artifact_id].filter(Boolean).join(' · ');
    case 'task.completed':
      return `${Array.isArray(payload.artifact_ids) ? payload.artifact_ids.length : 0} 个成果${payload.quality_verdict ? ` · ${payload.quality_verdict}` : ''}`;
    case 'task.failed':
    case 'task.partial':
    case 'task.recoverable': {
      const err = payload.error || payload.errors;
      if (err && typeof err === 'object') return String(err.message || err.code || JSON.stringify(err));
      if (Array.isArray(err)) return err.map((item) => item?.message || item).join('；');
      return err ? String(err) : '';
    }
    case 'task.progress': {
      const stage = payload.stage || payload.phase || payload.status || '';
      const done = payload.done ?? payload.analyzed_blocks;
      const total = payload.total ?? payload.expected_blocks;
      return [stage, done !== undefined && total !== undefined ? `${done}/${total}` : ''].filter(Boolean).join(' · ');
    }
    default: {
      const text = JSON.stringify(payload);
      return text && text !== '{}' ? text.slice(0, 120) : '';
    }
  }
}

export function TaskStream({ onReconnect, onCancel, onRetry, onResume, onDisconnect } = {}) {
  const el = createElement('section', { className: 'rw-card rw-stream-card', 'aria-label': '任务状态与事件流' });

  const head = createElement('div', { className: 'rw-card-head' });
  const left = createElement('div');
  left.appendChild(createElement('h2', { className: 'rw-card-title' }, '任务与事件流'));
  left.appendChild(
    createElement('p', { className: 'rw-card-sub' }, 'GET /tasks/{id}/events（SSE）。离开页面只断开本地流，不取消服务端任务。')
  );
  head.appendChild(left);

  const lampWrap = createElement('div', { className: 'rw-lamp-wrap' });
  const lamp = createElement('span', { className: 'rw-lamp', 'aria-hidden': 'true' });
  const lampText = createElement('span', { className: 'rw-lamp-text' }, '未连接');
  lampWrap.appendChild(lamp);
  lampWrap.appendChild(lampText);
  head.appendChild(lampWrap);
  el.appendChild(head);

  const body = createElement('div', { className: 'rw-card-body' });

  const statusRow = createElement('div', { className: 'rw-stream-status' });
  const taskPill = createElement('span');
  const kindText = createElement('span', { className: 'rw-mono rw-small' }, '—');
  const seqText = createElement('span', { className: 'rw-mono rw-small' }, '最后事件序号：—');
  const attemptText = createElement('span', { className: 'rw-small rw-muted' }, '');
  statusRow.appendChild(taskPill);
  statusRow.appendChild(kindText);
  statusRow.appendChild(attemptText);
  statusRow.appendChild(seqText);
  body.appendChild(statusRow);

  const messageEl = createElement('p', { className: 'rw-stream-message', role: 'status', 'aria-live': 'polite' });
  body.appendChild(messageEl);

  const errorEl = createElement('div', { className: 'rw-stream-error' });
  body.appendChild(errorEl);

  const controls = createElement('div', { className: 'rw-stream-controls' });
  body.appendChild(controls);

  const logHead = createElement('div', { className: 'rw-log-head' });
  logHead.appendChild(createElement('span', { className: 'rw-label' }, '事件日志'));
  logHead.appendChild(createElement('span', { className: 'rw-hint' }, '最多保留最近 200 条；序号用于续订。'));
  body.appendChild(logHead);

  const log = createElement('ol', { className: 'rw-log', 'aria-live': 'polite', 'aria-label': '任务事件日志' });
  body.appendChild(log);
  const logEmpty = createElement('p', { className: 'rw-hint' }, '尚无事件。任务开始后会逐条显示 id / event / 摘要。');
  body.appendChild(logEmpty);

  el.appendChild(body);

  let task = null;
  let streamState = 'idle';
  let events = [];
  const seenSequences = new Set();

  function renderStatus() {
    const meta = STREAM_META[streamState] || STREAM_META.idle;
    lamp.className = `rw-lamp rw-lamp-${meta.tone}`;
    lampText.textContent = meta.label;
    if (!task) {
      taskPill.replaceChildren(pill('无任务', 'gray'));
      kindText.textContent = '—';
      attemptText.textContent = '';
      return;
    }
    const status = taskStatusMeta(task.status);
    taskPill.replaceChildren(pill(status.label, status.tone));
    kindText.textContent = `${KIND_LABELS[task.kind] || task.kind} · ${task.id}`;
    attemptText.textContent = `第 ${task.attempt_no || 0} 次尝试 · revision ${task.state_revision}`;
  }

  function renderControls() {
    controls.replaceChildren();
    if (!task) return;
    const running = task.status === 'queued' || task.status === 'running';
    const terminal = ['succeeded', 'partial', 'failed', 'cancelled'].includes(task.status);
    if (running && onCancel) {
      controls.appendChild(
        button('取消任务', {
          tone: 'danger',
          onClick: () => onCancel(task),
          title: '取消会终止服务端任务；仅在用户明确确认后执行',
        })
      );
    }
    if (!terminal && onReconnect) {
      const reconnect = button(streamState === 'error' || streamState === 'closed' ? '重新连接事件流' : '立即续订', {
        onClick: () => onReconnect(task),
        title: '从最后一条事件序号续订，不重跑任务',
      });
      reconnect.insertBefore(iconBox(iconRefresh, 13), reconnect.firstChild);
      controls.appendChild(reconnect);
    }
    if (!terminal && onDisconnect) {
      controls.appendChild(
        button('断开本地流', {
          onClick: () => onDisconnect(task),
          title: '只停止浏览器读取 SSE，服务端任务继续执行',
        })
      );
    }
    if ((task.status === 'failed' || task.status === 'recoverable') && task.can_retry && onRetry) {
      controls.appendChild(
        button('重试任务', { tone: 'primary', onClick: () => onRetry(task), title: '带 expected_state_revision 重试' })
      );
    }
    if ((task.can_resume || task.status === 'needs_input') && onResume) {
      const input = createElement('input', {
        className: 'rw-input rw-resume-input',
        type: 'text',
        maxlength: '2000',
        placeholder: '补充说明（提交为 answers.user_note，可留空）',
        'aria-label': '补充说明',
      });
      controls.appendChild(input);
      controls.appendChild(
        button('恢复任务', {
          tone: 'primary',
          onClick: () => onResume(task, input.value.trim()),
          title: '提交 expected_state_revision 与补充说明',
        })
      );
    }
  }

  function renderError() {
    errorEl.replaceChildren();
    if (!task) return;
    if (task.error) {
      const message = task.error.message || task.error.code || JSON.stringify(task.error);
      errorEl.appendChild(
        notice({
          tone: 'red',
          title: `任务${task.status === 'failed' ? '失败' : '异常'}`,
          text: `${message}${task.error.code ? `（${task.error.code}）` : ''}`,
        })
      );
    }
    if (task.warnings && task.warnings.length) {
      errorEl.appendChild(
        notice({ tone: 'amber', title: '任务警告', text: task.warnings.join('；') })
      );
    }
  }

  function setTask(next) {
    task = next || null;
    renderStatus();
    renderControls();
    renderError();
  }

  function setStream(next = {}) {
    streamState = next.state || 'idle';
    if (next.lastSequence !== undefined && next.lastSequence !== null) {
      seqText.textContent = `最后事件序号：${next.lastSequence}`;
    }
    messageEl.textContent = next.message || '';
    const meta = STREAM_META[streamState] || STREAM_META.idle;
    lamp.className = `rw-lamp rw-lamp-${meta.tone}`;
    lampText.textContent = meta.label;
    renderControls();
  }

  function pushEvent(frame) {
    if (!frame) return;
    const data = frame.data || {};
    // 续订时服务端可能重发已收到的事件；按序号去重，避免日志重复与重复渲染。
    const seqKey = data.sequence ?? frame.id ?? null;
    if (seqKey !== null && seqKey !== undefined) {
      const key = String(seqKey);
      if (seenSequences.has(key)) return;
      seenSequences.add(key);
    }
    events.push(frame);
    if (events.length > 200) events = events.slice(events.length - 200);
    const row = createElement('li', { className: 'rw-log-row' });
    row.appendChild(createElement('span', { className: 'rw-log-seq' }, `#${data.sequence ?? frame.id ?? '—'}`));
    row.appendChild(createElement('span', { className: 'rw-log-type' }, data.type || frame.event || 'message'));
    const summary = summarizePayload(data.type || frame.event, data.payload || {});
    if (summary) row.appendChild(createElement('span', { className: 'rw-log-summary' }, summary));
    row.appendChild(
      createElement('span', { className: 'rw-log-time' }, formatClock(data.created_at))
    );
    log.appendChild(row);
    while (log.children.length > 200) log.removeChild(log.firstChild);
    logEmpty.hidden = true;
    log.scrollTop = log.scrollHeight;
  }

  function reset() {
    task = null;
    events = [];
    seenSequences.clear();
    log.replaceChildren();
    logEmpty.hidden = false;
    seqText.textContent = '最后事件序号：—';
    messageEl.textContent = '';
    errorEl.replaceChildren();
    controls.replaceChildren();
    setStream({ state: 'idle' });
    renderStatus();
  }

  reset();
  return { el, setTask, setStream, pushEvent, reset, getEvents: () => events.slice() };
}
