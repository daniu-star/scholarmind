// R1-T18 · 单条诊断项卡片（严重度/定位/依据/未解决项）
import { createElement } from '../../utils/dom.js';
import {
  button,
  notice,
  pill,
  severityMeta,
  shortId,
} from './shared.js';

const VERIFICATION_LABELS = {
  tool: '工具校验',
  model: '模型判断',
  human: '需人工确认',
  none: '无校验',
};

function locatorLines(locator) {
  if (!locator) return [];
  if (typeof locator === 'string') return [locator];
  if (typeof locator !== 'object') return [String(locator)];
  return Object.entries(locator)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`);
}

export function FindingCard({
  finding,
  index = 0,
  selected = false,
  onToggle,
  onAdopt,
  adoptDisabled = false,
  adoptDisabledReason = '',
} = {}) {
  const severity = severityMeta(finding.severity);
  const cardEl = createElement('article', {
    className: `rw-finding rw-finding-${finding.severity || 'minor'}${selected ? ' rw-finding-selected' : ''}`,
    'aria-label': `诊断项 ${index + 1}`,
  });

  const head = createElement('div', { className: 'rw-finding-head' });
  const checkId = `rw-finding-${finding.id}`;
  const checkbox = createElement('input', {
    type: 'checkbox',
    id: checkId,
    className: 'rw-check',
    'aria-label': `选择诊断项 ${index + 1} 作为修改目标`,
  });
  checkbox.checked = Boolean(selected);
  checkbox.addEventListener('change', () => onToggle?.(finding.id, checkbox.checked));
  head.appendChild(checkbox);

  const label = createElement('label', { className: 'rw-finding-label', for: checkId });
  label.appendChild(pill(`${severity.label} · ${finding.category || '未分类'}`, severity.tone));
  label.appendChild(
    pill(finding.scope === 'local' ? '局部片段' : '全文范围', finding.scope === 'local' ? 'gray' : 'blue')
  );
  label.appendChild(
    createElement(
      'span',
      { className: 'rw-small rw-muted' },
      `${VERIFICATION_LABELS[finding.verification_method] || finding.verification_method || '未知校验'} · 编号 ${shortId(finding.id, 14)}`
    )
  );
  head.appendChild(label);
  cardEl.appendChild(head);

  if (finding.required_user_action) {
    cardEl.appendChild(
      notice({
        tone: 'amber',
        title: '需要你处理',
        text: finding.required_user_action,
      })
    );
  }

  const body = createElement('div', { className: 'rw-finding-body' });

  const problem = createElement('div', { className: 'rw-finding-section' });
  problem.appendChild(createElement('h4', { className: 'rw-finding-title' }, finding.problem || '问题描述为空'));
  if (finding.quote) {
    const quote = createElement('blockquote', { className: 'rw-quote' }, finding.quote);
    problem.appendChild(quote);
  }
  const locs = locatorLines(finding.locator);
  if (locs.length) {
    const locBox = createElement('div', { className: 'rw-locator' });
    locBox.appendChild(createElement('span', { className: 'rw-label' }, '定位'));
    const list = createElement('ul', { className: 'rw-plain-list rw-mono-list' });
    locs.forEach((line) => list.appendChild(createElement('li', {}, line)));
    locBox.appendChild(list);
    problem.appendChild(locBox);
  }
  body.appendChild(problem);

  if (finding.reason) {
    const reason = createElement('div', { className: 'rw-finding-section' });
    reason.appendChild(createElement('h4', { className: 'rw-finding-title' }, '为什么是问题'));
    reason.appendChild(createElement('p', { className: 'rw-finding-text' }, finding.reason));
    body.appendChild(reason);
  }

  if (finding.recommendation) {
    const recommendation = createElement('div', { className: 'rw-finding-section' });
    recommendation.appendChild(createElement('h4', { className: 'rw-finding-title' }, '修改建议'));
    recommendation.appendChild(createElement('p', { className: 'rw-finding-text' }, finding.recommendation));
    body.appendChild(recommendation);
  }

  if (Array.isArray(finding.evidence_refs) && finding.evidence_refs.length) {
    const evidence = createElement('div', { className: 'rw-finding-section' });
    evidence.appendChild(createElement('h4', { className: 'rw-finding-title' }, `依据（${finding.evidence_refs.length}）`));
    const chips = createElement('div', { className: 'rw-chips' });
    finding.evidence_refs.forEach((ref) => {
      const text = typeof ref === 'string' ? ref : JSON.stringify(ref);
      chips.appendChild(pill(shortId(text, 40), 'gray'));
    });
    evidence.appendChild(chips);
    body.appendChild(evidence);
  }

  if (Array.isArray(finding.checked_sections) && finding.checked_sections.length) {
    const checked = createElement('div', { className: 'rw-finding-section' });
    checked.appendChild(createElement('h4', { className: 'rw-finding-title' }, '已核对的小节'));
    const chips = createElement('div', { className: 'rw-chips' });
    finding.checked_sections.forEach((section) => {
      chips.appendChild(pill(typeof section === 'string' ? section : JSON.stringify(section), 'gray'));
    });
    checked.appendChild(chips);
    body.appendChild(checked);
  }

  cardEl.appendChild(body);

  const footer = createElement('div', { className: 'rw-finding-footer' });
  if (adoptDisabled && adoptDisabledReason) {
    footer.appendChild(createElement('span', { className: 'rw-hint' }, adoptDisabledReason));
  }
  if (onAdopt) {
    footer.appendChild(
      button('仅此项生成修改建议', {
        onClick: () => onAdopt(finding),
        disabled: adoptDisabled,
        title: adoptDisabled ? adoptDisabledReason : '创建只含该诊断项的 revision 任务',
      })
    );
  }
  cardEl.appendChild(footer);

  return cardEl;
}
