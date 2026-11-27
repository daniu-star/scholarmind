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

已知历史坑：Vercel CLI 在本机会因主机名含中文而崩（`byteString ... 20113`），必须用 `node --require /c/vtmp/fixhost.cjs .../vc.js`；`npm` 在 MSYS 里要用 `npm.cmd`；SQLite 绝对路径要写四个斜杠（`sqlite+aiosqlite:////C:/...`）。
