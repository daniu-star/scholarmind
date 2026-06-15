import { createElement } from '../utils/dom.js';
import { state } from '../app/store.js';
import { navigateTo } from '../app/router.js';
import { agentApi } from '../services/agentApi.js';
import { NetworkError } from '../services/api.js';
import { AGENT_META } from '../utils/constants.js';

const agentMeta = AGENT_META;

const defaultMeta = {
  name: '学术助手',
  role: '智能学术研究助手',
  suggestions: [
    { icon: '💬', title: '自由对话', desc: '直接提出你的研究问题或需求' },
    { icon: '📄', title: '文档分析', desc: '上传或粘贴研究文档，我会帮你分析' },
    { icon: '🔍', title: '知识查询', desc: '询问任何学术相关的知识或方法' },
  ],
  placeholder: '输入任何问题，开始对话...',
};

export function AgentPage({ agentId } = {}) {
  const meta = agentMeta[agentId] || defaultMeta;
  const page = createElement('div', { className: 'page active' });

  // ========== HEADER ==========
  const header = createElement('div', { className: 'chat-welcome-area', style: 'padding-bottom:8px;' });
  const headerRow = createElement('div', { style: 'display:flex;align-items:center;justify-content:space-between;max-width:680px;margin:0 auto;' });
  const backBtn = createElement('button', {
    className: 'btn-back',
    style: 'font-size:0.8rem;',
  }, '← 返回');
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
  headerRow.appendChild(createElement('div', { style: 'flex:1;' }));
  const title = createElement('h2', {
    className: 'chat-welcome-title',
    style: 'font-family:var(--font-serif);font-size:1.3rem;margin:0;',
  }, meta.name);
  headerRow.appendChild(title);
  headerRow.appendChild(createElement('div', { style: 'flex:1;' }));
  header.appendChild(headerRow);
  // 角色描述副标题，始终可见
  const subtitle = createElement('p', {
    className: 'chat-header-subtitle',
    style: 'font-size:0.78rem;color:var(--text-tertiary);text-align:center;margin:2px 0 0 0;',
  }, meta.role);
  header.appendChild(subtitle);
  page.appendChild(header);

  // ========== WELCOME AREA (hidden if messages exist) ==========
  const sessionMsgs = state.messages[agentId] || [];
  const hasMessages = sessionMsgs.length > 0;

  let welcomeArea = null;
  if (!hasMessages) {
    welcomeArea = createElement('div', { className: 'chat-welcome-area' });
    const roleLine = createElement('p', { className: 'chat-welcome-role' }, meta.role);
    welcomeArea.appendChild(roleLine);

    const cards = createElement('div', { className: 'prompt-cards' });
    meta.suggestions.forEach(s => {
      const card = createElement('div', { className: 'prompt-card' });
      card.innerHTML =
        `<div class="prompt-card-icon">${s.icon}</div>` +
        `<div class="prompt-card-title">${s.title}</div>` +
        `<div class="prompt-card-desc">${s.desc}</div>`;
      card.addEventListener('click', () => {
        input.value = s.desc;
        input.focus();
        // 自动选中第一个占位符 [xxx]，方便用户直接输入替换
        const match = /\[([^\]]+)\]/.exec(s.desc);
        if (match) {
          const idx = s.desc.indexOf(match[0]);
          input.setSelectionRange(idx, idx + match[0].length);
        }
      });
      cards.appendChild(card);
    });
    welcomeArea.appendChild(cards);

    const hint = createElement('p', { className: 'chat-welcome-hint' }, '👆 点击上方卡片快速开始，或直接输入你的问题');
    welcomeArea.appendChild(hint);
    page.appendChild(welcomeArea);
  }

  // ========== MESSAGES CONTAINER ==========
  const messagesContainer = createElement('div', {
    className: 'chat-messages',
    id: 'chat-messages',
    style: 'flex:1;overflow-y:auto;padding:12px 24px;max-height:calc(100vh - 200px);' + (hasMessages ? '' : 'display:none;'),
  });
  page.appendChild(messagesContainer);

  // ========== EMPTY STATE (shown when no messages and no welcome) ==========
  if (hasMessages && sessionMsgs.length === 0) {
    const emptyState = createElement('div', { style: 'text-align:center;padding:40px 20px;color:var(--text-tertiary);' },
      createElement('p', { style: 'font-size:0.9rem;' }, '暂无消息，开始对话吧'),
    );
    page.appendChild(emptyState);
  }

  // ========== INPUT AREA ==========
  const inputArea = createElement('div', {
    className: 'chat-input-area',
    style: 'display:flex;gap:8px;padding:12px 24px;border-top:1px solid var(--border);',
  });

  const input = createElement('input', {
    type: 'text',
    className: 'chat-input',
    placeholder: meta.placeholder,
    'aria-label': '输入消息',
  });

  const sendBtn = createElement('button', {
    className: 'chat-send-btn',
    'aria-label': '发送消息',
    style: 'border:none;cursor:pointer;',
  }, '➤');

  inputArea.appendChild(input);
  inputArea.appendChild(sendBtn);
  page.appendChild(inputArea);

  // ========== HELPERS ==========
  let firstMessageSent = false;

  function hideWelcome() {
    if (welcomeArea && welcomeArea.parentNode) {
      welcomeArea.remove();
      welcomeArea = null;
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function addMessage(role, content) {
    const bubble = createElement('div', {
      className: `chat-bubble chat-bubble-${role === 'user' ? 'user' : 'ai'}`,
    });
    bubble.innerHTML = escapeHtml(content);
    messagesContainer.appendChild(bubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function addError(content) {
    const err = createElement('div', {
      className: 'chat-bubble chat-bubble-ai',
      style: 'border-left-color:var(--accent-red);background:rgba(248,81,73,0.06);',
    });
    err.innerHTML = content;
    messagesContainer.appendChild(err);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // ========== RESTORE HISTORY ==========
  sessionMsgs.forEach(m => addMessage(m.role, m.content));

  // ========== SEND ==========
  async function sendMessage() {
    const text = input.value.trim();
    if (!text) {
      input.style.animation = 'shake 0.4s ease';
      setTimeout(() => { input.style.animation = ''; }, 400);
      return;
    }

    input.value = '';
    input.disabled = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '...';

    if (!firstMessageSent) {
      firstMessageSent = true;
      hideWelcome();
    }

    addMessage('user', text);

    // Show typing indicator
    const skills = detectSkill(text);
    const typingEl = createElement('div', { className: 'typing-indicator' },
      createElement('div', { className: 'typing-dot' }),
      createElement('div', { className: 'typing-dot' }),
      createElement('div', { className: 'typing-dot' }),
      createElement('span', { className: 'typing-text' }, '思考中...'),
    );
    if (skills.length > 0) {
      const skillTags = createElement('div', { className: 'typing-skill-tags' });
      skills.forEach(s => {
        skillTags.appendChild(createElement('span', { className: 'skill-tag' }, s));
      });
      typingEl.appendChild(skillTags);
    }
    messagesContainer.appendChild(typingEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    if (!state.currentSessionId) {
      state.currentSessionId = crypto.randomUUID();
    }

    if (!state.messages[agentId]) state.messages[agentId] = [];
    state.messages[agentId].push({ role: 'user', content: text });

    try {
      const res = await agentApi.chat({
        agent_id: agentId,
        session_id: state.currentSessionId,
        message: text,
      });

      // Remove typing indicator
      if (typingEl && typingEl.parentNode) {
        typingEl.remove();
      }

      const reply = res.reply || res.message || '（无回复）';
      addMessage('assistant', reply);
      state.messages[agentId].push({ role: 'assistant', content: reply });

      if (res.options && res.options.length > 0) {
        const opts = createElement('div', { className: 'chat-options' });
        res.options.forEach(opt => {
          const btn = createElement('button', { className: 'chat-option-btn' }, opt);
          btn.addEventListener('click', () => {
            input.value = opt;
            sendMessage();
          });
          opts.appendChild(btn);
        });
        messagesContainer.appendChild(opts);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      }
    } catch (e) {
      // Remove typing indicator on error
      if (typingEl && typingEl.parentNode) {
        typingEl.remove();
      }
      let errorHtml = '';
      if (e instanceof NetworkError) {
        errorHtml = '后端服务未启动，请在终端执行 <code style="background:rgba(0,0,0,0.2);padding:2px 8px;border-radius:4px;font-size:0.82rem;">cd src/backend &amp;&amp; uvicorn app:app --reload</code>';
      } else if (e.name === 'ApiError' && e.message) {
        errorHtml = e.message;
      } else {
        errorHtml = e.message || '请求失败，请检查后端是否启动';
      }
      addError(errorHtml);
      console.error('Chat error:', e);
    } finally {
      sendBtn.textContent = '➤';
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  // ========== EVENTS ==========
  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') sendMessage();
  });

  setTimeout(() => input.focus(), 100);

  return page;
}