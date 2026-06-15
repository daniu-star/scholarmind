import { api } from './api.js';
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
  getConversation: (sessionId) =>
    api.get(`/api/v1/agent/conversation/${sessionId}`),
  clearConversation: (sessionId) =>
    api.delete(`/api/v1/agent/conversation/${sessionId}`),
  listAgents: () => api.get('/api/v1/agent/agents'),
};