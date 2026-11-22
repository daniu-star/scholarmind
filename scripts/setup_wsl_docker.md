# WSL2 + Docker Engine 环境检查与启用脚本（Windows）

用途：给「真实 Redis / Celery / PostgreSQL 恢复演练」准备 Linux 容器环境。
只装 **Docker Engine**（开源免费），不需要 Docker Desktop 订阅。

## 用法

```powershell
# 1) 只体检（不需要管理员）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_wsl_docker.ps1 -Check

# 2) 启用 Windows 功能（需要管理员，会提示重启）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_wsl_docker.ps1 -Apply
```

`-Apply` 之后按屏幕提示重启，再回到「Ubuntu 与 Docker Engine」一节。

## 一、BIOS（必须人工做一次）

开机的厂商 Logo 出现时连按 `F2` / `F10` / `Del`（视机型）进入 BIOS：

1. `Intel Virtualization Technology`（或 `VT-x`、`SVM Mode`）= **Enabled**
2. `VT-d` / `IOMMU` = Enabled（可选，容器网络更稳）
3. 保存退出（通常 `F10`）

Windows 里验证：

```powershell
# 应看到 Hyper-V Requirements 不再提示 "A hypervisor has been detected" 之外的限制；
# 也可以在任务管理器 → 性能 → CPU 里看 "虚拟化: 已启用"
```

## 二、Windows 功能

管理员 PowerShell：

```powershell
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
```

然后**重启**。

## 三、Ubuntu 与 Docker Engine

```powershell
wsl --update
wsl --set-default-version 2
wsl --install -d Ubuntu      # 首次会要求设置 Linux 用户名/密码
wsl -l -v                    # 确认 VERSION = 2
```

进入 Ubuntu：

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # 重新登录后生效
docker --version
docker run --rm hello-world
```

> Docker Desktop 的订阅与这里无关：Docker Engine 是 Apache-2.0，永久免费。

## 四、演练所需的两个服务

```bash
docker run -d --name drill-redis -p 6379:6379 redis:7
docker run -d --name drill-pg    -p 5432:5432 -e POSTGRES_PASSWORD=drill postgres:16
```

## 五、本仓库接着要跑的命令

```powershell
# 真实 PG 恢复演练（已有）
.\.venv\Scripts\python.exe scripts\research_recovery_drill.py --lease-seconds 8

# Redis / Celery 恢复演练（本脚本装好 Docker 后可用）
.\.venv\Scripts\python.exe scripts\research_broker_drill.py --redis-url redis://127.0.0.1:6379/0
```

## 排障

| 现象 | 处理 |
| --- | --- |
| `WSL2 无法启动，因为 BIOS 中未启用虚拟化` | 回到第一节开 VT-x；部分品牌机还需关掉「快速启动」 |
| `wsl --install` 报 0x80370102 | 虚拟化未开或 `VirtualMachinePlatform` 未启用 |
| Docker 报 `permission denied` | 重新登录 Ubuntu 会话，或 `newgrp docker` |
| 端口 6379/5432 被占用 | 换宿主端口（`-p 6380:6379`），并相应改 `--redis-url` |
