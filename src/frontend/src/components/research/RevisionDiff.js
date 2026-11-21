// R1-T18 · 修改建议展示：解析提案 markdown，展示逐条 diff，并说明整份采纳范围
import { createElement } from '../../utils/dom.js';
import {
  button,
  keyValue,
  notice,
  pill,
  shortId,
  formatBytes,
} from './shared.js';

// 解析 revision_service._render_proposal_markdown 的固定格式。
// 只做只读展示；hunk 的真实 ID 不暴露在客户端，因此不能逐条 apply。
export function parseProposalMarkdown(markdown) {
  const text = String(markdown || '');
  const meta = {};
  const hunks = [];
  let current = null;
  let field = null;

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;

    const hunkMatch = /^###\s*(\d+)\.\s*码点\s*(\d+)\s*[–-]\s*(\d+)\s*（诊断项\s*([^）]+)）/.exec(line);
    if (hunkMatch) {
      current = {
        index: Number(hunkMatch[1]),
        start: Number(hunkMatch[2]),
        end: Number(hunkMatch[3]),
        findingId: hunkMatch[4].trim(),
        original: '',
        replacement: '',
        reason: '',
      };
      hunks.push(current);
      field = null;
      continue;
    }

    if (line === '## 修改清单' || line === '## 验证说明' || line === '# 修改建议') {
      current = null;
      field = null;
      continue;
    }

    if (!current) {
      const metaMatch = /^-\s*([^：:]+)[：:]\s*(.*)$/.exec(line);
      if (metaMatch) meta[metaMatch[1].trim()] = metaMatch[2].trim();
      continue;
    }

    if (line === '原文：') {
      field = 'original';
      continue;
    }
    if (line === '建议：') {
      field = 'replacement';
      continue;
    }
    if (line.startsWith('修改原因：')) {
      current.reason = line.slice('修改原因：'.length).trim();
      field = null;
      continue;
    }
    if (field && line.startsWith('>')) {
      const value = line.replace(/^>\s?/, '');
      current[field] = current[field] ? `${current[field]}\n${value}` : value;
    }
  }

  return { meta, hunks };
}

export function RevisionDiff({
  artifact = null,
  validation = null,
  markdown = '',
  applyState = 'idle',
  applyError = null,
  conflict = false,
  applyResult = null,
  onApply,
  onRediagnose,
  onDownload,
} = {}) {
  const parsed = parseProposalMarkdown(markdown);
  const hunks = parsed.hunks;
  const meta = parsed.meta;
  const proposalId = validation?.proposal_id || meta['提案'] || '';
  const hunkCount = validation?.hunk_count ?? (meta['补丁数'] ? Number(meta['补丁数']) : hunks.length);
  const baseVersion = validation?.base_version_id || meta['基准版本'] || '';
  const valid = validation?.valid !== false;

  const wrap = createElement('section', { className: 'rw-card rw-revision', 'aria-label': '修改建议' });
  const head = createElement('div', { className: 'rw-card-head' });
  const left = createElement('div');
  left.appendChild(createElement('h2', { className: 'rw-card-title' }, '修改建议'));
  left.appendChild(
    createElement(
      'p',
      { className: 'rw-card-sub' },
      '修改建议是待采纳补丁，不会自动改写文档；应用时服务端会再次校验基准版本与原文哈希。'
    )
  );
  head.appendChild(left);

  const actions = createElement('div', { className: 'rw-card-actions' });
  if (artifact && onDownload) {
    actions.appendChild(button('下载提案原文', { onClick: () => onDownload(artifact) }));
  }
  head.appendChild(actions);
  wrap.appendChild(head);

  const body = createElement('div', { className: 'rw-card-body' });

  body.appendChild(
    notice({
      tone: 'blue',
      title: '采纳范围：整份提案',
      text: '后端 apply 接口需要 hunk_ids，但客户端无法获得逐条 hunk 的真实 ID，因此本页只提交 hunk_ids: []（应用整份提案）。若只想采纳某一条，请对该诊断项单独生成一份修改建议。',
    })
  );

  body.appendChild(
    keyValue([
      ['提案', proposalId ? shortId(proposalId, 18) : '—'],
      ['补丁数', String(hunkCount ?? hunks.length)],
      ['基准版本', baseVersion ? shortId(baseVersion, 18) : '—'],
      ['服务端校验', validation ? (valid ? '通过' : '未通过') : '未提供'],
      ['基准原文哈希', validation?.base_text_hash ? shortId(validation.base_text_hash, 16) : '—'],
      ['成果大小', artifact?.size_bytes ? formatBytes(artifact.size_bytes) : '—'],
    ])
  );

  if (!valid) {
    body.appendChild(
      notice({
        tone: 'red',
        title: '提案未通过服务端校验',
        text: '该提案存在区间或原文匹配问题，不能应用；请重新生成修改建议。',
      })
    );
  }

  if (!hunks.length) {
    body.appendChild(
      notice({
        tone: 'gray',
        title: '没有可解析的补丁',
        text: markdown
          ? '提案正文未能按固定格式解析出补丁；下面是只读原文，供核对。'
          : '尚未读取到提案正文。',
      })
    );
    if (markdown) {
      body.appendChild(createElement('pre', { className: 'rw-pre' }, markdown));
    }
  } else {
    body.appendChild(createElement('h3', { className: 'rw-subtitle' }, `补丁清单（${hunks.length}）`));
    const list = createElement('ol', { className: 'rw-diff-list' });
    hunks.forEach((hunk) => {
      const item = createElement('li', { className: 'rw-diff' });
      const diffHead = createElement('div', { className: 'rw-diff-head' });
      diffHead.appendChild(createElement('span', { className: 'rw-diff-index' }, `#${hunk.index}`));
      diffHead.appendChild(
        createElement('span', { className: 'rw-mono rw-small' }, `码点 ${hunk.start}–${hunk.end}`)
      );
      diffHead.appendChild(pill(`诊断项 ${shortId(hunk.findingId, 14)}`, 'gray'));
      item.appendChild(diffHead);

      const grid = createElement('div', { className: 'rw-diff-grid' });
      const original = createElement('div', { className: 'rw-diff-block rw-diff-original' });
      original.appendChild(createElement('div', { className: 'rw-diff-label' }, '原文'));
      original.appendChild(createElement('pre', { className: 'rw-diff-text' }, hunk.original || '（空）'));
      grid.appendChild(original);

      const suggestion = createElement('div', { className: 'rw-diff-block rw-diff-suggestion' });
      suggestion.appendChild(createElement('div', { className: 'rw-diff-label' }, '建议'));
      suggestion.appendChild(createElement('pre', { className: 'rw-diff-text' }, hunk.replacement || '（删除）'));
      grid.appendChild(suggestion);
      item.appendChild(grid);

      if (hunk.reason) {
        item.appendChild(createElement('p', { className: 'rw-diff-reason' }, `修改原因：${hunk.reason}`));
      }
      list.appendChild(item);
    });
    body.appendChild(list);
  }

  body.appendChild(
    notice({
      tone: 'gray',
      title: '保护说明',
      text: '默认保护数字、日期、人名、直接引语与引文；应用时若基准版本或原文哈希变化，服务端会以 409 VERSION_CONFLICT 拒绝，不会静默覆盖。',
    })
  );

  if (conflict) {
    body.appendChild(
      notice({
        tone: 'red',
        title: '版本冲突，提案未应用',
        text: '文档在提案生成后已变化（409 VERSION_CONFLICT）。本提案不能安全应用，请基于最新版本重新诊断并生成新的修改建议。',
        actions: onRediagnose
          ? [button('重新诊断', { tone: 'primary', onClick: onRediagnose })]
          : [],
      })
    );
  }

  if (applyError) {
    body.appendChild(
      notice({
        tone: 'red',
        title: '应用失败',
        text: applyError.message || String(applyError),
      })
    );
  }

  if (applyResult) {
    body.appendChild(
      notice({
        tone: 'green',
        title: '提案已应用，生成新文档版本',
        text: `新版本：${applyResult.new_version_id} · 应用补丁 ${Array.isArray(applyResult.applied_hunk_ids) ? applyResult.applied_hunk_ids.length : 0} 个 · 变更记录成果 ${applyResult.change_log_artifact_id || '—'}。请在上方文档列表确认新版本后再导出。`,
      })
    );
  }

  const applyBar = createElement('div', { className: 'rw-apply-bar' });
  const applying = applyState === 'applying';
  applyBar.appendChild(
    button(applying ? '正在应用…' : '采纳整份提案', {
      tone: 'primary',
      disabled: applying || !valid || !proposalId,
      onClick: () => onApply?.({ proposalId, validation, hunks }),
      title: !valid
        ? '提案未通过服务端校验，不能应用'
        : '提交 expected_version_id=基准版本 与 hunk_ids: []（整份）',
    })
  );
  applyBar.appendChild(
    createElement(
      'span',
      { className: 'rw-hint' },
      '点击后调用 POST /revision-proposals/{id}/apply，成功后当前文档会出现新版本；失败会保留原文档并显示原因。'
    )
  );
  body.appendChild(applyBar);

  wrap.appendChild(body);
  return wrap;
}
