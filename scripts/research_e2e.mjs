#!/usr/bin/env node
/**
 * ScholarMind 研究域端到端验收（Playbook T20 / R2_INTERFACE_SPEC §5）
 *
 * 默认模式（浏览器验收）：
 *   1. 依赖检查：import('playwright') 失败 → 打印安装命令并 exit 3（不伪造通过）
 *   2. 用 python -m uvicorn 起隔离后端（临时 sqlite + RESEARCH_MODEL_STUB=true）
 *   3. 用 dist/ 起 Node 静态服务，并把 /api、/ws 代理到后端（同源，前端走相对路径）
 *   4. API 注册/登录 → 建项目 → 上传 Markdown → 浏览器真实注册/登出/登录
 *      → 打开 #research → 断言工作区/能力/项目/文档/SSE/诊断/导出下载/图表
 *
 * 浏览器可执行文件解析顺序（任一成功即用，失败信息会列出全部尝试）：
 *   1) Playwright 自带 chromium（npx playwright install chromium）
 *   2) 环境变量 E2E_CHROMIUM_EXECUTABLE 指向的 chrome.exe
 *   3) 本机 ms-playwright 缓存里已安装的最新 chromium/chromium_headless_shell
 *
 * 其他模式：
 *   --api-only   只跑 API 全链路（不驱动浏览器；不能算浏览器验收通过）
 *   --serve-only 只起后端 + 静态服务并做自检（GET / 、能力 401/200），不驱动浏览器
 *   --duration=N 配合 --serve-only：自检后保持服务 N 秒再退出（默认保持到 Ctrl+C）
 *   --keep       失败/结束时保留临时目录（默认清理）
 *
 * 退出码：
 *   0 通过；1 断言失败；2 环境/依赖缺失；3 Playwright 未安装
 */
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DIST = path.join(ROOT, 'dist');
const TMP_ROOT = path.join(ROOT, 'tmp');
// 截图证据单独存放（不随 --keep 的临时运行目录一起删除）
const EVIDENCE_DIR = path.join(TMP_ROOT, 'e2e-evidence');
const PLAYWRIGHT_HINT = 'npm i -D playwright && npx playwright install chromium';

const EXIT_PASS = 0;
const EXIT_FAIL = 1;
const EXIT_ENV = 2;
const EXIT_PLAYWRIGHT = 3;

const PASSWORD = 'E2e!Passw0rd-2026';
const OBJECTIVE = '检查论证、方法与证据链是否成立，并核对结果表述。';
const DOC_FILENAME = 'e2e-paper.md';

// 含全部必备章节（引言/方法/结论/参考文献）+ 标题 + 段落 + 一张管道表，
// 保证替身模型 0 model findings 时结构完整性检查也不产出 finding，
// 从而复现契约里的 “no findings + notes，报告仍需出现”。
const DOC_MARKDOWN = `# 数字化时代的学术写作：证据链与方法透明度

## 引言

近年来，学术写作的可复核性受到持续关注。本文以一个内容分析案例说明证据链如何被记录与核对。

## 方法

本研究采用内容分析方法，对 128 篇样本文献的编码过程进行记录，编码一致性由两名编码员独立复核。

| 变量 | 均值 | 标准差 |
| --- | --- | --- |
| 样本量 | 128 | 0.00 |
| 编码一致性 | 0.82 | 0.04 |
| 复核覆盖率 | 0.95 | 0.02 |

分年度统计如下（全数值表，供图表能力按显式列映射出图）：

| 年份 | 样本量 | 编码一致性 |
| --- | --- | --- |
| 2021 | 120 | 0.79 |
| 2022 | 128 | 0.82 |
| 2023 | 136 | 0.84 |

## 结论

结果显示编码一致性较高，但复核覆盖率仍有提升空间。结论仅适用于本研究的样本范围。

## 参考文献

[1] 张三. 学术写作中的证据链研究[J]. 新闻与传播研究, 2024, 31(2): 45-60.

[2] 李四. 内容分析方法手册[M]. 北京: 科学出版社, 2023.
`;

let stageNo = 0;
const log = (msg) => console.log(`[e2e] ${msg}`);
const logStage = (msg) => console.log(`[e2e] [${++stageNo}] ${msg}`);
const logDetail = (msg) => console.log(`[e2e]     ${msg}`);

class E2eError extends Error {
  constructor(message, details) {
    super(message);
    this.name = 'E2eError';
    this.details = details;
  }
}

class EnvError extends E2eError {
  constructor(message, details) {
    super(message, details);
    this.name = 'EnvError';
  }
}

class PlaywrightMissingError extends Error {}

function assert(condition, message, details) {
  if (!condition) throw new E2eError(message, details);
}

function parseArgs(argv) {
  const opts = { mode: 'browser', keep: false, duration: 0, help: false, a11y: false };
  for (const arg of argv) {
    if (arg === '--serve-only') opts.mode = 'serve-only';
    else if (arg === '--api-only') opts.mode = 'api-only';
    else if (arg === '--keep') opts.keep = true;
    else if (arg === '--a11y') opts.a11y = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else if (arg.startsWith('--duration=')) {
      const value = Number(arg.slice('--duration='.length));
      if (!Number.isFinite(value) || value < 0) throw new E2eError(`--duration 需要非负秒数：${arg}`);
      opts.duration = value;
    } else {
      throw new E2eError(`未知参数：${arg}（用 --help 查看用法）`);
    }
  }
  return opts;
}

function printHelp() {
  console.log(`ScholarMind 研究域 e2e（Playbook T20 / R2 §5）

用法：
  node scripts/research_e2e.mjs                 # 浏览器验收（需要 playwright）
  node scripts/research_e2e.mjs --api-only      # 只跑 API 全链路（不驱动浏览器）
  node scripts/research_e2e.mjs --serve-only    # 只起隔离后端 + 静态服务并自检
  node scripts/research_e2e.mjs --serve-only --duration=30
  node scripts/research_e2e.mjs --keep          # 保留临时目录
  node scripts/research_e2e.mjs --a11y          # 追加 390px 窄屏 / 键盘可达 / 双账号隔离验收

前提：
  - npm run build:frontend 已生成 dist/（模块化产物，非原型 HTML）
  - python 可导入 fastapi/uvicorn/sqlalchemy/alembic（优先用 .venv/Scripts/python.exe）
  - 浏览器模式需要：${PLAYWRIGHT_HINT}

退出码：0 通过 / 1 断言失败 / 2 环境或依赖缺失 / 3 Playwright 未安装
`);
}

// ── 基础工具 ─────────────────────────────────────────────────────────

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

function resolvePython() {
  const candidates = [];
  if (process.env.E2E_PYTHON) candidates.push(process.env.E2E_PYTHON);
  candidates.push(
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(ROOT, '.venv', 'bin', 'python'),
    'python'
  );
  for (const candidate of candidates) {
    if (candidate === 'python') return candidate;
    if (fs.existsSync(candidate)) return candidate;
  }
  return 'python';
}

function checkPythonDeps(python) {
  const check = spawnSync(
    python,
    ['-c', 'import fastapi, uvicorn, sqlalchemy, alembic, aiosqlite; print("ok")'],
    { encoding: 'utf8', timeout: 60000 }
  );
  if (check.status !== 0) {
    const detail = (check.stderr || check.stdout || check.error?.message || '').trim();
    throw new EnvError(
      `python 依赖不完整（${python}）。请在仓库 venv 中安装后端依赖后重试。`,
      detail.split('\n').slice(-6).join('\n')
    );
  }
}

function tailFile(filePath, lines = 20) {
  try {
    const text = fs.readFileSync(filePath, 'utf8');
    return text.trimEnd().split(/\r?\n/).slice(-lines).join('\n');
  } catch {
    return '';
  }
}

// ── 隔离后端 ─────────────────────────────────────────────────────────

function createRunDirs() {
  fs.mkdirSync(TMP_ROOT, { recursive: true });
  const runRoot = fs.mkdtempSync(path.join(TMP_ROOT, 'e2e-run-'));
  const dirs = {
    root: runRoot,
    uploads: path.join(runRoot, 'uploads'),
    charts: path.join(runRoot, 'charts'),
    conversations: path.join(runRoot, 'conversations'),
    chroma: path.join(runRoot, 'chroma'),
    skills: path.join(runRoot, 'skills'),
    legacyDb: path.join(runRoot, 'legacy.db'),
    db: path.join(runRoot, 'e2e.db'),
    backendLog: path.join(runRoot, 'backend.log'),
  };
  fs.mkdirSync(dirs.root, { recursive: true });
  return dirs;
}

function backendEnv(dirs) {
  const sqliteUrl = 'sqlite+aiosqlite:///' + dirs.db.replace(/\\/g, '/');
  return {
    // 隔离数据库与文件目录：绝不碰开发 data/ 或生产库
    DATABASE_URL: sqliteUrl,
    DB_PATH: dirs.legacyDb,
    UPLOAD_DIR: dirs.uploads,
    CHARTS_DIR: dirs.charts,
    CONVERSATIONS_DIR: dirs.conversations,
    CHROMA_DIR: dirs.chroma,
    SKILLS_DIR: dirs.skills,
    // 替身模型 + 测试环境
    RESEARCH_MODEL_STUB: 'true',
    ENVIRONMENT: 'test',
    ENABLE_VERIFIED_CHARTS: 'true',
    // 关闭向量预热：torch/sentence-transformers 首次加载会饿死事件循环，
    // 导致 /api/v1/health 在 90s 内不可达（曾把 E2E 误判为环境缺失）。
    DISABLE_VECTOR_PREWARM: 'true',
    // 让 model.llm 稳定为 degraded（通过前端诊断 gate），又绝不发外网请求
    DEEPSEEK_API_KEY: 'sk-e2e-local-probe',
    DEEPSEEK_BASE_URL: 'http://127.0.0.1:1',
    HF_HUB_OFFLINE: '1',
    TRANSFORMERS_OFFLINE: '1',
    // 不连开发 Redis（.env 里可能指向 localhost 开发实例）
    REDIS_URL: 'redis://127.0.0.1:1/0',
    PYTHONUNBUFFERED: '1',
    PYTHONIOENCODING: 'utf-8',
    MPLBACKEND: 'Agg',
  };
}

function startBackend(port, dirs) {
  const python = resolvePython();
  const fd = fs.openSync(dirs.backendLog, 'w');
  const child = spawn(
    python,
    [
      '-m', 'uvicorn', 'src.backend.app:create_app', '--factory',
      '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning',
    ],
    { cwd: ROOT, env: { ...process.env, ...backendEnv(dirs) }, stdio: ['ignore', fd, fd], windowsHide: true }
  );
  child.on('error', () => {
    /* 由 waitForHealth 统一报错，避免未处理事件 */
  });
  // 父进程必须释放自己的句柄，否则 Windows 上临时目录（backend.log）无法删除
  try {
    fs.closeSync(fd);
  } catch {
    /* 忽略 */
  }
  return child;
}

// 健康检查超时可用 E2E_HEALTH_TIMEOUT_MS 覆盖：本机后台 Python 进程较多时，
// 后端从 startup complete 到可服务可能超过 90s（非应用缺陷，已用 DISABLE_VECTOR_PREWARM 缓解）。
async function waitForHealth(backendBase, child, dirs, timeoutMs = Number(process.env.E2E_HEALTH_TIMEOUT_MS || 180000)) {
  if (child.pid === undefined) {
    throw new EnvError('后端进程无法启动（python 可执行文件不存在或不可执行）', tailFile(dirs.backendLog, 10));
  }
  const deadline = Date.now() + timeoutMs;
  let lastError = '';
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new EnvError(
        `后端进程提前退出（exit ${child.exitCode}）`,
        tailFile(dirs.backendLog, 25)
      );
    }
    try {
      const res = await fetch(`${backendBase}/api/v1/health`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return;
      lastError = `HTTP ${res.status}`;
    } catch (err) {
      lastError = err?.message || String(err);
    }
    await sleep(700);
  }
  throw new EnvError(`后端健康检查超时（${timeoutMs}ms，最后错误：${lastError}）`, tailFile(dirs.backendLog, 25));
}

// ── 静态服务 + 同源代理 ──────────────────────────────────────────────

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.otf': 'font/otf',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
};

function serveStatic(req, res) {
  const url = new URL(req.url, 'http://localhost');
  let rel;
  try {
    rel = decodeURIComponent(url.pathname);
  } catch {
    res.writeHead(400).end('bad request');
    return;
  }
  const filePath = path.resolve(DIST, '.' + rel);
  if (!filePath.startsWith(DIST)) {
    res.writeHead(403).end('forbidden');
    return;
  }
  let target = filePath;
  if (!fs.existsSync(target) || fs.statSync(target).isDirectory()) {
    // SPA fallback：#research 等哈希路由都由 index.html 承载
    const fallback = path.join(DIST, 'index.html');
    if (fs.existsSync(fallback)) target = fallback;
  }
  if (!fs.existsSync(target)) {
    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' }).end('not found');
    return;
  }
  const stat = fs.statSync(target);
  res.writeHead(200, {
    'content-type': MIME[path.extname(target).toLowerCase()] || 'application/octet-stream',
    'content-length': stat.size,
    'cache-control': 'no-store',
  });
  fs.createReadStream(target).pipe(res);
}

function proxyHttp(req, res, backendPort) {
  const proxyReq = http.request(
    {
      host: '127.0.0.1',
      port: backendPort,
      path: req.url,
      method: req.method,
      headers: {
        ...req.headers,
        host: `127.0.0.1:${backendPort}`,
        // 关掉压缩，保证 SSE 事件流不被缓冲
        'accept-encoding': 'identity',
      },
    },
    (proxyRes) => {
      const headers = { ...proxyRes.headers };
      delete headers.connection;
      delete headers['transfer-encoding'];
      delete headers['keep-alive'];
      res.writeHead(proxyRes.statusCode || 502, headers);
      proxyRes.pipe(res);
    }
  );
  proxyReq.on('error', () => {
    if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('backend unavailable');
  });
  req.pipe(proxyReq);
}

function proxyUpgrade(req, socket, head, backendPort) {
  const upstream = net.connect(backendPort, '127.0.0.1', () => {
    const lines = [`${req.method} ${req.url} HTTP/1.1`];
    for (const [key, value] of Object.entries(req.headers)) {
      const text = Array.isArray(value) ? value.join(', ') : value;
      lines.push(`${key}: ${key === 'host' ? `127.0.0.1:${backendPort}` : text}`);
    }
    lines.push('', '');
    upstream.write(lines.join('\r\n'));
    if (head?.length) upstream.write(head);
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
}

function startWebServer(backendPort, port = 0) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (req.url.startsWith('/api') || req.url.startsWith('/ws')) {
        proxyHttp(req, res, backendPort);
      } else {
        serveStatic(req, res);
      }
    });
    server.on('upgrade', (req, socket, head) => {
      if (req.url.startsWith('/ws')) proxyUpgrade(req, socket, head, backendPort);
      else socket.destroy();
    });
    server.on('error', reject);
    server.listen(port, '127.0.0.1', () => {
      const actualPort = server.address().port;
      resolve({ server, port: actualPort, base: `http://127.0.0.1:${actualPort}` });
    });
  });
}

// ── API 封装 ─────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function callApi(backendBase, pathname, { method = 'GET', token, json, form, headers = {}, timeoutMs = 60000 } = {}) {
  const requestHeaders = { ...headers };
  if (token) requestHeaders.authorization = `Bearer ${token}`;
  let body;
  if (json !== undefined) {
    requestHeaders['content-type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  const res = await fetch(`${backendBase}${pathname}`, {
    method,
    headers: requestHeaders,
    body,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  return { status: res.status, ok: res.ok, data, text, headers: res.headers };
}

function apiErrorDetail(response) {
  const err = response.data?.error;
  return err ? `${err.code ?? 'ERROR'}: ${err.message ?? ''}` : (response.text || '').slice(0, 400);
}

function expectOk(response, label) {
  if (!response.ok) {
    throw new E2eError(`${label} 失败（HTTP ${response.status}）`, apiErrorDetail(response));
  }
  return response.data;
}

function grantReviewEntitlement(dirs, userId) {
  const script = [
    'import sqlite3, sys, time',
    'db, uid = sys.argv[1], int(sys.argv[2])',
    'deadline = time.time() + 15',
    'while True:',
    '    try:',
    '        con = sqlite3.connect(db, timeout=5)',
    '        exp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 30 * 86400))',
    '        cur = con.execute("UPDATE user_quotas SET external_review_expires_at=? WHERE user_id=?", (exp, uid))',
    '        con.commit(); con.close()',
    '        print(cur.rowcount)',
    '        break',
    '    except Exception as exc:',
    '        if time.time() > deadline: raise',
    '        time.sleep(0.4)',
  ].join('\n');
  const run = spawnSync(resolvePython(), ['-c', script, dirs.db, String(userId)], { encoding: 'utf8', timeout: 30000 });
  if (run.status !== 0) {
    throw new E2eError('写入 review 权益夹具失败', (run.stderr || run.stdout || '').trim().slice(-400));
  }
  return Number((run.stdout || '').trim());
}

// ── API 全链路 ───────────────────────────────────────────────────────

async function runApiChain(backendBase, dirs) {
  const runId = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
  const email = `e2e-${runId}-${Math.random().toString(16).slice(2, 8)}@example.com`;

  logStage('API：注册 + 登录');
  const registered = expectOk(
    await callApi(backendBase, '/api/v1/auth/register', {
      method: 'POST',
      json: {
        email,
        password: PASSWORD,
        nickname: 'e2e',
        device_fingerprint: 'e2e-playwright-fp',
        device_name: 'playwright',
        trust_device: true,
      },
    }),
    '注册'
  );
  const login = expectOk(
    await callApi(backendBase, '/api/v1/auth/login', { method: 'POST', json: { email, password: PASSWORD } }),
    '登录'
  );
  const token = login.access_token;
  assert(typeof token === 'string' && token.length > 20, '登录未返回 access_token');
  assert(login.user?.id != null, '登录未返回 user.id');
  const userId = login.user.id;
  logDetail(`用户 ${email}（id=${userId}）登录成功，entitlements=${JSON.stringify(login.entitlements ?? {})}`);

  logStage('API：读取能力清单（登录前 free 计划应为 unauthorized）');
  const capsBefore = expectOk(await callApi(backendBase, '/api/v1/research/capabilities', { token }), '读取能力');
  const capsMap = new Map((capsBefore.capabilities || []).map((cap) => [cap.name, cap]));
  const reviewBefore = capsMap.get('task.review');
  logDetail(`task.review=${reviewBefore?.status ?? 'missing'}，model.llm=${capsMap.get('model.llm')?.status ?? 'missing'}`);
  assert(reviewBefore, '能力清单缺少 task.review');

  logStage('API：写入 review 权益夹具（隔离 DB，不改后端代码）');
  const rows = grantReviewEntitlement(dirs, userId);
  assert(rows === 1, `权益夹具应更新 1 行，实际 ${rows} 行（user_quotas 行可能尚未创建）`);
  const caps = expectOk(await callApi(backendBase, '/api/v1/research/capabilities', { token }), '重新读取能力');
  const byName = new Map((caps.capabilities || []).map((cap) => [cap.name, cap.status]));
  const reviewStatus = byName.get('task.review');
  assert(['ready', 'degraded'].includes(reviewStatus), `task.review 仍不可用（${reviewStatus}），诊断按钮会被前端禁用`);
  assert(['ready', 'degraded'].includes(byName.get('task.engine')), `task.engine=${byName.get('task.engine')}，无法执行任务`);
  assert(byName.get('model.llm') !== 'disabled', `model.llm=${byName.get('model.llm')}，诊断 gate 不通过`);
  const unavailable = [...byName.entries()].filter(([, status]) => !['ready', 'degraded'].includes(status));
  logDetail(`能力：task.review=${reviewStatus}，model.llm=${byName.get('model.llm')}，不可用项=${unavailable.map(([name]) => name).join(',') || '无'}`);

  logStage('API：创建项目');
  const project = expectOk(
    await callApi(backendBase, '/api/v1/research/projects', { method: 'POST', token, json: { title: `e2e 浏览器验收 ${runId}` } }),
    '创建项目'
  );
  assert(project.id?.startsWith('rproj_'), `项目 id 异常：${project.id}`);

  logStage('API：上传 Markdown 文档（标题/段落/管道表）');
  const form = new FormData();
  form.append('file', new Blob([DOC_MARKDOWN], { type: 'text/markdown' }), DOC_FILENAME);
  const uploaded = expectOk(
    await callApi(backendBase, `/api/v1/research/projects/${project.id}/documents`, { method: 'POST', token, form }),
    '上传文档'
  );
  assert(uploaded.document?.filename === DOC_FILENAME, `上传文件名不符：${uploaded.document?.filename}`);
  assert(uploaded.version?.parse_status === 'complete', `解析状态非 complete：${uploaded.version?.parse_status}`);
  logDetail(`文档 ${uploaded.document.id}，版本 ${uploaded.version.id}，${uploaded.version.codepoints} codepoints，parse_status=complete`);

  logStage('API：创建 review 诊断任务并等待终态');
  const key = `e2e-${runId}-${Math.random().toString(16).slice(2, 8)}`;
  const taskResponse = await callApi(backendBase, '/api/v1/research/tasks', {
      method: 'POST',
      token,
      headers: { 'idempotency-key': key },
      json: {
        schema_version: '1.0',
        project_id: project.id,
        kind: 'review',
        objective: OBJECTIVE,
        input: { document_version_id: uploaded.version.id, source_ids: [] },
        scope: { section_ids: [], dimensions: ['argument', 'method', 'evidence', 'expression', 'format'], finding_ids: [] },
        constraints: {
          protected_block_ids: [],
          preserve: ['numbers', 'dates', 'names', 'direct_quotes', 'citations'],
          journal_style: 'generic',
          no_new_empirical_claims: true,
        },
        mode: 'flash',
        skill_ids: [],
      },
    });
  const taskCreated = expectOk(taskResponse, '创建诊断任务');
  assert(taskResponse.status === 202, `创建诊断任务应 202，实际 ${taskResponse.status}`);
  const taskId = taskCreated.task_id;
  assert(taskId, '创建任务未返回 task_id');
  logDetail(`任务 ${taskId} 已入队（status=${taskCreated.status}）`);

  const terminal = new Set(['succeeded', 'failed', 'partial', 'cancelled']);
  const deadline = Date.now() + 120000;
  let snapshot = null;
  while (Date.now() < deadline) {
    snapshot = expectOk(await callApi(backendBase, `/api/v1/research/tasks/${taskId}`, { token }), '读取任务');
    if (terminal.has(snapshot.status)) break;
    await sleep(800);
  }
  assert(snapshot && terminal.has(snapshot.status), `任务未在 120s 内到达终态（当前 ${snapshot?.status}）`);
  logDetail(`任务终态 status=${snapshot.status}，quality_verdict=${snapshot.quality_verdict}，attempt_no=${snapshot.attempt_no}`);
  assert(snapshot.status === 'succeeded', `诊断任务失败：${apiErrorDetail({ data: { error: snapshot.error } })}`);

  logStage('API：读取诊断项');
  const findings = expectOk(
    await callApi(backendBase, `/api/v1/research/tasks/${taskId}/findings?limit=100`, { token }),
    '读取诊断项'
  );
  const findingItems = Array.isArray(findings.items) ? findings.items : [];
  logDetail(`findings=${findingItems.length}，next_cursor=${findings.next_cursor ?? 'null'}`);
  assert(findingItems.length === 0, `替身模型 + 完整章节文档应无 finding，实际 ${findingItems.length} 项`);

  logStage('API：导出 Markdown 并校验下载非空');
  const exportResponse = await callApi(backendBase, '/api/v1/research/exports', {
      method: 'POST',
      token,
      headers: { 'idempotency-key': `export-${runId}-${Math.random().toString(16).slice(2, 8)}` },
      json: {
        project_id: project.id,
        document_version_id: uploaded.version.id,
        format: 'md',
        journal_style: 'generic',
        include_report: true,
        include_change_log: false,
      },
    });
  const exported = expectOk(exportResponse, '导出');
  assert(exportResponse.status === 201, `导出应 201，实际 ${exportResponse.status}`);
  assert(exported.size_bytes > 0, `导出报告为空：${JSON.stringify(exported)}`);
  const downloadUrl = exported.download_url || `/api/v1/research/artifacts/${exported.id}/download`;
  const downloadRes = await fetch(`${backendBase}${downloadUrl}`, {
    headers: { authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(60000),
  });
  assert(downloadRes.status === 200, `下载导出成果失败（HTTP ${downloadRes.status}）`);
  const downloaded = Buffer.from(await downloadRes.arrayBuffer());
  assert(downloaded.length > 0, '下载的导出文件为空');
  const downloadedText = downloaded.toString('utf8').trimStart();
  // 导出器会去掉 Markdown 标题的 # 前缀（实测首行是标题正文），所以按正文标题校验
  assert(downloadedText.includes('数字化时代的学术写作'), '导出 Markdown 未包含文档标题正文');
  assert(!/<html/i.test(downloadedText.slice(0, 200)), '导出内容疑似 HTML 错误页');
  logDetail(`下载内容首行：${downloadedText.split(/\r?\n/)[0].slice(0, 60)}`);
  logDetail(`导出 ${exported.id}：${exported.filename}，${exported.size_bytes} B，校验=${exported.validation?.status ?? 'n/a'}`);

  logStage('API：生成验证图表（scatter_density）并校验 PNG 下载');
  const chartResponse = await callApi(backendBase, '/api/v1/research/charts', {
    method: 'POST',
    token,
    headers: { 'idempotency-key': `chart-${runId}-${Math.random().toString(16).slice(2, 8)}` },
    json: {
      project_id: project.id,
      document_version_id: uploaded.version.id,
      chart_type: 'scatter_density',
      x_column: '样本量',
      y_columns: ['编码一致性'],
      title: 'e2e 分年度编码一致性',
      table_index: 1,
    },
  });
  let chart;
  if (chartResponse.status === 503 && apiErrorDetail(chartResponse).includes('CHART_CAPABILITY_DISABLED')) {
    // 后端契约：能力关闭是 503 CHART_CAPABILITY_DISABLED（不是 422），此处按“显式关闭”记录
    logDetail('图表能力显式关闭（503 CHART_CAPABILITY_DISABLED），记录为能力关闭而非失败');
    chart = { capability: 'disabled', status: 503, code: 'CHART_CAPABILITY_DISABLED' };
  } else {
    const chartBody = expectOk(chartResponse, '生成图表');
    assert(chartResponse.status === 201, `生成图表应 201，实际 ${chartResponse.status}`);
    assert(chartBody.id, `图表响应缺少 id：${JSON.stringify(chartBody).slice(0, 200)}`);
    assert(
      String(chartBody.mime || '').includes('png') || String(chartBody.filename || '').endsWith('.png'),
      `图表产物不是 PNG：mime=${chartBody.mime} filename=${chartBody.filename}`
    );
    const chartUrl = chartBody.download_url || `/api/v1/research/artifacts/${chartBody.id}/download`;
    const chartDownload = await fetch(`${backendBase}${chartUrl}`, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(60000),
    });
    assert(chartDownload.status === 200, `下载图表失败（HTTP ${chartDownload.status}）`);
    const png = Buffer.from(await chartDownload.arrayBuffer());
    assert(png.length > 100, `图表 PNG 过小：${png.length} B`);
    const pngMagic = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    assert(png.subarray(0, 8).equals(pngMagic), `图表下载不是 PNG（前 8 字节：${png.subarray(0, 8).toString('hex')}）`);
    const chartPath = path.join(dirs.root, 'api-chart.png');
    fs.writeFileSync(chartPath, png);
    logDetail(`图表 ${chartBody.id}：${chartBody.filename}，${png.length} B，PNG 签名通过，已保存 ${chartPath}`);
    chart = {
      capability: 'enabled',
      status: 201,
      id: chartBody.id,
      bytes: png.length,
      filename: chartBody.filename,
      path: chartPath,
    };
  }

  return {
    email,
    userId,
    token,
    refreshToken: login.refresh_token,
    user: login.user,
    entitlements: login.entitlements,
    project,
    document: uploaded.document,
    version: uploaded.version,
    taskId,
    task: snapshot,
    findingsCount: findingItems.length,
    exportResult: exported,
    exportBytes: downloaded.length,
    chart,
  };
}

// ── 浏览器验收 ───────────────────────────────────────────────────────

async function loadPlaywright() {
  let playwright;
  try {
    playwright = await import('playwright');
  } catch {
    throw new PlaywrightMissingError('未安装 playwright');
  }
  if (typeof playwright.chromium?.launch !== 'function') {
    throw new PlaywrightMissingError('playwright 包存在但没有 chromium 导出');
  }
  return playwright;
}

async function waitUntil(fn, { timeout = 15000, interval = 250, label = '条件' } = {}) {
  const deadline = Date.now() + timeout;
  let lastError = '';
  while (Date.now() < deadline) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (err) {
      lastError = err?.message || String(err);
    }
    await sleep(interval);
  }
  throw new E2eError(`等待超时（${label}，${timeout}ms）`, lastError);
}

async function capture(page, name) {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
  const file = path.join(EVIDENCE_DIR, `${stamp}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  logDetail(`截图：${file}`);
  return file;
}

// 本机已安装的 Chromium（Playwright 自带浏览器版本不匹配时的兜底，不联网）
function chromiumExecutableCandidates() {
  const roots = [
    process.env.PLAYWRIGHT_BROWSERS_PATH,
    process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'ms-playwright') : '',
    process.env.HOME ? path.join(process.env.HOME, '.cache', 'ms-playwright') : '',
  ].filter(Boolean);
  const found = new Map();
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    let names = [];
    try {
      names = fs.readdirSync(root);
    } catch {
      continue;
    }
    for (const name of names) {
      const revision = Number((name.match(/-(\d+)$/) || [])[1]);
      if (!Number.isFinite(revision)) continue;
      const executables = [];
      if (name.startsWith('chromium_headless_shell-')) {
        executables.push(
          path.join(root, name, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe'),
          path.join(root, name, 'chrome-headless-shell-linux64', 'chrome-headless-shell')
        );
      } else if (name.startsWith('chromium-')) {
        executables.push(
          path.join(root, name, 'chrome-win64', 'chrome.exe'),
          path.join(root, name, 'chrome-win', 'chrome.exe'),
          path.join(root, name, 'chrome-linux', 'chrome')
        );
      }
      for (const exe of executables) {
        if (fs.existsSync(exe)) found.set(exe, { exe, revision, name });
      }
    }
  }
  return [...found.values()].sort((a, b) => b.revision - a.revision);
}

async function launchChromium(playwright) {
  const attempts = [];
  const tryLaunch = async (options, label) => {
    try {
      const browser = await playwright.chromium.launch({ headless: true, timeout: 45000, ...options });
      return { browser, label };
    } catch (err) {
      attempts.push(`${label}：${(err.message || String(err)).split('\n')[0]}`);
      return null;
    }
  };

  const builtin = await tryLaunch({}, 'Playwright 自带 chromium');
  if (builtin) return builtin;

  const envExe = process.env.E2E_CHROMIUM_EXECUTABLE;
  if (envExe) {
    if (!fs.existsSync(envExe)) {
      attempts.push(`E2E_CHROMIUM_EXECUTABLE：文件不存在 ${envExe}`);
    } else {
      const viaEnv = await tryLaunch({ executablePath: envExe }, `E2E_CHROMIUM_EXECUTABLE=${envExe}`);
      if (viaEnv) return viaEnv;
    }
  }

  // 只试最新 3 个，避免每个陈旧浏览器都等一次 45s 超时
  for (const candidate of chromiumExecutableCandidates().slice(0, 3)) {
    const launched = await tryLaunch({ executablePath: candidate.exe }, `已安装 ${candidate.name}（${candidate.exe}）`);
    if (launched) return launched;
  }

  throw new PlaywrightMissingError(
    `Chromium 无法启动（已尝试 ${attempts.length} 个可执行文件）：\n- ${attempts.join('\n- ')}\n` +
      `修复：${PLAYWRIGHT_HINT}\n或设置 E2E_CHROMIUM_EXECUTABLE 指向本机 chrome.exe`
  );
}

async function dismissOnboarding(page) {
  // 首次进入时 App 会在 500ms 后插入引导遮罩，会拦截所有点击；用真实 UI「跳过引导」关闭。
  const skip = page.locator('.onboarding-skip-btn');
  try {
    await skip.waitFor({ state: 'visible', timeout: 5000 });
    await skip.click({ timeout: 5000 });
    logDetail('关闭首次引导遮罩（点击「跳过引导」）');
  } catch {
    logDetail('未出现首次引导遮罩（或本地已记录跳过）');
  }
}

async function openPasswordAuth(page) {
  const toggle = page.getByText('+ 使用密码登录', { exact: true }).first();
  await toggle.waitFor({ timeout: 15000 });
  await toggle.click();
  const password = page.locator('input[placeholder="设置密码（至少 6 位）"]');
  await password.waitFor({ state: 'visible', timeout: 15000 });
  return password;
}

async function submitAuthAndWaitForToken(page, label) {
  await page.locator('form.auth-form .auth-submit').first().click();
  try {
    // 注意：store.js 登出时会把 localStorage 写成字符串 "null"，必须排除，否则登录还没完成就误判成功
    await page.waitForFunction(
      () => {
        const token = localStorage.getItem('sm_token');
        return Boolean(token) && token !== 'null' && token !== 'undefined';
      },
      null,
      { timeout: 30000 }
    );
  } catch {
    const errors = (await page.locator('.auth-error').allTextContents()).map((text) => text.trim()).filter(Boolean);
    throw new E2eError(`浏览器${label}失败：${errors.join(' | ') || '30s 内未写入 sm_token'}`, `url=${page.url()}`);
  }
  return JSON.parse(await page.evaluate(() => localStorage.getItem('sm_user')));
}

async function runBrowserFlow(playwright, webBase, apiContext, dirs) {
  logStage('浏览器：启动 Chromium（真实 UI 注册/登出/登录）');
  const launched = await launchChromium(playwright);
  const browser = launched.browser;
  logDetail(`浏览器可执行文件：${launched.label}`);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    acceptDownloads: true,
    locale: 'zh-CN',
  });
  const consoleErrors = [];
  const streamResets = [];
  const failedRequests = [];
  const page = await context.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(`console: ${msg.text()}`);
  });
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText || '';
    failedRequests.push(`${failure} ${request.method()} ${request.url()}`);
    if (request.url().includes('/events') && /RESET|ABORTED/i.test(failure)) {
      streamResets.push(`${failure} ${request.url()}`);
    }
  });

  const screenshots = [];
  const takeShot = async (name) => {
    const file = await capture(page, name);
    screenshots.push(file);
    return file;
  };

  try {
    // ── 真实 UI 注册（不使用 token 注入）────────────────────────────
    logStage('浏览器：真实 UI 注册新账号');
    const browserEmail = `browser-${Date.now()}-${Math.random().toString(16).slice(2, 6)}@example.com`;
    await page.goto(`${webBase}/#auth`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const authTitle = page.locator('#authTitle');
    await authTitle.waitFor({ timeout: 20000 });
    await dismissOnboarding(page);
    assert((await authTitle.textContent()).includes('登录'), `登录页标题异常：${await authTitle.textContent()}`);
    await page.locator('.auth-switch-link').first().click();
    await waitUntil(async () => (await authTitle.textContent()).includes('注册'), { label: '切换到注册模式', timeout: 10000 });

    await page.locator('input[placeholder="您的邮箱地址"]').fill(browserEmail);
    const registerPassword = await openPasswordAuth(page);
    await registerPassword.fill(PASSWORD);
    const nickname = page.locator('input[placeholder="昵称（可选）"]');
    if (await nickname.isVisible()) await nickname.fill('e2e-browser');
    const registeredUser = await submitAuthAndWaitForToken(page, '注册');
    // 后端返回的用户对象不暴露 email（phone 为 null），用 id + 昵称 + token 证明注册会话成立
    assert(registeredUser?.id != null, `注册后 sm_user 缺少 id：${JSON.stringify(registeredUser)}`);
    assert(registeredUser?.nickname === 'e2e-browser', `注册后 sm_user 昵称不符：${JSON.stringify(registeredUser)}`);
    await waitUntil(async () => (await page.evaluate(() => location.hash)) === '#homepage', {
      label: '注册后跳转 #homepage',
      timeout: 15000,
    });
    logDetail(`注册成功：${browserEmail}（id=${registeredUser.id}），已跳转 #homepage`);
    await takeShot('01-register-home');

    // ── 登出：清 token，刷新后回到未登录导航 ────────────────────────
    logStage('浏览器：刷新后断言登录态可见，再执行登出');
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
    const logoutBtn = page.locator('button[aria-label="退出登录"]');
    await logoutBtn.waitFor({ timeout: 20000 });
    logDetail('刷新后 TopNav 显示退出登录按钮（localStorage 登录态生效）');
    await takeShot('02-auth-persisted');
    await logoutBtn.click();
    const afterLogout = await page.evaluate(() => ({
      token: localStorage.getItem('sm_token'),
      user: localStorage.getItem('sm_user'),
      refreshToken: localStorage.getItem('sm_refresh_token'),
    }));
    // store.js 的 auth watcher 会把 null 序列化成字符串 "null" 写回，因此两种都算已清除
    const cleared = (value) => value === null || value === 'null';
    assert(cleared(afterLogout.token), `登出后 sm_token 未清除：${String(afterLogout.token)}`);
    assert(cleared(afterLogout.user), `登出后 sm_user 未清除：${String(afterLogout.user)}`);
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.locator('button[aria-label="登录"]').waitFor({ timeout: 20000 });
    logDetail('登出后刷新：TopNav 回到未登录态（登录/注册按钮可见）');
    await takeShot('03-logout');

    // ── 真实 UI 登录（API 主账号，后续工作区使用该账号数据）─────────
    logStage('浏览器：真实 UI 登录 API 主账号');
    await page.goto(`${webBase}/#auth`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.locator('#authTitle').waitFor({ timeout: 20000 });
    await page.locator('input[placeholder="您的邮箱地址"]').fill(apiContext.email);
    const loginPassword = await openPasswordAuth(page);
    await loginPassword.fill(PASSWORD);
    const loggedInUser = await submitAuthAndWaitForToken(page, '登录');
    assert(
      String(loggedInUser?.id) === String(apiContext.userId),
      `登录后 sm_user.id=${loggedInUser?.id} 与 API 用户 ${apiContext.userId} 不一致`
    );
    await waitUntil(async () => (await page.evaluate(() => location.hash)) === '#homepage', {
      label: '登录后跳转 #homepage',
      timeout: 15000,
    });
    logDetail(`登录成功：${apiContext.email}（id=${loggedInUser.id}）`);
    await takeShot('04-login-home');

    // 刷新后以 localStorage 会话进入研究工作区（等价于真实用户下次打开）
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.locator('button[aria-label="退出登录"]').waitFor({ timeout: 20000 });

    logStage('浏览器：打开 #research 工作区');
    await page.goto(`${webBase}/#research`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('h1.rw-title', { timeout: 25000 });

    const title = (await page.locator('h1.rw-title').first().textContent())?.trim();
    assert(title === '研究工作区', `工作区标题异常：${title}`);
    const headerText = (await page.locator('.rw-header-right').first().textContent()) || '';
    assert(!headerText.includes('能力状态未知'), '能力状态未知（capabilities 读取失败）');
    assert(!headerText.includes('能力清单未上报'), '能力清单未上报（后端返回空能力列表）');
    assert(/能力就绪|项能力不可用/.test(headerText), `能力状态 pill 未渲染：${headerText.slice(0, 120)}`);
    logDetail(`头部 pill：${headerText.replace(/\s+/g, ' ').trim().slice(0, 160)}`);

    logStage('浏览器：断言能力面板与项目列表');
    const capPanel = page.locator('section[aria-label="研究域能力状态"]');
    await capPanel.waitFor({ timeout: 15000 });
    const capRows = await capPanel.locator('.rw-cap-row').count();
    assert(capRows >= 5, `能力面板行数异常：${capRows}`);
    assert((await capPanel.textContent()).includes('能力状态'), '能力面板标题缺失');

    const projects = page.locator('section[aria-label="研究项目列表"]');
    await projects.waitFor({ timeout: 15000 });
    const projectButton = projects.locator('button.rw-list-item').filter({ hasText: apiContext.project.title }).first();
    await projectButton.waitFor({ timeout: 15000 });
    logDetail(`项目「${apiContext.project.title}」已出现在列表`);

    logStage('浏览器：选择项目并断言上传文档可见');
    await projectButton.click();
    const docs = page.locator('section[aria-label="文档上传与选择"]');
    const docButton = docs.locator('button.rw-list-item').filter({ hasText: DOC_FILENAME }).first();
    await docButton.waitFor({ timeout: 20000 });
    await docButton.click();
    const docsText = (await docs.textContent()) || '';
    assert(docsText.includes(DOC_FILENAME), '文档列表未显示上传的 Markdown 文件');
    assert((await page.locator('.rw-header-right').textContent()).includes(`项目：`), '头部未显示当前项目');
    logDetail(`文档 ${DOC_FILENAME} 可见并已选中`);

    logStage('浏览器：填写诊断目标并启动 review 任务');
    const objective = page.locator('textarea[aria-label="诊断目标"]');
    await objective.waitFor({ timeout: 15000 });
    await objective.fill(OBJECTIVE);
    const startBtn = page.getByRole('button', { name: '开始全文诊断' }).first();
    await waitUntil(async () => (await startBtn.isEnabled()), { label: '开始全文诊断按钮可用', timeout: 20000 });
    await startBtn.click();

    logStage('浏览器：断言 SSE 事件流真实到达（started/终态/序号）');
    const stream = page.locator('section[aria-label="任务状态与事件流"]');
    await stream.waitFor({ timeout: 20000 });
    await waitUntil(async () => (await stream.locator('ol[aria-label="任务事件日志"] li.rw-log-row').count()) >= 3, {
      label: 'SSE 事件日志至少 3 条',
      timeout: 90000,
    });
    const streamText = (await stream.textContent()) || '';
    const seqMatch = streamText.match(/最后事件序号：(\d+)/);
    assert(seqMatch && Number(seqMatch[1]) > 0, `SSE 最后事件序号无效：${seqMatch?.[1] ?? '未显示'}`);
    const eventTypes = await stream.locator('ol[aria-label="任务事件日志"] .rw-log-type').allTextContents();
    assert(eventTypes.includes('task.started'), `SSE 事件缺少 task.started：${eventTypes.join(',')}`);
    assert(
      eventTypes.includes('task.completed') || eventTypes.includes('task.partial'),
      `SSE 事件缺少终态（task.completed/task.partial）：${eventTypes.join(',')}`
    );
    const lampText = (await stream.locator('.rw-lamp-text').first().textContent())?.trim();
    assert(lampText !== '连接异常', 'SSE 连接异常（事件流报错）');
    logDetail(
      `SSE：${eventTypes.length} 条事件（${eventTypes.slice(0, 6).join(', ')}），最后序号=${seqMatch[1]}，状态灯=${lampText}`
    );
    await takeShot('05-sse-events');

    logStage('浏览器：等待诊断结论与覆盖范围出现（替身模型，0 findings）');
    const report = page.locator('section[aria-label="诊断结论"]');
    await report.waitFor({ timeout: 20000 });
    await waitUntil(async () => {
      const text = (await report.textContent()) || '';
      return text.includes('问题与依据（') && text.includes('已完成');
    }, { label: '诊断报告终态', timeout: 180000 });
    const reportText = (await report.textContent()) || '';
    assert(!reportText.includes('诊断项读取失败'), '诊断项读取失败（findings 接口报错）', reportText.slice(0, 300));
    assert(reportText.includes('问题与依据（0）'), `报告未显示 0 项诊断：${reportText.replace(/\s+/g, ' ').slice(0, 300)}`);
    assert(
      reportText.includes('没有可展示的问题') || reportText.includes('暂无诊断项'),
      '报告缺少 0 findings 的空态说明',
    );
    logDetail(`诊断报告：${reportText.replace(/\s+/g, ' ').trim().slice(0, 200)}`);
    await takeShot('06-report');

    logStage('浏览器：导出 Markdown 并验证下载非空');
    await page.locator('select[aria-label="导出格式"]').selectOption('md');
    const includeReport = page.locator('label', { hasText: '附带诊断报告' }).locator('input[type="checkbox"]').first();
    if (!(await includeReport.isChecked())) await includeReport.check();
    const exportBtn = page.getByRole('button', { name: '生成导出成果' }).first();
    await waitUntil(async () => (await exportBtn.isEnabled()), { label: '导出按钮可用', timeout: 20000 });
    await exportBtn.click();
    await waitUntil(async () => ((await page.locator('body').textContent()) || '').includes('导出成果'), {
      label: '导出成果出现',
      timeout: 60000,
    });
    const downloadPromise = page.waitForEvent('download', { timeout: 60000 });
    await page.getByRole('button', { name: '下载文件' }).first().click();
    const download = await downloadPromise;
    const downloadPath = path.join(dirs.root, 'browser-download.md');
    await download.saveAs(downloadPath);
    const bytes = fs.readFileSync(downloadPath);
    assert(bytes.length > 0, '浏览器下载的导出文件为空');
    const head = bytes.toString('utf8').trimStart();
    assert(head.includes('数字化时代的学术写作'), '浏览器下载的 Markdown 未包含文档标题正文');
    assert((download.suggestedFilename() || '').endsWith('.md'), `下载文件名异常：${download.suggestedFilename()}`);
    logDetail(`浏览器下载：${download.suggestedFilename()}，${bytes.length} B，首行「${head.split(/\r?\n/)[0].slice(0, 60)}」`);
    await takeShot('07-export-downloaded');

    logStage('浏览器：图表前端面板（数值表识别 → 生成 → 图片与校验信息）');
    const chartPanel = page.locator('section.rw-chart-panel').first();
    await chartPanel.waitFor({ timeout: 30000 });
    const chartPanelText = (await chartPanel.textContent()) || '';
    assert(chartPanelText.includes('真实数据图表'), '图表面板标题缺失');
    assert(
      !chartPanelText.includes('图表能力当前不可用'),
      '图表能力不可用，无法验收前端面板（应显式关闭或被 gate 拦住）',
    );
    await waitUntil(async () => ((await chartPanel.textContent()) || '').includes('识别到'), {
      label: '图表面板识别表格',
      timeout: 30000,
    });
    const tablePill = (await chartPanel.locator('.rw-pill').first().textContent()) || '';
    assert(/识别到 \d+ 张表/.test(tablePill), `图表面板未识别到表格：${tablePill.trim()}`);
    // 生成按钮的 aria-label 取 title（「按当前列生成 PNG 图表」），不能按可见文本匹配。
    const chartButton = chartPanel.locator('.rw-card-actions button.rw-btn').first();
    await chartButton.waitFor({ timeout: 20000 });
    await waitUntil(async () => (await chartButton.isEnabled()), { label: '生成图表按钮可用', timeout: 20000 });
    await chartButton.click();
    await sleep(2000);
    logDetail(`图表面板文本：${((await chartPanel.textContent()) || '').replace(/\s+/g, ' ').trim().slice(0, 400)}`);
    const chartImg = chartPanel.locator('img.rw-chart-image').first();
    await chartImg.waitFor({ timeout: 120000 });
    const chartSrc = (await chartImg.getAttribute('src')) || '';
    assert(chartSrc.startsWith('blob:'), `图表图片 src 不是本地 objectURL：${chartSrc.slice(0, 60)}`);
    const natural = await chartImg.evaluate((el) => ({ w: el.naturalWidth, h: el.naturalHeight }));
    assert(natural.w > 100 && natural.h > 100, `图表图片未真正解码：${natural.w}x${natural.h}`);
    const chartResultText = (await chartPanel.locator('.rw-chart-result').first().textContent()) || '';
    assert(chartResultText.includes('重开校验通过'), '图表校验信息缺少「重开校验通过」（render_verified）');
    assert(chartResultText.includes('PNG 摘要'), '图表校验信息缺少「PNG 摘要」（png_sha256）');
    assert(chartResultText.includes('值域'), '图表校验信息缺少「值域」（value_ranges）');
    const chartShot = await takeShot('08-chart-panel');
    logDetail(
      `图表前端：${tablePill.trim()}，图片 ${natural.w}x${natural.h}，校验信息含 重开校验通过/PNG 摘要/值域（${chartShot}）`
    );

    logStage('浏览器：检查控制台错误（外链 CDN 离线 / SSE 终态断流不算失败）');
    const externalErrors = consoleErrors.filter((item) => /jsdelivr|favicon/i.test(item));
    const withoutExternal = consoleErrors.filter((item) => !/jsdelivr|favicon/i.test(item));
    // SSE 在任务终态后由前端 abort（任务已经结束，服务端连接被关闭），Chrome 会把这类关闭记为
    // net::ERR_CONNECTION_RESET。只有确实存在 /events 连接级失败时才把它归为预期噪音。
    const sseResetErrors = streamResets.length
      ? withoutExternal.filter((item) => /net::ERR_CONNECTION_RESET/.test(item))
      : [];
    // CodeMirror 等外链资源来自 jsdelivr：离线环境下 Chrome 只报「Failed to load resource: net::…」，
    // 控制台文本不含 URL。这里用 requestfailed 的 URL 判断：只要没有任何本项目源（web/后端）的
    // 请求失败，就不把这类无 URL 的资源加载错误算作功能缺陷（并把外链清单打印出来供核对）。
    const internalFailures = failedRequests.filter((item) => {
      return item.includes(webBase) || item.includes('/api/v1/');
    });
    const externalFailures = failedRequests.filter((item) => !internalFailures.includes(item));
    const resourceErrors = withoutExternal.filter(
      (item) => /Failed to load resource/.test(item) && !sseResetErrors.includes(item)
    );
    const externalResourceErrors = internalFailures.length === 0 ? resourceErrors : [];
    const realErrors = withoutExternal.filter(
      (item) => !sseResetErrors.includes(item) && !externalResourceErrors.includes(item)
    );
    if (consoleErrors.length) {
      logDetail(
        `控制台错误 ${consoleErrors.length} 条（外链文本命中 ${externalErrors.length} 条，外链请求失败归因 ${externalResourceErrors.length} 条，SSE 终态断流 ${sseResetErrors.length} 条）`
      );
    }
    if (externalResourceErrors.length) {
      const hosts = [...new Set(externalFailures.map((item) => (item.match(/https?:\/\/[^/]+/) || [''])[0]))].filter(Boolean);
      logDetail(`外链资源失败 ${externalFailures.length} 条（主机：${hosts.join('、') || '未知'}），非本项目源，不计失败`);
    }
    if (sseResetErrors.length) logDetail(`SSE 连接级失败 ${streamResets.length} 条（任务终态后断开，非功能缺陷）`);
    if (failedRequests.length) {
      logDetail(`连接级失败 ${failedRequests.length} 条：`);
      for (const item of failedRequests.slice(0, 12)) console.log(`[e2e]       ! ${item}`);
    }
    assert(realErrors.length === 0, `页面控制台错误：${realErrors.slice(0, 5).join(' | ')}`);

    return { downloadBytes: bytes.length, consoleErrors: realErrors.length, title, headerText, screenshots };
  } catch (err) {
    const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
    const shot = path.join(EVIDENCE_DIR, `fail-${stamp}.png`);
    try {
      fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
      await page.screenshot({ path: shot, fullPage: true });
      logDetail(`失败截图：${shot}`);
    } catch {
      logDetail('失败截图保存失败');
    }
    if (consoleErrors.length) {
      console.log('[e2e]     浏览器控制台错误（最多 10 条）：');
      for (const item of consoleErrors.slice(0, 10)) console.log(`[e2e]       - ${item}`);
    }
    console.log('[e2e]     后端日志尾部：');
    console.log(tailFile(dirs.backendLog, 25).replace(/^/gm, '[e2e]       '));
    throw err;
  } finally {
    // 无论成功/失败都关闭浏览器，否则 Chromium 会拖住 node 事件循环导致进程不退出
    await browser.close().catch(() => {});
  }
}

// ── 主流程 ───────────────────────────────────────────────────────────

async function loginViaUi(page, webBase, email) {
  await page.goto(`${webBase}/#auth`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.locator('#authTitle').waitFor({ timeout: 20000 });
  await dismissOnboarding(page);
  await page.locator('input[placeholder="您的邮箱地址"]').fill(email);
  const password = await openPasswordAuth(page);
  await password.fill(PASSWORD);
  const user = await submitAuthAndWaitForToken(page, '登录');
  assert(user?.id != null, `登录后 sm_user 缺少 id：${JSON.stringify(user)}`);
  return user;
}

async function runA11yFlow(playwright, webBase, apiContext, dirs) {
  logStage('无障碍/响应式：启动 Chromium（390px 窄屏 + 键盘 + 双账号隔离）');
  const launched = await launchChromium(playwright);
  const browser = launched.browser;
  const screenshots = [];
  const consoleErrors = [];
  const attach = (page) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(`console: ${msg.text()}`);
    });
    page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));
  };
  const shot = async (page, name) => {
    const file = await capture(page, name);
    screenshots.push(file);
    return file;
  };

  try {
    // ── A. 390×844 窄屏：无横向溢出、关键区块可见 ──────────────────
    logStage('窄屏 390×844：断言无横向溢出且关键区块可见');
    const narrow = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      locale: 'zh-CN',
    });
    const phone = await narrow.newPage();
    attach(phone);
    await loginViaUi(phone, webBase, apiContext.email);
    await phone.goto(`${webBase}/#research`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await phone.waitForSelector('h1.rw-title', { timeout: 25000 });
    const metrics = await phone.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    assert(
      metrics.scrollWidth <= metrics.innerWidth + 2,
      `窄屏出现横向溢出：scrollWidth=${metrics.scrollWidth} > innerWidth=${metrics.innerWidth}`
    );
    const projectsSection = phone.locator('section[aria-label="研究项目列表"]');
    await projectsSection.waitFor({ timeout: 20000 });
    const narrowProjectText = (await projectsSection.textContent()) || '';
    assert(narrowProjectText.includes(apiContext.project.title), '窄屏项目列表未显示已有项目');
    const chartBox = await phone.locator('section.rw-chart-panel').first().boundingBox();
    if (chartBox) {
      assert(chartBox.width <= metrics.innerWidth + 2, `窄屏图表卡片超出视口：${chartBox.width} > ${metrics.innerWidth}`);
    }
    logDetail(
      `窄屏：scrollWidth=${metrics.scrollWidth} / innerWidth=${metrics.innerWidth}，图表卡片宽度=${
        chartBox ? Math.round(chartBox.width) : '未渲染'
      }`
    );
    await shot(phone, 'a11y-01-narrow-research');
    await narrow.close();

    // ── B. 键盘可达：Tab 到「新建项目」→ Enter 聚焦输入 → 输入 Enter 创建 ──
    logStage('键盘可达：Tab 到达「新建项目」并用键盘创建项目');
    const desk = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
    const keyboardPage = await desk.newPage();
    attach(keyboardPage);
    await loginViaUi(keyboardPage, webBase, apiContext.email);
    await keyboardPage.goto(`${webBase}/#research`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await keyboardPage.waitForSelector('h1.rw-title', { timeout: 25000 });
    await keyboardPage.locator('section[aria-label="研究项目列表"]').waitFor({ timeout: 20000 });

    let reachedNewProject = false;
    for (let i = 0; i < 80; i += 1) {
      await keyboardPage.keyboard.press('Tab');
      const label = await keyboardPage.evaluate(() => {
        const el = document.activeElement;
        if (!el) return '';
        return `${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''} ${el.textContent || ''}`.trim();
      });
      if (label.includes('新建项目')) {
        reachedNewProject = true;
        break;
      }
    }
    assert(reachedNewProject, '键盘 Tab 80 次未能到达「新建项目」按钮（焦点顺序不可达）');

    await keyboardPage.keyboard.press('Enter');
    const focusedClass = await keyboardPage.evaluate(() => document.activeElement?.className || '');
    assert(
      typeof focusedClass === 'string' && focusedClass.includes('rw-input'),
      `按 Enter 后焦点未落到新建项目输入框：${focusedClass}`
    );

    const keyboardTitle = `键盘创建项目-${Date.now().toString().slice(-6)}`;
    await keyboardPage.keyboard.type(keyboardTitle);
    await keyboardPage.keyboard.press('Enter');
    await waitUntil(
      async () =>
        ((await keyboardPage.locator('section[aria-label="研究项目列表"]').textContent()) || '').includes(keyboardTitle),
      { label: '键盘创建项目出现在列表', timeout: 45000 }
    );
    logDetail(`键盘：Tab 命中「新建项目」→ Enter 聚焦输入 → 输入并回车创建「${keyboardTitle}」`);
    await shot(keyboardPage, 'a11y-02-keyboard-create');
    await desk.close();

    // ── C. 双账号隔离：账号 B 看不到账号 A 的项目，直连 A 的项目得 404 ──
    logStage('双账号隔离：新注册账号看不到他人项目，且直连他人项目 404');
    const second = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
    const secondPage = await second.newPage();
    attach(secondPage);
    const secondEmail = `isolation-${Date.now()}-${Math.random().toString(16).slice(2, 6)}@example.com`;
    await secondPage.goto(`${webBase}/#auth`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await secondPage.locator('#authTitle').waitFor({ timeout: 20000 });
    await dismissOnboarding(secondPage);
    await secondPage.locator('.auth-switch-link').first().click();
    await waitUntil(async () => (await secondPage.locator('#authTitle').textContent()).includes('注册'), {
      label: '切换到注册模式',
      timeout: 10000,
    });
    await secondPage.locator('input[placeholder="您的邮箱地址"]').fill(secondEmail);
    const secondPassword = await openPasswordAuth(secondPage);
    await secondPassword.fill(PASSWORD);
    const secondNickname = secondPage.locator('input[placeholder="昵称（可选）"]');
    if (await secondNickname.isVisible()) await secondNickname.fill('e2e-isolation');
    await submitAuthAndWaitForToken(secondPage, '注册');

    await secondPage.goto(`${webBase}/#research`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await secondPage.waitForSelector('h1.rw-title', { timeout: 25000 });
    const secondProjects = secondPage.locator('section[aria-label="研究项目列表"]');
    await secondProjects.waitFor({ timeout: 20000 });
    const secondText = (await secondProjects.textContent()) || '';
    assert(!secondText.includes(apiContext.project.title), '账号 B 的项目列表泄漏了账号 A 的项目');
    assert(!secondText.includes('键盘创建项目-'), '账号 B 的项目列表泄漏了账号 A 键盘创建的项目');

    const probe = await secondPage.evaluate(async (projectId) => {
      const token = localStorage.getItem('sm_token');
      const response = await fetch(`/api/v1/research/projects/${projectId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      return { status: response.status, body: (await response.text()).slice(0, 200) };
    }, apiContext.project.id);
    assert(probe.status === 404, `账号 B 直连账号 A 的项目应 404，实际 ${probe.status}：${probe.body}`);
    logDetail(`双账号：B 列表不含 A 的项目，直连 A 项目 HTTP ${probe.status}（统一 NOT_FOUND）`);
    await shot(secondPage, 'a11y-03-isolation');
    await second.close();

    // 外链 CDN（jsdelivr 的 CodeMirror）在离线环境必然失败，且会连带 CodeMirror 未定义的 pageerror。
    // 这里只把「非外链归因」的 pageerror 视为失败；资源加载错误按条数记录，供人工核对。
    const pageErrors = consoleErrors.filter((item) => item.startsWith('pageerror:'));
    const unexpectedPageErrors = pageErrors.filter((item) => !/CodeMirror/.test(item));
    const resourceErrors = consoleErrors.filter((item) => item.includes('Failed to load resource'));
    assert(
      unexpectedPageErrors.length === 0,
      `无障碍/响应式流程出现未预期 pageerror：${unexpectedPageErrors.slice(0, 3).join(' | ')}`
    );
    logDetail(
      `无障碍/响应式：截图 ${screenshots.length} 张，资源加载错误 ${resourceErrors.length} 条（外链 CDN 离线），非外链 pageerror ${unexpectedPageErrors.length} 条`
    );
    return { screenshots, consoleErrors: unexpectedPageErrors.length };
  } finally {
    await browser.close();
  }
}

function killTree(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', timeout: 15000 });
  } else {
    try {
      process.kill(pid, 'SIGTERM');
    } catch {
      /* 已退出 */
    }
  }
}

function pidsListeningOn(port) {
  if (process.platform !== 'win32' || !port) return [];
  const result = spawnSync('netstat', ['-ano', '-p', 'tcp'], { encoding: 'utf8', timeout: 15000 });
  const pids = new Set();
  for (const line of (result.stdout || '').split(/\r?\n/)) {
    if (!line.includes(`:${port}`) || !/LISTEN|LISTENING/i.test(line)) continue;
    const pid = Number(line.trim().split(/\s+/).pop());
    if (pid > 0) pids.add(pid);
  }
  return [...pids];
}

async function shutdownServers(web, backend, dirs, backendPort) {
  if (web?.server) {
    // 先断开存量连接（SSE 会一直挂着，否则 close 永远等不到回调）
    if (web.server.closeAllConnections) web.server.closeAllConnections();
    await Promise.race([
      new Promise((resolve) => web.server.close(() => resolve())),
      sleep(3000),
    ]);
  }
  if (backend) {
    // Windows 上 .venv/Scripts/python.exe 会再拉起真实解释器；只 kill 父进程会留下子进程和文件锁，
    // 所以整棵树一起杀，再用监听端口兜底（防止父进程先退出导致 /T 找不到子进程）。
    if (backend.exitCode === null) killTree(backend.pid);
    await Promise.race([
      new Promise((resolve) => {
        if (backend.exitCode !== null) resolve(true);
        else backend.once('exit', () => resolve(true));
      }),
      sleep(3000),
    ]);
    for (const pid of pidsListeningOn(backendPort)) killTree(pid);
    for (let i = 0; i < 20 && pidsListeningOn(backendPort).length; i++) await sleep(200);
  }
  if (!dirs) return;
}

async function cleanupDirs(dirs, keep) {
  if (!dirs?.root) return;
  if (keep) {
    log(`保留临时目录：${dirs.root}`);
    return;
  }
  // Windows 上后端刚退出时 sqlite WAL / 上传文件可能短暂仍被占用，多试几次
  await sleep(500);
  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      fs.rmSync(dirs.root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
      return;
    } catch (err) {
      if (attempt === 5) {
        log(`临时目录清理失败（可手动删除）：${dirs.root}（${err.code || err.message}）`);
        return;
      }
      await sleep(1000);
    }
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    printHelp();
    return EXIT_PASS;
  }
  const startedAt = Date.now();

  let dirs = null;
  let backend = null;
  let web = null;
  let backendPort = 0;

  try {
    if (opts.mode === 'browser') {
      logStage('检查 Playwright（浏览器验收硬依赖）');
      try {
        await loadPlaywright();
      } catch {
        console.error('[e2e] 缺少浏览器驱动：playwright 未安装或不可用。');
        console.error(`[e2e] 安装命令：${PLAYWRIGHT_HINT}`);
        return EXIT_PLAYWRIGHT;
      }
      logDetail('playwright 可用');
    }

    logStage('检查构建产物 dist/（必须是 vite 模块化构建，不是原型 HTML）');
    const indexHtml = path.join(DIST, 'index.html');
    if (!fs.existsSync(indexHtml)) {
      console.error('[e2e] dist/index.html 不存在。先运行：npm run build:frontend');
      return EXIT_ENV;
    }
    const indexText = fs.readFileSync(indexHtml, 'utf8');
    if (!/src="\/assets\/index-[A-Za-z0-9_-]+\.js"/.test(indexText)) {
      console.error('[e2e] dist/index.html 不含模块化入口（/assets/index-*.js）。先运行：npm run build:frontend');
      return EXIT_ENV;
    }
    logDetail('dist/index.html 含模块化入口');

    logStage('检查 python 与后端依赖');
    checkPythonDeps(resolvePython());
    logDetail(`python=${resolvePython()}`);

    dirs = createRunDirs();
    const [selectedBackendPort, webPort] = await Promise.all([freePort(), freePort()]);
    backendPort = selectedBackendPort;
    const backendBase = `http://127.0.0.1:${backendPort}`;

    logStage(`启动隔离后端（127.0.0.1:${backendPort}，临时 DB：${dirs.db}）`);
    backend = startBackend(backendPort, dirs);
    await waitForHealth(backendBase, backend, dirs);
    logDetail('后端 /api/v1/health 200');

    logStage(`启动静态服务 + /api、/ws 同源代理（127.0.0.1:${webPort}）`);
    web = await startWebServer(backendPort, webPort);
    logDetail(`web=${web.base} backend=${backendBase}`);

    if (opts.mode === 'serve-only') {
      logStage('serve-only：自检首页、健康检查、能力 401/200');
      const home = await fetch(`${web.base}/`, { signal: AbortSignal.timeout(15000) });
      const homeText = await home.text();
      assert(home.status === 200, `首页 HTTP ${home.status}`);
      assert(/<script[^>]*type="module"[^>]*src="\/assets\/index-[A-Za-z0-9_-]+\.js"/.test(homeText), '首页缺少模块化入口脚本');
      const health = await fetch(`${web.base}/api/v1/health`, { signal: AbortSignal.timeout(15000) });
      assert(health.status === 200, `代理 /api/v1/health 返回 ${health.status}`);

      const unauth = await fetch(`${web.base}/api/v1/research/capabilities`, { signal: AbortSignal.timeout(15000) });
      const unauthBody = await unauth.text();
      assert(unauth.status === 401, `未带 token 的能力请求应 401，实际 ${unauth.status}`);
      logDetail(`未带 token：HTTP 401（${unauthBody.slice(0, 120)}）`);

      const email = `serve-${Date.now()}@example.com`;
      const registered = expectOk(
        await callApi(backendBase, '/api/v1/auth/register', {
          method: 'POST',
          json: { email, password: PASSWORD, nickname: 'serve-only', device_fingerprint: 'e2e-serve-only' },
        }),
        'serve-only 注册'
      );
      const authed = await fetch(`${web.base}/api/v1/research/capabilities`, {
        headers: { authorization: `Bearer ${registered.access_token}` },
        signal: AbortSignal.timeout(15000),
      });
      const authedBody = await authed.json();
      assert(authed.status === 200, `带 token 的能力请求应 200，实际 ${authed.status}`);
      assert(Array.isArray(authedBody.capabilities) && authedBody.capabilities.length > 0, '能力清单为空');
      logDetail(`带 token：HTTP 200，capabilities=${authedBody.capabilities.length} 项`);

      log(`serve-only 自检通过，服务地址：${web.base}/#research（后端 ${backendBase}）`);
      if (opts.duration > 0) {
        log(`保持服务 ${opts.duration} 秒后退出（可用 curl 复核）`);
        await sleep(opts.duration * 1000);
      } else {
        log('按 Ctrl+C 结束服务');
        await new Promise((resolve) => {
          const stop = () => resolve();
          process.once('SIGINT', stop);
          process.once('SIGTERM', stop);
        });
      }
      return EXIT_PASS;
    }

    logStage('执行 API 全链路（注册/登录 → 项目 → 上传 → review → 导出）');
    const apiContext = await runApiChain(backendBase, dirs);

    if (opts.mode === 'api-only') {
      log('API 全链路通过（未驱动浏览器，不能作为浏览器验收结论）。');
      return EXIT_PASS;
    }

    logStage('执行浏览器验收（真实 UI 注册/登出/登录 → #research → 断言 → 导出下载）');
    const browserResult = await runBrowserFlow(await loadPlaywright(), web.base, apiContext, dirs);

    let a11yResult = null;
    if (opts.a11y) {
      a11yResult = await runA11yFlow(await loadPlaywright(), web.base, apiContext, dirs);
    }

    logStage('全部断言通过');
    logDetail(`API：findings=${apiContext.findingsCount}，导出 ${apiContext.exportBytes} B`);
    logDetail(
      `图表：${apiContext.chart.capability === 'enabled' ? `201 / ${apiContext.chart.bytes} B PNG（${apiContext.chart.path}）` : '503 CHART_CAPABILITY_DISABLED（显式关闭）'}`
    );
    logDetail(`浏览器：下载 ${browserResult.downloadBytes} B，控制台错误 ${browserResult.consoleErrors} 条`);
    if (a11yResult) {
      logDetail(
        `无障碍/响应式：截图 ${a11yResult.screenshots.length} 张，非外链 pageerror ${a11yResult.consoleErrors} 条`
      );
      for (const file of a11yResult.screenshots) console.log(`[e2e]       ${file}`);
    }
    logDetail(`截图证据（${browserResult.screenshots.length} 张）：`);
    for (const file of browserResult.screenshots) console.log(`[e2e]       ${file}`);
    logDetail(`总耗时 ${((Date.now() - startedAt) / 1000).toFixed(1)} s`);
    console.log(`[e2e] 结果：PASS（浏览器验收 + 发布链）`);
    return EXIT_PASS;
  } catch (err) {
    if (err instanceof PlaywrightMissingError) {
      console.error(`[e2e] ${err.message}`);
      console.error(`[e2e] 安装命令：${PLAYWRIGHT_HINT}`);
      return EXIT_PLAYWRIGHT;
    }
    console.error(`[e2e] 结果：FAIL - ${err.message}`);
    if (err.details) console.error(`[e2e] 详情：${String(err.details).replace(/\n/g, '\n[e2e] ')}`);
    if (dirs && fs.existsSync(dirs.backendLog)) {
      console.error('[e2e] 后端日志尾部：');
      console.error(tailFile(dirs.backendLog, 20).replace(/^/gm, '[e2e]   '));
    }
    if (err instanceof EnvError) {
      console.error('[e2e] 结果：ENV-MISSING（环境/依赖问题，退出码 2）');
      return EXIT_ENV;
    }
    return EXIT_FAIL;
  } finally {
    await shutdownServers(web, backend, dirs, backendPort);
    await cleanupDirs(dirs, opts.keep);
  }
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((err) => {
    console.error(`[e2e] 未捕获错误：${err?.stack || err}`);
    process.exitCode = EXIT_FAIL;
  });
