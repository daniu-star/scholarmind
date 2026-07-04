import { api, ApiError } from './api.js';

// P0-2: SSE 流式对话 — 通过 fetch + ReadableStream 消费后端 /agent/stream 端点
// 事件类型: token, thought, options, done, error
async function streamChat(params, { onToken, onThought, onOptions, onDone, onError, signal }) {
  const baseUrl = (await import('../app/store.js')).state.settings?.apiBase
    || (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE)
    || '';
  const url = `${baseUrl}/api/v1/agent/stream`;
  const storedToken = localStorage.getItem('sm_token');
  let token = '';
  try { const t = JSON.parse(storedToken); token = t || storedToken || ''; } catch { token = storedToken || ''; }

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(params),
    signal,
  });

  if (!res.ok) {
    let errData;
    try { errData = await res.json(); } catch { errData = null; }
    throw new ApiError(res.status, errData?.detail || `请求失败 (${res.status})`, errData);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          switch (data.type) {
            case 'token': if (onToken) onToken(data.content || ''); break;
            case 'thought': if (onThought) onThought(data.content || ''); break;
            case 'options': if (onOptions) onOptions(data.options || []); break;
            case 'done':
              if (onDone) onDone({
                skills_used: data.skills_used || [],
                chart_info: data.chart_info || null,
                cnki_results: data.cnki_results || null,
                skill_hint: data.skill_hint || null,
              });
              break;
            case 'error': if (onError) onError(new Error(data.message || '未知错误')); break;
          }
        } catch {}
      }
    }
  }
}

export const agentApi = {
  // 支持两种调用方式：对象参数 {agent_id, session_id, message, context} 或 位置参数
  chat: (messageOrParams, agentId, sessionId, context) => {
    if (typeof messageOrParams === 'object') {
      return api.post('/api/v1/agent/chat', messageOrParams);
    }
    return api.post('/api/v1/agent/chat', {
      message: messageOrParams, agent_id: agentId, session_id: sessionId, context,
    });
  },
  // P0-2: SSE 流式对话
  streamChat,
  getConversation: (sessionId) =>
    api.get(`/api/v1/agent/conversation/${sessionId}`),
  getSessions: (agentId) =>
    api.get(`/api/v1/agent/sessions${agentId ? `?agent_id=${agentId}` : ''}`),
  clearConversation: (sessionId) =>
    api.delete(`/api/v1/agent/conversation/${sessionId}`),
  listAgents: () => api.get('/api/v1/agent/agents'),
  // P2-T3：获取指定学科的热门选题（4 学科各 15 个 Top 议题）
  getTopics: (disciplineId) =>
    api.get(`/api/v1/agent/topics/${disciplineId || 'humanities'}`),
  // P1-T6 补全：会话重命名与删除（对应后端 PATCH/DELETE /agent/sessions/{id})
  renameSession: (sessionId, title) =>
    api.patch(`/api/v1/agent/sessions/${sessionId}`, { title }),
  deleteSession: (sessionId) =>
    api.delete(`/api/v1/agent/sessions/${sessionId}`),
};