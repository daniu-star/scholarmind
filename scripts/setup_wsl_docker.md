# WSL2 + Docker Engine 运行手册（Windows，本机已实测通过）

用途：给「真实 Redis / PostgreSQL / Celery 恢复演练」准备 Linux 容器环境。
本机（Windows 11 家庭版，Intel Core Ultra 5 125H）于 2026-11-27 按本文完整跑通：
WSL 2.6.3.0 → Ubuntu 26.04.1 → Docker Engine 29.10.1 → `redis:7` 容器 →
`scripts/research_broker_drill.py` 的 Docker 模式 **11/11 PASS**。

只装 **Docker Engine**（Apache-2.0，免费），不需要 Docker Desktop 订阅。

体检脚本（只读，不需要管理员）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_wsl_docker.ps1 -Check
```

## 0. 先确认 BIOS 是否真的没开虚拟化

很多机器（包括本机）**BIOS 虚拟化本来就是开的**，真正的阻塞是 Windows 功能没启用。
先看 `systeminfo` 的结尾：

```powershell
systeminfo | Select-String -Pattern "Hyper-V","虚拟化","Virtualization"
```

- 出现 `A hypervisor has been detected` / `Hyper-V 要求: 已检测到虚拟机监控程序` → **不用进 BIOS**。
- 出现 `Virtualization Enabled In Firmware: No` 且没有 hypervisor → 才需要进 BIOS 打开
  `Intel Virtualization Technology (VT-x)` / `SVM Mode`，保存重启。

> 注意：`Get-CimInstance Win32_Processor` 的 `VirtualizationFirmwareEnabled` 在 VBS
> （基于虚拟化的安全）运行时可能显示 `False`，这是假信号；以 `systeminfo` 是否检测到
> hypervisor 为准。

## 1. 启用 Windows 功能（需要管理员，一次）

```powershell
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart
```

三条命令的退出码 `3010` 表示「成功但需要重启」。然后**重启一次**（本机就是这一步之后
WSL2 才真正可用）。

非管理员会话可以通过 UAC 提权执行（脚本路径不要含中文，先复制到 `%TEMP%`）：

```powershell
Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","$env:TEMP\enable-wsl.ps1"
```

验证：

```powershell
wsl --status        # 不再提示"未启用虚拟化"
wsl --version       # 2.x，内核 6.x
```

## 2. 安装 Ubuntu

```powershell
wsl --install -d Ubuntu --no-launch
wsl -d Ubuntu -u root -e bash -lc 'cat /etc/os-release | head -3'
```

本机结果：`Ubuntu 26.04.1 LTS`，内核 `6.6.87.2-microsoft-standard-WSL2`。

启用 systemd（后续用 systemd 托管 dockerd）：

```powershell
wsl -d Ubuntu -u root -e bash -lc "printf '[boot]\nsystemd=true\n' > /etc/wsl.conf"
wsl --terminate Ubuntu
```

> 改了 `wsl.conf` 后发行版会重启，**`/tmp` 会被清空**——安装包要放 `/opt`。

## 3. 安装 Docker Engine（静态二进制，绕开 Docker Desktop）

不要用 `curl -fsSL https://get.docker.com | sh`：本机 WSL 会继承 Windows PATH，
`docker` 会先解析到 Docker Desktop 的 shim，报
`The command 'docker' could not be found in this WSL 2 distro`。

```bash
set -e
mkdir -p /opt/docker-static && cd /opt/docker-static
# 版本可在 https://download.docker.com/linux/static/stable/x86_64/ 查看
curl -fL --retry 3 -o docker.tgz https://download.docker.com/linux/static/stable/x86_64/docker-29.10.1.tgz
tar -xzf docker.tgz
install -m 0755 docker/* /usr/local/bin/
/usr/local/bin/docker --version   # Docker version 29.10.1
```

## 4. 配置镜像源（中国大陆网络）

本机 `registry-1.docker.io` 被 DNS 解析到 `198.18.x` 假地址、直连超时。可用镜像源实测：
`docker.1ms.run`、`docker.xuanyuan.me`（返回 401 属正常，说明服务在线）。

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me",
    "https://docker.m.daocloud.io"
  ]
}
JSON
```

## 5. 用 systemd 启动 dockerd

TCP 端点用于 Windows 侧管理容器（见 §7 的原因）：

```bash
cat > /etc/systemd/system/docker.service <<'UNIT'
[Unit]
Description=Docker Engine (static binaries)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/dockerd -H unix:///var/run/docker.sock -H tcp://0.0.0.0:2375
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now docker
systemctl is-active docker     # active
docker info | head -20
```

### 两个必踩的启动错误

| 报错 | 原因 / 修复 |
| --- | --- |
| `invalid userland-proxy-path: userland-proxy is enabled, but userland-proxy-path is not set` | 静态包里的 `docker-proxy` 没被复制；执行 `install -m 0755 /opt/docker-static/docker/docker-proxy /usr/local/bin/` 后 `systemctl restart docker` |
| `failed to register "bridge" driver: failed to create NAT chain DOCKER: iptables not found` | 最小 Ubuntu 没装防火墙工具；`DEBIAN_FRONTEND=noninteractive apt-get install -y iptables nftables iproute2` |

## 6. 起 Redis 容器

```bash
docker run -d --name drill-redis -p 6380:6379 --restart unless-stopped redis:7
docker exec drill-redis redis-cli ping     # PONG
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
```

用 6380 而不是 6379：Windows 主机上 6379 往往已被其它项目（或前几轮演练的本机 Redis）占用。

## 7. 从 Windows 侧使用（演练脚本对接）

三条本机实测结论：

1. **Windows → WSL 的 `127.0.0.1` 端口转发不一定生效**（本机连 6380 报 `Error 10061`），
   但 WSL IP 可以直连：

   ```powershell
   wsl -d Ubuntu -u root -e hostname -I     # 例如 192.168.218.232
   ./ .venv/Scripts/python.exe -c "import redis; print(redis.Redis(host='192.168.218.232', port=6380).ping())"
   ```

2. **Windows 侧 Python 不能 spawn `wsl.exe`**（返回 `Wsl/E_ACCESSDENIED`，用 cmd/powershell
   包一层也一样）。所以演练脚本通过 **dockerd 的 TCP 端点** 管理容器：

   ```powershell
   docker -H tcp://192.168.218.232:2375 ps
   ```

   如果 Windows 没有 docker CLI，可直接用 HTTP：
   `Invoke-RestMethod http://192.168.218.232:2375/containers/json`。

3. **WSL 空闲会休眠**，容器状态会显示 `Up 1 second`（被重新拉起）。演练期间保持唤醒：

   ```powershell
   Start-Process -WindowStyle Hidden wsl -ArgumentList '-d','Ubuntu','-u','root','-e','sleep','3600'
   ```

运行演练：

```powershell
./.venv/Scripts/python.exe scripts/research_broker_drill.py `
  --redis-url redis://192.168.218.232:6380/0 `
  --redis-container drill-redis `
  --docker-host tcp://192.168.218.232:2375
```

预期：**11/11 checks PASS，exit 0**，结果写入 `tmp/broker-drill.json`。
报告见 `docs/reports/R2_BROKER_DRILL.md` §7。

## 8. 排障表

| 现象 | 排查 |
| --- | --- |
| `wsl --status` 仍报未启用虚拟化 | §0：确认 `systeminfo` 是否检测到 hypervisor；§1：三条 DISM 是否 `Enabled`、是否重启 |
| `docker: command not found` | 静态二进制是否 `install` 到 `/usr/local/bin`；`echo $PATH` |
| `Cannot connect to the Docker daemon` | `systemctl status docker`；`journalctl -u docker -n 100` |
| `docker pull` 超时 / `i/o timeout` | §4 镜像源；`docker info` 看 `Registry Mirrors` |
| Windows 连不上 WSL 端口 | 用 `hostname -I` 的 IP，不要用 `127.0.0.1` |
| 容器频繁显示 `Up 1 second` | WSL 空闲休眠；用 §7 的 `sleep 3600` 保活 |

## 9. 清理

```bash
docker rm -f drill-redis
systemctl disable --now docker
```

Windows 侧如需回收磁盘：`wsl --shutdown`，再删除不再需要的发行版（`wsl --unregister Ubuntu`，
会删除该发行版内所有数据，谨慎）。
