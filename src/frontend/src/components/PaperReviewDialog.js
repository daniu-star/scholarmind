import { paperReviewApi } from '../services/paperPipelineApi.js';
import { iconClose, iconClipboardCheck, iconCheck } from '../utils/icons.js';

const RESEARCH_TYPES = [
  { id: 'qualitative', name: '质化研究' },
  { id: 'quantitative', name: '量化研究' },
  { id: 'computational', name: '计算社会科学' },
  { id: 'mixed', name: '混合方法' },
  { id: 'interview_report', name: '访谈报告' },
  { id: 'theoretical', name: '理论建构' },
];

const JOURNAL_STYLES = [
  { id: 'xwycbyj', name: '新闻与传播研究' },
  { id: 'gjxwj', name: '国际新闻界' },
  { id: 'xwdx', name: '新闻大学' },
  { id: 'shxyj', name: '社会学研究' },
];

export function showPaperReviewDialog({ onStarted, onCancel } = {}) {
  const existing = document.getElementById('paperReviewDialog');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'paperReviewDialog';
  overlay.className = 'topic-dialog-overlay';
  overlay.innerHTML =
    '<div class="topic-dialog-card paper-gen-card">' +
      '<div class="topic-dialog-decoration"></div>' +
      '<div class="topic-dialog-header">' +
        '<div class="topic-dialog-icon-wrap"><span class="topic-dialog-icon-emoji">' + iconClipboardCheck(20) + '</span></div>' +
        '<h3 class="topic-dialog-title">论文修改链条</h3>' +
        '<button class="paper-gen-close" aria-label="关闭">' + iconClose(18) + '</button>' +
      '</div>' +
      '<p class="topic-dialog-desc">7 Agent 循环式审稿优化：约束注入 → 外审专家 → 意见路由 → 并行修改 → 风格守卫 → 指令守卫 → 格式输出</p>' +
      '<div class="paper-gen-form">' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">论文全文 <span class="paper-gen-required">*</span></label>' +
          '<textarea class="paper-gen-textarea paper-gen-textarea-large" rows="6" placeholder="粘贴论文全文（至少 10 个字符）" id="pr-paper"></textarea>' +
        '</div>' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">研究类型</label>' +
          '<div class="paper-gen-chips" id="pr-research-type">' +
            RESEARCH_TYPES.map((t, i) =>
              '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + t.id + '">' + t.name + '</button>'
            ).join('') +
          '</div>' +
        '</div>' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">期刊格式</label>' +
          '<div class="paper-gen-chips" id="pr-journal-style">' +
            JOURNAL_STYLES.map((j, i) =>
              '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + j.id + '">' + j.name + '</button>'
            ).join('') +
          '</div>' +
        '</div>' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">修改重点（可选）</label>' +
          '<input type="text" class="paper-gen-input" id="pr-focus" placeholder="例如：加强理论对话、优化方法论">' +
        '</div>' +
      '</div>' +
      '<div class="paper-gen-actions">' +
        '<button class="btn btn-ghost paper-gen-cancel">取消</button>' +
        '<button class="btn btn-primary paper-gen-start">' +
          '<span class="paper-gen-start-text">启动审稿</span>' +
        '</button>' +
      '</div>' +
      '<div class="paper-gen-status" id="pr-status" style="display:none;"></div>' +
    '</div>';

  document.body.appendChild(overlay);

  const card = overlay.querySelector('.paper-gen-card');
  const closeBtn = overlay.querySelector('.paper-gen-close');
  const cancelBtn = overlay.querySelector('.paper-gen-cancel');
  const startBtn = overlay.querySelector('.paper-gen-start');
  const startText = overlay.querySelector('.paper-gen-start-text');
  const statusEl = overlay.querySelector('#pr-status');

  let selectedResearchType = RESEARCH_TYPES[0].id;
  let selectedJournalStyle = JOURNAL_STYLES[0].id;

  overlay.querySelectorAll('#pr-research-type .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#pr-research-type .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      selectedResearchType = chip.dataset.value;
    });
  });

  overlay.querySelectorAll('#pr-journal-style .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#pr-journal-style .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      selectedJournalStyle = chip.dataset.value;
    });
  });

  function close() {
    if (overlay.parentNode) overlay.remove();
    if (onCancel) onCancel();
  }

  closeBtn.addEventListener('click', close);
  cancelBtn.addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  startBtn.addEventListener('click', async () => {
    const paperText = overlay.querySelector('#pr-paper').value.trim();
    if (paperText.length < 10) {
      const ta = overlay.querySelector('#pr-paper');
      ta.style.animation = 'shake 0.4s ease';
      setTimeout(() => { ta.style.animation = ''; }, 400);
      ta.focus();
      return;
    }

    const focus = overlay.querySelector('#pr-focus').value.trim();
    const sessionId = 'pr-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);

    startBtn.disabled = true;
    startText.textContent = '启动中...';
    statusEl.style.display = '';
    statusEl.className = 'paper-gen-status paper-gen-status-loading';
    statusEl.innerHTML = '<span class="paper-gen-spinner"></span>正在启动 7 Agent 审稿 Pipeline...';

    try {
      const res = await paperReviewApi.startReview({
        paper_text: paperText,
        research_type: selectedResearchType,
        journal_style: selectedJournalStyle,
        output_format: 'word',
        max_rounds: 5,
        session_id: sessionId,
        revision_focus: focus || null,
        pipeline_type: 'modification',
      });

      statusEl.className = 'paper-gen-status paper-gen-status-success';
      statusEl.innerHTML = iconCheck(16) + ' 审稿已启动！ID: ' + (res.review_id || '').slice(0, 12) + '...';

      startText.textContent = '已启动';
      setTimeout(() => {
        close();
        if (onStarted) onStarted(res);
      }, 1500);
    } catch (err) {
      statusEl.className = 'paper-gen-status paper-gen-status-error';
      statusEl.textContent = '启动失败: ' + (err.message || '未知错误');
      startBtn.disabled = false;
      startText.textContent = '重试';
    }
  });

  requestAnimationFrame(() => card.classList.add('topic-dialog-card-in'));
}
