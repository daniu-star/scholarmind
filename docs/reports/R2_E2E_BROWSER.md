# R2 真实浏览器 E2E 验收记录（Playwright）

记录时间：2026-11-20 16:02（+08:00）
执行人：R2 浏览器验收代理
**结论：默认浏览器模式真实跑通，`node scripts/research_e2e.mjs --keep` 退出码 0。**
本节所有结果均来自本机真实运行，日志与截图见 §5；未覆盖项在 §6 明确列出，未宣称通过。

## 1. 与旧记录的关系

`docs/reports/R2_E2E.md` 记录的是 2026-11-20 11:45 的状态：当时仓库没有 `node_modules/playwright`，
浏览器模式按契约退出 3，浏览器断言“只写进脚本、未执行”。本次已完成依赖安装并真实执行全部浏览器断言，
因此 `R2_E2E.md` 的 §3.4、§4（退出码 3）、§6.2（“浏览器验收未运行”）已被本文件取代；
旧文件末尾已追加更新说明，历史记录本身保留不改。

## 2. 环境

| 项目 | 值 |
| --- | --- |
| OS | Windows 10.0.26300.9974 |
| Node / npm | `node v24.16.0` / `npm 11.6.0` |
| Python | 3.14.5（`C:\Users\13067\Desktop\全能研究Agent\.venv\Scripts\python.exe`） |
| Playwright（node） | 1.65.1（根 `devDependencies`，`node_modules/playwright`） |
| 浏览器 | Playwright 自带 Chromium revision 1255（Chrome 159），headless，1440×1000 |
| 构建产物 | `dist/index.html`（2026-11-20 12:00 构建，vite 模块化入口） |
| 后端 | 隔离 uvicorn 实例 + 临时 sqlite（`tmp/e2e-run-<id>/e2e.db`） |
| 模型 | `RESEARCH_MODEL_STUB=true` 替身模型（不联网、不调用真实模型 API） |

安装命令（本次真实执行，均成功）：

```bash
npm i -D playwright@1.65.1 --no-audit --no-fund      # 根目录，added 3 packages
npx playwright install chromium                        # 下载 chromium-1255 + headless-shell-1255
```

脚本保留 `executablePath` 兜底：若下载浏览器失败，可设置 `E2E_CHROMIUM_EXECUTABLE` 指向本机
`chrome.exe`，或自动使用 `%LOCALAPPDATA%\ms-playwright` 下最新的已安装 Chromium。本次实际使用的是
Playwright 自带浏览器，日志行：`浏览器可执行文件：Playwright 自带 chromium`。

## 3. 运行命令与结果

最终证据运行（本文件引用此轮）：

```bash
node scripts/research_e2e.mjs --keep
```

| 指标 | 实测 |
| --- | --- |
| 退出码 | **0** |
| 脚本内部总耗时 | **34.7 s** |
| 墙钟耗时（`time`） | **38.3 s**（real 0m38.347s） |
| API 链路 | 通过（项目/文档/任务/导出/图表） |
| 浏览器链路 | 通过（注册/登出/登录/工作区/SSE/报告/导出下载） |
| 页面真实控制台错误 | **0 条** |
| 完整日志 | `tmp/r2-browser-final2.log` |
| 保留的隔离运行目录 | `tmp/e2e-run-pAZXeR/`（`backend.log`、`e2e.db`、`api-chart.png`、`browser-download.md`） |

关键日志（原文，未改写）：

```text
[e2e] [18] 浏览器：真实 UI 注册新账号
[e2e]     注册成功：browser-1795161727035-b608@example.com（id=2），已跳转 #homepage
[e2e] [19] 浏览器：刷新后断言登录态可见，再执行登出
[e2e]     登出后刷新：TopNav 回到未登录态（登录/注册按钮可见）
[e2e] [20] 浏览器：真实 UI 登录 API 主账号
[e2e]     登录成功：e2e-20261120080204-fcbf20@example.com（id=1）
[e2e] [25] 浏览器：断言 SSE 事件流真实到达（started/终态/序号）
[e2e]     SSE：5 条事件（task.accepted, task.started, task.progress, artifact.created, task.completed），最后序号=5，状态灯=流已结束
[e2e] [26] 浏览器：等待诊断结论与覆盖范围出现（替身模型，0 findings）
[e2e] [27] 浏览器：导出 Markdown 并验证下载非空
[e2e]     浏览器下载：e2e-paper.md，1315 B，首行「数字化时代的学术写作：证据链与方法透明度」
[e2e] [29] 全部断言通过
[e2e]     API：findings=0，导出 1315 B
[e2e]     图表：201 / 77876 B PNG（…\tmp\e2e-run-pAZXeR\api-chart.png）
[e2e]     浏览器：下载 1315 B，控制台错误 0 条
[e2e]     总耗时 34.7 s
[e2e] 结果：PASS（浏览器验收 + 发布链）
```

补充：`node scripts/research_e2e.mjs --api-only` 也已实测 exit 0（图表用例修复后），
日志 `tmp/r2-api-run2.log`。浏览器模式本身已包含同一 API 链路，因此最终以浏览器轮次为准。

## 4. 逐步断言结果（全部真实执行）

| # | 步骤 | 断言（实际检查内容） | 结果 |
| --- | --- | --- | --- |
| 1 | Playwright 依赖 | `import('playwright')` 成功且 `chromium.launch` 可用 | PASS |
| 2 | 构建产物 | `dist/index.html` 存在且含 `src="/assets/index-*.js"` 模块化入口 | PASS |
| 3 | Python 依赖 | `.venv` 内 fastapi/uvicorn/sqlalchemy/alembic/aiosqlite 可导入 | PASS |
| 4 | 隔离后端 | `/api/v1/health` 返回 200 | PASS |
| 5 | 静态服务 + 代理 | `dist/` 静态服务可访问，`/api`、`/ws` 代理到隔离后端 | PASS |
| 6 | API 注册 + 登录 | 新用户 id=1，返回 token/entitlements | PASS |
| 7 | API 能力清单 | free 用户未带权益时 `task.review=unauthorized`；写测试夹具后 `task.review=ready`、`model.llm=degraded` | PASS |
| 8 | API 创建项目 | `POST /research/projects` → **201**，id 以 `rproj_` 开头 | PASS |
| 9 | API 上传 Markdown | `POST /projects/{id}/documents` → **201**，`parse_status=complete`，517 codepoints | PASS |
| 10 | API 创建 review 任务 | `POST /research/tasks` → **202**（queued） | PASS |
| 11 | API 任务终态 | 轮询至 `status=succeeded`、`quality_verdict=no_major_issues_found`、`attempt_no=1` | PASS |
| 12 | API 诊断项 | `GET /tasks/{id}/findings?limit=100` → 200，`findings=0`、`next_cursor=null` | PASS |
| 13 | API 导出 | `POST /research/exports` → **201**，`e2e-paper.md` 1315 B，正文首行含文档标题 | PASS |
| 14 | API 图表 | `POST /research/charts`（scatter_density，数值表）→ **201**，PNG 77876 B，PNG 签名 `89504e470d0a1a0a` 通过 | PASS |
| 15 | 浏览器启动 | Playwright 自带 Chromium 启动成功（headless） | PASS |
| 16 | 真实 UI 注册 | `#auth` 标题为登录 → 点「注册」切换 → 展开密码框 → 填邮箱/密码/昵称 → 提交；`sm_token` 写入且非字符串 `"null"`；`sm_user.id` 有值、昵称 `e2e-browser`；hash=`#homepage` | PASS |
| 17 | 登录态持久化 | 刷新后 TopNav 出现 `button[aria-label="退出登录"]` | PASS |
| 18 | 真实 UI 登出 | 点击退出登录后 `sm_token`/`sm_user` 已清除（接受 `null` 或字符串 `"null"`）；再刷新后 TopNav 出现 `button[aria-label="登录"]` 与注册按钮 | PASS |
| 19 | 真实 UI 登录 | 用 API 主账号邮箱+密码登录；`sm_user.id === API userId(1)`；hash=`#homepage`；刷新后仍显示退出登录 | PASS |
| 20 | 打开工作区 | `#research` 渲染 `h1.rw-title` 文本为「研究工作区」 | PASS |
| 21 | 能力状态 | 头部 pill 不含「能力状态未知」「能力清单未上报」，文案匹配「能力就绪」或「项能力不可用」（实测含「4 项能力不可用」「2 项降级」） | PASS |
| 22 | 能力面板 | `section[aria-label="研究域能力状态"]` 存在，`.rw-cap-row` ≥ 5，含「能力状态」 | PASS |
| 23 | 项目列表 | `section[aria-label="研究项目列表"]` 出现刚创建的项目并可选 | PASS |
| 24 | 文档选择 | 文档卡出现 `e2e-paper.md` 并可点击选中，头部显示「项目：…」 | PASS |
| 25 | 发起 review | 「诊断目标」textarea 可填；「开始全文诊断」按钮可用后点击 | PASS |
| 26 | SSE 事件到达 | `section[aria-label="任务状态与事件流"]` 出现；`ol[aria-label="任务事件日志"]` ≥3 行（实测 5 行）；「最后事件序号：5」>0；事件类型含 `task.started` 与 `task.completed`；状态灯=`流已结束`（非「连接异常」） | PASS |
| 27 | 诊断报告/空态 | 「诊断结论」区出现「问题与依据（0）」与「已完成」；空态说明含「没有可展示的问题」；无「诊断项读取失败」；覆盖率 13/13=100% | PASS |
| 28 | 导出 + 下载 | 选 `md`、勾选「附带诊断报告」→「生成导出成果」→ 出现「导出成果」→ 点「下载文件」；文件 `e2e-paper.md`、1315 B、非空、含标题正文、扩展名 `.md` | PASS |
| 29 | 控制台 | 过滤 jsdelivr/favicon 后真实 console error/pageerror **0 条** | PASS |

关于任务要求里的“findings 或空态展示”：本次替身模型固定返回 0 findings，因此**只覆盖了空态**，
未覆盖有 findings 时的卡片渲染，见 §6。

## 5. 证据（截图与产物）

截图目录：`C:\Users\13067\Desktop\全能研究Agent\tmp\e2e-evidence\`（本轮 7 张，均为真实页面整页截图）：

| 步骤 | 文件 |
| --- | --- |
| 注册成功、跳转首页 | [20261120080210-01-register-home.png](../../tmp/e2e-evidence/20261120080210-01-register-home.png) |
| 刷新后仍登录 | [20261120080211-02-auth-persisted.png](../../tmp/e2e-evidence/20261120080211-02-auth-persisted.png) |
| 登出后回到未登录 | [20261120080212-03-logout.png](../../tmp/e2e-evidence/20261120080212-03-logout.png) |
| 真实 UI 登录成功 | [20261120080213-04-login-home.png](../../tmp/e2e-evidence/20261120080213-04-login-home.png) |
| SSE 事件流 + 诊断过程 | [20261120080215-05-sse-events.png](../../tmp/e2e-evidence/20261120080215-05-sse-events.png) |
| 诊断结论（0 findings 空态） | [20261120080215-06-report.png](../../tmp/e2e-evidence/20261120080215-06-report.png) |
| 导出下载完成 | [20261120080216-07-export-downloaded.png](../../tmp/e2e-evidence/20261120080216-07-export-downloaded.png) |

运行产物（`--keep` 保留，可复核）：

- `tmp/e2e-run-pAZXeR/browser-download.md` — 浏览器真实下载的导出文件，1315 B
- `tmp/e2e-run-pAZXeR/api-chart.png` — 图表接口真实下载的 PNG，77876 B
- `tmp/e2e-run-pAZXeR/backend.log` — 隔离后端请求日志（含 health/register/login/projects/documents/tasks/findings/exports/charts）
- `tmp/r2-browser-final2.log` — 本轮完整 stdout/stderr，含每个断言的实际值

注意：`tmp/` 是 gitignore 的运行目录，清理后证据会消失；如需长期留档，应把截图/日志归档到
受版本控制的目录（本轮未新增图片文件，因交付范围只允许写本 Markdown 与脚本）。

## 6. 未覆盖项（明确不宣称通过）

1. **窄屏/移动端**：只测了 1440×1000 桌面视口；未测 375px/768px 响应式布局、移动端触摸交互。
2. **键盘可访问性**：全部交互通过 Playwright 定位点击/填表完成，未验证纯键盘 Tab/Enter 路径、焦点顺序、可见焦点环。
3. **双账号数据隔离**：浏览器只登录一个主账号；API 另建了注册账号，但未验证两个账号在浏览器内互相看不到项目/文档/任务。
4. **有 findings 的渲染**：替身模型固定 0 findings，只验证空态；finding 卡片、严重度、证据链展开、`verification_method` 展示均未覆盖。
   另：`R2_E2E.md` §7 记录的 structural finding 500 缺陷本次未触发（夹具补齐四章节）。
5. **图表前端 UI**：`ResearchWorkspace` 目前没有图表入口；图表只在 API 层验证 201 + PNG，未在浏览器里生成/展示/下载图表。
6. **验证码/手机号/第三方登录**：只覆盖邮箱+密码；短信验证码、OAuth 未覆盖。
7. **真实模型语义诊断**：`RESEARCH_MODEL_STUB=true`，不联网、不调用真实模型；诊断质量、真实 findings 不在此次范围。
8. **异常/断线路径**：未测 SSE 断线重连、网络中断、任务失败/partial、刷新页面时任务进行中、后端重启恢复。
9. **权限负路径**：未在浏览器里验证未登录访问 `#research`、越权访问他人项目、过期 token 跳转。
10. **浏览器矩阵/渲染质量**：只测 Playwright 自带 Chromium 1255 headless；未测 Firefox/WebKit、headed 模式、视觉回归、性能、无障碍审计。
11. **并发/多标签页**：未测同一账号多标签页同时操作、重复提交幂等（API 侧只用了一个幂等键）。
12. **本地化/时区**：固定 `locale=zh-CN`，未测英文界面或其他时区。

## 7. 本次发现的前端行为（未修改，超出可改范围）

1. **localStorage 的 `null` 被写成字符串 `"null"`**
   `src/frontend/src/app/store.js` 的 auth watcher 调用 `storage.set('sm_token', v?.token || null)`，
   `src/frontend/src/utils/storage.js` 用 `JSON.stringify`，于是登出后 `localStorage.sm_token` 的值是字符串
   `"null"` 而不是删除。任何用 `Boolean(localStorage.getItem('sm_token'))` 判断登录态的轮询都会**误判为已登录**。
   本次脚本因此两处修正：登出断言接受 `null`/`"null"`；等待登录完成时排除 `"null"`/`"undefined"`。
   应用自身读取走 `JSON.parse`，功能上能正确得到 `null`，但这是容易踩坑的实现细节。
2. **TopNav 不随登录/登出即时刷新**
   `src/frontend/src/components/TopNav.js` 的 `renderAuthButtons()` 只在构造时执行；登录/登出后必须刷新页面
   才能看到导航按钮变化。E2E 用刷新来断言持久化（真实用户下次打开的行为），但当前 UX 下同页登录后导航滞后。
3. **登出未清除 `sm_refresh_token`**
   `src/frontend/src/components/TopNav.js:300-305` 只移除 `sm_token`/`sm_user`/`sm_entitlements`，
   残留 refresh token。脚本未对其做断言（当前产品行为），建议 owner 评估是否应在登出时一并清除。
4. 首次进入会出现引导遮罩（`#onboardingOverlay`），脚本用真实 UI「跳过引导」关闭；若后续引导改版，步骤 16 需同步。

以上均未改 `src/**`（任务禁止），仅记录。

## 8. 失败迭代记录（证明不是“一次就绿”）

调试过程中的失败均保留日志，最终通过不是降低断言换来的：

| 轮次 | 日志 | 退出码 | 失败断言（原文摘要） | 修正 |
| --- | --- | --- | --- | --- |
| 1 | `tmp/r2-browser-run1.log` | 1（进程因浏览器未关闭需 kill） | `.auth-switch-link` 点击超时：`<div id="onboardingOverlay">…</div> intercepts pointer events` | 用真实 UI 点「跳过引导」；`finally` 关闭浏览器 |
| 2 | `tmp/r2-browser-run2.log` | 1 | `注册后 sm_user 邮箱不符：{"id":2,"phone":null,"nickname":"e2e-browser","plan":"free"}` | 后端用户对象不暴露 email，改断言 id + 昵称 |
| 3 | `tmp/r2-browser-run3.log` | 1 | `登出后 sm_token 未清除：null`（实际是字符串 `"null"`） | 登出断言同时接受 `null` 与 `"null"` |
| 4 | `tmp/r2-browser-run4.log` | 1 | `登录后 sm_user.id=undefined 与 API 用户 1 不一致`（陈旧 `"null"` 让等待提前返回） | 等待 token 时排除 `"null"`/`"undefined"` |
| API 图表首试 | `tmp/r2-api-run.log` | 1 | `生成图表 失败（HTTP 422）`，`CHART_NON_NUMERIC`：第 1 行「变量」列 `样本量` 不是数值 | 换成全数值的第二张表（年份/样本量/编码一致性），未改后端 |
| 最终 | `tmp/r2-browser-final2.log` | **0** | 全断言通过 | — |

图表 422 的根因在只读代码里核实：`src/backend/research/chart_data_source.py:365-393` 的 `load_table`
会先把**整张表每一列**都当数值校验，文本列（`变量`）先触发错误，`select_columns`（同文件 412 行）在其后；
因此不是 x/y 列选错，而是夹具表结构不满足“整表数值”。这是后端契约现状，e2e 用数值表规避。

## 9. 复现步骤

```bash
cd C:\Users\13067\Desktop\全能研究Agent

# 1) 一次性依赖（本机已完成；换机需重做）
npm i -D playwright@1.65.1 --no-audit --no-fund
npx playwright install chromium

# 2) 构建（dist 已存在时可跳过）
npm run build:frontend

# 3) 真实浏览器验收（默认模式；--keep 保留临时目录与证据）
node scripts/research_e2e.mjs --keep
echo $?        # 期望 0

# 4) 只跑 API 链路 / 只起服务
node scripts/research_e2e.mjs --api-only
node scripts/research_e2e.mjs --serve-only --duration=25
```

若 `npx playwright install chromium` 因网络失败，可用本机已有浏览器：

```bash
# Git Bash 示例：指向任意可用的 Chrome/Chromium
E2E_CHROMIUM_EXECUTABLE="/c/Users/13067/AppData/Local/ms-playwright/chromium-1255/chrome-win64/chrome.exe" \
  node scripts/research_e2e.mjs --keep
```

脚本会依次尝试：Playwright 自带浏览器 → `E2E_CHROMIUM_EXECUTABLE` → `%LOCALAPPDATA%\ms-playwright`
下最新 3 个 Chromium/headless-shell；全部失败才以退出码 3 结束，并打印每个尝试的错误与安装命令。

## 10. 本次脚本改动（`scripts/research_e2e.mjs`）

- 浏览器启动：新增 `launchChromium()` 与 `chromiumExecutableCandidates()`，支持自带浏览器、环境变量、
  本机已安装浏览器三级兜底；失败信息列出每个尝试路径与修复命令。
- 浏览器流程由“注入 token 直接进 `#research`”改为**真实 UI**：注册（切换注册模式/展开密码/昵称）→
  刷新验证登录态 → 登出 → 刷新验证未登录 → 用 API 主账号真实登录 → 刷新 → 进入 `#research`。
  断言强度只增不减（新增真实注册/登出/登录与 localStorage 清理检查）。
- 新增 SSE 断言：事件日志 ≥3 条、含 `task.started` 与终态、序号 >0、状态灯非「连接异常」。
- 新增图表 API 用例：`scatter_density` → 201 + PNG 魔数校验并保存 `api-chart.png`；
  能力关闭时按后端契约记录 `503 CHART_CAPABILITY_DISABLED`（不是 422）。
- 新增分步截图（`tmp/e2e-evidence/<stamp>-NN-*.png`）、失败截图同目录、总耗时日志、`finally` 关闭浏览器。
- `package.json` 仅新增 `devDependencies.playwright: ^1.65.1`；未改 `src/**`、未改后端、未降低任何断言。

## 11. 附录（Lead 追加，2026-11-20 16:42）

浏览器 E2E 交付后，Lead 补了两件当时报告标注"未覆盖"的事，并实测通过：

1. **图表前端 UI 接线**：新增 `src/frontend/src/components/research/ChartPanel.js`，
   并在 `ResearchWorkspace.js` 挂载（能力/表格/列映射/生成/结果校验信息）；`researchApi.js`
   增加 `createChart` 与 `fetchArtifactBlob`（blob 走带鉴权下载，不把 Bearer 拼进 `<img src>`）。
   面板对多张表给出显式「表格」选择，默认选第一张**全数值**表——分类表若被送去后端只会
   422 `CHART_NON_NUMERIC`，属诚实拒绝，不在前端伪造图。
2. **把图表前端纳入 E2E 断言**：`scripts/research_e2e.mjs` 新增第 [28] 步，断言面板标题、
   能力非关闭、识别到表格、生成按钮可用、点击后图片为 `blob:` 且 `naturalWidth>100`、
   校验信息含「重开校验通过 / PNG 摘要 / 值域」，并截图 `08-chart-panel.png`。

实测（本机，同一脚本 `node scripts/research_e2e.mjs`）：

| 项 | 结果 |
| --- | --- |
| 退出码 | **0**（PASS） |
| 图表面板 | 识别到 2 张表（表 1 非全数值、表 2 全数值），自动选表 2 |
| 生成结果 | 图片 1351×963，`blob:` objectURL |
| 校验信息 | 表格序号 1、行数 3、列映射 `年份 → 样本量, 编码一致性`、值域三项、`重开校验通过`、PNG 摘要 |
| 控制台错误 | 0 |
| 截图 | `tmp/e2e-evidence/20261120084205-08-chart-panel.png` |

同时修掉一个**真实的提交时序缺陷**（新 E2E 断言暴露，非图表专属）：

- 现象：`POST /research/exports` 返回 201 后立刻 `GET /artifacts/{id}/download` 偶发 **404**；
  另一处表现为上传成功后立刻建 review 任务偶发 `NOT_FOUND: 文档版本不存在`。
- 根因：`src/backend/db/session.py` 的 `get_db` 依赖在**响应发出之后**才 `commit`，客户端紧接着读
  自己刚创建的资源会撞上提交竞态。
- 修复：`src/backend/routers/research.py` 新增 `_commit(db)`，在 12 个写端点（项目建/改、上传/删除、
  来源、任务建/续跑/取消/重试、图表、采纳、导出）返回前显式提交。修复后连跑 3 次 E2E，导出下载与
  建任务不再 404。

因此本报告 §6 的"图表前端 UI 未覆盖"一条在本附录生效后不再成立；其余未覆盖项（窄屏、键盘操作、
双账号、有 findings 的卡片渲染）仍然成立。

## 12. 附录二（Lead，2026-11-21 02:2x）：E2E 复跑 exit 0 与两处环境修复

### 12.1 复跑结果

命令：`node scripts/research_e2e.mjs --keep`（默认浏览器模式，真实 Chromium headless 1440×1000）

| 项 | 结果 |
| --- | --- |
| 退出码 | **0（PASS）** |
| 总耗时 | 139.3 s（含等待后端就绪） |
| 浏览器控制台错误 | 0 |
| 图表 API | 201，`scatter_density` PNG 77,876 B，PNG 签名通过 |
| 图表前端面板 | 识别到 2 张表 → 生成 → `1351×963` 图，校验信息含「重开校验通过 / PNG 摘要 / 值域」 |
| 导出 | 201，`e2e-paper.md` 1,315 B，下载非空 |
| 截图 | `tmp/e2e-evidence/20261120182812-08-chart-panel.png` |

### 12.2 本轮修掉的两个环境级缺陷（非产品功能缺陷，但会让验收假阴性）

1. **向量预热饿死事件循环**：`src/backend/core/events.py` 的后台预热线程首次 `import torch/sentence-transformers` 会长时间持有 GIL，
   在核数有限的机器上把事件循环拖到 `/api/v1/health` 数分钟不可达。修复：新增配置 `DISABLE_VECTOR_PREWARM`（默认 `false`，E2E 隔离后端设为 `true`），
   跳过预热并记日志 `VectorService prewarm disabled by DISABLE_VECTOR_PREWARM`；RAG 仍在首次使用时懒加载。
2. **健康检查超时不可配置**：`waitForHealth` 原硬编码 90 s。修复：支持 `E2E_HEALTH_TIMEOUT_MS`（默认 180 s），并在超时错误里附带后端日志尾部。

> 说明：这两处都不改变产品行为，只影响"能不能稳定跑验收"。修之前同一脚本连续两次 exit 2（ENV-MISSING），修之后 exit 0。

## 13. 附录三（Lead，2026-11-21 20:0x）：`--a11y` 窄屏 / 键盘 / 双账号

- 命令：`node scripts/research_e2e.mjs --a11y --keep` → **exit 0（PASS）**，主浏览器链路 + 三段附加断言全部通过；截图 `tmp/e2e-evidence/a11y-01-narrow-research.png`、`a11y-02-keyboard-create.png`、`a11y-03-isolation.png`。
- 窄屏 390×844：`scrollWidth=409`、`innerWidth=409`（无横向溢出）；项目列表、工作区标题可见；图表卡片在无文档选中时不渲染。
- 键盘：仅用 `Tab`/`Enter`，80 次内命中「新建项目」→ Enter 把焦点送入 `.rw-create-form .rw-input` → 键入标题并回车 → 项目出现在列表。
- 双账号：同浏览器新 context 注册账号 B；B 的项目列表不含 A 的项目；B 直接请求 A 的项目 ID 得到 404 `NOT_FOUND`。
- 判定细化（避免环境噪音掩盖真实失败）：
  1. 控制台错误改为按 `requestfailed` 的 URL 归因：jsdelivr 外链在离线环境必然失败且控制台文本无 URL；只有出现本项目源（web 或 `/api/v1/`）的连接级失败才判失败。
  2. a11y 流程只把「非外链归因的 pageerror」计为失败（CodeMirror 未定义由外链失败连带产生）。
- 未覆盖：真机（iOS Safari / Android Chrome）、读屏软件、横屏/平板断点、触控手势。

## 14. 附录四（Lead，2026-11-21）：基础图表与分类轴 E2E

命令：`node scripts/research_e2e.mjs --keep`（默认真实浏览器模式，隔离后端 + E2E 夹具文档）

本轮新增断言（API 段，紧跟 `scatter_density` 之后）：

| 项 | 断言 | 实测 |
| --- | --- | --- |
| 分类柱状图 | `POST /research/charts`：`chart_type=bar`、`x_column=变量`、`y_columns=[均值]`、`table_index=0` → 201 | `art_8e247894665840fb88051f016b4696dd` |
| x 轴语义 | `validation.chart_type == "bar"`、`x_mode == "categorical"` | 通过 |
| 分类标签 | `x_labels` 长度 3、内容为表 0 第一列 | `样本量/编码一致性/复核覆盖率` |
| 数值保真 | `value_ranges` 不含分类列 `变量` | 通过 |
| 产物 | 下载 PNG 魔数通过并保存 `api-chart-bar.png` | 49,891 B |

浏览器 UI 段同时验证图表面板：表下拉把「表 1（变量 / 均值 / 标准差）」标为「· 分类轴」，类型下拉含「分类柱状图（支持文本 x 轴）」「分类折线图（支持文本 x 轴）」。

结果：**exit 0（PASS）**，脚本耗时约 2 分 20 秒（含浏览器全链路 + 分类轴断言）；日志 `tmp/e2e-bar.log`。

未覆盖：`line` 的浏览器 UI 断言（仅 API 覆盖）、饼图（未实现）、多单位共轴显示效果。
