# ScholarMind - 全能研究 Agent

面向高校科研人员的智能学术研究助手，基于 RAG + LangGraph + 6 层企业架构。

## 核心功能

- **5 Agent 协作**：研究员 / 审查员 / 架构师 / 综述员 / 润色员，覆盖选题 → 审查 → 架构 → 综述 → 润色全流程
- **13 Agent 循环式论文精炼 Pipeline（v7.0）**：GAN 对抗评分驱动，支持 6 种研究类型 + 4 种 CSSCI 期刊格式
- **8 个预设技能 + 自定义技能扩展**
- **12 种 Origin 风格学术图表**
- **6 层企业架构**：多级降级、熔断器保护、Prometheus 监控

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI · LangGraph · DeepSeek · ChromaDB · RAG · Celery+Redis · SQLAlchemy · WebSocket · Matplotlib |
| 前端 | React · Vite · TailwindCSS · CodeMirror · Marked |
| 原型 | 单文件 HTML（`prototypes/interactive-prototype.html`） |

## 目录结构

```
AI产品/
├── prototypes/                  # 交互原型（单 HTML 文件，火山主题）
│   └── interactive-prototype.html
├── src/
│   ├── backend/                 # FastAPI 后端
│   │   ├── app.py               # 应用入口
│   │   ├── config.py            # 配置（读 .env）
│   │   ├── routers/             # API 路由
│   │   ├── services/            # 业务服务层
│   │   ├── models/              # Pydantic Schema / ORM / 枚举
│   │   ├── db/                  # 数据库仓储与会话
│   │   ├── crawlers/            # 文献爬虫（CNKI/WoS/PubMed/CrossRef）
│   │   ├── scheduler/           # Celery 调度层：定时任务（文献抓取/订单过期等周期任务）
│   │   ├── tasks/               # Celery 业务任务层：异步图表生成等用户触发的异步任务
│   │   └── ab_testing/          # A/B 测试框架
│   └── frontend/                # React 前端
│       └── src/
│           ├── pages/           # 页面组件
│           ├── components/      # 通用组件
│           ├── services/        # API 封装
│           ├── app/             # store / router
│           └── utils/           # 工具函数
├── data/                        # 运行时数据（已 gitignore）
├── .env                         # 环境变量（已 gitignore，需手动创建）
├── .mcp.json                    # MCP 配置（已 gitignore）
└── .gitignore
```

## 安装与运行

### 前置条件

- Python 3.10+
- Node.js 18+
- Redis（可选，用于 Celery 任务队列）

### 后端

```bash
cd src/backend
pip install -r requirements.txt

# 配置环境变量（从 .env.example 复制并填入真实密钥）
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 等

# 应用工厂模式启动（推荐）
uvicorn src.backend.app:create_app --factory --host 127.0.0.1 --port 8000
# 后端默认运行在 http://localhost:8000
# 或直接使用项目根目录的 start.bat 一键启动
```

### 产品主界面（当前默认）

通过 `start.bat` 或 `start.ps1` 启动后访问：

```text
http://localhost:8000/app/interactive-prototype.html
```

这里是当前完整功能与最新 UI 的统一入口。

### 工程版前端（迁移开发）

```bash
cd src/frontend
npm install
npm run dev
# 前端默认运行在 http://localhost:5173
```

### 主界面静态预览

直接打开 HTML 仅可做视觉预览；手机号登录、历史记录、额度和支付必须通过
`http://localhost:8000/app/interactive-prototype.html` 使用。

### 账户与套餐

- 手机号 + 自定义密码注册/登录；新账号自动获得 20 次免费 Agent 对话。
- ¥4.99：1 次论文生成 Pipeline。
- ¥19.99：5 次论文生成/修改共享额度，并开通 30 天外审专家。
- ¥39.90：30 天全功能、不限对话与 Pipeline，使用 Flash 模型。
- ¥59.90：30 天全功能 Pro、不限对话与 Pipeline，默认使用 Pro 模型。

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（必需） | - |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 默认模型名 | `deepseek-chat` |
| `DEEPSEEK_MODEL_FLASH` | Flash 模型名（前端 toggle 切换，免费/Pro 默认走此模型） | `deepseek-v4-flash` |
| `DEEPSEEK_MODEL_PRO` | Pro 模型名（Pro 用户 toggle 切换） | `deepseek-v4-pro` |
| `SKILLS_DIR` | 技能目录路径 | `data/skills` |
| `SKILL_SOURCE_DIRS` | 只读外部 Skill 根目录列表，递归读取 `SKILL.md` | `C:/Users/13067/.trae-cn/skills` |
| `DATABASE_URL` | 数据库连接 | `sqlite+aiosqlite:///data/scholarmind_orm.db` |
| `REDIS_URL` | Redis 连接 | `redis://localhost:6379/0` |
| `PASSWORD_MIN_LENGTH` | 密码最小长度 | `8` |
| `DEBUG` | 调试模式 | `true` |
| `CODE_EXECUTION_ENABLED` | 代码执行入口总开关（P0 安全）。`false` 时 `/api/v1/code-execution/*` 路由完全不注册（返回 404）；`true` 时注册但强制 `require_admin` 鉴权 + 审计日志。**生产环境默认关闭**，仅在受控内部环境且确需在线代码沙箱时显式设为 `true`。`/pip-install` 端点已永久移除，任何环境都不可用 | `false` |
| `JWT_SECRET_KEY` | JWT 签名密钥，生产环境至少 32 字符 | - |
| `LLM_PROXY_BASE_URL` | 可选：模型调用经本地上下文压缩代理（billion-context）转发，留空=直连。示例 `http://127.0.0.1:8790/bili/https://api.deepseek.com/v1`。启动与实测见 [docs/reports/BILLION_CONTEXT.md](docs/reports/BILLION_CONTEXT.md)；正常流量原样转发，不省 token | 空 |
| `LLM_PROXY_SESSION_HEADER` | 代理会话头名，需与代理配置 `sessionHeader` 一致 | `x-acp-session` |
| `LLM_PROXY_TIMEOUT_SECONDS` | 启用代理时的客户端超时（折叠历史会发侧请求，需更长） | `180` |

| `PAYMENT_ENABLED` | 支付总开关。`false` 时仍可读取商品目录，但下单返回 503、回调拒绝处理；配置真实商户凭证后设为 `true` | `false` |
| `PAYMENT_VERIFY_REQUIRED` | 支付回调是否强制验签。`true`（默认）时无签名或签名失败一律返回 `failure`；`false` 仅用于本地联调，生产环境必须为 `true` | `true` |
| `ALIPAY_APP_ID` / `ALIPAY_PRIVATE_KEY` / `ALIPAY_PUBLIC_KEY` | 支付宝应用 ID、应用私钥和支付宝公钥；PEM 可直接填写或使用绝对文件路径 | - |
| `ALIPAY_SELLER_ID` | 支付宝卖家 ID，用于回调商户校验 | - |
| `WECHAT_PAY_APP_ID` / `WECHAT_PAY_MCH_ID` | 微信应用 ID 与商户号 | - |
| `WECHAT_PAY_PRIVATE_KEY` / `WECHAT_PAY_CERT_SERIAL_NO` | 微信商户 API 私钥与证书序列号 | - |
| `WECHAT_PAY_APIV3_KEY` | 微信 API v3 密钥，用于回调报文 AES-GCM 解密 | - |
| `WECHAT_PAY_PLATFORM_PUBLIC_KEY` | 微信支付平台公钥（也可配置 `WECHAT_PAY_PLATFORM_CERT`） | - |
| `ADMIN_USERNAMES` | 管理员用户名白名单（逗号分隔），用于 `require_admin` 依赖判定代码执行等高危端点的访问权限 | `admin` |

## 外部 Skills 与 Browser Agent

应用启动后会递归注册 `C:/Users/13067/.trae-cn/skills` 下的全部 Skill 定义。外部 Skill 以只读方式加载，不会复制或修改该目录；只有在 Web 对话中显式选择后，才会注入该 Skill 的 `SKILL.md` 内容。

- `GET /api/v1/skills`：登录后获取可用 Skill 清单
- `GET /api/v1/skills/{skill_id}`：登录后获取某个 Skill 的完整规则
- `/api/v1/agent/chat`、`/api/v1/agent/stream` 支持 `skill_ids` 字段，前端已提供按需选择器
- `POST /api/v1/browser-agent/command`：登录后通过安全白名单调用本机 `agent-browser` CLI；不支持任意 Shell、`eval` 或路径穿越

Browser Agent CLI 路径可通过 `AGENT_BROWSER_BIN` 覆盖。浏览器会话按 ScholarMind 会话 ID 隔离，下载、截图和 PDF 输出应使用相对路径。

## 架构决策

### 原型 vs 正式前端

当前阶段以 `prototypes/interactive-prototype.html` 为产品主界面（功能完整、最新 UI 在此落地）。`src/frontend` 为工程化迁移版本，不作为 `start.bat` 默认打开页面。

### `scheduler/` 与 `tasks/` 职责区分

项目同时存在两个 Celery 相关目录，**故意未合并**（合并涉及多模块路径重写，风险较高，待后续重构专项处理）：

- `src/backend/scheduler/`：**调度层**。承载周期性定时任务（文献抓取、过期订单清理等），由 Celery Beat 触发。
- `src/backend/tasks/`：**业务任务层**。承载用户行为触发的异步任务（异步图表生成等）。

两者各自持有 `celery_app.py` 实例（已知冗余，后续重构将统一为单一 Celery 实例并通过 `task_routes` 区分队列）。

## 安全须知

- `.env`、`.mcp.json`、`cookies.json` 已在 `.gitignore` 中，**切勿提交真实密钥**
- 若密钥曾泄露，请立即到对应平台吊销并重新生成
- 前端渲染用户输入时使用 DOMPurify 清洗（防 XSS）
- **代码执行入口默认关闭**（`CODE_EXECUTION_ENABLED=false`）：`/api/v1/code-execution/run` 与 `/pip-install` 在默认配置下返回 404。仅在受控环境且需要在线代码沙箱时显式启用，启用后仍强制管理员鉴权 + 审计日志；`/pip-install` 已永久移除。
- **支付默认安全关闭**（`PAYMENT_ENABLED=false`）：商品目录仍可展示，但无法创建订单，支付宝/微信回调也不会查询或升级订单。启用后执行平台验签、商户/金额校验、微信报文解密和幂等权益发放。

## License

私有项目，未授权分发。

## 启动方式

### 一键启动（推荐）

双击项目根目录的 `start.bat` 即可，脚本会自动完成以下操作：

1. 检查 Python 环境与虚拟环境（`src/backend/.venv`，存在则激活，否则使用系统 Python）
2. 检查 `langgraph` 依赖（未安装时给出提示，但不阻塞启动）
3. 后台启动 FastAPI 后端（`uvicorn src.backend.app:create_app --factory --host 127.0.0.1 --port 8000`，工厂模式 + 仅绑定本机回环）
4. 等待 3 秒后自动打开浏览器访问 `http://localhost:8000/app/interactive-prototype.html`

> **为什么用 `start.bat` 而非直接双击打开 HTML？**
>
> 通过 `file://` 协议打开 `prototypes/interactive-prototype.html` 时，浏览器 origin 为 `null`，会被 CORS 策略拦截，导致前端无法调用后端 API（界面一直停留在"离线模式"）。`start.bat` 利用 `app.py` 中的静态文件挂载（`/app` → `prototypes/`）以同源（same-origin）方式提供前端页面，彻底规避 CORS 跨域问题。

启动后可在控制台窗口查看后端运行日志，按 `Ctrl+C` 终止后端服务（或直接关闭窗口）。
