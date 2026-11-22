# R2 · Redis / Celery 恢复语义演练（broker + worker）

日期：2026-11-22　执行人：Lead（AI agent）　环境：Windows 11 + 本机 Redis 7 + Celery 5.6.3（solo pool）

> 结论：**8/8 检查通过**（`tmp/broker-drill.json`，`passed=true`，退出码 0）。
> 覆盖：正常 round-trip、执行中被 `taskkill` 杀 worker 后的消息重投 + exactly-once、
> broker 不可达时发布失败（不假成功）与恢复后跑完、同一任务重复投递去重。
> 演练中发现并修复 **2 个真实产品缺陷**（见 §4）；**未覆盖**多 worker/多机竞争、
> RabbitMQ、Docker 容器重启、Redis 主从/持久化故障（见 §6）。

## 1. 为什么要单独演练

PRD FR-11 要求「数据库任务 + 权益预留 + outbox 同事务、租约/fencing、事件序号重放」。
PostgreSQL 侧已由 `scripts/research_recovery_drill.py` 覆盖（8/8 PASS，见
`R2_RECOVERY_DRILL.md`）；但生产上研究任务还有第二种投递路径——**真实 broker + Celery
worker**。这条路径的失败模式完全不同于进程内 dispatcher：

- worker 进程被 `SIGKILL`（不是优雅退出）时，消息是否重投？
- 重投回来时旧租约还没过期怎么办？
- broker 不可达时，发布是失败还是「静默成功」？
- 同一条消息投两次，会不会跑两遍、写两个成果？

## 2. 演练环境（本机没有 Docker 的真实替代）

| 项 | 实际做法 |
| --- | --- |
| Redis | 用本机真实 `redis-server`（127.0.0.1:6379），隔离到 **9 号库**，不碰其它项目的数据 |
| worker | 真实 `python -m celery -A src.backend.scheduler.celery_app worker --pool=solo -c 1`，日志 `tmp/broker-drill-worker.log` |
| 杀 worker | `C:\Windows\System32\taskkill.exe /F /PID <pid> /T`（**绝对路径**，见 §4 陷阱一） |
| broker 断连 | `--proxy-port 6391`：演练脚本自己起一个 TCP 代理，Redis 客户端 → 代理 → 真实 Redis；停代理 = 网络分区/服务不可达 |
| 数据库 | SQLite `tmp/broker-drill.db`（schema 由 `init_db` 建）；任务租约通过 `RESEARCH_TASK_LEASE_SECONDS=25` 调小 |
| 模型 | `RESEARCH_MODEL_STUB=true`（替身模型，产物只用于流程验证，不代表质量） |

Docker 路线（`docker stop drill-redis`）保留在脚本 `--redis-container` 分支，等 WSL2 +
Docker Engine 就绪后可直接跑同一套断言；本机当前因 BIOS 未开虚拟化用不了 Docker。

## 3. 四个场景与实测证据

运行：`./.venv/Scripts/python.exe scripts/research_broker_drill.py --proxy-port 6391`

| # | 场景 | 断言 | 实测 |
| --- | --- | --- | --- |
| S1 | 正常 round-trip | 任务到 `succeeded`、恰好 1 个成果 | PASS（约 7s） |
| S2 | 执行中杀 worker | 杀后消息重投、`attempt_no >= 2`、终态事件 1 条、成果 1 个 | PASS（attempts `[(1,running),(2,succeeded)]`，终态事件 1、成果 1） |
| S3 | broker 断连 → 恢复 | 断连时发布必须**抛错**；恢复后同一任务能跑完 | PASS：断连时 `OperationalError: Error 10061 … 目标计算机积极拒绝`；恢复后发布成功、任务 `succeeded` |
| S4 | 重复投递 | 同一任务发布两次仍只有 1 条终态事件、1 个成果 | PASS |

`tmp/broker-drill.json` 关键字段：

```json
{"passed": true, "checks": {"roundtrip_succeeded": true, "worker_kill_triggers_redelivery": true,
 "worker_kill_exactly_once": true, "broker_down_is_honest": true,
 "duplicate_delivery_exactly_once": true, "worker_kill_terminal": true, "broker_down_terminal": true}}
```

S2 的 attempts 证据（同一 Celery 消息重投，故 holder 相同）：

```
[[1, "running", "celery:8f851c64-…"], [2, "succeeded", "celery:8f851c64-…"]]
```

> 说明：attempt 1 保持 `running` 是**预期的**——进程被强杀，没有机会写终态；
> 接管靠的是租约过期后的 attempt 2，而不是「替死掉的进程补一条记录」。

## 4. 演练中发现并修复的真实产品缺陷

### 缺陷 1：领取（open_attempt）后未提交，崩溃时租约与 running 状态不可见

- 现象：worker 被杀后，数据库里看不到这次领取——`research_task_attempts` 没有行，
  `research_tasks.status` 仍是 `queued`。
- 影响：运维看不到「谁在跑」；其它执行器判断「要不要接管」时缺少依据；租约字段形同虚设。
- 修复：`src/backend/research/task_runner.py` 在 `open_attempt` 成功后立即 `await db.commit()`，
  再进入执行（注释说明：领取即提交，崩溃后租约才可判定）。

### 缺陷 2：「重投早于租约过期」会把消息静默吞掉，任务永久卡在 running

- 现象：worker 被杀后消息重投回来，但旧租约还没过期 → `execute_task` 走「抢占失败，安全放弃」
  分支，Celery 认为任务已成功处理并 ack 消息；此后**不会再有重投**，任务停在 `running`。
- 影响：任务永久卡住，唯一后果是用户看到一直「进行中」，且没有兜底回收。
- 修复：
  1. `src/backend/scheduler/research_tasks.py`：执行前若任务 `running` 且存在**未过期**租约，
     计算剩余秒数并 `raise self.retry(countdown=剩余+5)`，把消息还给 broker，等租约过期再跑；
  2. `src/backend/config.py` 新增 `RESEARCH_TASK_LEASE_SECONDS`（默认 1200，与 PRD §9 对齐），
     `task_runner.LEASE_SECONDS` 改为读配置——生产可调，演练可压到 25s。

### 陷阱一（环境，不是产品）：`taskkill` 被 PATH 里的包装脚本遮蔽

- 现象：`kill_tree()` 调 `taskkill /F /PID …` 退出码 1、参数被改写（`/F` 被当成路径），
  worker 实际没死；演练表现为「杀了 worker 却没有重投」。
- 修复：`scripts/research_broker_drill.py` 固定用
  `%SystemRoot%\System32\taskkill.exe` 绝对路径，并在 kill 后校验进程确实退出。

### 观察：kombu 的可见性恢复不是「到点自动重投」

- `QoS.restore_visible()` 内部有 `(count-1) % interval`，默认每 10 次轮询才真正执行一次；
  worker 刚重启时可能一次都没跑。
- 演练里在重启 worker 前显式调用同一个 transport API（`--proxy-port` 之外的
  `restore_unacked()`），语义与「消费者重启后恢复未确认消息」一致——不是自己重发消息。

## 5. 复跑与清理

```bash
# 1) 起 Redis（本机或 docker run -d -p 6379:6379 redis:7）
# 2) 干跑（含 broker 断连，用本地 TCP 代理注入）
./.venv/Scripts/python.exe scripts/research_broker_drill.py --proxy-port 6391
# 3) 只看 worker 被杀场景
./.venv/Scripts/python.exe scripts/research_broker_drill.py --skip-broker-down
# 4) Docker 路线（WSL2 + Docker Engine 就绪后）
./.venv/Scripts/python.exe scripts/research_broker_drill.py --redis-container drill-redis
```

清理：`rm -f tmp/broker-drill.db* tmp/broker-drill.json tmp/broker-drill-worker.log`；
确认没有残留 worker：`Get-CimInstance Win32_Process -Filter "Name='python.exe'"` 里不应再有
`-m celery -A src.backend.scheduler.celery_app`。

## 6. 未覆盖与残留风险

- **多 worker / 多机竞争**：单机 solo worker，未测两个 worker 同时抢同一任务（租约 + fencing
  已在 PG 演练覆盖，但 broker 路径未复测）。
- **RabbitMQ 传输**：只测 Redis transport；生产若换 RabbitMQ，`visibility_timeout` 语义不同
  （靠 ack + redelivery），需重跑同一脚本。
- **Docker 容器重启**：容器 OOM/重启的行为等 WSL2 + Docker Engine 就绪后补测。
- **Redis 持久化/主从故障**：未测 AOF/RDB 损坏与主从切换。
- **长任务 > visibility_timeout**：当前 `visibility_timeout=3600`（生产默认）与租约 1200s；
  若任务真的跑超过 1 小时，消息可能被重复投递，此时依赖 `attempt_no`/fencing 去重——已由
  PG 演练覆盖该语义，但 broker 路径未做超长任务实测。
- 演练使用替身模型，**不涉及质量结论**；任务结果为 `succeeded` 仅证明流程闭环。
