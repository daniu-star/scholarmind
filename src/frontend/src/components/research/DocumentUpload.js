// R1-T18 · 文档列表与上传
import { createElement } from '../../utils/dom.js';
import {
  button,
  formatBytes,
  formatWhen,
  notice,
  pill,
  iconBox,
} from './shared.js';
import { iconDoc } from '../../utils/icons.js';

export const MAX_FILE_BYTES = 20 * 1024 * 1024;
const ALLOWED_EXT = ['.txt', '.md', '.pdf', '.docx'];

function extOf(name) {
  const index = String(name || '').lastIndexOf('.');
  return index === -1 ? '' : String(name).slice(index).toLowerCase();
}

function parseMeta(status) {
  switch (status) {
    case 'complete':
      return { label: '解析完成', tone: 'green' };
    case 'partial':
      return { label: '部分解析', tone: 'amber' };
    case 'unsupported':
      return { label: '格式不支持', tone: 'red' };
    case 'failed':
      return { label: '解析失败', tone: 'red' };
    default:
      return { label: '解析状态未知', tone: 'gray' };
  }
}

export function DocumentUpload({
  project = null,
  documents = [],
  selectedDocumentId = null,
  loadingDocumentId = null,
  uploading = false,
  uploadError = null,
  onSelectDocument,
  onUpload,
  parserGateFor,
  legacyCandidate = null,
  onImportLegacy,
} = {}) {
  const wrap = createElement('section', { className: 'rw-card rw-docs', 'aria-label': '文档上传与选择' });

  const head = createElement('div', { className: 'rw-card-head' });
  const left = createElement('div');
  left.appendChild(createElement('h2', { className: 'rw-card-title' }, '文档'));
  left.appendChild(createElement('p', { className: 'rw-card-sub' }, '点击文档切换当前诊断对象。'));
  head.appendChild(left);
  wrap.appendChild(head);

  const body = createElement('div', { className: 'rw-card-body' });

  if (!project) {
    body.appendChild(
      notice({ tone: 'gray', title: '尚未选择项目', text: '先在左侧选择或新建一个项目，然后上传文档。' })
    );
    wrap.appendChild(body);
    return wrap;
  }

  const limits = project.limits || {};
  const countText = `${documents.length} / ${limits.max_files_per_project || '—'}`;

  const uploadRow = createElement('div', { className: 'rw-upload-row' });
  const input = createElement('input', {
    type: 'file',
    className: 'rw-file-input',
    accept: '.txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'aria-label': '选择要上传的文档',
  });
  input.id = 'rw-file-input';
  const label = createElement('label', {
    className: 'btn btn-primary btn-sm rw-btn',
    for: 'rw-file-input',
    role: 'button',
  }, uploading ? '上传并解析中…' : '选择文件上传');
  if (uploading) label.classList.add('rw-disabled');
  input.disabled = Boolean(uploading);
  const localError = createElement('p', { className: 'rw-field-error', role: 'alert' });
  localError.hidden = true;

  const handleFile = async (file) => {
    if (!file) return;
    localError.hidden = true;
    const ext = extOf(file.name);
    if (!ALLOWED_EXT.includes(ext)) {
      localError.textContent = `不支持的文件类型 ${ext || '（无扩展名）'}；仅支持 ${ALLOWED_EXT.join(' / ')}。`;
      localError.hidden = false;
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      localError.textContent = `文件 ${formatBytes(file.size)} 超过单文件上限 ${formatBytes(MAX_FILE_BYTES)}，未上传。`;
      localError.hidden = false;
      return;
    }
    if (file.size === 0) {
      localError.textContent = '文件为空，未上传。';
      localError.hidden = false;
      return;
    }
    const gate = typeof parserGateFor === 'function' ? parserGateFor(file.name) : { ok: true };
    if (!gate.ok) {
      localError.textContent = gate.reason;
      localError.hidden = false;
      return;
    }
    try {
      await onUpload?.(file);
    } catch {
      // 具体错误由页面通过 uploadError 展示；这里只在控件旁提示一句。
      localError.textContent = '上传失败，详情见右侧错误提示。';
      localError.hidden = false;
    } finally {
      input.value = '';
    }
  };

  input.addEventListener('change', () => {
    handleFile(input.files?.[0]);
  });
  uploadRow.appendChild(input);
  uploadRow.appendChild(label);
  body.appendChild(uploadRow);
  body.appendChild(
    createElement(
      'p',
      { className: 'rw-hint' },
      `单文件 ≤ ${formatBytes(MAX_FILE_BYTES)}；支持 .txt / .md / .pdf / .docx；本工作区共 ${countText} 份文档。`
    )
  );
  body.appendChild(localError);

  if (uploading) {
    const busy = createElement('div', { className: 'rw-inline-busy', role: 'status' });
    busy.appendChild(createElement('span', { className: 'rw-spinner rw-spinner-sm', 'aria-hidden': 'true' }));
    busy.appendChild(createElement('span', {}, '上传并等待解析（大文件可能需要数秒）…'));
    body.appendChild(busy);
  }

  if (uploadError) {
    body.appendChild(
      notice({
        tone: 'red',
        title: '上传失败',
        text: uploadError.message || String(uploadError),
      })
    );
  }

  if (legacyCandidate && legacyCandidate.chars > 0) {
    const legacy = createElement('div', { className: 'rw-legacy' });
    legacy.appendChild(
      notice({
        tone: 'amber',
        title: '检测到旧版本地写作内容',
        text: `浏览器里存有约 ${legacyCandidate.chars} 字的旧版内容（sm_writing_content）。导入前会请求你确认，导入后作为当前项目的一份 .md 文档。`,
        actions: [
          button('导入到当前项目', {
            tone: 'primary',
            onClick: () => onImportLegacy?.(),
            disabled: uploading,
          }),
        ],
      })
    );
    body.appendChild(legacy);
  }

  if (!documents.length) {
    body.appendChild(
      notice({
        tone: 'gray',
        title: '项目内还没有文档',
        text: '上传成功后会自动选中该文档，并展示解析状态与版本信息。',
      })
    );
  } else {
    const list = createElement('ul', { className: 'rw-list' });
    documents.forEach((doc) => {
      const isActive = doc.id === selectedDocumentId;
      const meta = parseMeta(doc.parse_status);
      const item = createElement('li');
      const btn = createElement('button', {
        type: 'button',
        className: `rw-list-item${isActive ? ' rw-list-item-active' : ''}`,
        'aria-pressed': isActive ? 'true' : 'false',
        title: doc.filename,
      });
      btn.disabled = loadingDocumentId !== null && loadingDocumentId !== doc.id;

      const top = createElement('span', { className: 'rw-list-top' });
      const name = createElement('span', { className: 'rw-list-title' });
      name.appendChild(iconBox(iconDoc, 14));
      name.appendChild(createElement('span', {}, doc.filename || '未命名文档'));
      top.appendChild(name);
      top.appendChild(pill(meta.label, meta.tone));
      btn.appendChild(top);

      const bits = [
        formatBytes(doc.size_bytes),
        doc.codepoints ? `${doc.codepoints} 码点` : '',
        doc.page_count ? `${doc.page_count} 页` : '',
        `上传于 ${formatWhen(doc.created_at)}`,
      ].filter(Boolean);
      btn.appendChild(createElement('span', { className: 'rw-list-meta' }, bits.join(' · ')));

      if (doc.parse_status === 'partial') {
        btn.appendChild(
          createElement('span', { className: 'rw-list-warn' }, '部分解析：诊断只会覆盖已解析内容，未解析部分不计入结论。')
        );
      } else if (doc.parse_status === 'unsupported' || doc.parse_status === 'failed') {
        btn.appendChild(
          createElement('span', { className: 'rw-list-err' }, '该文档无法解析，不能作为诊断输入；请更换文件。')
        );
      }

      btn.addEventListener('click', () => onSelectDocument?.(doc.id));
      item.appendChild(btn);
      list.appendChild(item);
    });
    body.appendChild(list);
  }

  wrap.appendChild(body);
  return wrap;
}
