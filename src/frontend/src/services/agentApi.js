import { api } from './api.js';
export const agentApi = {
  chat: (message, agentId, sessionId, context) =>
    api.post('/api/v1/agent/chat', { message, agent_id: agentId, session_id: sessionId, context }),
  getConversation: (sessionId) =>
    api.get(`/api/v1/agent/conversation/${sessionId}`),
  clearConversation: (sessionId) =>
    api.delete(`/api/v1/agent/conversation/${sessionId}`),
  listAgents: () => api.get('/api/v1/agent/agents'),
};