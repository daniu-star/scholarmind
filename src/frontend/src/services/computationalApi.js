import { api } from './api.js';

export const computationalApi = {
  runCode: (code, language = 'python', timeout = 30) =>
    api.post('/api/v1/code-execution/run', { code, language, timeout }),
  listPackages: () =>
    api.get('/api/v1/code-execution/packages'),
};
