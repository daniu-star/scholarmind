# 部署状态与验收记录（www.quannengyanjiu.cn）

> 记录时间：2026-11-27 13:45（Asia/Shanghai）
> 结论：**前端已上线并加载模块化产物；API 经 Cloudflare 隧道回源到本机后端，可用。**

## 1. 当前拓扑

| 层 | 位置 | 说明 |
| --- | --- | --- |
| 前端 | Vercel 项目 `scholarmind`（`prj_q54TKTkfOFFMsUmSepdGerirNxie`，团队 `daniu-stars-projects`） | 生产别名 `https://www.quannengyanjiu.cn`；构建产物 `dist/`（Vite，入口 2,299 B 的 `index.html` + `/assets/index-*.js`） |
| API 代理 | `vercel.json` 的 `/api/*` rewrite | 指向 Cloudflare 快速隧道 `https://<随机>.trycloudflare.com/api/$1` |
| 后端 | 本机 `uvicorn src.backend.app:create_app --factory --port 8020` | 由 `cloudflared tunnel --url http://127.0.0.1:8020` 暴露；`/api/v1/readyz` 探活 |
| 数据 | 本机 SQLite `C:/smdeploy_runtime/scholarmind_public.db` | 迁移头 `m6_research_attempt_checkpoint`；上传目录 `C:/smdeploy_runtime/uploads` |

Railway 侧：项目 `resplendent-illumination` 仍存在，但**试用已到期**，`scholarmind`/`celery-worker`/`celery-beat` 部署为 `FAILED` 且无法重新部署；`Postgres`/`Redis` 只有内网地址（`postgres.railway.internal`），没有公网端口。因此本轮没有走 Railway。

## 2. 线上验收证据（2026-11-27 13:37–13:46）

| 检查 | 结果 |
| --- | --- |
| `GET https://www.quannengyanjiu.cn/` | 200，`index.html` 2,299 B，入口 `/assets/index-yMsRCndM.js`，无旧原型 `api-base` 残留 |
| `GET /api/platform-status` | 200 `{"status":"ok","backend":"ok","database":true,"detail":"All systems operational"}` |
| `GET /api/v1/readyz`（公网） | 200 |
| `GET /api/v1/research/capabilities`（匿名） | 401（符合预期） |
| 注册 + 登录（公网 API） | 200，`/api/v1/auth/me` 200 |
| 浏览器登录（Chrome，`#auth` → `#homepage`） | 成功，`localStorage.sm_token`/`sm_user` 写入 |
| 浏览器打开 `#research` | 能力面板正常：授权前「6 项能力不可用 / 2 项降级」，给测试账号开通 `monthly_pro` 后「3 项能力不可用 / 2 项降级」，`全文诊断任务` 由「无权限」变为「可用」 |
| 真实诊断链路（公网 API，真实模型） | `project 201 → upload 201 → task 202 → succeeded`，`quality_verdict=issues_found`，覆盖率 6/6，诊断项 7 条（3 条 critical 命中刻意设置的缺陷：日志两周却推长期效应、便利样本却称全国推广、相关却下因果结论） |

诊断任务：`task_962b3156c5394151adc92745c2ea7401`（测试账号 `deploy-check-1795757964@example.com`）。

## 3. 本轮提交

| 提交 | 内容 |
| --- | --- |
| `bb119da` | Vercel 构建安装前端依赖（`installCommand`） |
| `bbeea08` | CI 改用 `npm --prefix src/frontend ci`，修 `frontend-build`/`research-gate` |
| `7812dcf`（main） | Vercel 只安装前端工作区，避免根 `playwright` devDependency 让安装失败 |
| `396c925` | `vercel.json` 的 `/api/*` rewrite 与 `api/platform-status.js` 的默认后端指向隧道；新增 `scripts/point_backend.py` |
| `94e1ca6`（main） | 把上述改动合并进 `main` |

`main` 已推到 `94e1ca6`；工作区其余改动仍是你原有的未提交内容，没有动。

## 4. 重要限制（必须知道）

1. **后端跑在这台电脑上。** 关机、睡眠或退出会话后，`https://www.quannengyanjiu.cn/api/*` 会返回 503/404。隧道进程与后端进程目前是本会话的后台任务。
2. **Cloudflare 快速隧道域名每次重启都会变。** 变了下一次要执行：
   ```bash
   python scripts/point_backend.py https://<新隧道域名>
   npm run build:frontend
   bash /c/vtmp/vc.sh build --prod
   bash /c/vtmp/vc.sh deploy --prebuilt --prod --yes
   ```
3. **数据是本地 SQLite**（`C:/smdeploy_runtime/scholarmind_public.db`），不是 Railway Postgres；换机器不会带走数据。
4. **Vercel 没接 Git 集成**：`git push` 不会自动上线，必须像上面那样用 CLI 部署。
5. 测试账号 `deploy-check-1795757964@example.com` 的 `monthly_pro` 是直接写本地库开通的（仅用于验收），不代表真实付费流程。

## 5. 如果要「长期稳定」

| 方案 | 代价 | 效果 |
| --- | --- | --- |
| Railway Hobby（$5/月） | 恢复现有 `scholarmind` 服务 + Postgres/Redis | 域名不变、后端 7×24、数据在云上 |
| 任意 VPS / 云托管（Dockerfile 已在仓库） | 一台小机器 | 同上，可控性更好 |
| 保留本机 + 隧道 | 0 元 | 电脑必须常开，隧道域名会变 |

## 6. 复现与排障

```bash
# 1) 起后端（本机）
bash /c/vtmp/run-backend.sh          # uvicorn 127.0.0.1:8020
# 2) 起隧道
/c/vtmp/cloudflared.exe tunnel --url http://127.0.0.1:8020 --no-autoupdate
# 3) 让前端指向隧道并部署
python scripts/point_backend.py https://<隧道域名>
npm run build:frontend && bash /c/vtmp/vc.sh build --prod && bash /c/vtmp/vc.sh deploy --prebuilt --prod --yes
# 4) 验收
curl -s https://www.quannengyanjiu.cn/api/platform-status
```

已知历史坑：Vercel CLI 在本机会因主机名含中文而崩（`byteString ... 20113`），必须用 `node --require /c/vtmp/fixhost.cjs .../vc.js`；`npm` 在 MSYS 里要用 `npm.cmd`；WSL systemd 用 interop 启动 Windows 进程时不会传播自定义环境变量，SQLite 路径必须落到 `PROJECT_ROOT` 默认位置或显式写在 ExecStart 的 `env` 变量里（详见 §7.2）。

## 7. 2026-11-28 稳定性加固与数据路径修复

> 触发：上一轮结束时，本机后端与 cloudflared 随会话进程一起退出，线上 `/api/platform-status` 变为
> `{"status":"degraded","detail":"Backend unreachable: fetch failed"}`。

### 7.1 常驻方式：WSL systemd（替代会话内进程）

| 单元 | 作用 | 关键配置 |
| --- | --- | --- |
| `/etc/systemd/system/scholarmind-backend.service` | 后端 8020 | `WorkingDirectory=/mnt/c/Users/13067/Desktop/全能研究Agent`；`ExecStart=/usr/bin/env … /mnt/c/.../.venv/Scripts/python.exe -m uvicorn src.backend.app:create_app --factory --host 127.0.0.1 --port 8020`；`Restart=always` |
| `/etc/systemd/system/scholarmind-tunnel.service` | Cloudflare 快速隧道 | `ExecStart=/mnt/c/vtmp/cloudflared.exe tunnel --url http://127.0.0.1:8020 --no-autoupdate --logfile C:\vtmp\cloudflared-svc.log`；`Restart=always` |

- 两个单元均 `systemctl enable --now`，重启 WSL/机器后自动恢复（`wsl --shutdown` 后需等系统启动，`systemctl` 自动拉起）。
- 已放弃的方案：`schtasks`（任务一直 `Queued` 不执行）、会话内 `Start-Process`（会话结束即被杀）。
- 当前隧道地址：`https://tribute-devel-capability-lips.trycloudflare.com`（每次隧道重启会变，需 `scripts/point_backend.py` + 重新部署）。

### 7.2 数据路径修复（真实缺陷）

现象：进程健康、`/api/v1/readyz` 显示 `database.connected=true`，但 `POST /api/v1/auth/login` 对既有账号返回
`AUTHENTICATION_FAILED`。

根因：`src/backend/config.py` 的 SQLite 相对路径会按 `PROJECT_ROOT`（= `src/backend/`）重建绝对 URL；而 WSL systemd 通过 interop 启动的 **Windows** 进程不继承 systemd 的 `Environment=`（自定义环境变量没有通过 WSLENV 传播），
于是 `DATABASE_URL` 未生效，进程回落到默认库 `src/backend/data/scholarmind_orm.db`（一个空库）。

修复：把线上数据放到默认库路径（不依赖环境变量传播）——`src/backend/data/scholarmind_orm.db`
（备份旧空库于 `C:/vtmp/scholarmind_orm.db.bak`，原数据副本保留在 `C:/smdeploy_runtime/scholarmind_public.db` 与仓库 `smdeploy_runtime/scholarmind_public.db`）。
修后立即验证：登录 200、`/api/v1/research/projects` 返回 3 个历史项目。

### 7.3 Vercel 侧网络绕行与 token 刷新

- `api.vercel.com`、`github.com` 间歇 TCP 超时，而 `vercel.com` 正常；`https://vercel.com/api` 可作为同一 API 网关。
- access token 过期后，用 `POST https://vercel.com/api/login/oauth/token`（`client_id=cl_HYyOPBNtFMfHhaUn9L4QPfTZz6TP47bp`、`grant_type=refresh_token`）刷新并回写 `auth.json`。
- CLI 仍用 `bash /c/vtmp/vc.sh`（`node --require /c/vtmp/fixhost.cjs …vc.js`，规避本机中文主机名导致的 `byteString` 崩溃）。

### 7.4 公网回归（2026-11-28 19:47–19:50）

| 检查 | 结果 |
| --- | --- |
| `GET https://www.quannengyanjiu.cn/api/platform-status` | `{"status":"ok","frontend":"ok","backend":"ok","backend_code":200,"database":true,"detail":"All systems operational"}` |
| `GET https://tribute-devel-capability-lips.trycloudflare.com/api/v1/readyz` | 200，`database.connected=true`、`llm_reachable=true` |
| `POST /api/v1/auth/login`（既有账号 `deploy-check-1795757964@example.com`） | 200，返回 `access_token` |
| `GET /api/v1/research/projects`（带 token） | 200，3 个历史项目（含 `公网验收 1795758280`） |
| `GET /api/v1/research/tasks/task_962b3156c5394151adc92745c2ea7401` | 200，`status=succeeded`、`quality_verdict=issues_found` |
| `GET …/findings` | 200，7 条历史诊断项 |

### 7.5 运维命令

```bash
# 状态 / 重启
wsl -d Ubuntu -u root -e systemctl status scholarmind-backend scholarmind-tunnel --no-pager
wsl -d Ubuntu -u root -e systemctl restart scholarmind-backend
# 健康
curl -s http://127.0.0.1:8020/api/v1/health
curl -s https://www.quannengyanjiu.cn/api/platform-status
```

### 7.6 仍存在的边界

- 后端跑在本机：**电脑关机/断网即不可用**；隧道地址重启会变，需要重新部署前端。
- 数据是单文件 SQLite（`src/backend/data/scholarmind_orm.db`），无备份机制。
- Vercel 项目未接 Git 集成，部署仍靠 CLI；CI（mypy/test/research-gate）仍红灯，属既有问题。
