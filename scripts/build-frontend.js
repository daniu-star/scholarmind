// ScholarMind 前端构建脚本（Vercel 部署专用）
// 作用：把 prototypes/ 下的原型 HTML + assets 复制到 dist/，
// 并在 dist/index.html 的 <head> 注入 <meta name="api-base">，
// 让前端在运行时通过 meta 标签读取后端 API 地址（指向 Railway）。

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const dist = path.join(root, 'dist');

// 后端 API 域名：优先读 VITE_API_BASE 环境变量，默认生产域名
// API_BASE 为空字符串 → 前端使用相对路径（/api/...），经由 Vercel 代理到 Railway
// 生产环境设置 VITE_API_BASE= 显式留空以绕过 api.quannengyanjiu.cn DNS 问题
const apiBase = process.env.VITE_API_BASE || '';

console.log(`[build-frontend] VITE_API_BASE = ${apiBase}`);

// 1. 清空 dist
if (fs.existsSync(dist)) {
  fs.rmSync(dist, { recursive: true, force: true });
}
fs.mkdirSync(dist, { recursive: true });

// 2. 复制原型 HTML 作为主入口
const srcHtml = path.join(root, 'prototypes/interactive-prototype.html');
const dstHtml = path.join(dist, 'index.html');
if (!fs.existsSync(srcHtml)) {
  console.error(`[build-frontend] FATAL: ${srcHtml} not found. Ensure prototypes/ is committed to git.`);
  process.exit(1);
}
fs.copyFileSync(srcHtml, dstHtml);

// 3. 复制 icons.browser.js
const srcIcons = path.join(root, 'prototypes/icons.browser.js');
const dstIcons = path.join(dist, 'icons.browser.js');
if (fs.existsSync(srcIcons)) {
  fs.copyFileSync(srcIcons, dstIcons);
} else {
  console.warn(`[build-frontend] WARN: ${srcIcons} not found, skipping.`);
}

// 4. 递归复制 assets/ 目录
const srcAssets = path.join(root, 'prototypes/assets');
const dstAssets = path.join(dist, 'assets');
if (fs.existsSync(srcAssets)) {
  fs.cpSync(srcAssets, dstAssets, { recursive: true });
} else {
  console.warn(`[build-frontend] WARN: ${srcAssets} not found, skipping.`);
}

// 5. 在 dist/index.html 的 <head> 注入 <meta name="api-base">
// 注意：必须只检测真正的 HTML meta 标签，避免误判：
//   - JS 注释里的 `<meta name="api-base" content="...">`（content="..." 满足 [^"']+）
//   - JS 代码里的 document.querySelector('meta[name="api-base"]')
// 因此要求 content 必须以 http:// 或 https:// 开头。
let html = fs.readFileSync(dstHtml, 'utf-8');
const metaTagRegex = /<meta\s+name=["']api-base["']\s+content=["']https?:\/\/[^"']+["']/i;
if (!metaTagRegex.test(html)) {
  const metaTag = `<meta name="api-base" content="${apiBase}">`;
  if (html.includes('<head>')) {
    html = html.replace('<head>', `<head>\n    ${metaTag}`);
  } else if (/<head[^>]*>/.test(html)) {
    html = html.replace(/<head[^>]*>/, match => `${match}\n    ${metaTag}`);
  } else {
    // 没有 <head> 标签，在 <!DOCTYPE html> 后注入
    html = html.replace(/<!DOCTYPE[^>]*>/i, match => `${match}\n<head>\n    ${metaTag}\n</head>`);
  }
  fs.writeFileSync(dstHtml, html);
  console.log(`[build-frontend] injected meta api-base = ${apiBase}`);
} else {
  console.log(`[build-frontend] meta api-base already present, skipping injection`);
}

// 6. 输出构建产物清单
console.log('[build-frontend] build artifacts:');
function listFiles(dir, prefix = '') {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    const relPath = path.relative(dist, fullPath).replace(/\\/g, '/');
    if (entry.isDirectory()) {
      console.log(`  ${prefix}${entry.name}/`);
      listFiles(fullPath, prefix + '  ');
    } else {
      const stat = fs.statSync(fullPath);
      console.log(`  ${prefix}${entry.name} (${stat.size} bytes)`);
    }
  }
}
listFiles(dist);

console.log('✓ Frontend built to dist/');
