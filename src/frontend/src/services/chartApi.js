import { api } from './api.js';
export const chartApi = {
  generate: (chartType, data, title = '', xLabel = '', yLabel = '') =>
    api.post('/api/v1/chart/generate', { chart_type: chartType, data, title, x_label: xLabel, y_label: yLabel }),
  getTypes: () => api.get('/api/v1/chart/types'),
  getChart: (chartId) => api.get(`/api/v1/chart/${chartId}`),
};