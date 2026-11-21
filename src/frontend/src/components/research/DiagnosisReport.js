// R1-T18 · 诊断结论：覆盖率、质量判定、警告与未解决项
import { createElement } from '../../utils/dom.js';
import {
  notice,
  pill,
  verdictMeta,
  keyValue,
  button,
  iconBox,
} from './shared.js';
import { iconRefresh } from '../../utils/icons.js';

function listBlock(title, items, className = 'rw-plain-list') {
  if (!items || !items.length) return null;
  const wrap = createElement('div', { className: 'rw-report-block' });
  wrap.appendChild(createElement('h3', { className: 'rw-subtitle' }, `${title}（${items.length}）`));
  const list = createElement('ul', { className });
  items.forEach((item) => {
    const text = typeof item === 'string' ? item : JSON.stringify(item);
    list.appendChild(createElement('li', {}, text));
  });
  wrap.appendChild(list);
  return wrap;
}

export function DiagnosisReport({
  task = null,
  findings = [],
  loading = false,
  error = null,
  onRetryLoad,
  onRetryTask,
} = {}) {
  const wrap = createElement('section', { className: 'rw-card rw-diagnosis', 'aria-label': '诊断结论' });

  const head = createElement('div', { className: 'rw-card-head' });
  const left = createElement('div');
  left.appendChild(createElement('h2', { className: 'rw-card-title' }, '诊断结论与覆盖范围'));
  left.appendChild(createElement('p', { className: 'rw-card-sub' }, '结论只对已分析内容成立；覆盖率之外的部分不构成“通过”。'));
  head.appendChild(left);
  wrap.appendChild(head);

  const body = createElement('div', { className: 'rw-card-body' });

  if (!task) {
    body.appendChild(notice({ tone: 'gray', title: '尚未发起诊断', text: '先选择文档并确认诊断范围，再启动全文诊断任务。' }));
    wrap.appendChild(body);
    return wrap;
  }

  if (task.status === 'partial') {
    body.appendChild(
      notice({
        tone: 'amber',
        title: '任务部分完成',
        text: '后端只完成了部分分析。未覆盖的段落/维度不会被自动视为通过，导出与修改建议会沿用该限制。',
      })
    );
  }
  if (task.status === 'failed') {
    body.appendChild(
      notice({
        tone: 'red',
        title: '诊断任务失败',
        text: task.error?.message || task.error?.code || '任务失败；可查看事件日志或重试任务。',
        actions: task.can_retry && onRetryTask
          ? [button('重试诊断', { tone: 'primary', onClick: () => onRetryTask(task) })]
          : [],
      })
    );
  }

  const verdict = verdictMeta(task.quality_verdict);
  const counts = findings.reduce(
    (acc, item) => {
      acc[item.severity] = (acc[item.severity] || 0) + 1;
      return acc;
    },
    { critical: 0, major: 0, minor: 0 }
  );
  const verdictText = task.quality_verdict === 'issues_found'
    ? `发现 ${findings.length} 项问题：严重 ${counts.critical} · 重要 ${counts.major} · 轻微 ${counts.minor}。`
    : task.quality_verdict === 'no_major_issues_found'
      ? '后端未发现重大问题。该结论只覆盖已分析内容，不等于论文达到发表标准。'
      : task.quality_verdict === 'insufficient_evidence'
        ? '证据不足，不能据此判断论文质量；请补充材料或改用更充分的模式后重新诊断。'
        : '后端尚未给出质量判定。';

  const summary = createElement('div', { className: 'rw-verdict' });
  const verdictLine = createElement('div', { className: 'rw-verdict-line' });
  verdictLine.appendChild(pill(verdict.label, verdict.tone));
  verdictLine.appendChild(createElement('span', { className: 'rw-verdict-text' }, verdictText));
  summary.appendChild(verdictLine);

  const coverage = task.coverage;
  const kvRows = [
    ['任务状态', taskStatusText(task.status)],
    ['尝试次数', String(task.attempt_no ?? 0)],
    ['解析状态', coverage?.parse_status || '—'],
    [
      '已分析 / 应分析块',
      coverage
        ? `${coverage.analyzed_eligible_blocks ?? 0} / ${coverage.expected_eligible_blocks ?? 0}`
        : '—',
    ],
    ['覆盖率', coverage && coverage.expected_eligible_blocks
      ? `${Math.round(((coverage.analyzed_eligible_blocks || 0) / coverage.expected_eligible_blocks) * 100)}%`
      : '—'],
    ['页数', coverage?.pages ? String(coverage.pages) : '—'],
    ['质量判定', task.quality_verdict || '—'],
  ];
  summary.appendChild(keyValue(kvRows));
  body.appendChild(summary);

  const unassessed = coverage?.unassessed_objects || [];
  const warningItems = [...(coverage?.warnings || []), ...(task.warnings || [])];
  const unresolved = task.unresolved_items || [];

  if (unassessed.length) {
    body.appendChild(
      notice({
        tone: 'amber',
        title: '存在未评估对象',
        text: `${unassessed.length} 个对象未被评估（例如图片、表格、脚注或解析失败的内容）；这些内容不会进入问题清单。`,
      })
    );
    const block = listBlock('未评估对象', unassessed, 'rw-plain-list rw-mono-list');
    if (block) body.appendChild(block);
  }
  if (warningItems.length) {
    const block = listBlock('警告', warningItems);
    if (block) body.appendChild(block);
  }
  if (unresolved.length) {
    const block = listBlock('未解决项', unresolved, 'rw-plain-list rw-warn-list');
    if (block) body.appendChild(block);
  }

  body.appendChild(createElement('h3', { className: 'rw-subtitle' }, `问题与依据（${findings.length}）`));

  if (loading) {
    const busy = createElement('div', { className: 'rw-inline-busy', role: 'status' });
    busy.appendChild(createElement('span', { className: 'rw-spinner rw-spinner-sm', 'aria-hidden': 'true' }));
    busy.appendChild(createElement('span', {}, '正在读取诊断项（GET /tasks/{id}/findings）…'));
    body.appendChild(busy);
  } else if (error) {
    const retry = onRetryLoad
      ? button('重新读取诊断项', { onClick: onRetryLoad })
      : null;
    if (retry) retry.insertBefore(iconBox(iconRefresh, 13), retry.firstChild);
    body.appendChild(
      notice({
        tone: 'red',
        title: '诊断项读取失败',
        text: error.message || String(error),
        actions: retry ? [retry] : [],
      })
    );
  } else if (!findings.length) {
    body.appendChild(
      notice({
        tone: 'gray',
        title: task.quality_verdict === 'no_major_issues_found' ? '没有可展示的问题' : '暂无诊断项',
        text: task.quality_verdict === 'insufficient_evidence'
          ? '证据不足时后端可能不产出 finding；请补充材料或改用 pro 模式重新诊断。'
          : '后端返回的 findings 为空。空列表是真实结果，页面不会用示例问题填充。',
      })
    );
  }

  wrap.appendChild(body);
  return wrap;
}

function taskStatusText(status) {
  const map = {
    queued: '排队中',
    running: '执行中',
    needs_input: '待补充输入',
    recoverable: '可恢复',
    partial: '部分完成',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };
  return map[status] || status || '—';
}
