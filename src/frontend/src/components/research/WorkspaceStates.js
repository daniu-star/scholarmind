// R1-T18 · 工作区级状态视图：loading / unauthorized / error / 能力面板
import { createElement } from '../../utils/dom.js';
import {
  capabilityMeta,
  pill,
  notice,
  button,
  iconBox,
} from './shared.js';
import { iconAlert, iconRefresh } from '../../utils/icons.js';

const CAPABILITY_LABELS = {
  database: '数据库',
  'model.llm': '语言模型',
  'document.parser.text': '文本解析（txt/md）',
  'document.parser.pdf': 'PDF 解析',
  'document.parser.docx': 'Word 解析',
  'retrieval.vector': '向量检索',
  'sources.metadata': '来源元数据',
  'library.local': '本地文献库',
  'task.engine': '任务引擎',
  'task.review': '全文诊断任务',
  'task.draft_from_outline': '大纲起草任务',
  'task.revision': '修改建议任务',
  'export.md': 'Markdown 导出',
  'export.docx': 'Word 导出',
  skills: '技能',
  code_execution: '代码执行',
  browser_agent: '浏览器代理',
  chart_generation: '图表生成',
};

const PRIORITY = [
  'database',
  'model.llm',
  'task.engine',
  'task.review',
  'task.revision',
  'document.parser.text',
  'document.parser.pdf',
  'document.parser.docx',
  'export.md',
  'export.docx',
  'sources.metadata',
  'retrieval.vector',
  'library.local',
  'task.draft_from_outline',
  'skills',
  'code_execution',
  'browser_agent',
  'chart_generation',
];

export function capabilityLabel(name) {
  return CAPABILITY_LABELS[name] || name;
}

export function LoadingState(text = '正在读取研究域能力与项目…') {
  const wrap = createElement('div', { className: 'rw-state rw-loading', role: 'status', 'aria-live': 'polite' });
  wrap.appendChild(createElement('div', { className: 'rw-spinner', 'aria-hidden': 'true' }));
  wrap.appendChild(createElement('p', { className: 'rw-state-title' }, text));
  wrap.appendChild(createElement('p', { className: 'rw-state-text' }, '首次加载需要访问 /api/v1/research/capabilities 与 /projects。'));
  return wrap;
}

export function UnauthorizedState({ onLogin, message = '' } = {}) {
  const wrap = createElement('div', { className: 'rw-state rw-unauthorized', role: 'alert' });
  const icon = iconBox(iconAlert, 28);
  icon.className += ' rw-state-icon';
  wrap.appendChild(icon);
  wrap.appendChild(createElement('h2', { className: 'rw-state-title' }, '需要登录后才能使用研究工作区'));
  wrap.appendChild(
    createElement(
      'p',
      { className: 'rw-state-text' },
      message || '研究域接口全部要求 Bearer Token。登录后本页会自动恢复最近一次的项目、文档与任务。'
    )
  );
  wrap.appendChild(
    notice({
      tone: 'gray',
      text: '未登录时不会读取或写入任何研究数据；页面也不会假装成功。',
    })
  );
  const actions = createElement('div', { className: 'rw-state-actions' });
  actions.appendChild(button('去登录', {
    tone: 'primary',
    onClick: () => {
      if (typeof onLogin === 'function') onLogin();
      else window.location.hash = 'auth';
    },
  }));
  wrap.appendChild(actions);
  return wrap;
}

export function ErrorState({ error, onRetry } = {}) {
  const wrap = createElement('div', { className: 'rw-state rw-error', role: 'alert' });
  const icon = iconBox(iconAlert, 28);
  icon.className += ' rw-state-icon';
  wrap.appendChild(icon);
  wrap.appendChild(createElement('h2', { className: 'rw-state-title' }, '研究工作区加载失败'));
  wrap.appendChild(
    createElement('p', { className: 'rw-state-text' }, error?.message || '未知错误，请稍后重试。')
  );
  if (error?.status) {
    wrap.appendChild(
      createElement('p', { className: 'rw-state-meta' }, `HTTP ${error.status}${error.data?.error?.code ? ` · ${error.data.error.code}` : ''}`)
    );
  }
  const actions = createElement('div', { className: 'rw-state-actions' });
  if (onRetry) {
    const retry = button('重新加载', { onClick: onRetry });
    retry.insertBefore(iconBox(iconRefresh, 14), retry.firstChild);
    actions.appendChild(retry);
  }
  actions.appendChild(button('去登录', { onClick: () => { window.location.hash = 'auth'; } }));
  wrap.appendChild(actions);
  return wrap;
}

export function CapabilityPanel({ capabilities = [], loading = false, error = null } = {}) {
  const wrap = createElement('section', { className: 'rw-card rw-cap-card', 'aria-label': '研究域能力状态' });
  const head = createElement('div', { className: 'rw-card-head' });
  const left = createElement('div');
  left.appendChild(createElement('h2', { className: 'rw-card-title' }, '能力状态'));
  left.appendChild(createElement('p', { className: 'rw-card-sub' }, '来自 GET /capabilities；不可用能力会给出原因并禁用对应操作。'));
  head.appendChild(left);
  wrap.appendChild(head);

  const body = createElement('div', { className: 'rw-card-body rw-cap-body' });
  if (loading) {
    body.appendChild(createElement('p', { className: 'rw-hint' }, '读取能力状态…'));
  } else if (error) {
    body.appendChild(
      notice({ tone: 'red', title: '能力状态读取失败', text: error.message || String(error) })
    );
  } else if (!capabilities.length) {
    body.appendChild(
      notice({
        tone: 'gray',
        title: '后端未返回能力清单',
        text: '页面不会假设能力可用；上传、诊断、导出仍由服务端校验并如实报错。',
      })
    );
  } else {
    const ordered = [...capabilities].sort((a, b) => {
      const ai = PRIORITY.indexOf(a.name);
      const bi = PRIORITY.indexOf(b.name);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
    const list = createElement('ul', { className: 'rw-cap-list' });
    ordered.forEach((cap) => {
      const meta = capabilityMeta(cap.status);
      const row = createElement('li', { className: 'rw-cap-row' });
      const line = createElement('div', { className: 'rw-cap-line' });
      line.appendChild(createElement('span', { className: 'rw-cap-name' }, capabilityLabel(cap.name)));
      line.appendChild(pill(meta.label, meta.tone));
      row.appendChild(line);
      if (cap.status !== 'ready') {
        const rawDetail = cap.detail == null || cap.detail === ''
          ? ''
          : (typeof cap.detail === 'string' ? cap.detail : JSON.stringify(cap.detail));
        const detail = [cap.reason, cap.granularity ? `粒度：${cap.granularity}` : '', rawDetail]
          .filter(Boolean)
          .join(' · ');
        if (detail) row.appendChild(createElement('p', { className: 'rw-cap-reason' }, detail));
      }
      list.appendChild(row);
    });
    body.appendChild(list);
  }
  wrap.appendChild(body);
  return wrap;
}
