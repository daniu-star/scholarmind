// R1-T18 · 项目列表：选择 / 新建 / 刷新
import { createElement } from '../../utils/dom.js';
import { button, formatWhen, notice, iconBox } from './shared.js';
import { iconRefresh } from '../../utils/icons.js';

export function ProjectList({
  projects = [],
  activeId = null,
  loadingId = null,
  creating = false,
  error = null,
  onCreate,
  onSelect,
  onRefresh,
} = {}) {
  const wrap = createElement('section', { className: 'rw-card rw-projects', 'aria-label': '研究项目列表' });

  const head = createElement('div', { className: 'rw-card-head' });
  const left = createElement('div');
  left.appendChild(createElement('h2', { className: 'rw-card-title' }, '研究项目'));
  left.appendChild(createElement('p', { className: 'rw-card-sub' }, '项目用于隔离文档与诊断任务。'));
  head.appendChild(left);
  const actions = createElement('div', { className: 'rw-card-actions' });
  if (onRefresh) {
    const refresh = button('刷新', { onClick: onRefresh, title: '重新读取项目列表' });
    refresh.insertBefore(iconBox(iconRefresh, 13), refresh.firstChild);
    actions.appendChild(refresh);
  }
  head.appendChild(actions);
  wrap.appendChild(head);

  const body = createElement('div', { className: 'rw-card-body' });

  const form = createElement('form', { className: 'rw-create-form' });
  const input = createElement('input', {
    className: 'rw-input',
    type: 'text',
    placeholder: '新项目标题（1–200 字）',
    maxlength: '200',
    'aria-label': '新项目标题',
  });
  const submit = createElement('button', { className: 'btn btn-primary btn-sm', type: 'submit' }, creating ? '创建中…' : '新建项目');
  submit.disabled = Boolean(creating);
  form.appendChild(input);
  form.appendChild(submit);
  const formError = createElement('p', { className: 'rw-field-error', role: 'alert' });
  formError.hidden = true;
  form.appendChild(formError);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const title = input.value.trim();
    if (!title) {
      formError.textContent = '项目标题不能为空。';
      formError.hidden = false;
      input.focus();
      return;
    }
    if (title.length > 200) {
      formError.textContent = '项目标题最多 200 字。';
      formError.hidden = false;
      return;
    }
    formError.hidden = true;
    submit.disabled = true;
    submit.textContent = '创建中…';
    try {
      await onCreate?.(title);
      input.value = '';
    } catch (err) {
      formError.textContent = err?.message || '创建项目失败。';
      formError.hidden = false;
    } finally {
      submit.disabled = false;
      submit.textContent = '新建项目';
    }
  });
  body.appendChild(form);

  if (error) {
    body.appendChild(
      notice({ tone: 'red', title: '项目列表读取失败', text: error.message || String(error) })
    );
  } else if (!projects.length) {
    body.appendChild(
      notice({
        tone: 'gray',
        title: '还没有研究项目',
        text: '创建项目后即可上传文档；空列表不会伪造示例数据。',
      })
    );
  } else {
    const list = createElement('ul', { className: 'rw-list' });
    projects.forEach((project) => {
      const item = createElement('li');
      const isActive = project.id === activeId;
      const btn = createElement('button', {
        type: 'button',
        className: `rw-list-item${isActive ? ' rw-list-item-active' : ''}`,
        'aria-pressed': isActive ? 'true' : 'false',
        title: project.title,
      });
      if (loadingId === project.id) btn.classList.add('rw-list-item-loading');
      btn.disabled = loadingId !== null && loadingId !== project.id;
      const top = createElement('span', { className: 'rw-list-top' });
      top.appendChild(createElement('span', { className: 'rw-list-title' }, project.title || '未命名项目'));
      if (isActive) top.appendChild(createElement('span', { className: 'rw-list-check', 'aria-hidden': 'true' }, '当前'));
      btn.appendChild(top);
      btn.appendChild(
        createElement(
          'span',
          { className: 'rw-list-meta' },
          `${project.document_count || 0} 份文档 · 更新于 ${formatWhen(project.updated_at)}`
        )
      );
      btn.addEventListener('click', () => onSelect?.(project.id));
      item.appendChild(btn);
      list.appendChild(item);
    });
    body.appendChild(list);
  }

  if (creating) {
    body.appendChild(createElement('p', { className: 'rw-hint' }, '正在创建项目…'));
  }
  wrap.appendChild(body);
  return wrap;
}
