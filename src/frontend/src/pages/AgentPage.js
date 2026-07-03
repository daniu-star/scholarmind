import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { agentApi } from '../services/agentApi.js';
import { NetworkError } from '../services/api.js';
import { AGENT_META } from '../utils/constants.js';
import { showToast } from '../components/ConfirmDialog.js';
import {
  renderIcon, iconSend, iconCopy, iconCheck, iconArrowLeft, iconLibrary,
  iconEdit, iconLightbulb, iconUpload, iconClock, iconBookOpen, iconChat, iconHome, iconDownload,
} from '../utils/icons.js';

const agentMeta = AGENT_META;

/**
 * 显示精美议题填空弹窗（居中遮罩 + 学科标签 + 竖向选项卡 + 热门建议 chip + 自由输入）
 * @param {object} opts - {title, desc, disciplineLabel, placeholder, suggestions[], options[], confirmText, cancelText, onConfirm, onCancel}
 *   - suggestions[]: 热门议题 chip（pill 形式）
 *   - options[]: 竖向选项卡列表（每项占满宽度，圆滑边框）
 */
function showTopicModal(opts) {
  opts = opts || {};
  const existing = document.getElementById('inputDialog');
  if (existing) existing.remove();

  // 从 state 读取学科标签
  const discLabel = opts.disciplineLabel ||
    ((state.disciplineName || state.researchTypeName)
      ? (state.disciplineName || '') + (state.researchTypeName ? '·' + state.researchTypeName : '')
      : '');
  const suggestions = opts.suggestions || [
    '算法推荐与信息茧房',
    'AI生成内容的传播伦理',
    '平台经济中的劳动控制',
  ];
  const options = opts.options || [];

  // 构建竖向选项卡 HTML（P3-T2：选项数 > 6 时启用 2 列网格 + 滚动，适配 15 议题）
  const gridClass = options.length > 6 ? ' topic-dialog-options-grid' : '';
  const optionsHtml = options.length > 0
    ? '<div class="topic-dialog-options' + gridClass + '">' +
        options.map((opt, idx) => {
          const isOther = /其他|请直接输入|直接输入/.test(opt);
          return '<button class="topic-dialog-option-item' + (isOther ? ' topic-dialog-option-other' : '') + '" data-option="' + opt + '" data-index="' + idx + '">' +
            '<span class="topic-dialog-option-icon">' + (isOther ? iconEdit(14) : '○') + '</span>' +
            '<span class="topic-dialog-option-text">' + opt + '</span>' +
          '</button>';
        }).join('') +
      '</div>'
    : '';

  const overlay = document.createElement('div');
  overlay.id = 'inputDialog';
  overlay.className = 'topic-dialog-overlay';
  overlay.innerHTML =
    '<div class="topic-dialog-card" role="dialog" aria-modal="true" aria-labelledby="topicDialogTitle">' +
      '<div class="topic-dialog-decoration"></div>' +
      '<div class="topic-dialog-header">' +
        '<div class="topic-dialog-icon-wrap"><span class="topic-dialog-icon-emoji">' + iconLightbulb(20) + '</span></div>' +
        '<h3 class="topic-dialog-title" id="topicDialogTitle">' + (opts.title || '请问您对何议题感兴趣？') + '</h3>' +
      '</div>' +
      (opts.desc || discLabel
        ? '<p class="topic-dialog-desc">' +
            (opts.desc || '告诉我您想探讨的研究议题，我将基于您的学科背景') +
            (discLabel ? ' <span class="topic-dialog-discipline-tag">' + discLabel + '</span>' : '') +
            (opts.desc ? '' : ' 为您生成针对性的引导选项。') +
          '</p>'
        : '') +
      optionsHtml +
      '<div class="topic-dialog-input-wrap">' +
        '<input type="text" id="inputDialogText" class="topic-dialog-input" placeholder="' + (opts.placeholder || '例如：短视频算法对青少年价值观的影响') + '" autocomplete="off" />' +
        '<div id="inputDialogHint" class="topic-dialog-hint"></div>' +
      '</div>' +
      (options.length === 0
        ? '<div class="topic-dialog-suggestions">' +
            '<span class="topic-dialog-suggestions-label">热门议题：</span>' +
            suggestions.map(s => '<button class="topic-dialog-chip" data-topic="' + s + '" tabindex="0">' + s + '</button>').join('') +
          '</div>'
        : '') +
      '<div class="topic-dialog-actions">' +
        '<button id="inputDialogCancel" class="btn btn-ghost">' + (opts.cancelText || '跳过') + '</button>' +
        '<button id="inputDialogConfirm" class="btn btn-primary">' + (opts.confirmText || '确认') + '</button>' +
      '</div>' +
    '</div>';

  document.body.appendChild(overlay);
  // Lock background scroll
  document.body.style.overflow = 'hidden';

  const input = document.getElementById('inputDialogText');
  const hint = document.getElementById('inputDialogHint');
  const card = overlay.querySelector('.topic-dialog-card');
  setTimeout(() => input.focus(), 120);

  // Focus trap
  const focusableInCard = () => card.querySelectorAll('button, input, [tabindex]:not([tabindex="-1"])');
  card.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const nodes = focusableInCard();
    if (!nodes.length) return;
    const first = nodes[0], last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // 竖向选项卡点击
  overlay.querySelectorAll('.topic-dialog-option-item').forEach(item => {
    item.addEventListener('click', () => {
      const optText = item.dataset.option;
      const isOther = /其他|请直接输入|直接输入/.test(optText);
      if (isOther) {
        // "其他"选项：聚焦输入框让用户自主填写
        input.value = '';
        input.focus();
        hint.textContent = '请在下方输入框中填写您的回答';
        hint.className = 'topic-dialog-hint';
      } else {
        input.value = optText;
        hint.textContent = '';
        hint.className = 'topic-dialog-hint';
      }
      // 选中态
      overlay.querySelectorAll('.topic-dialog-option-item').forEach(c => c.classList.remove('selected'));
      item.classList.add('selected');
    });
  });

  // chip 点击填入 + 键盘支持
  overlay.querySelectorAll('.topic-dialog-chip').forEach(chip => {
    const handleChipSelect = () => {
      input.value = chip.dataset.topic;
      hint.textContent = '';
      hint.className = 'topic-dialog-hint';
      input.focus();
      overlay.querySelectorAll('.topic-dialog-chip').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
    };
    chip.addEventListener('click', handleChipSelect);
    chip.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleChipSelect();
      }
    });
  });

  const confirmHandler = () => {
    const val = input.value.trim();
    if (!val) {
      hint.textContent = '请输入或选择一个议题后再继续';
      hint.className = 'topic-dialog-hint error';
      input.classList.add('error');
      card.classList.add('topic-dialog-shake');
      setTimeout(() => {
        card.classList.remove('topic-dialog-shake');
        input.classList.remove('error');
      }, 1500);
      input.focus();
      return;
    }
    document.body.style.overflow = '';
    overlay.remove();
    if (typeof opts.onConfirm === 'function') opts.onConfirm(val);
  };

  const cancelHandler = () => {
    document.body.style.overflow = '';
    overlay.remove();
    if (typeof opts.onCancel === 'function') opts.onCancel();
  };

  document.getElementById('inputDialogConfirm').addEventListener('click', confirmHandler);
  document.getElementById('inputDialogCancel').addEventListener('click', cancelHandler);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      confirmHandler();
    } else if (e.key === 'Escape') {
      cancelHandler();
    }
  });
}

const defaultMeta = {
  name: '学术助手',
  color: 'amber',
  role: '智能学术研究助手',
  suggestions: [
    { icon: 'chat', title: '自由对话', desc: '直接提出你的研究问题或需求' },
    { icon: 'doc', title: '文档分析', desc: '上传或粘贴研究文档，我会帮你分析' },
    { icon: 'search', title: '知识查询', desc: '询问任何学术相关的知识或方法' },
  ],
  placeholder: '输入任何问题，开始对话...',
};

// Agent 颜色 → CSS 变量映射
const AGENT_COLORS = {
  amber: 'var(--accent-amber)',
  blue: 'var(--accent-blue)',
  teal: 'var(--accent-teal)',
  purple: 'var(--accent-purple)',
  green: 'var(--accent-green)',
};

export function AgentPage({ agentId } = {}) {
  const meta = agentMeta[agentId] || defaultMeta;
  const accentColor = AGENT_COLORS[meta.color] || AGENT_COLORS.amber;
  const page = createElement('div', { className: 'page active page-agent' });
  const workspace = createElement('div', { className: 'agent-workspace' });
  const projectPanel = createElement('aside', {
    className: 'agent-project-panel',
    'aria-label': '项目导航',
  });
  const conversation = createElement('main', { className: 'agent-conversation', 'data-agent-color': meta.color });
  const insightPanel = createElement('aside', {
    className: 'agent-insight-panel',
    'aria-label': '研究任务与资料',
  });

  const currentTopic = localStorage.getItem('scholarmind_user_topic') || '未命名研究项目';
  const projectTitle = createElement('h2', { className: 'project-panel-title' }, currentTopic);
  const projectHead = createElement('div', { className: 'project-panel-head' },
    createElement('span', { className: 'project-panel-eyebrow' }, '当前项目'),
    projectTitle,
    createElement('span', { className: 'status-chip status-chip-success' }, '研究中'),
  );
  projectPanel.appendChild(projectHead);

  const projectNav = createElement('nav', { className: 'project-nav', 'aria-label': '项目内容' });
  [
    { icon: iconChat(17), label: '对话', count: '当前', active: true },
    { icon: iconLibrary(17), label: '文献与文件', count: '0' },
    { icon: iconClock(17), label: '任务', count: '1' },
    { icon: iconEdit(17), label: '论文版本', count: '0' },
  ].forEach(item => {
    const btn = createElement('button', {
      className: 'project-nav-item' + (item.active ? ' active' : ''),
      type: 'button',
      'aria-current': item.active ? 'page' : 'false',
    });
    btn.innerHTML = item.icon + `<span>${item.label}</span><span class="project-nav-count">${item.count}</span>`;
    if (item.label === '论文版本') btn.addEventListener('click', () => { state.currentAgent = agentId; navigateTo('writing'); });
    if (item.label === '文献与文件') btn.addEventListener('click', () => {
      insightPanel.classList.add('mobile-panel-open');
      activateInsightTab('sources');
    });
    if (item.label === '任务') btn.addEventListener('click', () => {
      insightPanel.classList.add('mobile-panel-open');
      activateInsightTab('tasks');
    });
    projectNav.appendChild(btn);
  });
  projectPanel.appendChild(projectNav);
  const newProjectBtn = createElement('button', { className: 'btn btn-secondary project-new-btn', type: 'button' }, '＋ 新建研究项目');
  newProjectBtn.addEventListener('click', () => navigateTo('homepage'));
  projectPanel.appendChild(newProjectBtn);

  const insightTabs = createElement('div', { className: 'insight-tabs', role: 'tablist', 'aria-label': '研究侧栏' });
  const insightBody = createElement('div', { className: 'insight-body' });
  const taskPanel = createElement('section', { className: 'insight-tab-panel active', 'data-panel': 'tasks', role: 'tabpanel' });
  const sourcesPanel = createElement('section', { className: 'insight-tab-panel', 'data-panel': 'sources', role: 'tabpanel' });
  const logPanel = createElement('section', { className: 'insight-tab-panel', 'data-panel': 'log', role: 'tabpanel' });

  function activateInsightTab(tabId) {
    insightTabs.querySelectorAll('.insight-tab').forEach(tab => {
      const selected = tab.dataset.tab === tabId;
      tab.classList.toggle('active', selected);
      tab.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    insightBody.querySelectorAll('.insight-tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.dataset.panel === tabId);
    });
  }

  [
    { id: 'tasks', label: '任务' },
    { id: 'sources', label: '资料' },
    { id: 'log', label: '协作' },
  ].forEach((tab, index) => {
    const btn = createElement('button', {
      className: 'insight-tab' + (index === 0 ? ' active' : ''),
      type: 'button',
      role: 'tab',
      'data-tab': tab.id,
      'aria-selected': index === 0 ? 'true' : 'false',
    }, tab.label);
    btn.addEventListener('click', () => activateInsightTab(tab.id));
    insightTabs.appendChild(btn);
  });

  const taskCard = createElement('article', { className: 'task-card task-card-active' });
  const taskStatusText = createElement('span', { className: 'task-state' }, '就绪');
  const taskProgressBar = createElement('span', { className: 'task-progress-value' });
  // Real steps matching the actual chat flow — no fake progress
  const taskStepsDef = ['已收到问题', '分析研究意图', '检索相关资料', '组织学术回答'];
  const taskStepItems = taskStepsDef.map((label, index) => {
    const item = createElement('li', { className: '' });
    item.innerHTML = `<span class="task-step-marker">${index + 1}</span><span>${label}</span>`;
    return item;
  });
  taskCard.append(
    createElement('div', { className: 'task-card-head' },
      createElement('div', {},
        createElement('span', { className: 'task-kicker' }, '研究任务'),
        createElement('h3', {}, meta.name + ' · 研究协作'),
      ),
      taskStatusText,
    ),
    createElement('div', {
      className: 'task-progress',
      role: 'progressbar',
      'aria-valuemin': '0',
      'aria-valuemax': '100',
      'aria-label': '任务状态'
    }, taskProgressBar),
    createElement('ol', { className: 'task-steps' }, ...taskStepItems),
    createElement('p', { className: 'task-recovery-note' }, '状态跟随对话实时更新'),
  );
  taskPanel.appendChild(taskCard);

  // Helper: update task progress honestly (no fake percentages)
  function updateTaskProgress(state, activeStep) {
    taskCard.classList.remove('is-running', 'is-complete', 'has-error');
    taskStatusText.textContent = state;
    const bar = taskCard.querySelector('.task-progress');
    const barVal = taskCard.querySelector('.task-progress-value');
    if (state === '运行中') {
      taskCard.classList.add('is-running');
      bar.setAttribute('aria-valuenow', '');
      barVal.style.width = ''; // CSS handles indeterminate animation
    } else if (state === '已完成') {
      taskCard.classList.add('is-complete');
      bar.setAttribute('aria-valuenow', '100');
      barVal.style.width = '100%';
    } else if (state === '需要重试') {
      taskCard.classList.add('has-error');
      bar.setAttribute('aria-valuenow', '');
      barVal.style.width = '';
    } else {
      bar.setAttribute('aria-valuenow', '0');
      barVal.style.width = '0%';
    }
    taskStepItems.forEach((item, idx) => {
      item.className = idx < activeStep ? 'done' : idx === activeStep ? 'current' : '';
    });
  }

  const sourceEmpty = createElement('div', { className: 'panel-empty-state' });
  sourceEmpty.innerHTML = iconBookOpen(28) + '<h3>还没有项目资料</h3><p>上传论文、访谈稿或数据，让回答基于你的真实材料。</p>';
  const uploadBtn = createElement('button', { className: 'btn btn-secondary btn-sm', type: 'button' });
  uploadBtn.innerHTML = iconUpload(15) + '<span>添加资料</span>';
  uploadBtn.addEventListener('click', () => {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.multiple = true;
    fileInput.accept = '.pdf,.doc,.docx,.txt,.md,.csv';
    fileInput.click();
  });
  sourceEmpty.appendChild(uploadBtn);
  sourcesPanel.appendChild(sourceEmpty);

  const logTimeline = createElement('div', { className: 'agent-timeline' });
  logTimeline.innerHTML =
    `<div class="agent-timeline-item active"><span class="timeline-dot"></span><div><strong>${meta.name}</strong><p>已进入项目，等待研究指令</p><time>刚刚</time></div></div>` +
    '<div class="agent-timeline-item"><span class="timeline-dot"></span><div><strong>项目知识库</strong><p>尚未添加可引用资料</p></div></div>';
  logPanel.appendChild(logTimeline);

  insightBody.append(taskPanel, sourcesPanel, logPanel);
  insightPanel.append(insightTabs, insightBody);
  workspace.append(projectPanel, conversation, insightPanel);
  page.appendChild(workspace);

  // ========== HEADER ==========
  const header = createElement('div', { className: 'chat-header-area' });
  const headerRow = createElement('div', { className: 'chat-header-row' });
  const backBtn = createElement('button', {
    className: 'btn-back',
    'aria-label': '返回上一页',
  });
  backBtn.innerHTML = iconArrowLeft(16) + '<span>返回</span>';
  backBtn.addEventListener('click', () => {
    if (state.readiness) {
      navigateTo('readiness');
    } else if (state.researchType) {
      navigateTo(state.discipline || 'homepage');
    } else {
      navigateTo('homepage');
    }
  });
  headerRow.appendChild(backBtn);
  headerRow.appendChild(createElement('div', { className: 'chat-header-spacer' }));
  const title = createElement('h2', { className: 'chat-header-title' }, meta.name);
  headerRow.appendChild(title);
  // 新对话 + 历史对话按钮
  const headerActions = createElement('div', { className: 'chat-header-actions' });
  const historyBtn = createElement('button', { className: 'btn btn-ghost btn-sm', 'aria-label': '历史对话', title: '历史对话' });
  historyBtn.innerHTML = iconLibrary(16) + ' <span>历史</span>';
  historyBtn.addEventListener('click', () => loadHistorySessions());
  const exportBtn = createElement('button', { className: 'btn btn-ghost btn-sm', 'aria-label': '导出对话', title: '导出对话为 Markdown' });
  exportBtn.innerHTML = iconDownload(16) + ' <span>导出</span>';
  exportBtn.addEventListener('click', () => exportChat());
  const newChatBtn = createElement('button', { className: 'btn btn-ghost btn-sm', 'aria-label': '新对话', title: '开始新对话' });
  newChatBtn.innerHTML = iconEdit(16) + ' <span>新对话</span>';
  newChatBtn.addEventListener('click', () => startNewChat());
  headerActions.appendChild(historyBtn);
  headerActions.appendChild(exportBtn);
  headerActions.appendChild(newChatBtn);
  headerRow.appendChild(headerActions);
  header.appendChild(headerRow);
  const subtitle = createElement('p', { className: 'chat-header-subtitle' }, meta.role);
  header.appendChild(subtitle);
  conversation.appendChild(header);

  // ========== 每次进入生成新 session_id（新聊天框）==========
  const currentSessionId = crypto.randomUUID();
  let chatMessages = []; // 当前对话消息（内存，不恢复历史）

  // ========== WELCOME AREA（始终显示）==========
  let welcomeArea = createElement('div', { className: 'chat-welcome-area' });
  const agentAvatar = createElement('div', { className: 'agent-avatar', innerHTML: renderIcon(agentId || 'researcher', 32) });
  welcomeArea.appendChild(agentAvatar);
  const roleLine = createElement('p', { className: 'chat-welcome-role' }, meta.role);
  welcomeArea.appendChild(roleLine);

  const cards = createElement('div', { className: 'prompt-cards' });
  meta.suggestions.forEach(s => {
    const card = createElement('div', { className: 'prompt-card', role: 'button', tabindex: '0', 'aria-label': s.title });
    card.innerHTML =
      `<div class="prompt-card-icon">${renderIcon(s.icon, 20)}</div>` +
      `<div class="prompt-card-title">${s.title}</div>` +
      `<div class="prompt-card-desc">${s.desc}</div>`;
    const activate = () => {
      input.value = s.desc;
      input.focus();
      const match = /\[([^\]]+)\]/.exec(s.desc);
      if (match) {
        const idx = s.desc.indexOf(match[0]);
        input.setSelectionRange(idx, idx + match[0].length);
      }
    };
    card.addEventListener('click', activate);
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); } });
    cards.appendChild(card);
  });
  welcomeArea.appendChild(cards);

  // P1-4: 研究模板库 — 常用学术任务快捷入口
  const templateSection = createElement('div', { className: 'chat-template-section' });
  templateSection.appendChild(createElement('p', { className: 'chat-template-label' }, '常用研究模板'));
  const templateChips = createElement('div', { className: 'chat-template-chips' });
  const TEMPLATES = [
    { label: '写文献综述', prompt: '请帮我撰写关于[研究主题]的文献综述，涵盖近5年国内外研究进展' },
    { label: '设计研究方法', prompt: '我的研究问题是[问题]，请帮我设计合适的研究方法和数据收集方案' },
    { label: '分析研究数据', prompt: '以下是我的研究数据：[数据]，请帮我进行分析并提炼关键发现' },
    { label: '撰写论文大纲', prompt: '请为我的研究"[研究主题]"设计一个完整的学术论文大纲' },
    { label: '润色学术语言', prompt: '请帮我润色以下学术文本，使其更加专业流畅：[文本]' },
    { label: '评估论文质量', prompt: '请从研究方法、论证逻辑、创新性等维度评估以下论文：[论文]' },
  ];
  TEMPLATES.forEach(t => {
    const chip = createElement('button', { className: 'chat-template-chip', type: 'button' }, t.label);
    chip.addEventListener('click', () => {
      input.value = t.prompt;
      input.focus();
      const bracketMatch = /\[([^\]]+)\]/.exec(t.prompt);
      if (bracketMatch) {
        const idx = t.prompt.indexOf(bracketMatch[0]);
        input.setSelectionRange(idx, idx + bracketMatch[0].length);
      }
    });
    templateChips.appendChild(chip);
  });
  templateSection.appendChild(templateChips);
  welcomeArea.appendChild(templateSection);

  const hint = createElement('p', { className: 'chat-welcome-hint' }, '选择一个方向开始，或直接输入您的问题');
  welcomeArea.appendChild(hint);
  conversation.appendChild(welcomeArea);

  // ========== MESSAGES CONTAINER ==========
  const messagesContainer = createElement('div', {
    className: 'chat-messages',
    id: 'chat-messages',
    'aria-live': 'polite',
    'aria-label': '对话消息',
  });
  messagesContainer.style.display = 'none'; // 初始隐藏，发送第一条消息后显示
  conversation.appendChild(messagesContainer);

  // ========== INPUT AREA ==========
  const inputArea = createElement('div', { className: 'chat-input-area' });
  const inputContext = createElement('div', { className: 'chat-input-context' });
  const fileCount = Object.keys(state.uploadedFiles || {}).length;
  const contextFileSpan = createElement('span', {}, '项目知识库 · ' + fileCount + ' 篇');
  if (fileCount === 0) contextFileSpan.style.display = 'none';
  inputContext.appendChild(createElement('span', { innerHTML: renderIcon(agentId || 'researcher', 14) + ' ' + meta.name }));
  const modelToggle = createElement('button', {
    className: 'chat-model-toggle',
    type: 'button',
    'aria-label': '切换推理模式',
    title: '点击切换 Fast / Pro 推理模式',
  }, 'Pro 深度推理');
  let isProMode = true;
  modelToggle.addEventListener('click', () => {
    isProMode = !isProMode;
    modelToggle.textContent = isProMode ? 'Pro 深度推理' : 'Fast 快速响应';
    modelToggle.classList.toggle('is-fast', !isProMode);
  });
  inputContext.appendChild(modelToggle);
  inputContext.appendChild(contextFileSpan);
  const composerRow = createElement('div', { className: 'chat-composer-row' });
  const toolBtn = createElement('button', {
    className: 'chat-tool-btn',
    type: 'button',
    'aria-label': '添加文件或工具',
    title: '添加文件或工具',
  });
  toolBtn.innerHTML = iconUpload(18);

  const input = createElement('textarea', {
    className: 'chat-input',
    placeholder: meta.placeholder,
    'aria-label': '输入消息',
    rows: '1',
  });

  const sendBtn = createElement('button', {
    className: 'chat-send-btn',
    'aria-label': '发送消息',
  });
  sendBtn.innerHTML = iconSend(18) + '<span>发送</span>';

  composerRow.append(toolBtn, input, sendBtn);
  inputArea.append(
    inputContext,
    composerRow,
    createElement('div', { className: 'chat-input-hint' }, 'Enter 发送 · Shift + Enter 换行 · 输入 / 使用命令'),
  );
  conversation.appendChild(inputArea);

  // Drag-upload: allow dropping files directly onto the conversation area
  const dropZone = createElement('div', { className: 'chat-drop-zone' }, '拖拽文件到此处上传');
  conversation.appendChild(dropZone);
  let dragCounter = 0;
  conversation.addEventListener('dragover', (e) => { e.preventDefault(); e.stopPropagation(); });
  conversation.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragCounter++;
    if (dragCounter === 1) dropZone.classList.add('active');
  });
  conversation.addEventListener('dragleave', (e) => {
    dragCounter--;
    if (dragCounter <= 0) { dragCounter = 0; dropZone.classList.remove('active'); }
  });
  conversation.addEventListener('drop', (e) => {
    e.preventDefault();
    dragCounter = 0;
    dropZone.classList.remove('active');
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      state.uploadedFiles = { ...(state.uploadedFiles || {}), ...Object.fromEntries(files.map(f => [f.name, f])) };
      contextFileSpan.textContent = '项目知识库 · ' + Object.keys(state.uploadedFiles).length + ' 篇';
      contextFileSpan.style.display = '';
      showToast('已添加 ' + files.length + ' 个文件到知识库', 'success');
    }
  });

  toolBtn.addEventListener('click', () => {
    insightPanel.classList.add('mobile-panel-open');
    activateInsightTab('sources');
  });

  const mobileTabs = createElement('nav', { className: 'agent-mobile-tabs', 'aria-label': '移动端工作区导航' });
  [
    { id: 'chat', label: '对话', icon: iconChat(18) },
    { id: 'project', label: '项目', icon: iconLibrary(18) },
    { id: 'tasks', label: '进度', icon: iconClock(18) },
    { id: 'sources', label: '资料', icon: iconBookOpen(18) },
    { id: 'home', label: '首页', icon: iconHome(18) },
  ].forEach((item, index) => {
    const btn = createElement('button', { className: 'mobile-tab' + (index === 0 ? ' active' : ''), type: 'button' });
    btn.innerHTML = item.icon + `<span>${item.label}</span>`;
    btn.addEventListener('click', () => {
      if (item.id === 'home') {
        navigateTo('homepage');
        return;
      }
      mobileTabs.querySelectorAll('.mobile-tab').forEach(el => el.classList.remove('active'));
      btn.classList.add('active');
      projectPanel.classList.toggle('mobile-panel-open', item.id === 'project');
      insightPanel.classList.toggle('mobile-panel-open', item.id === 'tasks' || item.id === 'sources');
      if (item.id === 'tasks' || item.id === 'sources') activateInsightTab(item.id);
    });
    mobileTabs.appendChild(btn);
  });
  page.appendChild(mobileTabs);

  // ========== HELPERS ==========
  let firstMessageSent = false;

  function hideWelcome() {
    if (welcomeArea && welcomeArea.parentNode) {
      welcomeArea.classList.add('chat-welcome-leaving');
      setTimeout(() => {
        if (welcomeArea && welcomeArea.parentNode) {
          welcomeArea.remove();
        }
        welcomeArea = null;
      }, 300);
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // 自适应高度
  function autoResize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  }
  input.addEventListener('input', autoResize);

  function formatTime() {
    const d = new Date();
    return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
  }

  function addMessage(role, content) {
    const bubble = createElement('div', {
      className: `chat-bubble chat-bubble-${role === 'user' ? 'user' : 'ai'} accent-${meta.color}`,
    });
    bubble.innerHTML = escapeHtml(content);

    // AI 消息添加操作按钮和时间戳
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

    messagesContainer.appendChild(bubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function addError(content) {
    const err = createElement('div', {
      className: 'chat-bubble chat-bubble-ai chat-bubble-error',
    });
    // P0-T9 XSS 修复：所有 content 均需清洗，避免恶意脚本注入
    if (content.includes('<code>')) {
      // 受信任的模板（如后端启动提示），但仍需清洗潜在的 script 与 on* 事件
      import('dompurify').then(purifyMod => {
        const DOMPurify = purifyMod.default || purifyMod;
        err.innerHTML = DOMPurify.sanitize(content, { ALLOWED_TAGS: ['code', 'pre', 'br', 'b', 'i', 'em', 'strong'] });
      }).catch(() => {
        // 降级：移除 script 与 on* 事件属性
        const sanitized = String(content)
          .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
          .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
          .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
          .replace(/\son\w+\s*=\s*[^\s>]+/gi, '');
        err.innerHTML = sanitized;
      });
    } else {
      err.innerHTML = escapeHtml(content);
    }
    // Add retry button
    const retryBtn = createElement('button', { className: 'btn btn-outline btn-sm chat-retry-btn' }, '重试');
    retryBtn.addEventListener('click', () => {
      err.remove();
      // Re-send the last user message if available
      const lastUserMsg = chatMessages.filter(m => m.role === 'user').pop();
      if (lastUserMsg) {
        input.value = lastUserMsg.content;
        sendMessage();
      }
    });
    err.appendChild(retryBtn);

    messagesContainer.appendChild(err);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // ========== SEND ==========
  let abortController = null;
  let undoBar = null;

  function removeUndoBar() {
    if (undoBar && undoBar.parentNode) undoBar.remove();
    undoBar = null;
  }

  function showUndoBar(text, userBubble) {
    removeUndoBar();
    undoBar = createElement('div', { className: 'chat-undo-bar' });
    undoBar.innerHTML = '<span>消息已发送</span>';
    const undoBtn = createElement('button', { className: 'chat-undo-btn' }, '撤销');
    undoBtn.addEventListener('click', () => {
      if (abortController) { abortController.abort(); abortController = null; }
      if (userBubble && userBubble.parentNode) userBubble.remove();
      // Remove last user message from chatMessages
      const lastIdx = chatMessages.length - 1;
      while (lastIdx >= 0 && chatMessages[lastIdx].role !== 'user') {
        chatMessages.pop();
      }
      if (lastIdx >= 0 && chatMessages[lastIdx].role === 'user') {
        chatMessages.pop();
      }
      // Restore input
      input.value = text;
      input.disabled = false;
      sendBtn.disabled = false;
      sendBtn.innerHTML = iconSend(18) + '<span>发送</span>';
      updateTaskProgress('就绪', -1);
      input.focus();
      removeUndoBar();
    });
    undoBar.appendChild(undoBtn);
    // Insert before input area
    conversation.insertBefore(undoBar, inputArea);
    // Auto-remove after 6s
    setTimeout(() => {
      if (undoBar && undoBar.parentNode) undoBar.remove();
      undoBar = null;
    }, 6000);
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) {
      input.style.animation = 'shake 0.4s ease';
      setTimeout(() => { input.style.animation = ''; }, 400);
      return;
    }

    input.value = '';
    input.style.height = 'auto';
    input.disabled = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span class="btn-spinner"></span><span>发送中</span>';
    updateTaskProgress('运行中', 1);

    if (!firstMessageSent) {
      firstMessageSent = true;
      hideWelcome();
      messagesContainer.style.display = '';
    }

    addMessage('user', text);
    chatMessages.push({ role: 'user', content: text });

    // Show undo bar
    const userBubble = messagesContainer.lastElementChild;
    showUndoBar(text, userBubble);

    // Show typing indicator
    const typingEl = createElement('div', { className: 'typing-indicator accent-' + meta.color },
      createElement('div', { className: 'typing-dot' }),
      createElement('div', { className: 'typing-dot' }),
      createElement('div', { className: 'typing-dot' }),
      createElement('span', { className: 'typing-text' }, '思考中...'),
    );
    messagesContainer.appendChild(typingEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    abortController = new AbortController();

    try {
      let aiBubble = null;
      let aiContent = '';
      let streamDone = false;

      // P0-2: SSE 流式对话 — 实时 token + 诚实进度
      await agentApi.streamChat({
        agent_id: agentId,
        session_id: currentSessionId,
        message: text,
        mode: isProMode ? 'pro' : 'flash',
        context: {
          discipline: state.discipline || '',
          discipline_name: state.disciplineName || '',
          research_type: state.researchType || '',
          research_type_name: state.researchTypeName || '',
          readiness: state.readiness || '',
          user_topic: localStorage.getItem('scholarmind_user_topic') || '',
          guidance_step: 0,
          guidance_data: {},
        },
      }, {
        onToken: (token) => {
          if (!aiBubble) {
            if (typingEl && typingEl.parentNode) typingEl.remove();
            aiBubble = createElement('div', { className: 'chat-bubble chat-bubble-ai accent-' + meta.color });
            messagesContainer.appendChild(aiBubble);
            updateTaskProgress('运行中', 2);
          }
          aiContent += token;
          aiBubble.innerHTML = escapeHtml(aiContent);
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        },
        onThought: (thought) => {
          updateTaskProgress('深度思考中', 1);
        },
        onDone: (meta2) => {
          streamDone = true;
          if (!aiBubble && aiContent) {
            if (typingEl && typingEl.parentNode) typingEl.remove();
            aiBubble = createElement('div', { className: 'chat-bubble chat-bubble-ai accent-' + meta.color });
            aiBubble.innerHTML = escapeHtml(aiContent);
            messagesContainer.appendChild(aiBubble);
          }
          // P1-8: 添加引用来源展示
          if (meta2.cnki_results && meta2.cnki_results.length > 0 && aiBubble) {
            const sourcesEl = createElement('div', { className: 'chat-sources' });
            sourcesEl.appendChild(createElement('div', { className: 'chat-sources-label' }, '参考文献来源'));
            meta2.cnki_results.slice(0, 5).forEach(r => {
              const item = createElement('div', { className: 'chat-source-item' });
              item.innerHTML = `<span class="chat-source-title">${escapeHtml(r.title || '')}</span><span class="chat-source-meta">${escapeHtml(r.author || '')} · ${escapeHtml(r.source || '')} (${r.year || ''}) · 被引 ${r.citations || 0}</span>`;
              sourcesEl.appendChild(item);
            });
            aiBubble.appendChild(sourcesEl);
          }
          // 操作按钮
          if (aiBubble) {
            const actions = createElement('div', { className: 'chat-bubble-actions' });
            const copyBtn = createElement('button', { className: 'chat-action-btn', 'aria-label': '复制消息' });
            copyBtn.innerHTML = iconCopy(14) + '<span>复制</span>';
            copyBtn.addEventListener('click', () => {
              navigator.clipboard.writeText(aiContent).then(() => {
                copyBtn.innerHTML = iconCheck(14) + '<span>已复制</span>';
                setTimeout(() => { copyBtn.innerHTML = iconCopy(14) + '<span>复制</span>'; }, 2000);
              });
            });
            actions.appendChild(copyBtn);
            aiBubble.appendChild(actions);
            const time = createElement('div', { className: 'chat-bubble-time' }, formatTime());
            aiBubble.appendChild(time);
          }
          chatMessages.push({ role: 'assistant', content: aiContent, meta: meta2 });
          updateTaskProgress('已完成', taskStepsDef.length);
          removeUndoBar();
          if (meta2.options && meta2.options.length > 0) {
            showTopicModal({
              title: '请选择您的方向',
              suggestions: meta2.options,
              confirmText: '确认选择',
              onConfirm: (inputValue) => {
                input.value = inputValue;
                sendMessage();
              },
            });
          }
        },
        onError: (err) => {
          throw err;
        },
        signal: abortController.signal,
      });

      if (typingEl && typingEl.parentNode) typingEl.remove();
    } catch (e) {
      if (typingEl && typingEl.parentNode) {
        typingEl.remove();
      }
      if (e && e.name === 'AbortError') {
        // User cancelled via undo — no error display needed
        return;
      }
      let errorHtml = '';
      if (e instanceof NetworkError) {
        errorHtml = '后端服务未启动，请在终端执行 <code>cd src/backend &amp;&amp; uvicorn app:app --reload</code>';
      } else if (e.name === 'ApiError' && e.message) {
        errorHtml = escapeHtml(e.message);
      } else {
        errorHtml = escapeHtml(e.message || '请求失败，请检查后端是否启动');
      }
      addError(errorHtml);
      updateTaskProgress('需要重试', -1);
      console.error('Chat error:', e);
    } finally {
      abortController = null;
      sendBtn.innerHTML = iconSend(18) + '<span>发送</span>';
      taskCard.classList.remove('is-running');
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  // ========== EVENTS ==========
  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => {
    // BC-07: Enter 发送，Shift+Enter 换行，Ctrl/Cmd+Enter 也发送
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      sendMessage();
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ========== 新对话 / 历史对话 ==========
  function startNewChat() {
    // 清空当前消息
    messagesContainer.innerHTML = '';
    messagesContainer.style.display = 'none';
    chatMessages = [];
    firstMessageSent = false;
    // 重新生成 session_id
    const newSessionId = crypto.randomUUID();
    // 重新显示欢迎区域
    if (!welcomeArea || !welcomeArea.parentNode) {
      welcomeArea = createElement('div', { className: 'chat-welcome-area' });
      welcomeArea.appendChild(createElement('div', { className: 'agent-avatar', innerHTML: renderIcon(agentId || 'researcher', 32) }));
      welcomeArea.appendChild(createElement('p', { className: 'chat-welcome-role' }, meta.role));
      const newCards = createElement('div', { className: 'prompt-cards' });
      meta.suggestions.forEach(s => {
        const card = createElement('div', { className: 'prompt-card', role: 'button', tabindex: '0' });
        card.innerHTML = `<div class="prompt-card-icon">${renderIcon(s.icon, 20)}</div><div class="prompt-card-title">${s.title}</div><div class="prompt-card-desc">${s.desc}</div>`;
        card.addEventListener('click', () => { input.value = s.desc; input.focus(); });
        newCards.appendChild(card);
      });
      welcomeArea.appendChild(newCards);
      welcomeArea.appendChild(createElement('p', { className: 'chat-welcome-hint' }, '选择一个方向开始，或直接输入您的问题'));
      conversation.insertBefore(welcomeArea, messagesContainer);
    }
    input.focus();
  }

  function exportChat() {
    if (chatMessages.length === 0) {
      showToast('暂无对话内容可导出', 'info');
      return;
    }
    const lines = [];
    lines.push('# ScholarMind 研究对话');
    lines.push('');
    lines.push('> Agent: ' + meta.name + ' | 日期: ' + new Date().toLocaleDateString('zh-CN'));
    lines.push('> 议题: ' + (localStorage.getItem('scholarmind_user_topic') || '未命名'));
    lines.push('');
    lines.push('---');
    lines.push('');
    chatMessages.forEach(m => {
      const roleLabel = m.role === 'user' ? '**你**' : '**' + meta.name + '**';
      lines.push(roleLabel);
      lines.push('');
      lines.push(m.content);
      lines.push('');
      lines.push('---');
      lines.push('');
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'scholarmind-' + meta.name + '-' + new Date().toISOString().slice(0, 10) + '.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('对话已导出为 Markdown', 'success');
  }

  async function loadHistorySessions() {
    // 创建历史对话侧边栏
    let sidebar = document.getElementById('history-sidebar');
    if (sidebar) { sidebar.remove(); return; }
    sidebar = createElement('div', { className: 'history-sidebar', id: 'history-sidebar' });
    const sidebarHeader = createElement('div', { className: 'history-sidebar-header' });
    sidebarHeader.innerHTML = '<h3>历史对话</h3>';
    const closeBtn = createElement('button', { className: 'btn btn-ghost btn-sm' }, '✕');
    closeBtn.addEventListener('click', () => sidebar.remove());
    sidebarHeader.appendChild(closeBtn);
    sidebar.appendChild(sidebarHeader);
    const list = createElement('div', { className: 'history-sidebar-list' });
    list.innerHTML = '<p style="color:var(--text-tertiary);text-align:center;padding:20px;">加载中...</p>';
    sidebar.appendChild(list);
    page.appendChild(sidebar);

    try {
      const res = await agentApi.getSessions(agentId);
      const sessions = res.sessions || res || [];
      list.innerHTML = '';
      if (sessions.length === 0) {
        list.innerHTML = '<p style="color:var(--text-tertiary);text-align:center;padding:20px;">暂无历史对话</p>';
        return;
      }
      sessions.forEach(s => {
        const item = createElement('div', { className: 'history-session-item' });
        item.innerHTML = `<div class="history-session-title">${escapeHtml(s.title || '未命名对话')}</div><div class="history-session-time">${s.created_at || s.updated_at || ''}</div>`;
        item.addEventListener('click', async () => {
          sidebar.remove();
          // 加载历史会话
          messagesContainer.innerHTML = '';
          const conv = await agentApi.getConversation(s.session_id);
          const msgs = conv.messages || conv || [];
          if (msgs.length > 0) {
            hideWelcome();
            messagesContainer.style.display = '';
            firstMessageSent = true;
            msgs.forEach(m => addMessage(m.role, m.content));
          }
        });
        list.appendChild(item);
      });
    } catch (e) {
      list.innerHTML = '<p style="color:var(--accent-red);text-align:center;padding:20px;">加载失败，请检查后端是否启动</p>';
    }
  }

  setTimeout(() => input.focus(), 100);

  // ========== 进入页面时自动弹出议题选择弹窗 ==========
  // 根据 Agent 类型生成动态标题
  const TOPIC_TITLES = {
    researcher: '请问您想研究什么议题？',
    reviewer: '请描述您的研究思路',
    architect: '请描述您的论文主题',
    synthesizer: '请输入您要综述的研究方向',
    polisher: '请描述您的润色或降重需求',
  };
  // P3-T1：异步从后端获取指定学科的热门议题（4 学科各 15 个 Top 议题）
  // 替代原硬编码 DISCIPLINE_SUGGESTIONS（仅 3 学科各 3 议题且缺 interdisciplinary）
  const FALLBACK_TOPICS = ['算法推荐与信息茧房', 'AI生成内容的传播伦理', '平台经济中的劳动控制'];
  async function fetchTopics() {
    try {
      const res = await agentApi.getTopics(state.discipline);
      const topics = (res && res.topics) ? res.topics.map(t => t.title).filter(Boolean) : [];
      return topics.length > 0 ? topics : FALLBACK_TOPICS;
    } catch (e) {
      console.warn('在线议题加载失败，已显示默认议题', e);
      return FALLBACK_TOPICS;
    }
  }

  // 智能弹出议题弹窗：仅在首次进入该 Agent 或无议题时弹出
  const topicKey = 'sm_' + agentId + '_topic_set';
  const existingTopic = localStorage.getItem('scholarmind_user_topic');
  const hasTopicForAgent = localStorage.getItem(topicKey) === '1';
  const hasMessages = !!(state.messages && state.messages[agentId] && state.messages[agentId].length > 0);

  if (!hasTopicForAgent && !hasMessages) {
    setTimeout(async () => {
      const topics = await fetchTopics();
      showTopicModal({
        title: TOPIC_TITLES[agentId] || '请问您对何议题感兴趣？',
        options: topics,
        suggestions: topics.slice(0, 5),
        confirmText: '确认',
        onConfirm: (topic) => {
          // 存储议题到 localStorage
          localStorage.setItem('scholarmind_user_topic', topic);
          localStorage.setItem(topicKey, '1');
          projectTitle.textContent = topic;
          // 在欢迎语中显示议题
          if (welcomeArea && welcomeArea.parentNode) {
            const topicLine = createElement('p', { className: 'chat-welcome-topic' });
            topicLine.innerHTML = '当前议题：<strong>' + topic + '</strong>';
            welcomeArea.insertBefore(topicLine, welcomeArea.firstChild.nextSibling);
          }
          input.focus();
        },
        onCancel: () => {
          // 跳过议题选择，标记已处理避免重复弹出
          localStorage.setItem(topicKey, '1');
          input.focus();
        },
      });
    }, 500);
  } else if (existingTopic && welcomeArea) {
    // 已有议题时，在欢迎区显示当前议题 + 更换按钮
    const topicLine = createElement('p', { className: 'chat-welcome-topic' });
    topicLine.innerHTML = '当前议题：<strong>' + existingTopic + '</strong> <button class="chat-welcome-topic-change" type="button">更换</button>';
    welcomeArea.insertBefore(topicLine, welcomeArea.firstChild.nextSibling);
    const changeBtn = topicLine.querySelector('.chat-welcome-topic-change');
    if (changeBtn) {
      changeBtn.addEventListener('click', async () => {
        const topics = await fetchTopics();
        showTopicModal({
          title: TOPIC_TITLES[agentId] || '请问您对何议题感兴趣？',
          options: topics,
          suggestions: topics.slice(0, 5),
          confirmText: '确认',
          onConfirm: (topic) => {
            localStorage.setItem('scholarmind_user_topic', topic);
            localStorage.setItem(topicKey, '1');
            projectTitle.textContent = topic;
            topicLine.innerHTML = '当前议题：<strong>' + topic + '</strong> <button class="chat-welcome-topic-change" type="button">更换</button>';
            const newBtn = topicLine.querySelector('.chat-welcome-topic-change');
            if (newBtn) {
              newBtn.addEventListener('click', changeBtn.onclick, { once: true });
            }
            input.focus();
          },
        });
      });
    }
  }

  return page;
}
