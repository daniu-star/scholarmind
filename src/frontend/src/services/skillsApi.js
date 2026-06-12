import { api } from './api.js';
export const skillsApi = {
  list: () => api.get('/api/v1/skills'),
  get: (id) => api.get(`/api/v1/skills/${id}`),
  create: (data) => api.post('/api/v1/skills', data),
  update: (id, data) => api.put(`/api/v1/skills/${id}`, data),
  delete: (id) => api.delete(`/api/v1/skills/${id}`),
  toggle: (id, enabled) => api.post(`/api/v1/skills/${id}/toggle`, { enabled }),
  upload: (file) => { const fd = new FormData(); fd.append('file', file); return api.upload('/api/v1/skills/upload', fd); },
  template: () => api.get('/api/v1/skills/template'),
};