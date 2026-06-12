import { api } from './api.js';
export const uploadApi = {
  upload: (files, sessionId) => {
    const fd = new FormData();
    Array.from(files).forEach(f => fd.append('files', f));
    return api.upload(`/api/v1/upload/${encodeURIComponent(sessionId)}`, fd);
  },
  list: (sessionId) => api.get(`/api/v1/upload/${sessionId}`),
  content: (sessionId, filename) => api.get(`/api/v1/upload/${sessionId}/${encodeURIComponent(filename)}/content`),
  delete: (sessionId, filename) => api.delete(`/api/v1/upload/${sessionId}/${encodeURIComponent(filename)}`),
};