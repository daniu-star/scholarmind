import { api } from './api.js';
export const cnkiApi = {
  search: (query, yearFilter = '', count = 20) =>
    api.post('/api/v1/knowledge/cnki/search', { query, year_filter: yearFilter, count }),
  status: () => api.get('/api/v1/knowledge/status'),
  config: (cfg) => api.post('/api/v1/knowledge/cnki/config', cfg),
};