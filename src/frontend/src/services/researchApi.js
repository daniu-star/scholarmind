// R1-T18 · 研究域 API 服务层（契约：docs/reports/R1_INTERFACE_SPEC.md §2.6）
// 约定：
// - JSON 请求一律复用 services/api.js 的 request（含 Bearer 注入、401 刷新、ApiError）。
// - SSE 必须用 fetch + ReadableStream：EventSource 不能带 Authorization 头。
// - 断线只结束本地流，不调用任何取消接口；服务端任务由任务状态机自行推进。
import { api, ApiError, NetworkError } from './api.js';
import { state } from '../app/store.js';

const RESEARCH = '/api/v1/research';
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9._:-]{8,128}$/;

// services/api.js 未导出内部 getBaseUrl，这里保持同样的优先级：
// 用户设置 > 构建期环境变量 > 相对路径（开发走 Vite 代理）。
function resolveBaseUrl() {
  if (state.settings?.apiBase) return state.settings.apiBase;
  // @ts-ignore — Vite 在构建时替换 import.meta.env.VITE_API_BASE
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  return '';
}

function readToken() {
  try {
    const token = localStorage.getItem('sm_token');
    return token ? token.trim() : '';
  } catch {
    return '';
  }
}

function authHeaders(extra = {}) {
  const token = readToken();
  return token ? { Authorization: `Bearer ${token}`, ...extra } : { ...extra };
}

function queryString(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
}

function assertIdempotencyKey(key) {
  if (!IDEMPOTENCY_PATTERN.test(String(key || ''))) {
    throw new Error('Idempotency-Key 必须为 8–128 位，且只含 A-Z a-z 0-9 . _ : -');
  }
  return String(key);
}

export function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // 兼容不支持 randomUUID 的浏览器（仍满足 8–128 位与字符集要求）
  const rand = () => Math.random().toString(36).slice(2, 12);
  return `sm-${Date.now().toString(36)}-${rand()}${rand()}`;
}

async function readErrorBody(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

function toApiError(res, data) {
  const message = data?.error?.message || data?.detail || `请求失败 (${res.status})`;
  return new ApiError(res.status, message, data);
}

// ── 能力与项目 ────────────────────────────────────────────────
export function getCapabilities() {
  return api.get(`${RESEARCH}/capabilities`);
}

export function listProjects(params = {}) {
  return api.get(`${RESEARCH}/projects${queryString(params)}`);
}

export function createProject(payload) {
  return api.post(`${RESEARCH}/projects`, payload);
}

export function getProject(projectId) {
  return api.get(`${RESEARCH}/projects/${encodeURIComponent(projectId)}`);
}

export function updateProject(projectId, payload) {
  return api.patch(`${RESEARCH}/projects/${encodeURIComponent(projectId)}`, payload);
}

// ── 文档 ──────────────────────────────────────────────────────
export function uploadDocument(projectId, file) {
  if (!(file instanceof Blob)) {
    throw new Error('uploadDocument 需要 File 或 Blob');
  }
  const form = new FormData();
  const filename = file.name || 'document.txt';
  form.append('file', file, filename);
  return api.upload(
    `${RESEARCH}/projects/${encodeURIComponent(projectId)}/documents`,
    form
  );
}

export function getDocument(documentId) {
  return api.get(`${RESEARCH}/documents/${encodeURIComponent(documentId)}`);
}

export function getDocumentBlocks(documentId, params = {}) {
  return api.get(
    `${RESEARCH}/documents/${encodeURIComponent(documentId)}/blocks${queryString(params)}`
  );
}

export function deleteDocument(documentId) {
  return api.delete(`${RESEARCH}/documents/${encodeURIComponent(documentId)}`);
}

export function searchSources(projectId, query, params = {}) {
  return api.post(
    `${RESEARCH}/projects/${encodeURIComponent(projectId)}/sources/search`,
    { query, ...params }
  );
}

// ── 任务 ──────────────────────────────────────────────────────
export function createTask(payload, idempotencyKey) {
  return api.post(`${RESEARCH}/tasks`, payload, {
    headers: { 'Idempotency-Key': assertIdempotencyKey(idempotencyKey) },
  });
}

export function getTask(taskId) {
  return api.get(`${RESEARCH}/tasks/${encodeURIComponent(taskId)}`);
}

export function cancelTask(taskId) {
  return api.post(`${RESEARCH}/tasks/${encodeURIComponent(taskId)}/cancel`, null);
}

export function resumeTask(taskId, payload, idempotencyKey) {
  const body = {
    expected_state_revision: payload?.expected_state_revision,
    answers: payload?.answers || {},
    supplemental_source_ids: payload?.supplemental_source_ids || [],
  };
  const options = idempotencyKey
    ? { headers: { 'Idempotency-Key': assertIdempotencyKey(idempotencyKey) } }
    : undefined;
  return api.post(`${RESEARCH}/tasks/${encodeURIComponent(taskId)}/resume`, body, options);
}

export function retryTask(taskId, expectedStateRevision) {
  const revision = typeof expectedStateRevision === 'number'
    ? expectedStateRevision
    : expectedStateRevision?.expected_state_revision;
  return api.post(`${RESEARCH}/tasks/${encodeURIComponent(taskId)}/retry`, {
    expected_state_revision: revision,
  });
}

export function getFindings(taskId, params = {}) {
  return api.get(
    `${RESEARCH}/tasks/${encodeURIComponent(taskId)}/findings${queryString(params)}`
  );
}

// 后端没有「逐条创建提案」路由（只有 revision-proposals/{id}/apply 与
// kind=revision 任务），因此保留签名但显式失败，避免页面误以为能创建。
export function createProposal() {
  return Promise.reject(
    new Error('后端未提供逐条提案创建接口；请创建 kind=revision 的任务生成修改建议。')
  );
}

// 读取提案（含逐条补丁的真实 id），用于逐条采纳。
export function getRevisionProposal(proposalId) {
  return api.get(`${RESEARCH}/revision-proposals/${encodeURIComponent(proposalId)}`);
}

export function applyProposal(proposalId, payload = {}) {
  return api.post(
    `${RESEARCH}/revision-proposals/${encodeURIComponent(proposalId)}/apply`,
    {
      expected_version_id: payload.expected_version_id,
      hunk_ids: Array.isArray(payload.hunk_ids) ? payload.hunk_ids : [],
    }
  );
}

// ── 成果与导出 ────────────────────────────────────────────────
export function getArtifact(artifactId) {
  return api.get(`${RESEARCH}/artifacts/${encodeURIComponent(artifactId)}`);
}

export function exportArtifact(payload) {
  return api.post(`${RESEARCH}/exports`, payload, {
    headers: { 'Idempotency-Key': newIdempotencyKey() },
  });
}

export function getExportUrl(artifactId) {
  return `${RESEARCH}/artifacts/${encodeURIComponent(artifactId)}/download`;
}

// T22：在已授权文档版本的数值表上出图；校验信息随成果返回，前端不自行算数。
export function createChart(payload) {
  return api.post(`${RESEARCH}/charts`, payload);
}

// 图表要放进 <img>，但不能把 Bearer token 拼进 URL；取回 blob 再转 object URL。
export function fetchArtifactBlob(artifactId) {
  return downloadWithAuth(artifactId, { save: false });
}

function filenameFromDisposition(header, fallback) {
  if (!header) return fallback;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      return fallback;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : fallback;
}

async function downloadWithAuth(artifactId, { save = true } = {}) {
  const url = `${resolveBaseUrl()}${getExportUrl(artifactId)}`;
  let res;
  try {
    res = await fetch(url, { headers: authHeaders({ Accept: '*/*' }) });
  } catch {
    throw new NetworkError('下载失败：无法连接后端。');
  }
  if (!res.ok) {
    throw toApiError(res, await readErrorBody(res));
  }
  const blob = await res.blob();
  const filename = filenameFromDisposition(
    res.headers.get('content-disposition'),
    `artifact-${artifactId}`
  );
  if (save) {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
  return { blob, filename };
}

// 供页面下载 md/docx/变更记录；浏览器带 Authorization 取回二进制。
export function downloadArtifact(artifactId) {
  return downloadWithAuth(artifactId, { save: true });
}

// 阅读 markdown 成果（如 revision_proposal）正文；不走浏览器下载。
export async function getArtifactText(artifactId) {
  const { blob } = await downloadWithAuth(artifactId, { save: false });
  return blob.text();
}

// ── SSE ──────────────────────────────────────────────────────
// 帧格式（后端 routers/research.py::_event_frame）：
//   id: <sequence>\nevent: <type>\ndata: <json>\n\n
// 续订只能二选一：after_sequence 查询参数或 Last-Event-ID 头；两者不一致后端 422。
function parseSseFrame(raw) {
  let id = null;
  let event = 'message';
  const dataLines = [];
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'id') id = value;
    else if (field === 'event') event = value;
    else if (field === 'data') dataLines.push(value);
  }
  if (!dataLines.length) return null;
  const text = dataLines.join('\n');
  let data = null;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text };
  }
  const sequence = id !== null && /^\d+$/.test(id) ? Number(id) : null;
  return { id: sequence, event, data };
}

// 返回 { aborted, lastSequence }；AbortError 视为正常收尾（离开页面只断本地流）。
export async function streamTaskEvents(taskId, options = {}) {
  const { onEvent, onOpen, onClose, signal, afterSequence, lastEventId } = options;
  if (
    afterSequence !== undefined && afterSequence !== null
    && lastEventId !== undefined && lastEventId !== null
    && String(afterSequence) !== String(lastEventId)
  ) {
    throw new Error('after_sequence 与 Last-Event-ID 只能二选一，且数值必须一致。');
  }

  const params = new URLSearchParams();
  if (lastEventId === undefined || lastEventId === null) {
    if (afterSequence !== undefined && afterSequence !== null) {
      params.set('after_sequence', String(afterSequence));
    }
  }
  const query = params.toString();
  const url = `${resolveBaseUrl()}${RESEARCH}/tasks/${encodeURIComponent(taskId)}/events${query ? `?${query}` : ''}`;

  const headers = authHeaders({ Accept: 'text/event-stream' });
  if (lastEventId !== undefined && lastEventId !== null) {
    headers['Last-Event-ID'] = String(lastEventId);
  }

  let res;
  try {
    res = await fetch(url, { headers, signal, cache: 'no-store' });
  } catch (err) {
    if (err?.name === 'AbortError') return { aborted: true, lastSequence: afterSequence ?? null };
    throw new NetworkError('事件流连接失败：请检查后端是否启动。');
  }

  if (!res.ok) {
    throw toApiError(res, await readErrorBody(res));
  }
  if (!res.body) {
    throw new Error('当前浏览器不支持读取事件流（ReadableStream 不可用）。');
  }

  let lastSequence = afterSequence !== undefined && afterSequence !== null
    ? Number(afterSequence)
    : null;
  if (onOpen) onOpen({ status: res.status });

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  const consume = (chunk) => {
    buffer += chunk.replace(/\r\n/g, '\n');
    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const rawFrame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const frame = parseSseFrame(rawFrame);
      if (frame) {
        if (frame.id !== null) lastSequence = frame.id;
        if (onEvent) onEvent(frame);
      }
      boundary = buffer.indexOf('\n\n');
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      consume(decoder.decode(value, { stream: true }));
    }
    consume(decoder.decode());
    const tail = parseSseFrame(buffer.trim());
    if (tail) {
      if (tail.id !== null) lastSequence = tail.id;
      if (onEvent) onEvent(tail);
    }
  } catch (err) {
    if (err?.name === 'AbortError') {
      return { aborted: true, lastSequence };
    }
    throw new NetworkError('事件流中断：连接被关闭。');
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* reader 已经释放 */
    }
  }

  if (onClose) onClose({ lastSequence });
  return { aborted: false, lastSequence };
}
