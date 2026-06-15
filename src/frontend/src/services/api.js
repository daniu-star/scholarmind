import { state } from '../app/store.js';

// 开发环境使用相对路径走 Vite 代理，用户可通过 settings.apiBase 覆盖
const getBaseUrl = () => state.settings.apiBase || '';

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

async function request(method, path, body = null, options = {}) {
  const url = `${getBaseUrl()}${path}`;
  const headers = { ...options.headers };

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
    if (err instanceof TypeError) {
      throw new NetworkError();
    }
    throw err;
  }

  if (!res.ok) {
    let errData;
    try { errData = await res.json(); } catch { errData = null; }
    throw new ApiError(
      res.status,
      errData?.error?.message || errData?.detail || `请求失败 (${res.status})`,
      errData
    );
  }

  const ct = res.headers.get('content-type');
  if (ct && (ct.includes('image/png') || ct.includes('image/jpeg'))) {
    const blob = await res.blob();
    return { blob, url: URL.createObjectURL(blob) };
  }

  return res.json();
}

async function healthCheck() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3000);

  try {
    const res = await fetch(`${getBaseUrl()}/api/v1/health`, {
      method: 'GET',
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return res.ok;
  } catch {
    clearTimeout(timeout);
    throw new NetworkError();
  }
}

export const api = {
  get: (path, opts) => request('GET', path, null, opts),
  post: (path, body, opts) => request('POST', path, body, opts),
  put: (path, body, opts) => request('PUT', path, body, opts),
  delete: (path, opts) => request('DELETE', path, null, opts),
  upload: (path, formData, opts) => request('POST', path, formData, opts),
};

export { ApiError, NetworkError, healthCheck };