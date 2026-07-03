import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { api, NetworkError } from '../services/api.js';
import { agentApi } from '../services/agentApi.js';
import { showToast } from '../components/ConfirmDialog.js';
import { iconArrowLeft, iconSend, iconCopy, iconCheck } from '../utils/icons.js';
import { checkWriting } from '../utils/writingChecker.js';

// 期刊样式映射
const JOURNAL_OPTIONS = [
  { id: 'gjxwj', label: '国际新闻界' },
  { id: 'xwycbyj', label: '新闻与传播研究' },
  { id: 'xwahz', label: '新闻爱好者' },
  { id: 'generic', label: '通用学术格式' },
];

const STORAGE_KEY = 'sm_writing_content';
const DEFAULT_CONTENT = `# 论文标题

在此撰写你的学术论文...

支持 Markdown 语法：
# 一级标题
## 二级标题
### 三级标题
**粗体** *斜体*
- 列表项
> 引用

## 参考文献
[1] 作者. 标题[J]. 期刊, 年份.
`;

export function WritingWorkspace() {
  const page = createElement('div', { className: 'page active page-writing-workspace' });

  // ========== HEADER ==========
  const header = createElement('div', { className: 'ws-header' });
  const headerLeft = createElement('div', { className: 'ws-header-left' });
  const backBtn = createElement('button', {
    className: 'btn btn-ghost btn-sm',
    'aria-label': '返回上一页',
  });
  backBtn.innerHTML = iconArrowLeft(16) + '<span>返回</span>';
  backBtn.addEventListener('click', () => {
    if (state.readiness) {
      navigateTo('readiness');
    } else if (state.discipline) {
      navigateTo(state.discipline);
    } else {
      navigateTo('homepage');
    }
  });
  headerLeft.appendChild(backBtn);
  const titleEl = createElement('h2', { className: 'ws-header-title' }, '写作工作台');
  headerLeft.appendChild(titleEl);
  header.appendChild(headerLeft);

  // 工具栏：编辑/预览切换 + 导出Word + 导出MD + 保存
  const toolbar = createElement('div', { className: 'ws-toolbar' });
  const modeGroup = createElement('div', { className: 'ws-mode-group', role: 'group', 'aria-label': '编辑/预览切换' });
  const editBtn = createElement('button', {
    className: 'btn btn-secondary btn-sm ws-mode-btn ws-mode-btn-active',
    'aria-label': '编辑模式',
  }, '编辑');
  const previewBtn = createElement('button', {
    className: 'btn btn-secondary btn-sm ws-mode-btn',
    'aria-label': '预览模式',
  }, '预览');
  modeGroup.appendChild(editBtn);
  modeGroup.appendChild(previewBtn);
  toolbar.appendChild(modeGroup);

  const actionsGroup = createElement('div', { className: 'ws-actions-group' });
  const exportWordBtn = createElement('button', {
    className: 'btn btn-secondary btn-sm',
    'aria-label': '导出 Word 文档',
  }, '导出 Word');
  exportWordBtn.addEventListener('click', () => exportWord());
  const exportMDBtn = createElement('button', {
    className: 'btn btn-secondary btn-sm',
    'aria-label': '导出 Markdown 文件',
  }, '导出 MD');
  exportMDBtn.addEventListener('click', () => exportMD());
  const saveBtn = createElement('button', {
    className: 'btn btn-primary btn-sm',
    'aria-label': '保存内容',
  }, '保存');
  saveBtn.addEventListener('click', () => saveContent());
  actionsGroup.appendChild(exportWordBtn);
  actionsGroup.appendChild(exportMDBtn);
  actionsGroup.appendChild(saveBtn);
  toolbar.appendChild(actionsGroup);
  header.appendChild(toolbar);
  page.appendChild(header);

  // ========== 主体：双栏布局 ==========
  const body = createElement('div', { className: 'ws-body' });

  // ---------- 左侧：编辑器 + 预览 ----------
  const leftPane = createElement('div', { className: 'ws-left-pane' });

  // 编辑器容器
  const editorWrap = createElement('div', { className: 'ws-editor-wrap' });
  const editor = createElement('textarea', {
    className: 'ws-editor',
    'aria-label': 'Markdown 编辑器',
    placeholder: '在此撰写你的学术论文...',
    spellcheck: 'false',
  });
  // 从 localStorage 恢复内容
  let savedContent = null;
  try { savedContent = localStorage.getItem(STORAGE_KEY); } catch {}
  editor.value = (savedContent && typeof savedContent === 'string' ? savedContent : DEFAULT_CONTENT);
  editor.addEventListener('input', () => {
    try { localStorage.setItem(STORAGE_KEY, editor.value); } catch {}
    scheduleLiveCheck();
  });
  editorWrap.appendChild(editor);
  leftPane.appendChild(editorWrap);

  // 预览容器（默认隐藏）
  const previewWrap = createElement('div', { className: 'ws-preview-wrap ws-preview-hidden' });
  const previewContent = createElement('div', { className: 'ws-preview-content', 'aria-live': 'polite' });
  previewWrap.appendChild(previewContent);
  leftPane.appendChild(previewWrap);

  page.appendChild(body);
  body.appendChild(leftPane);

  // ---------- 右侧：Agent对话 / 实时检测 ----------
  const rightPane = createElement('div', { className: 'ws-right-pane' });

  // 标签切换
  const tabsBar = createElement('div', { className: 'ws-tabs-bar', role: 'tablist' });
  const tabAgent = createElement('button', {
    className: 'ws-tab ws-tab-active',
    role: 'tab',
    'aria-selected': 'true',
    'aria-controls': 'ws-tab-panel-agent',
  }, 'Agent 对话');
  const tabCheck = createElement('button', {
    className: 'ws-tab',
    role: 'tab',
    'aria-selected': 'false',
    'aria-controls': 'ws-tab-panel-check',
  }, '实时检测');
  tabsBar.appendChild(tabAgent);
  tabsBar.appendChild(tabCheck);
  rightPane.appendChild(tabsBar);

  // Agent 对话面板
  const agentPanel = createElement('div', {
    className: 'ws-tab-panel ws-tab-panel-active',
    id: 'ws-tab-panel-agent',
    role: 'tabpanel',
  });

  // 欢迎气泡
  const agentMessages = createElement('div', { className: 'ws-chat-messages', 'aria-live': 'polite' });
  const welcomeBubble = createElement('div', { className: 'chat-bubble chat-bubble-ai' },
    '你好！在写作工作台中，你可以在左侧撰写论文，同时右侧与 Agent 对话寻求帮助。选中左侧文本后点击「引用」可将内容发送给 Agent 分析。',
  );
  agentMessages.appendChild(welcomeBubble);
  agentPanel.appendChild(agentMessages);

  // 输入区
  const agentInputArea = createElement('div', { className: 'ws-chat-input-area' });
  const quoteBtn = createElement('button', {
    className: 'btn btn-secondary btn-sm',
    'aria-label': '引用编辑器选中文本',
    title: '引用编辑器选中文本到对话输入框',
  }, '引用');
  quoteBtn.addEventListener('click', () => quoteSelection());
  const agentInput = createElement('textarea', {
    className: 'ws-chat-input',
    placeholder: '输入消息与 Agent 对话...',
    rows: '1',
    'aria-label': 'Agent 对话输入',
  });
  const agentSendBtn = createElement('button', {
    className: 'btn btn-primary btn-sm',
    'aria-label': '发送消息',
  }, '发送');
  agentInputArea.appendChild(quoteBtn);
  agentInputArea.appendChild(agentInput);
  agentInputArea.appendChild(agentSendBtn);
  agentPanel.appendChild(agentInputArea);

  rightPane.appendChild(agentPanel);

  // 实时检测面板
  const checkPanel = createElement('div', {
    className: 'ws-tab-panel',
    id: 'ws-tab-panel-check',
    role: 'tabpanel',
  });
  const checkHeader = createElement('div', { className: 'ws-check-header' },
    createElement('span', { className: 'ws-check-title' }, '实时写作检测'),
    createElement('button', {
      className: 'btn btn-secondary btn-sm ws-check-refresh',
      'aria-label': '重新检测',
    }, '重新检测'),
  );
  checkPanel.appendChild(checkHeader);
  const checkRefreshBtn = checkHeader.querySelector('.ws-check-refresh');
  checkRefreshBtn.addEventListener('click', () => runLiveCheck(true));

  const checkSummary = createElement('div', { className: 'ws-check-summary' });
  checkPanel.appendChild(checkSummary);

  const checkDetails = createElement('div', { className: 'ws-check-details' });
  checkPanel.appendChild(checkDetails);

  rightPane.appendChild(checkPanel);
  body.appendChild(rightPane);

  // ========== 状态变量 ==========
  let currentMode = 'edit'; // edit / preview
  let liveCheckTimer = null;
  const sessionId = crypto.randomUUID();

  // ========== 模式切换 ==========
  function switchMode(mode) {
    if (mode === currentMode) return;
    currentMode = mode;
    if (mode === 'edit') {
      editBtn.classList.add('ws-mode-btn-active');
      previewBtn.classList.remove('ws-mode-btn-active');
      editorWrap.classList.remove('ws-editor-hidden');
      previewWrap.classList.add('ws-preview-hidden');
      editor.focus();
    } else {
      editBtn.classList.remove('ws-mode-btn-active');
      previewBtn.classList.add('ws-mode-btn-active');
      editorWrap.classList.add('ws-editor-hidden');
      previewWrap.classList.remove('ws-preview-hidden');
      renderPreview();
    }
  }
  editBtn.addEventListener('click', () => switchMode('edit'));
  previewBtn.addEventListener('click', () => switchMode('preview'));

  function renderPreview() {
    const md = editor.value || '';
    try {
      // 动态导入 marked（已通过 npm 安装）
      import('marked').then(async markedMod => {
        const marked = markedMod.marked || markedMod.default;
        const html = marked.parse(md, { breaks: true, gfm: true });
        // P0-T8 XSS 修复：优先使用 DOMPurify 清洗，未安装时降级到简易清洗
        try {
          const purifyMod = await import('dompurify');
          const DOMPurify = purifyMod.default || purifyMod;
          previewContent.innerHTML = DOMPurify.sanitize(html);
        } catch (e) {
          // 降级：移除 script 标签与 on* 事件属性
          const sanitized = html
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
            .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
            .replace(/\son\w+\s*=\s*[^\s>]+/gi, '');
          previewContent.innerHTML = sanitized;
        }
      }).catch(() => {
        // 降级：简单转义 + 换行
        const div = document.createElement('div');
        div.textContent = md;
        previewContent.innerHTML = '<pre style="white-space:pre-wrap;">' + div.innerHTML + '</pre>';
      });
    } catch (e) {
      const div = document.createElement('div');
      div.textContent = md;
      previewContent.innerHTML = '<pre style="white-space:pre-wrap;">' + div.innerHTML + '</pre>';
    }
  }

  // ========== 导出 MD ==========
  function exportMD() {
    const content = editor.value || '';
    if (!content.trim()) {
      showToast('内容为空，无法导出', 'warning');
      return;
    }
    try {
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'scholarmind-paper.md';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('Markdown 文件已导出', 'success');
    } catch (e) {
      showToast('导出失败：' + (e.message || e), 'error');
    }
  }

  // ========== 导出 Word ==========
  function exportWord() {
    const content = editor.value || '';
    if (!content.trim()) {
      showToast('内容为空，无法导出', 'warning');
      return;
    }
    showJournalDialog((journalStyle, meta) => {
      doExportWord(content, journalStyle, meta);
    });
  }

  function showJournalDialog(onConfirm) {
    const overlay = createElement('div', { className: 'confirm-overlay' });
    const dialog = createElement('div', { className: 'confirm-dialog ws-journal-dialog' });
    const titleEl = createElement('div', { className: 'confirm-dialog-title' }, '选择期刊格式');
    dialog.appendChild(titleEl);
    const msgEl = createElement('div', { className: 'confirm-dialog-message' }, '请选择导出 Word 文档所使用的期刊格式：');
    dialog.appendChild(msgEl);

    // 期刊选择
    const journalList = createElement('div', { className: 'ws-journal-list' });
    let selectedJournal = 'generic';
    JOURNAL_OPTIONS.forEach((opt, idx) => {
      const item = createElement('label', {
        className: 'ws-journal-option' + (idx === JOURNAL_OPTIONS.length - 1 ? ' ws-journal-option-selected' : ''),
      });
      const radio = createElement('input', { type: 'radio', name: 'ws-journal', value: opt.id });
      if (idx === JOURNAL_OPTIONS.length - 1) radio.checked = true;
      radio.addEventListener('change', () => {
        selectedJournal = opt.id;
        journalList.querySelectorAll('.ws-journal-option').forEach(el => el.classList.remove('ws-journal-option-selected'));
        item.classList.add('ws-journal-option-selected');
      });
      item.appendChild(radio);
      item.appendChild(createElement('span', {}, opt.label));
      journalList.appendChild(item);
    });
    dialog.appendChild(journalList);

    // 标题输入
    const titleLabel = createElement('label', { className: 'ws-field-label' }, '论文标题（可选）');
    const titleInput = createElement('input', {
      type: 'text',
      className: 'input-base ws-field-input',
      placeholder: '请输入论文标题',
    });
    titleLabel.appendChild(titleInput);
    dialog.appendChild(titleLabel);

    // 作者输入
    const authorLabel = createElement('label', { className: 'ws-field-label' }, '作者（可选）');
    const authorInput = createElement('input', {
      type: 'text',
      className: 'input-base ws-field-input',
      placeholder: '请输入作者姓名',
    });
    authorLabel.appendChild(authorInput);
    dialog.appendChild(authorLabel);

    // 操作按钮
    const actions = createElement('div', { className: 'confirm-dialog-actions' });
    const cancelBtn = createElement('button', { className: 'btn btn-outline' }, '取消');
    const confirmBtn = createElement('button', { className: 'btn btn-primary' }, '导出 Word');
    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    dialog.appendChild(actions);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    confirmBtn.focus();

    function close() {
      overlay.style.animation = 'fadeIn 0.15s ease reverse';
      setTimeout(() => overlay.remove(), 150);
    }
    cancelBtn.addEventListener('click', close);
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', function escHandler(e) {
      if (e.key === 'Escape') {
        document.removeEventListener('keydown', escHandler);
        close();
      }
    });
    confirmBtn.addEventListener('click', () => {
      const meta = {
        title: titleInput.value.trim() || null,
        author: authorInput.value.trim() || null,
      };
      close();
      onConfirm(selectedJournal, meta);
    });
  }

  async function doExportWord(content, journalStyle, meta) {
    const origText = exportWordBtn.textContent;
    exportWordBtn.disabled = true;
    exportWordBtn.innerHTML = '<span class="btn-spinner"></span> 生成中...';
    try {
      const baseUrl = state.settings?.apiBase || '';
      const res = await fetch(`${baseUrl}/api/v1/export/docx`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          journal_style: journalStyle,
          title: meta.title,
          author: meta.author,
        }),
      });
      if (!res.ok) {
        let errData = null;
        try { errData = await res.json(); } catch {}
        throw new Error(errData?.detail || errData?.error?.message || `导出失败 (${res.status})`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'scholarmind-paper.docx';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('Word 文档已导出', 'success');
    } catch (e) {
      if (e instanceof TypeError) {
        showToast('后端服务未启动，请先启动后端', 'error');
      } else {
        showToast('导出失败：' + (e.message || e), 'error');
      }
    } finally {
      exportWordBtn.disabled = false;
      exportWordBtn.textContent = origText;
    }
  }

  // ========== 保存 ==========
  function saveContent() {
    try {
      localStorage.setItem(STORAGE_KEY, editor.value);
      showToast('写作内容已保存', 'success');
    } catch (e) {
      showToast('保存失败：' + (e.message || e), 'error');
    }
  }

  // ========== Agent 对话 ==========
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function formatTime() {
    const d = new Date();
    return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
  }

  function addAgentMessage(role, content) {
    const bubble = createElement('div', {
      className: 'chat-bubble ' + (role === 'user' ? 'chat-bubble-user' : 'chat-bubble-ai'),
    });
    bubble.innerHTML = escapeHtml(content);
    if (role === 'assistant') {
      const actions = createElement('div', { className: 'chat-bubble-actions' });
      const copyBtn = createElement('button', { className: 'chat-action-btn', 'aria-label': '复制消息' });
      copyBtn.innerHTML = iconCopy(14) + '<span>复制</span>';
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(content).then(() => {
          copyBtn.innerHTML = iconCheck(14) + '<span>已复制</span>';
          setTimeout(() => { copyBtn.innerHTML = iconCopy(14) + '<span>复制</span>'; }, 2000);
        });
      });
      actions.appendChild(copyBtn);
      bubble.appendChild(actions);
      const time = createElement('div', { className: 'chat-bubble-time' }, formatTime());
      bubble.appendChild(time);
    }
    agentMessages.appendChild(bubble);
    agentMessages.scrollTop = agentMessages.scrollHeight;
  }

  function addAgentError(content) {
    const err = createElement('div', { className: 'chat-bubble chat-bubble-ai chat-bubble-error' });
    err.innerHTML = escapeHtml(content);
    agentMessages.appendChild(err);
    agentMessages.scrollTop = agentMessages.scrollHeight;
  }

  function quoteSelection() {
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    if (start === end) {
      showToast('请先在编辑器中选中文本', 'info');
      return;
    }
    const selected = editor.value.substring(start, end);
    const quoted = '> ' + selected.split('\n').join('\n> ');
    agentInput.value = (agentInput.value ? agentInput.value + '\n\n' : '') + quoted;
    agentInput.focus();
    autoResizeAgentInput();
    showToast('已引用选中文本到对话输入框', 'success');
  }

  function autoResizeAgentInput() {
    agentInput.style.height = 'auto';
    agentInput.style.height = Math.min(agentInput.scrollHeight, 120) + 'px';
  }
  agentInput.addEventListener('input', autoResizeAgentInput);

  async function sendToAgent() {
    const text = agentInput.value.trim();
    if (!text) {
      agentInput.style.animation = 'shake 0.4s ease';
      setTimeout(() => { agentInput.style.animation = ''; }, 400);
      return;
    }
    agentInput.value = '';
    agentInput.style.height = 'auto';
    agentInput.disabled = true;
    agentSendBtn.disabled = true;
    agentSendBtn.textContent = '...';

    addAgentMessage('user', text);

    // typing indicator
    const typingEl = createElement('div', { className: 'typing-indicator accent-amber' },
      createElement('div', { className: 'typing-dot' }),
      createElement('div', { className: 'typing-dot' }),
      createElement('div', { className: 'typing-dot' }),
      createElement('span', { className: 'typing-text' }, '思考中...'),
    );
    agentMessages.appendChild(typingEl);
    agentMessages.scrollTop = agentMessages.scrollHeight;

    try {
      const res = await agentApi.chat({
        agent_id: 'researcher',
        session_id: sessionId,
        message: text,
      });
      if (typingEl && typingEl.parentNode) typingEl.remove();
      const reply = res.reply || res.message || '（无回复）';
      addAgentMessage('assistant', reply);
    } catch (e) {
      if (typingEl && typingEl.parentNode) typingEl.remove();
      let errMsg = '';
      if (e instanceof NetworkError) {
        errMsg = '后端服务未启动，请检查后端是否运行';
      } else {
        errMsg = e.message || '请求失败，请检查后端是否启动';
      }
      addAgentError(errMsg);
    } finally {
      agentSendBtn.disabled = false;
      agentInput.disabled = false;
      agentSendBtn.textContent = '发送';
      agentInput.focus();
    }
  }

  agentSendBtn.addEventListener('click', sendToAgent);
  agentInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendToAgent();
    }
  });

  // ========== 标签切换 ==========
  function switchTab(tab) {
    if (tab === 'agent') {
      tabAgent.classList.add('ws-tab-active');
      tabAgent.setAttribute('aria-selected', 'true');
      tabCheck.classList.remove('ws-tab-active');
      tabCheck.setAttribute('aria-selected', 'false');
      agentPanel.classList.add('ws-tab-panel-active');
      checkPanel.classList.remove('ws-tab-panel-active');
    } else {
      tabCheck.classList.add('ws-tab-active');
      tabCheck.setAttribute('aria-selected', 'true');
      tabAgent.classList.remove('ws-tab-active');
      tabAgent.setAttribute('aria-selected', 'false');
      checkPanel.classList.add('ws-tab-panel-active');
      agentPanel.classList.remove('ws-tab-panel-active');
      runLiveCheck();
    }
  }
  tabAgent.addEventListener('click', () => switchTab('agent'));
  tabCheck.addEventListener('click', () => switchTab('check'));

  // ========== 实时检测 ==========
  function scheduleLiveCheck() {
    if (!checkPanel.classList.contains('ws-tab-panel-active')) return;
    if (liveCheckTimer) clearTimeout(liveCheckTimer);
    liveCheckTimer = setTimeout(() => runLiveCheck(), 600);
  }

  function runLiveCheck(force = false) {
    if (!force && !checkPanel.classList.contains('ws-tab-panel-active')) return;
    const content = editor.value || '';
    const result = checkWriting(content);
    renderCheckResult(result);
  }

  function renderCheckResult(result) {
    // 清空并重新渲染概要与详情
    renderSummary();
    renderDetails();

    function renderSummary() {
      checkSummary.innerHTML = '';
      const wc = result.wordCount || {};
      const st = result.structure || {};
      const gm = result.grammar || {};
      const ac = result.academic || {};
      const issueCount = (gm.issues?.length || 0) + (ac.issues?.length || 0) + (result.suggestions?.length || 0);

      const stats = [
        { label: '总字数', value: wc.total || 0, color: 'var(--accent-amber)' },
        { label: '中文字', value: wc.chinese || 0, color: 'var(--accent-blue)' },
        { label: '英文词', value: wc.english || 0, color: 'var(--accent-teal)' },
        { label: '段落数', value: wc.paragraphs || 0, color: 'var(--accent-purple)' },
        { label: '标题数', value: st.headings?.length || 0, color: 'var(--accent-green)' },
        { label: '问题数', value: issueCount, color: issueCount > 0 ? 'var(--accent-red)' : 'var(--accent-green)' },
      ];
      stats.forEach(s => {
        const card = createElement('div', { className: 'ws-stat-card' },
          createElement('div', { className: 'ws-stat-value', style: 'color:' + s.color + ';' }, String(s.value)),
          createElement('div', { className: 'ws-stat-label' }, s.label),
        );
        checkSummary.appendChild(card);
      });
    }

    function renderDetails() {
      checkDetails.innerHTML = '';
      const sections = [];

      // 结构分析
      const st = result.structure || {};
      if (st.headings && st.headings.length > 0) {
        const items = st.headings.map(h => `· [H${h.level}] ${h.text}`).join('\n');
        sections.push({
          title: '文档结构',
          status: 'ok',
          content: items,
        });
      } else {
        sections.push({
          title: '文档结构',
          status: 'warn',
          content: '未检测到 Markdown 标题，建议使用 # 添加层级结构',
        });
      }

      // 语法检查
      const gm = result.grammar || {};
      if (gm.issues && gm.issues.length > 0) {
        sections.push({
          title: '语法/格式',
          status: 'warn',
          content: gm.issues.map(i => `· ${i.message}${i.position ? ` (位置 ${i.position})` : ''}`).join('\n'),
        });
      } else {
        sections.push({
          title: '语法/格式',
          status: 'ok',
          content: '未发现明显语法/格式问题',
        });
      }

      // 学术规范
      const ac = result.academic || {};
      if (ac.issues && ac.issues.length > 0) {
        sections.push({
          title: '学术规范',
          status: 'warn',
          content: ac.issues.map(i => `· ${i}`).join('\n'),
        });
      } else if (ac.citations && ac.citations.length > 0) {
        sections.push({
          title: '学术规范',
          status: 'ok',
          content: `检测到 ${ac.citations.length} 处引用，参考文献部分${ac.hasReferences ? '已' : '未'}包含`,
        });
      } else {
        sections.push({
          title: '学术规范',
          status: 'warn',
          content: '未检测到引用，学术论文应包含充分的文献引用',
        });
      }

      // 写作建议
      const sug = result.suggestions || [];
      if (sug.length > 0) {
        sections.push({
          title: '写作建议',
          status: 'info',
          content: sug.map(s => `· ${s}`).join('\n'),
        });
      }

      sections.forEach(sec => {
        const sectionEl = createElement('div', { className: 'ws-check-section' });
        const headerEl = createElement('div', { className: 'ws-check-section-header' });
        const statusClass = sec.status === 'ok' ? 'ws-status-ok' : sec.status === 'warn' ? 'ws-status-warn' : 'ws-status-info';
        const statusIcon = sec.status === 'ok' ? '✓' : sec.status === 'warn' ? '!' : 'i';
        headerEl.innerHTML = `<span class="ws-status-badge ${statusClass}">${statusIcon}</span><span class="ws-check-section-title">${sec.title}</span>`;
        sectionEl.appendChild(headerEl);
        const bodyEl = createElement('pre', { className: 'ws-check-section-body' }, sec.content);
        sectionEl.appendChild(bodyEl);
        checkDetails.appendChild(sectionEl);
      });
    }
  }

  // 初始化：执行一次检测
  setTimeout(() => runLiveCheck(true), 50);

  return page;
}
