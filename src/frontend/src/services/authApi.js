import { api } from './api.js';

export const authApi = {
  login: (phone, password) =>
    api.post('/api/v1/auth/login', { phone, password }),
  loginWithCode: (target, code) =>
    api.post('/api/v1/auth/login', { phone: target, username: target, code }),
  register: (phone, password, nickname) =>
    api.post('/api/v1/auth/register', {
      phone,
      password,
      nickname: nickname || undefined,
    }),
  registerWithCode: (target, code, nickname) =>
    api.post('/api/v1/auth/register', {
      phone: target, username: target, code,
      nickname: nickname || undefined,
    }),
  sendCode: (target, purpose = 'login') =>
    api.post('/api/v1/auth/send-code', { target, purpose }),
  me: () => api.get('/api/v1/auth/me'),
  refresh: (refreshToken) =>
    api.post('/api/v1/auth/refresh', { refresh_token: refreshToken }),
};
