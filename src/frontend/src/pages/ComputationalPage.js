import { createElement } from '../utils/dom.js';
import { state, watch } from '../app/store.js';
import { showToast } from '../components/ConfirmDialog.js';
import { agentApi } from '../services/agentApi.js';
import { computationalApi } from '../services/computationalApi.js';
import { iconGear, iconEdit, iconDownload, iconLightning, iconStar, iconSend, iconPlay, iconPackage, iconTrash, iconDoc, iconClipboardCheck, iconSearch, iconChart, iconMicroscope, iconClock } from '../utils/icons.js';

// 应用主题 → CodeMirror 主题映射
const CM_THEME_MAP = {
  dark: 'dracula',
  light: 'eclipse',
  pure: 'neo',
  warm: 'ayu-light',
};

function getCmTheme() {
  return CM_THEME_MAP[state.settings?.theme] || 'dracula';
}

// 默认示例代码：微博话题情感分析
const DEFAULT_CODE = `# 微博话题情感分析示例
import pandas as pd
from snownlp import SnowNLP
import matplotlib.pyplot as plt

# 1. 加载数据
df = pd.read_csv('weibo_comments.csv')

# 2. 情感打分
df['sentiment'] = df['content'].apply(lambda x: SnowNLP(str(x)).sentiments)

# 3. 可视化
plt.figure(figsize=(10, 6))
plt.hist(df['sentiment'], bins=30, color='#FFA657', edgecolor='white')
plt.title('微博评论情感分布')
plt.xlabel('情感得分（0=消极，1=积极）')
plt.ylabel('频次')
plt.show()

print(f'平均情感得分: {df["sentiment"].mean():.3f}')
print(f'积极评论占比: {(df["sentiment"] > 0.6).mean():.1%}')
`;

const CAPABILITIES = [
  '撰写并执行 Python 爬虫脚本',
  '数据清洗与统计分析',
  '可视化图表生成',
  '机器学习建模',
  '参考 HuggingFace 交互范式',
];

const SUGGESTIONS = [
  { icon: iconSearch(14), title: '爬取社交媒体数据', desc: '帮我爬取微博某话题的评论并做情感分析' },
  { icon: iconChart(14), title: '数据可视化', desc: '用 matplotlib 绘制论文级别的小提琴图和冲积图' },
  { icon: iconMicroscope(14), title: '机器学习建模', desc: '对文本数据进行主题建模（LDA）并可视化' },
];

/**
 * 计算社会科学页面：三栏布局
 * 左栏：Agent 信息 + 会话管理
 * 中栏：对话区
 * 右栏：CodeMirror 代码编辑器 + 输出区
 */
export function ComputationalPage() {
  // 每次进入生成新 session_id
  const sessionId = crypto.randomUUID();
  let chatMessages = [];
  let execCount = 0;
  let modelMode = 'flash';
  let codeEditor = null;

  const page = createElement('div', { className: 'page active page-computational' });

  // ── 三栏布局容器 ──
  const layout = createElement('div', { className: 'computational-layout' });

  // ════════════════ 左栏：Agent 信息 ════════════════
  const sidebar = createElement('div', { className: 'computational-sidebar' });

  const avatarEl = createElement('div', { className: 'computational-avatar' });
  avatarEl.innerHTML = iconGear(28);
  sidebar.appendChild(avatarEl);
  sidebar.appendChild(createElement('div', { className: 'computational-name' }, '计算社会科学'));
  sidebar.appendChild(createElement('div', { className: 'computational-role' }, '爬虫 · 数据分析 · 可视化'));

  const statusWrap = createElement('div', { className: 'computational-status' });
  statusWrap.innerHTML = '<span class="status-dot green"></span> 在线';
  sidebar.appendChild(statusWrap);

  // 能力说明
  const capSection = createElement('div', { className: 'computational-sidebar-section' });
  capSection.appendChild(createElement('div', { className: 'computational-sidebar-title' }, '能力说明'));
  const capList = createElement('div', { className: 'computational-cap-list' });
  CAPABILITIES.forEach(c => {
    capList.appendChild(createElement('div', { className: 'computational-cap-item' }, '· ' + c));
  });
  capSection.appendChild(capList);
  sidebar.appendChild(capSection);

  // 会话信息
  const sessSection = createElement('div', { className: 'computational-sidebar-section' });
  sessSection.appendChild(createElement('div', { className: 'computational-sidebar-title' }, '会话信息'));
  const sessInfo = createElement('div', { className: 'computational-sess-info' });
  const sessIdEl = createElement('div', {}, '会话 ID: ');
  const sessIdVal = createElement('span', { className: 'computational-sess-id' }, sessionId.slice(0, 8));
  sessIdEl.appendChild(sessIdVal);
  const execInfo = createElement('div', {}, '执行次数: ');
  const execVal = createElement('span', { className: 'computational-exec-count' }, '0');
  execInfo.appendChild(execVal);
  sessInfo.appendChild(sessIdEl);
  sessInfo.appendChild(execInfo);
  sessSection.appendChild(sessInfo);
  sidebar.appendChild(sessSection);

  // 操作按钮
  const btnSection = createElement('div', { className: 'computational-sidebar-section' });
  const newChatBtn = createElement('button', { className: 'computational-sidebar-btn' });
  newChatBtn.innerHTML = iconEdit(14) + ' 新建对话';
  newChatBtn.addEventListener('click', () => {
    chatMessages = [];
    execCount = 0;
    execVal.textContent = '0';
    renderMessages();
    showToast('已开启新对话', 'success');
  });
  const exportBtn = createElement('button', { className: 'computational-sidebar-btn' });
  exportBtn.innerHTML = iconDownload(14) + ' 导出对话';
  exportBtn.addEventListener('click', () => {
    const exportData = {
      session_id: sessionId,
      messages: chatMessages,
      exec_count: execCount,
      timestamp: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `computational-${sessionId.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('对话已导出', 'success');
  });
  btnSection.appendChild(newChatBtn);
  btnSection.appendChild(exportBtn);
  sidebar.appendChild(btnSection);

  layout.appendChild(sidebar);

  // ════════════════ 中栏：对话区 ════════════════
  const chatCol = createElement('div', { className: 'computational-chat' });

  // 欢迎消息 + 建议卡片
  const messagesEl = createElement('div', { className: 'computational-messages' });

  const welcomeBubble = createElement('div', { className: 'computational-bubble computational-bubble-ai' });
  welcomeBubble.innerHTML = `
    <div class="computational-bubble-name">${iconGear(14)} 计算社会科学助手</div>
    <div class="computational-bubble-text">
      你好！我是计算社会科学助手，擅长 Python 爬虫、数据分析、可视化和机器学习建模。<br>
      你可以：<br>
      · 在右侧编辑器中直接编写并运行 Python 代码<br>
      · 在下方描述你的研究需求，我会生成对应的代码<br>
      · 点击建议卡片快速开始
    </div>
  `;
  messagesEl.appendChild(welcomeBubble);

  // 建议卡片
  const suggestionsWrap = createElement('div', { className: 'computational-suggestions' });
  SUGGESTIONS.forEach(s => {
    const card = createElement('div', { className: 'computational-suggestion-card' });
    card.innerHTML = `
      <div class="computational-suggestion-icon">${s.icon}</div>
      <div class="computational-suggestion-body">
        <div class="computational-suggestion-title">${s.title}</div>
        <div class="computational-suggestion-desc">${s.desc}</div>
      </div>
    `;
    card.addEventListener('click', () => {
      inputEl.value = s.desc;
      inputEl.focus();
    });
    suggestionsWrap.appendChild(card);
  });
  messagesEl.appendChild(suggestionsWrap);

  chatCol.appendChild(messagesEl);

  // 输入区
  const inputArea = createElement('div', { className: 'computational-input-area' });

  // Flash/Pro 模式切换
  const modelToggle = createElement('div', { className: 'model-toggle', role: 'group', 'aria-label': '模型模式切换' });
  const flashBtn = createElement('button', { type: 'button', className: 'model-toggle-btn active', 'data-mode': 'flash', title: 'Flash 模式：响应更快' });
  flashBtn.innerHTML = iconLightning(14) + ' Flash';
  const proBtn = createElement('button', { type: 'button', className: 'model-toggle-btn', 'data-mode': 'pro', title: 'Pro 模式：深度分析' });
  proBtn.innerHTML = iconStar(14) + ' Pro';
  flashBtn.addEventListener('click', () => {
    modelMode = 'flash';
    flashBtn.classList.add('active');
    proBtn.classList.remove('active');
  });
  proBtn.addEventListener('click', () => {
    modelMode = 'pro';
    proBtn.classList.add('active');
    flashBtn.classList.remove('active');
    showToast('Pro 模式需要付费订阅，当前使用 Flash 免费试用', 'info');
  });
  modelToggle.appendChild(flashBtn);
  modelToggle.appendChild(proBtn);
  inputArea.appendChild(modelToggle);

  const inputEl = createElement('input', { type: 'text', className: 'computational-input', placeholder: '描述你的研究需求，如"爬取微博话题评论并做情感分析"...' });
  inputArea.appendChild(inputEl);

  const sendBtn = createElement('button', { className: 'computational-send-btn', 'aria-label': '发送消息' });
  sendBtn.innerHTML = iconSend(16);
  sendBtn.addEventListener('click', () => sendMessage());
  inputArea.appendChild(sendBtn);

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  chatCol.appendChild(inputArea);
  layout.appendChild(chatCol);

  // ════════════════ 右栏：代码编辑器 + 输出 ════════════════
  const editorCol = createElement('div', { className: 'computational-editor-area' });

  // 工具栏
  const toolbar = createElement('div', { className: 'computational-editor-toolbar' });
  const runBtn = createElement('button', { className: 'computational-run-btn', title: '运行代码 (Ctrl+Enter)' });
  runBtn.innerHTML = iconPlay(14) + ' 运行';
  const pkgBtn = createElement('button', { title: '安装 Python 包' });
  pkgBtn.innerHTML = iconPackage(14) + ' 安装包';
  const clearBtn = createElement('button', { title: '清空输出' });
  clearBtn.innerHTML = iconTrash(14) + ' 清空';
  const exampleBtn = createElement('button', { title: '加载示例代码' });
  exampleBtn.innerHTML = iconDoc(14) + ' 示例';
  const langLabel = createElement('span', { className: 'computational-lang-label' }, 'Python 3.x');
  toolbar.appendChild(runBtn);
  toolbar.appendChild(pkgBtn);
  toolbar.appendChild(clearBtn);
  toolbar.appendChild(exampleBtn);
  toolbar.appendChild(langLabel);
  editorCol.appendChild(toolbar);

  // CodeMirror 容器
  const editorContainer = createElement('div', { className: 'computational-editor-container' });
  const textarea = createElement('textarea', {});
  textarea.value = DEFAULT_CODE;
  editorContainer.appendChild(textarea);
  editorCol.appendChild(editorContainer);

  // 输出区
  const outputArea = createElement('div', { className: 'computational-output-area' });
  const outputToolbar = createElement('div', { className: 'computational-output-toolbar' });
  outputToolbar.innerHTML = '<span>' + iconClipboardCheck(14) + ' 输出</span><span class="computational-exec-status">就绪</span>';
  outputArea.appendChild(outputToolbar);
  const outputContent = createElement('div', { className: 'computational-output-content' });
  outputContent.innerHTML = '<div class="computational-output-placeholder">点击「' + iconPlay(14) + ' 运行」执行代码，或与左侧 Agent 对话生成代码</div>';
  outputArea.appendChild(outputContent);
  editorCol.appendChild(outputArea);

  layout.appendChild(editorCol);
  page.appendChild(layout);

  // ════════════════ 消息渲染函数 ════════════════
  function renderMessages() {
    // 保留欢迎气泡和建议卡片，清除后续消息
    const allBubbles = messagesEl.querySelectorAll('.computational-bubble-user, .computational-bubble-ai-dynamic');
    allBubbles.forEach(b => b.remove());

    chatMessages.forEach(msg => {
      const bubble = createElement('div', { className: msg.role === 'user' ? 'computational-bubble computational-bubble-user' : 'computational-bubble computational-bubble-ai computational-bubble-ai-dynamic' });
      if (msg.role === 'ai') {
        bubble.innerHTML = `<div class="computational-bubble-name">${iconGear(14)} 计算社会科学助手</div><div class="computational-bubble-text">${msg.content}</div>`;
      } else {
        bubble.textContent = msg.content;
      }
      messagesEl.appendChild(bubble);
    });
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // ════════════════ 发送消息（真实 API 调用）═══════════════
  let abortCtrl = null;
  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    chatMessages.push({ role: 'user', content: text });
    inputEl.value = '';
    renderMessages();
    inputEl.disabled = true;
    sendBtn.disabled = true;

    const typingEl = createElement('div', { className: 'computational-bubble computational-bubble-ai computational-bubble-ai-dynamic' });
    typingEl.innerHTML = '<div class="computational-bubble-name">' + iconGear(14) + ' 计算社会科学助手</div><div class="computational-bubble-text">思考中...</div>';
    messagesEl.appendChild(typingEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    abortCtrl = new AbortController();
    let aiContent = '';

    agentApi.streamChat({
      agent_id: 'custom',
      session_id: sessionId,
      message: text,
      mode: modelMode,
    }, {
      onToken: (token) => {
        aiContent += token;
        typingEl.querySelector('.computational-bubble-text').textContent = aiContent;
        messagesEl.scrollTop = messagesEl.scrollHeight;
      },
      onDone: () => {
        chatMessages.push({ role: 'ai', content: aiContent });
        renderMessages();
        inputEl.disabled = false;
        sendBtn.disabled = false;
        inputEl.focus();
        // 尝试从 AI 回复中提取代码并更新编辑器
        const codeMatch = aiContent.match(/```python\n?([\s\S]*?)```/);
        if (codeMatch && codeEditor) {
          codeEditor.setValue(codeMatch[1].trim());
          showToast('代码已加载到编辑器，点击运行执行', 'info');
        }
      },
      onError: (err) => {
        chatMessages.push({ role: 'ai', content: '错误：' + (err.message || '请求失败') });
        renderMessages();
        inputEl.disabled = false;
        sendBtn.disabled = false;
        inputEl.focus();
      },
      signal: abortCtrl.signal,
    });
  }

  // ════════════════ 代码运行（真实后端执行）═══════════════
  function runCode() {
    const code = codeEditor ? codeEditor.getValue() : textarea.value;
    if (!code.trim()) {
      showToast('请先输入代码', 'warning');
      return;
    }

    execCount++;
    execVal.textContent = String(execCount);
    outputContent.innerHTML = '<div class="computational-output-running">' + iconClock(14) + ' 执行中...</div>';
    document.querySelector('.computational-exec-status').textContent = '运行中';

    computationalApi.runCode(code, 'python', 30)
      .then(res => {
        let output = '';
        if (res.stdout) output += res.stdout;
        if (res.stderr) output += '\n[stderr]\n' + res.stderr;
        if (!output) output = '（无输出）';
        output += '\n进程已结束，退出码 ' + (res.exit_code != null ? res.exit_code : '—');
        output += ' (' + (res.duration_ms != null ? res.duration_ms + 'ms' : '—') + ')';
        outputContent.innerHTML = '<div class="computational-output-stdout">' + output.replace(/\n/g, '<br>') + '</div><div class="computational-output-exit-0">✓ 执行完成</div>';
        document.querySelector('.computational-exec-status').textContent = '完成';
      })
      .catch(err => {
        if (err.status === 403 || (err.message && err.message.includes('admin'))) {
          outputContent.innerHTML = '<div class="computational-output-running" style="color:var(--color-warning)">代码执行功能需要管理员权限。请在设置中启用 CODE_EXECUTION_ENABLED 并配置权限。</div>';
        } else {
          outputContent.innerHTML = '<div class="computational-output-running" style="color:var(--color-danger)">执行失败：' + (err.message || '后端服务未就绪') + '</div>';
        }
        document.querySelector('.computational-exec-status').textContent = '就绪';
      });
  }

  runBtn.addEventListener('click', runCode);

  // Ctrl+Enter 运行
  editorContainer.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      runCode();
    }
  });

  // 清空输出
  clearBtn.addEventListener('click', () => {
    outputContent.innerHTML = '<div class="computational-output-placeholder">输出已清空</div>';
    document.querySelector('.computational-exec-status').textContent = '就绪';
  });

  // 加载示例
  exampleBtn.addEventListener('click', () => {
    if (codeEditor) {
      codeEditor.setValue(DEFAULT_CODE);
      showToast('已载入示例代码', 'success');
    }
  });

  // 安装包 — 调用真实后端 API
  pkgBtn.addEventListener('click', () => {
    computationalApi.listPackages()
      .then(res => {
        const pkgs = res.packages || [];
        outputContent.innerHTML = '<div class="computational-output-stdout">已安装的 Python 包：<br>' + (pkgs.length > 0 ? pkgs.map(p => '· ' + (p.name || p) + ' ' + (p.version || '')).join('<br>') : '（无法获取包列表 — 代码执行功能可能未启用）') + '</div>';
      })
      .catch(() => {
        outputContent.innerHTML = '<div class="computational-output-stdout" style="color:var(--color-warning)">包管理功能需要后端启用 CODE_EXECUTION_ENABLED。请在服务器配置中启用后重试。</div>';
      });
  });

  // ════════════════ 初始化 CodeMirror ════════════════
  setTimeout(() => {
    if (window.CodeMirror && textarea.parentNode) {
      codeEditor = window.CodeMirror.fromTextArea(textarea, {
        mode: 'python',
        theme: getCmTheme(),
        lineNumbers: true,
        matchBrackets: true,
        autoCloseBrackets: true,
        indentUnit: 4,
        tabSize: 4,
        lineWrapping: true,
      });
    }
  }, 100);

  // 监听主题变化，动态切换 CodeMirror 主题
  const unsubTheme = watch('settings', (newSettings) => {
    if (codeEditor && newSettings?.theme) {
      codeEditor.setOption('theme', getCmTheme());
    }
  });
  // 页面卸载时取消订阅
  page._unsubTheme = unsubTheme;

  return page;
}
