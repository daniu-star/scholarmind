import { state } from '../app/store.js';

// 优先级：用户设置 > 环境变量（生产构建时注入）> 相对路径（开发走 Vite 代理）
const getBaseUrl = () => {
  if (state.settings.apiBase) return state.settings.apiBase;
  // @ts-ignore — Vite 在构建时替换 import.meta.env.VITE_API_BASE
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  return '';
};

class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.status = status;
    this.data = data;
    this.name = 'ApiError';
  }
}

class NetworkError extends Error {
  constructor(message = '网络连接失败，请检查后端是否启动') {
    super(message);
    this.name = 'NetworkError';
  }
}

// P0-3: 全局错误事件总线 — 页面可订阅以显示统一错误 UI
const errorListeners = [];
function onGlobalError(fn) { errorListeners.push(fn); return () => { const i = errorListeners.indexOf(fn); if (i >= 0) errorListeners.splice(i, 1); }; }
function emitGlobalError(error) { errorListeners.forEach(fn => { try { fn(error); } catch {} }); }

// ── Token 刷新状态机 ──
let _isRefreshing = false;
let _refreshPromise = null;

async function _tryRefreshToken() {
  const refreshToken = localStorage.getItem('sm_refresh_token');
  if (!refreshToken) return false;

  if (_isRefreshing) {
    // 已有刷新进行中，等待其结果
    try { await _refreshPromise; } catch { /* ignore */ }
    return !!localStorage.getItem('sm_token');
  }

  _isRefreshing = true;
  _refreshPromise = (async () => {
    try {
      const base = getBaseUrl();
      const res = await fetch(`${base}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) throw new Error('refresh failed');
      const data = await res.json();
      localStorage.setItem('sm_token', data.access_token);
      localStorage.setItem('sm_refresh_token', data.refresh_token);
      if (data.user) localStorage.setItem('sm_user', JSON.stringify(data.user));
      // 同步到 store
      if (state.auth) {
        state.auth.token = data.access_token;
        state.auth.user = data.user || null;
        state.auth.isAuthenticated = true;
      }
      return true;
    } catch {
      localStorage.removeItem('sm_token');
      localStorage.removeItem('sm_refresh_token');
      localStorage.removeItem('sm_user');
      return false;
    } finally {
      _isRefreshing = false;
      _refreshPromise = null;
    }
  })();

  try { return await _refreshPromise; } catch { return false; }
}

async function request(method, path, body = null, options = {}) {
  const url = `${getBaseUrl()}${path}`;
  const headers = { ...options.headers };
  const storedToken = localStorage.getItem('sm_token');
  if (storedToken && !headers.Authorization) {
    headers.Authorization = `Bearer ${storedToken}`;
  }

  if (!(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body instanceof FormData ? body : (body ? JSON.stringify(body) : null),
      signal: options.signal,
    });
  } catch (err) {
    const netErr = new NetworkError();
    emitGlobalError(netErr);
    if (err instanceof TypeError) throw netErr;
    throw err;
  }

  if (!res.ok) {
    let errData;
    try { errData = await res.json(); } catch { errData = null; }

    // C3: 401 时先尝试自动刷新 Token，而非直接踢出
    if (res.status === 401 && path !== '/api/v1/auth/refresh') {
      const refreshed = await _tryRefreshToken();
      if (refreshed) {
        // 刷新成功：用新 token 重试原请求
        const newToken = localStorage.getItem('sm_token');
        if (newToken) headers.Authorization = `Bearer ${newToken}`;
        try {
          const retryRes = await fetch(url, {
            method,
            headers,
            body: body instanceof FormData ? body : (body ? JSON.stringify(body) : null),
            signal: options.signal,
          });
          if (retryRes.ok) {
            const ct = retryRes.headers.get('content-type');
            if (ct && (ct.includes('image/png') || ct.includes('image/jpeg'))) {
              const blob = await retryRes.blob();
              return { blob, url: URL.createObjectURL(blob) };
            }
            return retryRes.json();
          }
          // 重试仍然失败，记录新的错误
          try { errData = await retryRes.json(); } catch { errData = null; }
          res = retryRes;
        } catch { /* 网络错误，继续使用原始 401 错误 */ }
      }
    }

    if (res.status === 401) {
      localStorage.removeItem('sm_token');
      localStorage.removeItem('sm_refresh_token');
      localStorage.removeItem('sm_user');
      emitGlobalError(new ApiError(401, '登录已过期，请重新登录'));
    }
    const apiErr = new ApiError(
      res.status,
      errData?.error?.message || errData?.detail || `请求失败 (${res.status})`,
      errData
    );
    emitGlobalError(apiErr);
    throw apiErr;
  }

  const ct = res.headers.get('content-type');
  if (ct && (ct.includes('image/png') || ct.includes('image/jpeg'))) {
    const blob = await res.blob();
    return { blob, url: URL.createObjectURL(blob) };
  }

  return res.json();
}

async function healthCheck() {
  // 重试机制：最多 3 次，间隔 1s
  for (let attempt = 1; attempt <= 3; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const res = await fetch(`${getBaseUrl()}/api/v1/health`, {
        method: 'GET',
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (res.ok) return true;
      if (attempt < 3) await new Promise(r => setTimeout(r, 1000));
    } catch {
      clearTimeout(timeout);
      if (attempt < 3) await new Promise(r => setTimeout(r, 1000));
      else throw new NetworkError();
    }
  }
  return false;
}

export const api = {
  get: (path, opts) => request('GET', path, null, opts),
  post: (path, body, opts) => request('POST', path, body, opts),
  put: (path, body, opts) => request('PUT', path, body, opts),
  patch: (path, body, opts) => request('PATCH', path, body, opts),
  delete: (path, opts) => request('DELETE', path, null, opts),
  upload: (path, formData, opts) => request('POST', path, formData, opts),
};

export { ApiError, NetworkError, healthCheck, onGlobalError };
