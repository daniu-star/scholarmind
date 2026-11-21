#!/usr/bin/env node
// ScholarMind 前端构建脚本（T20 发布链）
//
// 旧实现是把 prototypes/interactive-prototype.html 原样复制到 dist/，
// 那条链路不构建模块化前端，e2e 无法验证真实产物。这里改为调用
// src/frontend 的 Vite 构建（outDir = ../../dist），并在构建后断言：
//   1) dist/index.html 存在且引用了 assets/index-<hash>.js 模块入口；
//   2) dist/index.html 不再包含原型 HTML 的标记（icons.browser.js、
//      api-base meta、v20260709 标题注释）；
//   3) 入口引用的 JS/CSS 文件确实落在 dist/ 里。
// 任一断言失败 → exit 1。
//
// 用法：
//   node scripts/build-frontend.js                     # 相对路径 /api（同源部署）
//   node scripts/build-frontend.js --api-base=http://localhost:8000
//   VITE_API_BASE=http://localhost:8000 node scripts/build-frontend.js
//
// API base 通过构建期 VITE_API_BASE 注入（src/frontend/src/services/api.js
// 的 import.meta.env.VITE_API_BASE），不再是运行时 <meta> 标签。

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.resolve(__dirname, '..');
const frontendDir = path.join(root, 'src', 'frontend');
const dist = path.join(root, 'dist');
const indexHtml = path.join(dist, 'index.html');

function parseArgs(argv) {
  const out = { apiBase: undefined, help: false };
  for (const arg of argv) {
    if (arg === '--help' || arg === '-h') out.help = true;
    else if (arg.startsWith('--api-base=')) out.apiBase = arg.slice('--api-base='.length);
    else {
      console.error(`[build-frontend] 未知参数：${arg}`);
      console.error('[build-frontend] 可用参数：--api-base=<url>、--help');
      process.exit(1);
    }
  }
  return out;
}

function fail(message) {
  console.error(`[build-frontend] FATAL: ${message}`);
  process.exit(1);
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  console.log('用法: node scripts/build-frontend.js [--api-base=<url>]');
  console.log('  --api-base  构建期注入的 API 地址；省略时使用相对路径（/api/...）');
  process.exit(0);
}

if (!fs.existsSync(path.join(frontendDir, 'package.json'))) {
  fail(`${frontendDir}/package.json 不存在，无法调用 src/frontend 的 Vite 构建。`);
}
if (!fs.existsSync(path.join(frontendDir, 'node_modules'))) {
  fail(`${frontendDir}/node_modules 不存在；请先执行 npm --prefix src/frontend install。`);
}

const apiBase = args.apiBase !== undefined ? args.apiBase : (process.env.VITE_API_BASE || '');
console.log(`[build-frontend] repo root    = ${root}`);
console.log(`[build-frontend] frontend dir = ${frontendDir}`);
console.log(`[build-frontend] dist dir     = ${dist}`);
console.log(`[build-frontend] VITE_API_BASE = ${apiBase || '(empty → relative paths)'}`);

// 1. 调 Vite 构建（outDir 在 vite.config.js 里固定为 ../../dist）
//    Windows 下 .cmd 必须经 shell 启动（Node ≥20.12 不允许直接 spawn .cmd）。
const env = { ...process.env, VITE_API_BASE: apiBase };
const command = 'npm --prefix src/frontend run build';
console.log(`[build-frontend] $ ${command}`);
const build = spawnSync(command, {
  cwd: root,
  env,
  stdio: 'inherit',
  shell: true,
});
if (build.error) {
  fail(`启动 Vite 构建失败：${build.error.message}`);
}
if (build.status !== 0) {
  fail(`Vite 构建失败（exit ${build.status}）。请检查 src/frontend 的构建输出。`);
}

// 2. 断言产物是模块化构建，不是原型 HTML 副本
if (!fs.existsSync(indexHtml)) {
  fail('Vite 构建结束但 dist/index.html 不存在（检查 vite.config.js 的 build.outDir）。');
}
const html = fs.readFileSync(indexHtml, 'utf8');
const problems = [];

const moduleEntry = html.match(/<script[^>]*type=["']module["'][^>]*src=["']([^"']+)["'][^>]*>/i);
if (!moduleEntry) {
  problems.push('dist/index.html 中没有 <script type="module" src="..."> 入口');
} else {
  const entrySrc = moduleEntry[1];
  if (!/^\/assets\/index-[\w.-]+\.js$/.test(entrySrc)) {
    problems.push(`模块入口不是 /assets/index-<hash>.js（实际：${entrySrc}）`);
  }
}

const prototypeMarkers = [
  { needle: 'icons.browser.js', why: '原型 icons.browser.js 引用' },
  { needle: 'name="api-base"', why: '原型 <meta name="api-base"> 标签' },
  { needle: 'v20260709 | ScholarMind', why: '原型 HTML 标题' },
];
for (const marker of prototypeMarkers) {
  if (html.includes(marker.needle)) problems.push(`dist/index.html 仍包含${marker.why}（${marker.needle}）`);
}

// 3. 入口与样式文件必须真实存在
const assetRefs = [...html.matchAll(/(?:src|href)=["'](\/assets\/[^"']+)["']/gi)].map((m) => m[1]);
if (!assetRefs.length) problems.push('dist/index.html 未引用任何 /assets/ 资源');
for (const ref of new Set(assetRefs)) {
  const file = path.join(dist, ref.replace(/^\//, ''));
  if (!fs.existsSync(file)) problems.push(`入口引用的资源不存在：${ref}`);
}

if (problems.length) {
  console.error('[build-frontend] 产物断言失败：');
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}

// 4. 开发变体：确认 API base 真的被编进 bundle（不是只打印了一行日志）
if (apiBase) {
  const assetsDir = path.join(dist, 'assets');
  const jsFiles = fs.readdirSync(assetsDir).filter((f) => f.endsWith('.js'));
  const baked = jsFiles.some((f) => fs.readFileSync(path.join(assetsDir, f), 'utf8').includes(apiBase));
  if (!baked) {
    fail(`VITE_API_BASE=${apiBase} 没有出现在 dist/assets/*.js 中，构建期注入无效。`);
  }
  console.log(`[build-frontend] VITE_API_BASE baked into bundle ✓ (${apiBase})`);
}

// 5. 产物清单
function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}
const files = walk(dist);
const total = files.reduce((sum, f) => sum + fs.statSync(f).size, 0);
console.log(`[build-frontend] build artifacts (${files.length} files, ${(total / 1024).toFixed(1)} KiB):`);
for (const file of files) {
  const rel = path.relative(dist, file).split(path.sep).join('/');
  console.log(`  ${rel} (${fs.statSync(file).size} bytes)`);
}

console.log(`✓ Frontend built to dist/ (vite, module entry ${moduleEntry[1]})`);
