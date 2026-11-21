# R2 浏览器 E2E 与发布链（T20 / AT-047·048·053）

记录时间：2026-11-20 11:45（+08:00）
环境：Windows，`node v24.16.0`、`npm 11.6.0`、`Python 3.14.5`（`.venv/Scripts/python.exe`）

> 本文件只记录**真实执行过**的命令与输出。记录时（11:45）浏览器验收**未运行**（Playwright 未安装）；
> 2026-11-20 16:02 已完成真实浏览器验收且 exit 0，见文末 §9 与 `R2_E2E_BROWSER.md`。
> 脚本层面的通过 ≠ Lead 手动浏览器验收。

## 1. 结论速览

| 项目 | 状态 | 证据（真实输出） |
| --- | --- | --- |
| 前端模块化构建 | 通过 | `npm run build:frontend` exit 0；vite v5.4.21，`✓ 50 modules transformed.`，`27 files, 643.6 KiB`，入口 `/assets/index-tucot6Q6.js` |
| API 全链路（注册→项目→上传→review→导出下载） | 通过 | `node scripts/research_e2e.mjs --api-only` exit 0；`quality_verdict=no_major_issues_found`、`findings=0`、导出 `1101 B` |
| 静态服务 + `/api`、`/ws` 同源代理自检 | 通过 | `--serve-only` exit 0；未带 token `401`，带 token `200`（18 项能力）；curl 复核 `health=200 / caps_unauth=401 / caps_auth=200` |
| Playwright 依赖检查 | 按契约失败 | 默认模式 exit **3**，打印 `npm i -D playwright && npx playwright install chromium` |
| 浏览器验收（真实点击 `#research` 工作区） | **未运行** | 无 Playwright；`dist/` + 代理服务可起，但未驱动浏览器 |
| Lead 手动浏览器验收 | **待执行** | 见 §6 清单 |

## 2. 交付物

| 文件 | 说明 |
| --- | --- |
| `scripts/research_e2e.mjs`（新建，1045 行） | 三种模式：默认浏览器验收、`--api-only`、`--serve-only`；另有 `--keep` / `--duration=N` / `--help` |
| `scripts/build-frontend.js`（重写，156 行） | 由“复制 `prototypes/interactive-prototype.html`”改为 `vite build`，并断言模块化入口/无原型标记/引用产物存在 |
| `package.json`（只改 scripts） | `build:frontend` 仍指向 `scripts/build-frontend.js`；新增 `test:research:e2e`；`build:frontend:dev` 改为 `--api-base=http://localhost:8000`（原先依赖未声明的 `cross-env`，必然失败） |
| `docs/reports/R2_E2E.md`（本文件，新建） | 真实命令、退出码、隔离边界、缺陷与限制 |

未改后端代码、未改前端页面/服务，未新增 `data-testid`（浏览器断言只用既有 `aria-label` 与文案）。
`package.json` 依赖未改动。

## 3. 真实运行命令与输出

### 3.1 构建链

```bash
node scripts/build-frontend.js          # 等价 npm run build:frontend
```

真实输出（节选）：

```text
vite v5.4.21 building for production...
✓ 50 modules transformed.
✓ built in 1.85s
[build-frontend] build artifacts (27 files, 643.6 KiB):
✓ Frontend built to dist/ (vite, module entry /assets/index-tucot6Q6.js)
```

断言结果：`dist/index.html` 含 `<script type="module" src="/assets/index-tucot6Q6.js">`；
`grep -c 'icons.browser.js|name="api-base"|v20260709' dist/index.html` = **0**（不含原型 HTML 标记）；
引用的 `/assets/*` 均存在。退出码 0。

`node scripts/build-frontend.js --api-base=http://localhost:8000` 也已实测 exit 0（API base 被写进产物并命中断言），
随后重跑默认构建恢复相对路径产物（入口回到 `index-tucot6Q6.js`）。

### 3.2 API 全链路（非浏览器验收）

```bash
node scripts/research_e2e.mjs --api-only
```

真实输出（节选）：

```text
[e2e] [3] 启动隔离后端（127.0.0.1:<port>，临时 DB：…\tmp\e2e-run-<id>\e2e.db）
[e2e]     后端 /api/v1/health 200
[e2e] [4] 启动静态服务 + /api、/ws 同源代理（127.0.0.1:<port>）
[e2e] [6] API：注册 + 登录
[e2e]     用户 e2e-<ts>@example.com（id=1）登录成功，entitlements={"plan":"free",…,"pipeline_access":{"generation":false,"external_review":false,"modification":false}}
[e2e] [7] API：读取能力清单（登录前 free 计划应为 unauthorized）
[e2e]     task.review=unauthorized，model.llm=degraded
[e2e] [8] API：写入 review 权益夹具（隔离 DB，不改后端代码）
[e2e]     能力：task.review=ready，model.llm=degraded，不可用项=task.draft_from_outline,task.revision,code_execution,browser_agent
[e2e] [10] API：上传 Markdown 文档（标题/段落/管道表）
[e2e]     文档 rdoc_a4a3184398a34cf3aabb7ce34e5118d9，版本 rver_d29187f22ed34600b22e23ff0edcd94d，379 codepoints，parse_status=complete
[e2e] [11] API：创建 review 诊断任务并等待终态
[e2e]     任务终态 status=succeeded，quality_verdict=no_major_issues_found，attempt_no=1
[e2e] [12] API：读取诊断项
[e2e]     findings=0，next_cursor=null
[e2e] [13] API：导出 Markdown 并校验下载非空
[e2e]     下载内容首行：数字化时代的学术写作：证据链与方法透明度
[e2e]     导出 art_df163a0ef7a043e586ca117bcec02408：e2e-paper.md，1101 B，校验=n/a
[e2e] API 全链路通过（未驱动浏览器，不能作为浏览器验收结论）。
```

退出码 0；临时目录（含 sqlite、上传文件、日志、chroma 目录）已清理，无残留 `tmp/e2e-run-*`。

要点：

- 替身模型（`RESEARCH_MODEL_STUB=true`）返回 0 findings + notes，报告仍生成；
  本文档夹具含标题、段落、一张管道表与 **引言/方法/结论/参考文献** 四章节，结构完整性检查也不产出 finding。
- free 用户默认 `task.review=unauthorized`，前端会禁用“开始全文诊断”；脚本在**隔离 DB**里写
  `user_quotas.external_review_expires_at`（30 天后）作为夹具，再断言 `task.review=ready`。
  这是测试夹具，不是产品后门，也未修改后端代码。
- 导出正文的 Markdown 标题不带 `#` 前缀（首行是标题正文），脚本按正文标题校验，不按 `#` 校验。

### 3.3 serve-only 自检（服务可起，但不等于浏览器验收）

```bash
node scripts/research_e2e.mjs --serve-only --duration=25
```

真实输出（节选）：

```text
[e2e]     未带 token：HTTP 401（{"error":{"code":"AUTHENTICATION_FAILED","message":"需要登录后使用研究功能。",…}}）
[e2e]     带 token：HTTP 200，capabilities=18 项
[e2e] serve-only 自检通过，服务地址：http://127.0.0.1:<port>/#research（后端 http://127.0.0.1:<port>）
[e2e] 保持服务 8 秒后退出（可用 curl 复核）
```

服务存活期间用 `curl` 复核（另一次运行的服务）：

```text
--- GET / ---                    200，返回 dist/index.html（<title>ScholarMind - 智能学术研究助手</title>）
--- health ---                  health=200
--- capabilities 无 token ---    caps_unauth=401
--- 注册并带 token ---           token_len=140
--- capabilities 带 token ---    caps_auth=200
```

退出码 0。`--serve-only` 用 `dist/` 起 Node 静态服务，`/api`（HTTP）与 `/ws`（upgrade）同源代理到隔离后端，
**未使用 vite dev server**。

### 3.4 默认浏览器模式（当前环境真实结果：exit 3）

```bash
node scripts/research_e2e.mjs            # 等价 npm run test:research:e2e
```

真实输出：

```text
[e2e] [1] 检查 Playwright（浏览器验收硬依赖）
[e2e] 缺少浏览器驱动：playwright 未安装或不可用。
[e2e] 安装命令：npm i -D playwright && npx playwright install chromium
```

退出码 **3**（未假装通过）。本机 `npm ls playwright --depth=0` 为空；
按要求未安装依赖、未用 curl 冒充浏览器。

## 4. 退出码

| 码 | 含义 | 实测 |
| --- | --- | --- |
| 0 | 通过（浏览器链路全部断言通过；`--api-only` / `--serve-only` 自检通过） | 构建 0；`--api-only` 0；`--serve-only` 0 |
| 1 | 断言失败（含 API 链路失败、页面断言失败、导出为空等） | 未触发 |
| 2 | 环境/依赖缺失（无 `dist`、无模块化入口、python 依赖不全、后端启动失败/健康检查超时） | 未触发 |
| 3 | Playwright 未安装/Chromium 起不来 | **实测 3** |

失败时的行为：浏览器链路失败会保存 `tmp/e2e-fail-<时间戳>.png`（整页截图），打印浏览器控制台错误与
`backend.log` 尾部；默认清理临时目录（`--keep` 保留）。

## 5. 隔离边界与实现要点

- **临时目录放在仓库 `tmp/`，不放系统 Temp**：早期探针在
  `C:\Users\<user>\AppData\Local\Temp\…\uploads` 建目录时后端启动抛出
  `PermissionError: [WinError 5] 拒绝访问`（`src/backend/config.py` 的 `ensure_dirs()`），
  改到仓库内 `tmp/e2e-run-<随机>` 后稳定。
- 后端命令固定为：
  `python -m uvicorn src.backend.app:create_app --factory --host 127.0.0.1 --port <p> --log-level warning`，
  子进程 stdio 写入临时目录 `backend.log`。
- 显式 env 覆盖（保证不连生产库/开发服务）：
  `DATABASE_URL=sqlite+aiosqlite:///<tmp>/e2e.db`、`DB_PATH`、`UPLOAD_DIR`、`CHARTS_DIR`、
  `CONVERSATIONS_DIR`、`CHROMA_DIR`、`SKILLS_DIR` 全部指向临时目录；
  `RESEARCH_MODEL_STUB=true`、`ENVIRONMENT=test`、`ENABLE_VERIFIED_CHARTS=true`；
  `DEEPSEEK_API_KEY=sk-e2e-local-probe`、`DEEPSEEK_BASE_URL=http://127.0.0.1:1`（让 `model.llm=degraded`，
  通过前端 gate，同时连接立即失败、不发外网请求）；`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`；
  `REDIS_URL=redis://127.0.0.1:1/0`（不连开发 Redis）。
- **`.env` 说明（限制）**：`src/backend/config.py` 的 `SettingsConfigDict(env_file=WORKSPACE_ROOT/'.env')`
  在导入时仍会读取仓库 `.env`。上述所有连接相关键都被显式环境变量覆盖（pydantic-settings 中 env 优先），
  因此不会连开发库/Redis/模型，但“完全不读开发 `.env`”需要后端提供测试加载方式（见 §7）。
- **进程树清理**：Windows 上 `.venv/Scripts/python.exe` 会再拉起真实解释器子进程，只 `kill` 父进程会留下
  子进程并锁住 sqlite WAL（实测残留 `PID 37496/44740`、`e2e.db: Device or resource busy`）。现在退出时用
  `taskkill /PID <pid> /T /F` 杀整棵树，并以 `netstat -ano` 监听端口兜底，再清理临时目录；修复后
  实测“无残留 `tmp/e2e-run-*`、无残留 `src.backend` 进程”。
- 浏览器模式：Chromium `headless`，`addInitScript` 写入 `localStorage.sm_token` / `sm_refresh_token` / `sm_user`，
  打开 `http://127.0.0.1:<web>/#research`；断言只用页面既有 `aria-label`/文案（未新增 testid）。

## 6. “脚本跑通” 与 “Lead 手动浏览器验收” 分开记录

### 6.1 脚本已跑通的部分（2026-11-20）

1. `npm run build:frontend` exit 0，产出模块化 `dist/`（无原型标记）。
2. `node scripts/research_e2e.mjs --api-only` exit 0：API 注册/登录、权益夹具、项目、上传、review 终态、
   findings 空、导出下载 1101 B。
3. `node scripts/research_e2e.mjs --serve-only --duration=25` exit 0：`dist/` 静态服务 + `/api`/`/ws` 代理，
   能力 401/200；curl 复核 200/401/200。
4. `node scripts/research_e2e.mjs` exit 3：Playwright 缺失，打印安装命令，未伪造通过。

### 6.2 浏览器验收：未运行（待 Lead 执行）

本机没有 Playwright，因此以下浏览器断言**只写进脚本、未执行**：

- `h1.rw-title` = 「研究工作区」；头部能力 pill 非「能力状态未知/未上报」，匹配 `能力就绪|项能力不可用`；
- 能力面板 `.rw-cap-row` ≥ 5；项目列表出现刚建的项目；上传的 `e2e-paper.md` 在文档卡可见并选中；
- 填诊断目标 → 「开始全文诊断」可用 → 点击；诊断卡出现「问题与依据（0）」+「已完成」+「没有可展示的问题」；
- 导出 md（附诊断报告）→ 点「下载文件」→ 下载非空、含标题正文、文件名为 `.md`；控制台无真实错误。

Lead 手动验收步骤（建议）：

```bash
npm i -D playwright && npx playwright install chromium
npm run build:frontend
npm run test:research:e2e        # 期望 exit 0；失败会留 tmp/e2e-fail-*.png
```

人工复核：浏览器打开脚本日志里的 `http://127.0.0.1:<web>/#research`（需在 `--serve-only` 运行期间），
确认项目/文档/诊断报告/导出下载与 `R2_INTERFACE_SPEC` 期望一致，并在本文件追加“人工验收”记录。

## 7. 已知缺陷与限制（不隐瞒）

1. **后端缺陷：`GET /tasks/{id}/findings` 在存在 structural finding 时 500**
   `pydantic_core ValidationError … verification_method … input_value='structural'`。
   链路：`src/backend/research/review_workflow.py:647` 写入 `verification_method="structural"`，
   `src/backend/research/task_service.py:780` 用 `Finding(...)` 校验，而
   `src/backend/research/contracts.py:146-150` 的 `VerificationMethod` 只有 `tool/model/human/none`。
   触发：`src/backend/research/completeness.py:175 document_level_findings()` 对必备章节
   （引言/方法/结论/参考文献）做子串匹配，缺任一即产出 document 级 finding。
   影响：缺失必备章节的文档，前端诊断卡会显示「诊断项读取失败」。
   e2e 规避：夹具文档补齐四章节，使 structural findings=0（导出直读 DB 行，不受此 bug 影响）。
   **修复需要后端 owner 处理（e2e 写范围禁止改后端）。**
2. 导出 Markdown 会去掉标题的 `#` 前缀（实测首行是正文标题，`## 引言` 变「引言」），脚本按正文校验。
   这是导出器现状，是否需要调整由 lead 判定。
3. 导出响应未带 `validation.status`（脚本显示 `校验=n/a`），不影响下载校验。
4. `--api-only` / `--serve-only` 是补充排障手段，**不能**作为浏览器验收结论。
5. 浏览器断言基于页面源码中的 `aria-label` 与文案；若后续页面文案/结构改动，断言需同步。
6. 脚本使用随机空闲端口与仓库内临时目录；CI 未接入（本轮未改 workflow）。

## 8. 复现（当前环境）

```bash
# 1) 构建
npm run build:frontend

# 2) API 全链路（无需浏览器）
node scripts/research_e2e.mjs --api-only

# 3) 服务自检（25 秒后自动退出；期间可 curl）
node scripts/research_e2e.mjs --serve-only --duration=25

# 4) 浏览器验收（本机当前预期 exit 3）
npm run test:research:e2e
```

## 9. 2026-11-20 16:02 更新：真实浏览器验收已通过

> 本节取代 §2 末尾“`package.json` 依赖未改动”、§3.4（默认模式 exit 3）、§4 表中“实测 3”、
> §6.1 第 4 条、§6.2“浏览器验收未运行”、§8 末尾“预期 exit 3”的旧状态。旧内容保留为历史记录，
> 最新结论以本节与 [`R2_E2E_BROWSER.md`](R2_E2E_BROWSER.md) 为准。

- 已在仓库根执行 `npm i -D playwright@1.65.1 --no-audit --no-fund` 与 `npx playwright install chromium`，
  `package.json` 新增 `devDependencies.playwright: ^1.65.1`（未改 `dependencies`、未改业务代码）。
- `node scripts/research_e2e.mjs --keep` 真实运行 **exit 0**，脚本内部耗时 **34.7 s**，墙钟 **38.3 s**；
  日志 `tmp/r2-browser-run` 系列的最终轮为 `tmp/r2-browser-final2.log`，保留目录 `tmp/e2e-run-pAZXeR/`。
- 浏览器链路真实覆盖：真实 UI 注册 → 刷新断言登录态 → 登出（清理 token/user，刷新后回到未登录）→
  真实 UI 登录 API 主账号 → `#research` 工作区 → 项目/文档选择 → 发起 review → **SSE 5 条事件**
  （task.accepted/task.started/task.progress/artifact.created/task.completed，序号 5）→
  诊断报告 0 findings 空态（问题与依据（0）、已完成、没有可展示的问题）→ 导出 md 并真实下载 1315 B
  （文件名 `.md`、含标题正文）→ 页面真实控制台错误 0 条。
- API 链路同轮覆盖：项目/上传 201+201、任务 202→succeeded、findings=0、导出 201、图表 201
  （scatter_density PNG 77876 B，PNG 签名通过，已保存 `tmp/e2e-run-pAZXeR/api-chart.png`）。
- 7 张真实页面截图见 `R2_E2E_BROWSER.md` §5；**未覆盖项**（窄屏/键盘/双账号/有 findings 的渲染/
  图表前端 UI/真实模型/断线重连等）已在 `R2_E2E_BROWSER.md` §6 明确列出，不能据此宣称这些项通过。
- 调试中 4 次浏览器失败与 1 次图表 422 的原始错误与修正见 `R2_E2E_BROWSER.md` §8；
  失败均保留日志与失败截图，最终通过没有降低断言强度。
- 仍待 Lead 执行：人工打开真实页面复核视觉/交互，并按 `docs/reports/R2_INTERFACE_SPEC` 验收。
