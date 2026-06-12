import { state } from '../app/store.js';

const getBaseUrl = () => state.settings.apiBase || 'http://localhost:8000';

class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.status = status;
    this.data = data;
    this.name = 'ApiError';
  }
}

async function request(method, path, body = null, options = {}) {
  const url = `${getBaseUrl()}${path}`;
  const headers = { ...options.headers };

  if (!(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(url, {
    method,
    headers,
    body: body instanceof FormData ? body : (body ? JSON.stringify(body) : null),
    signal: options.signal,
  });

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

export const api = {
  get: (path, opts) => request('GET', path, null, opts),
  post: (path, body, opts) => request('POST', path, body, opts),
  put: (path, body, opts) => request('PUT', path, body, opts),
  delete: (path, opts) => request('DELETE', path, null, opts),
  upload: (path, formData, opts) => request('POST', path, formData, opts),
};

export { ApiError };