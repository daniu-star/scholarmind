import { paperPipelineApi, paperReviewApi } from '../services/paperPipelineApi.js';
import { api } from '../services/api.js';
import { state } from '../app/store.js';
import {
  iconClose, iconSparkles, iconCheck, iconDoc, iconUpload,
  iconClipboardCheck,
} from '../utils/icons.js';

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

const ALLOWED_EXTENSIONS = ['.docx', '.pdf', '.md', '.txt'];
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB

/**
 * 论文工作台弹窗
 * 两个标签页：「上传审稿」支持拖拽上传附件 + 调用审稿 Pipeline
 *            「一键生成」从研究主题启动 13 Agent 生成 Pipeline
 */
export function showPaperWorkbenchDialog({ onStarted, onCancel } = {}) {
  const existing = document.getElementById('paperWorkbenchDialog');
  if (existing) existing.remove();

  let uploadedFile = null;
  let uploadedText = '';

  const overlay = document.createElement('div');
  overlay.id = 'paperWorkbenchDialog';
  overlay.className = 'topic-dialog-overlay';
  overlay.innerHTML =
    '<div class="topic-dialog-card paper-wb-card">' +
      '<div class="topic-dialog-decoration"></div>' +
      '<div class="topic-dialog-header">' +
        '<div class="topic-dialog-icon-wrap"><span class="topic-dialog-icon-emoji">' + iconSparkles(20) + '</span></div>' +
        '<h3 class="topic-dialog-title">论文工作台</h3>' +
        '<button class="paper-gen-close" aria-label="关闭">' + iconClose(18) + '</button>' +
      '</div>' +
      '<p class="topic-dialog-desc">上传论文附件进行审稿优化，或输入研究主题一键生成论文</p>' +

      // ===== 标签页切换 =====
      '<div class="paper-wb-tabs">' +
        '<button class="paper-wb-tab paper-wb-tab-active" data-tab="review">' +
          iconClipboardCheck(16) + ' <span>上传审稿</span>' +
        '</button>' +
        '<button class="paper-wb-tab" data-tab="generate">' +
          iconSparkles(16) + ' <span>一键生成</span>' +
        '</button>' +
      '</div>' +

      // ===== 审稿标签页 =====
      '<div class="paper-wb-panel" id="wb-panel-review">' +
        // 文件上传区
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">上传论文 <span class="paper-gen-required">*</span></label>' +
          '<div class="paper-wb-upload" id="wb-upload-zone">' +
            '<div class="paper-wb-upload-icon">' + iconUpload(28) + '</div>' +
            '<div class="paper-wb-upload-text">拖拽文件到此处，或点击上传</div>' +
            '<div class="paper-wb-upload-hint">支持 .docx / .pdf / .md / .txt，最大 20MB</div>' +
            '<input type="file" id="wb-file-input" accept=".docx,.pdf,.md,.txt" style="display:none;">' +
          '</div>' +
          '<div class="paper-wb-file-info" id="wb-file-info" style="display:none;"></div>' +
        '</div>' +
        // 或粘贴论文全文
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">或直接粘贴论文全文' +
            ' <span class="paper-gen-required">*</span>' +
            '<span class="paper-wb-char-count" id="wb-char-count">0 字</span>' +
          '</label>' +
          '<textarea class="paper-gen-textarea paper-gen-textarea-large" rows="8" ' +
            'placeholder="粘贴论文全文（至少 10 个字符），支持 Markdown 格式" ' +
            'id="wb-paper-text"></textarea>' +
        '</div>' +
        '<div class="paper-gen-row">' +
          '<div class="paper-gen-field paper-gen-field-half">' +
            '<label class="paper-gen-label">研究类型</label>' +
            '<div class="paper-gen-chips" id="wb-review-research-type">' +
              RESEARCH_TYPES.map((t, i) =>
                '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + t.id + '">' + t.name + '</button>'
              ).join('') +
            '</div>' +
          '</div>' +
          '<div class="paper-gen-field paper-gen-field-half">' +
            '<label class="paper-gen-label">期刊格式</label>' +
            '<div class="paper-gen-chips" id="wb-review-journal-style">' +
              JOURNAL_STYLES.map((j, i) =>
                '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + j.id + '">' + j.name + '</button>'
              ).join('') +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="paper-gen-field">' +
          '<label class="paper-gen-label">修改重点（可选）</label>' +
          '<input type="text" class="paper-gen-input" id="wb-review-focus" placeholder="例如：加强理论对话、优化方法论">' +
        '</div>' +
        '<div class="paper-gen-actions">' +
          '<button class="btn btn-ghost paper-gen-cancel">取消</button>' +
          '<button class="btn btn-primary paper-gen-start" id="wb-review-start">' +
            '<span class="paper-gen-start-text">启动审稿 Pipeline</span>' +
          '</button>' +
        '</div>' +
        '<div class="paper-gen-status" id="wb-review-status" style="display:none;"></div>' +
      '</div>' +

      // ===== 生成标签页 =====
      '<div class="paper-wb-panel paper-wb-panel-hidden" id="wb-panel-generate">' +
        '<div class="paper-gen-form">' +
          '<div class="paper-gen-field">' +
            '<label class="paper-gen-label">研究主题 <span class="paper-gen-required">*</span></label>' +
            '<textarea class="paper-gen-textarea" rows="3" ' +
              'placeholder="例如：算法推荐对信息茧房的影响机制研究" ' +
              'id="wb-gen-topic"></textarea>' +
          '</div>' +
          '<div class="paper-gen-row">' +
            '<div class="paper-gen-field paper-gen-field-half">' +
              '<label class="paper-gen-label">研究类型</label>' +
              '<div class="paper-gen-chips" id="wb-gen-research-type">' +
                RESEARCH_TYPES.map((t, i) =>
                  '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + t.id + '">' + t.name + '</button>'
                ).join('') +
              '</div>' +
            '</div>' +
            '<div class="paper-gen-field paper-gen-field-half">' +
              '<label class="paper-gen-label">期刊格式</label>' +
              '<div class="paper-gen-chips" id="wb-gen-journal-style">' +
                JOURNAL_STYLES.map((j, i) =>
                  '<button class="paper-gen-chip' + (i === 0 ? ' selected' : '') + '" data-value="' + j.id + '">' + j.name + '</button>'
                ).join('') +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="paper-gen-row">' +
            '<div class="paper-gen-field paper-gen-field-half">' +
              '<label class="paper-gen-label">字数目标</label>' +
              '<input type="number" class="paper-gen-input" id="wb-gen-words" value="15000" min="3000" max="50000" step="500">' +
            '</div>' +
            '<div class="paper-gen-field paper-gen-field-half">' +
              '<label class="paper-gen-label">最大轮次</label>' +
              '<input type="number" class="paper-gen-input" id="wb-gen-rounds" value="5" min="1" max="10">' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="paper-gen-actions">' +
          '<button class="btn btn-ghost paper-gen-cancel">取消</button>' +
          '<button class="btn btn-primary paper-gen-start" id="wb-gen-start">' +
            '<span class="paper-gen-start-text">启动生成 Pipeline</span>' +
          '</button>' +
        '</div>' +
        '<div class="paper-gen-status" id="wb-gen-status" style="display:none;"></div>' +
      '</div>' +
    '</div>';

  document.body.appendChild(overlay);
  setTimeout(() => {
    overlay.querySelector('.topic-dialog-card').classList.add('topic-dialog-card-in');
  }, 10);

  // ========== DOM 引用 ==========
  const card = overlay.querySelector('.paper-wb-card');
  const closeBtn = overlay.querySelector('.paper-gen-close');
  const cancelBtns = overlay.querySelectorAll('.paper-gen-cancel');

  // 标签页
  const tabReview = overlay.querySelector('[data-tab="review"]');
  const tabGenerate = overlay.querySelector('[data-tab="generate"]');
  const panelReview = overlay.querySelector('#wb-panel-review');
  const panelGenerate = overlay.querySelector('#wb-panel-generate');

  // 审稿Tab - 元素
  const uploadZone = overlay.querySelector('#wb-upload-zone');
  const fileInput = overlay.querySelector('#wb-file-input');
  const fileInfo = overlay.querySelector('#wb-file-info');
  const paperText = overlay.querySelector('#wb-paper-text');
  const charCount = overlay.querySelector('#wb-char-count');
  const reviewStartBtn = overlay.querySelector('#wb-review-start');
  const reviewStartText = reviewStartBtn.querySelector('.paper-gen-start-text');
  const reviewStatus = overlay.querySelector('#wb-review-status');
  const reviewFocus = overlay.querySelector('#wb-review-focus');

  // 生成Tab - 元素
  const genTopic = overlay.querySelector('#wb-gen-topic');
  const genWords = overlay.querySelector('#wb-gen-words');
  const genRounds = overlay.querySelector('#wb-gen-rounds');
  const genStartBtn = overlay.querySelector('#wb-gen-start');
  const genStartText = genStartBtn.querySelector('.paper-gen-start-text');
  const genStatus = overlay.querySelector('#wb-gen-status');

  // 选中值
  let reviewResearchType = RESEARCH_TYPES[0].id;
  let reviewJournalStyle = JOURNAL_STYLES[0].id;
  let genResearchType = RESEARCH_TYPES[0].id;
  let genJournalStyle = JOURNAL_STYLES[0].id;

  // ========== 标签页切换 ==========
  function switchTab(tab) {
    if (tab === 'review') {
      tabReview.classList.add('paper-wb-tab-active');
      tabGenerate.classList.remove('paper-wb-tab-active');
      panelReview.classList.remove('paper-wb-panel-hidden');
      panelGenerate.classList.add('paper-wb-panel-hidden');
    } else {
      tabGenerate.classList.add('paper-wb-tab-active');
      tabReview.classList.remove('paper-wb-tab-active');
      panelGenerate.classList.remove('paper-wb-panel-hidden');
      panelReview.classList.add('paper-wb-panel-hidden');
    }
  }
  tabReview.addEventListener('click', () => switchTab('review'));
  tabGenerate.addEventListener('click', () => switchTab('generate'));

  // ========== Chip 选择（审稿Tab） ==========
  overlay.querySelectorAll('#wb-review-research-type .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#wb-review-research-type .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      reviewResearchType = chip.dataset.value;
    });
  });
  overlay.querySelectorAll('#wb-review-journal-style .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#wb-review-journal-style .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      reviewJournalStyle = chip.dataset.value;
    });
  });

  // ========== Chip 选择（生成Tab） ==========
  overlay.querySelectorAll('#wb-gen-research-type .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#wb-gen-research-type .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      genResearchType = chip.dataset.value;
    });
  });
  overlay.querySelectorAll('#wb-gen-journal-style .paper-gen-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      overlay.querySelectorAll('#wb-gen-journal-style .paper-gen-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      genJournalStyle = chip.dataset.value;
    });
  });

  // ========== 文件上传 ==========
  function updateFileDisplay(name, size) {
    const sizeStr = size < 1024 * 1024
      ? (size / 1024).toFixed(1) + ' KB'
      : (size / (1024 * 1024)).toFixed(2) + ' MB';
    fileInfo.style.display = '';
    fileInfo.innerHTML =
      '<div class="paper-wb-file-item">' +
        iconDoc(18) + ' ' +
        '<span class="paper-wb-file-name">' + escapeHtml(name) + '</span>' +
        '<span class="paper-wb-file-size">' + sizeStr + '</span>' +
        '<button class="paper-wb-file-remove" title="移除文件">&times;</button>' +
      '</div>';
    fileInfo.querySelector('.paper-wb-file-remove').addEventListener('click', () => {
      uploadedFile = null;
      uploadedText = '';
      fileInput.value = '';
      fileInfo.style.display = 'none';
      paperText.placeholder = '粘贴论文全文（至少 10 个字符），支持 Markdown 格式';
    });
    uploadZone.classList.add('paper-wb-upload-has-file');
  }

  function processUploadedFile(file) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      showUploadError('不支持的文件格式，请上传 .docx / .pdf / .md / .txt 文件');
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      showUploadError('文件过大，最大支持 20MB');
      return;
    }
    uploadedFile = file;
    updateFileDisplay(file.name, file.size);

    // 对于 .txt 和 .md，直接读取文本内容
    if (ext === '.txt' || ext === '.md') {
      const reader = new FileReader();
      reader.onload = () => {
        uploadedText = reader.result;
        paperText.value = uploadedText;
        updateCharCount();
      };
      reader.onerror = () => {
        showUploadError('文件读取失败，请重试');
      };
      reader.readAsText(file, 'UTF-8');
    } else {
      // 对于 .docx 和 .pdf，标记为二进制文件供后端处理
      paperText.placeholder = '已选择文件：' + file.name + '（二进制格式将通过后端解析）';
      uploadedText = '';
    }
  }

  function showUploadError(msg) {
    fileInfo.style.display = '';
    fileInfo.innerHTML =
      '<div class="paper-wb-file-item paper-wb-file-error">' + msg + '</div>';
    setTimeout(() => {
      if (fileInfo.querySelector('.paper-wb-file-error')) {
        fileInfo.style.display = 'none';
      }
    }, 3000);
  }

  // 点击上传
  uploadZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files.length > 0) {
      processUploadedFile(fileInput.files[0]);
    }
  });

  // 拖拽上传
  uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    uploadZone.classList.add('paper-wb-upload-dragover');
  });
  uploadZone.addEventListener('dragleave', (e) => {
    e.preventDefault();
    e.stopPropagation();
    uploadZone.classList.remove('paper-wb-upload-dragover');
  });
  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    uploadZone.classList.remove('paper-wb-upload-dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processUploadedFile(e.dataTransfer.files[0]);
    }
  });

  // 粘贴区事件：粘贴文件
  paperText.addEventListener('paste', (e) => {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (const item of items) {
      if (item.kind === 'file') {
        e.preventDefault();
        processUploadedFile(item.getAsFile());
        return;
      }
    }
  });

  // 字数统计
  function updateCharCount() {
    const len = paperText.value.length;
    charCount.textContent = len + ' 字';
    charCount.className = 'paper-wb-char-count' + (len < 10 && len > 0 ? ' paper-wb-char-count-warn' : '');
  }
  paperText.addEventListener('input', updateCharCount);

  // ========== 关闭 ==========
  function close() {
    if (overlay.parentNode) overlay.remove();
    if (onCancel) onCancel();
  }
  closeBtn.addEventListener('click', close);
  cancelBtns.forEach(b => b.addEventListener('click', close));
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  document.addEventListener('keydown', function escHandler(e) {
    if (e.key === 'Escape') { document.removeEventListener('keydown', escHandler); close(); }
  });

  // ========== 审稿启动 ==========
  reviewStartBtn.addEventListener('click', async () => {
    let text = paperText.value.trim();

    // 检查是否有内容
    if (!text && !uploadedFile) {
      shakeElement(paperText);
      return;
    }

    // 如果没有粘贴内容但有上传文件，尝试用文件名标记
    if (!text && uploadedFile) {
      text = '[附件: ' + uploadedFile.name + ']';
    }

    if (text.length < 10 && !uploadedFile) {
      shakeElement(paperText);
      return;
    }

    const focus = reviewFocus.value.trim();
    const sessionId = 'wb-review-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);

    reviewStartBtn.disabled = true;
    reviewStartText.textContent = '启动中...';
    reviewStatus.style.display = '';
    reviewStatus.className = 'paper-gen-status paper-gen-status-loading';
    reviewStatus.innerHTML = '<span class="paper-gen-spinner"></span>正在启动 7 Agent 审稿 Pipeline...';

    try {
      // 构建请求体
      const payload = {
        paper_text: text,
        research_type: reviewResearchType,
        journal_style: reviewJournalStyle,
        output_format: 'word',
        max_rounds: 5,
        session_id: sessionId,
        revision_focus: focus || null,
        pipeline_type: 'modification',
      };

      // 如果有上传的二进制文件，使用 FormData
      let res;
      if (uploadedFile && (uploadedFile.name.endsWith('.docx') || uploadedFile.name.endsWith('.pdf'))) {
        const formData = new FormData();
        formData.append('file', uploadedFile);
        Object.entries(payload).forEach(([k, v]) => {
          if (v !== null && v !== undefined) formData.append(k, String(v));
        });
        res = await api.upload('/api/v1/paper-review/start', formData);
      } else {
        res = await paperReviewApi.startReview(payload);
      }

      reviewStatus.className = 'paper-gen-status paper-gen-status-success';
      reviewStatus.innerHTML = iconCheck(16) + ' 审稿已启动！ID: ' + (res.review_id || '').slice(0, 12) + '...';

      reviewStartText.textContent = '已启动';
      setTimeout(() => {
        close();
        if (onStarted) onStarted(res);
      }, 1500);
    } catch (err) {
      reviewStatus.className = 'paper-gen-status paper-gen-status-error';
      reviewStatus.textContent = '启动失败: ' + (err.message || '未知错误，请检查后端是否启动');
      reviewStartBtn.disabled = false;
      reviewStartText.textContent = '重试';
    }
  });

  // ========== 生成启动 ==========
  genStartBtn.addEventListener('click', async () => {
    const topic = genTopic.value.trim();
    if (!topic) {
      shakeElement(genTopic);
      return;
    }

    const words = parseInt(genWords.value, 10) || 15000;
    const rounds = parseInt(genRounds.value, 10) || 5;
    const sessionId = 'wb-gen-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);

    genStartBtn.disabled = true;
    genStartText.textContent = '启动中...';
    genStatus.style.display = '';
    genStatus.className = 'paper-gen-status paper-gen-status-loading';
    genStatus.innerHTML = '<span class="paper-gen-spinner"></span>正在启动 13 Agent Pipeline...';

    try {
      const discipline = state.discipline || 'communication';
      const res = await paperPipelineApi.startPipeline({
        session_id: sessionId,
        agent_id: 'architect',
        guidance_data: {
          topic: topic,
          user_target_words: words,
        },
        discipline: discipline,
        research_type: genResearchType,
        journal_style: genJournalStyle,
        max_rounds: rounds,
        pass_threshold: 90,
      });

      genStatus.className = 'paper-gen-status paper-gen-status-success';
      genStatus.innerHTML = iconCheck(16) + ' Pipeline 已启动！ID: ' + (res.pipeline_id || '').slice(0, 12) + '...';

      genStartText.textContent = '已启动';
      setTimeout(() => {
        close();
        if (onStarted) onStarted(res);
      }, 1500);
    } catch (err) {
      genStatus.className = 'paper-gen-status paper-gen-status-error';
      genStatus.textContent = '启动失败: ' + (err.message || '未知错误，请检查后端是否启动');
      genStartBtn.disabled = false;
      genStartText.textContent = '重试';
    }
  });
}

// ========== 辅助函数 ==========
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function shakeElement(el) {
  el.style.animation = 'shake 0.4s ease';
  setTimeout(() => { el.style.animation = ''; }, 400);
  el.focus();
}
