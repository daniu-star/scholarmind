# R2 真实 PostgreSQL 恢复演练报告

- 日期：2026-11-21（本地 23:3x – 次日 01:0x）
- 演练脚本：`scripts/research_recovery_drill.py`
- 结果文件：`tmp/recovery-drill.json`（运行产物，不入库；本文摘录全部关键数字）
- 环境：PostgreSQL **16.4**（官方 Windows 便携版二进制），端口 **55433**，`lease_seconds=8`
- 结论：**PASS（8/8 检查项）**，并在演练中发现 **3 个真实缺陷**：2 个产品缺陷当场修复，1 个 FR-11 fencing 缺陷当场修复并复验通过
- 未覆盖：Redis / Celery（本机无真实 Redis 服务，Docker 不可用）——如实声明，不用 SQLite 或替身冒充

## 0. 结论摘要

| 恢复语义（PRD FR-11 / §7.1） | 期望 | 实测 | 判定 |
| --- | --- | --- | --- |
| 领取执行权即写 `task.started` | attempt 1 + fencing 1 + started 事件 | attempt 1 / token 1 / seq 2 `task.started` | PASS |
| 执行器崩溃后租约过期可被接管 | attempt 递增、token 递增、任务终态 | attempt 2 / token 2 / `succeeded` | PASS |
| 事件序号严格单调、无重复终态 | 序号 1..N 递增、终态事件 1 条 | `[1,2,3,4,5,6,7]`、终态事件 1 条 | PASS |
| 成果只产一份 | Artifact 1 条 | 1 条 | PASS |
| 旧执行器（租约已转移）写入被拒 | `STALE_ATTEMPT` 冲突 | 迟到事件与迟到迁移**均被拒** | PASS |
| 重复投递只执行一次 | 1 attempt / 1 终态事件 / 1 Artifact | 1 / 1 / 1（另一执行器安全放弃） | PASS |
| 数据库崩溃重启后状态一致 | 状态、序号、成果数不变 | 一致 | PASS |
| 迁移与 schema 落地 | 15 张 research_* 表 + 4 个唯一约束 | 15 张 + 4 个约束，server 16.4 | PASS |

## 1. 环境与踩坑（可复现要点）

1. **数据目录必须 ASCII**：`initdb` 在含中文的仓库路径下报
   `FATAL: invalid byte sequence for encoding "UTF8": 0xc4 0xdc`。
   `C:\pgdrill` 无写权限、系统临时目录对当前进程写被拒，最终用盘符映射：
   `subst X: "<repo>"`，数据目录 `X:\pgdrill\data`。脚本用 `DRILL_PG_ROOT` 覆盖根目录，默认即 `X:\pgdrill`。
2. **不要复用别人正在跑的 PG**：本机 55432 已有另一个项目的集群
   （`show data_directory` = `C:/pgdata_mc`）。首版脚本只看 `pg_isready` 就复用了它，
   把 `scholarmind_drill` 建到了别人的实例里。现已：
   - 清除污染（`pg_terminate_backend` + `dropdb scholarmind_drill`）；
   - 改为扫描 `port..port+40`，启动后用 `show data_directory` 二次校验，非自己的集群直接换端口。
3. **`pg_ctl start` 会挂住父进程**：`subprocess.run(capture_output=True)` 时 postgres 继承管道、
   父进程等不到 EOF，实测挂 10 分钟以上。改为 `stdin=DEVNULL`、stdout/stderr 写日志文件句柄。
4. **崩溃模拟**：`stop -m immediate`（先校验端口不再监听）再 `start_pg()`，不依赖 `postmaster.opts`。

## 2. 演练场景与证据

### 2.1 迁移与 schema（真实 PG）

- `alembic upgrade head` 在 PG 上跑通；`research_*` 表 **15** 张齐全（projects/documents/versions/blocks/chunks/source_records/evidences/tasks/task_attempts/task_events/findings/revision_proposals/artifacts/billing_operations/outbox_messages）。
- 4 个唯一约束存在：`uq_event_task_sequence`、`uq_task_owner_idempotency`、`uq_billing_group_operation`、`uq_artifact_task_kind_ver`。
- `server_version = 16.4`。

### 2.2 崩溃接管（kill → 租约过期 → 新执行器接管）

1. 子进程 A 领取：`attempt_no=1`、`fencing_token=1`，写 `task.started`（seq 2），随后挂起。
2. 主进程 `taskkill /F`（Windows）杀掉 A —— 模拟进程崩溃，**不写任何收尾**。
3. 租约按数据库时钟真实过期（脚本轮询 `lease_expires_at`，`lease_seconds=8`）。
4. 执行器 B（`execute_task(holder="drill-worker-b")`，真实代码路径 + 真实模型替身）接管：
   attempts = `[(1,'running',token 1), (2,'succeeded',token 2)]`，任务 `succeeded`，
   事件 `task.accepted, task.started, task.started, task.progress, task.progress, artifact.created, task.completed`，
   序号 `[1..7]` 单调，终态事件 1 条，Artifact 1 个，`quality_verdict=issues_found`。

> 说明：崩溃的 attempt 1 行按设计保留为 `running`（审计与 fencing 需要），不会被改写；
> 回收依据是 `lease_expires_at`，不是 attempt 状态。

### 2.3 迟到写入（fencing）

接管完成后，让旧执行器 A 用自己的 token 再写一次：

- `append_event(..., "task.progress", fencing_token=1)` → 拒绝
- `transition(..., FAILED, fencing_token=1)` → 拒绝

两次都返回 `ResearchAPIError`（`STALE_ATTEMPT`：「执行权已转移，本次写入被拒绝。」），
任务状态保持 `succeeded`，终态事件仍为 1 条。

### 2.4 重复投递

两个子进程同时对同一新任务调用 `execute_task`：

- 结果：终态 `succeeded`、attempt 数 **1**、终态事件 **1**、Artifact **1**；
- 落后的那个子进程收到 `ResearchAPIError: 不能从 succeeded 迁移到 partial`（安全放弃，不重复结算）。

### 2.5 数据库崩溃重启

`pg_ctl stop -m immediate` → 立即 `start_pg()` → 重读：状态、事件序号、Artifact 数、billing 行完全一致
（`db_restart_consistent = true`）。

## 3. 演练中发现并修复的真实缺陷

### 3.1 产品缺陷 A：`_extend_30_days` 返回带时区时间，PG 写入失败（已修）

`src/backend/services/entitlement_service.py` 中续期计算返回 `tzinfo=utc` 的 datetime，写入
`TIMESTAMP WITHOUT TIME ZONE` 列时 asyncpg 直接报错：

```
asyncpg.exceptions.DataError: invalid input for query argument $2: datetime.datetime(..., tzinfo=datetime.timezone.utc)
(can't subtract offset-naive and offset-aware datetimes)
```

SQLite 不做类型校验，所以 R0–R2 全部测试都没暴露。修复：`(base + timedelta(days=30)).replace(tzinfo=None)`，
并在注释里绑定 PRD §6「UTC naive」约定。

### 3.2 产品缺陷 B：`grant_product` 的 `source_ref` 幂等会静默串号（已修）

`EntitlementService.grant_product` 以 `source_ref` 去重时，若该 `source_ref` 已属于**另一个用户**，
原实现直接 `return get_snapshot(...)`：不开通、不报错、调用方以为成功。修复为抛
`ValueError("source_ref ... 已属于用户 X，不能用于用户 Y")`，把冲突暴露给调用方。

### 3.3 FR-11 缺陷 R2-A13：fencing token 只落库、未在写入路径生效（已修）

**现象**（修复前，真实 PG 上复现）：租约过期、任务已被 attempt 2（token 2）接管后，
旧 attempt 1（token 1）仍能：

- `append_event("task.progress")` 成功（拿到 seq 2）；
- `transition(FAILED)` 成功（running→failed 是合法迁移），把已接管的任务改成失败。

**根因**：`append_event` / `transition` / `close_attempt` 都不接收、也不校验 fencing token。

**修复**（`src/backend/research/task_repository.py` + `task_runner.py`）：

- 新增上下文变量 `_LEASE_TOKEN` 与 `set_lease_scope()` / `reset_lease_scope()`；
- 新增 `_current_fencing_token()`（该任务最大 attempt 的 token）与 `_enforce_fence()`：
  写入 token 与该值不一致 → `conflict("STALE_ATTEMPT", ...)`；
- `append_event` / `transition` / `close_attempt` 增加可选 `fencing_token=` 参数，
  未显式传入时回退到上下文 token，两者都没有（如 API 层 cancel/retry 这类无租约写入）不校验；
- `execute_task` 在领取成功后用 `set_lease_scope(attempt.fencing_token)` 绑定上下文，`finally` 复位。

**复验**：同一演练重跑，`stale_write_rejected` 变为 PASS，8/8 全绿；
三套回归 `529 passed, 1 skipped in 371.35s`（R0 290 / R1 161 / R2 78），`ruff` 全绿。

## 4. 未覆盖项（明确声明）

- **Redis**：本机无 `redis-server`，Docker 引擎不可用（`com.docker.service` 无法启动，需管理员）。
  已安装 `fakeredis`，但它不是真实网络服务，**不能**用来证明限流/连接恢复语义。
  相关代码（`src/backend/middleware/redis_rate_limit.py`、`src/backend/utils/redis_client.py`）
  在 Redis 不可用时降级为内存/None，降级路径有单测覆盖，但「真实 Redis 断连重连」未验证。
- **Celery worker**：`src/backend/scheduler/celery_app.py` 配置为 `task_acks_late=True`、
  `prefetch=1`、`max_retries=3`，但研究域当前走**进程内 dispatcher**（`TASK_BACKEND="background"`），
  且无可用 broker；因此「worker 被杀后 broker 重投」未演练。
- **多节点并发**：所有演练都在单机单进程（+ 子进程）完成，未做多机竞争。

## 5. 复跑与清理

```powershell
# 1) 映射盘符（数据目录必须 ASCII）
subst X: "C:\Users\13067\Desktop\全能研究Agent"

# 2) 复跑演练（会自动 initdb / 迁移 / 演练 / 停止集群）
.\.venv\Scripts\python.exe scripts\research_recovery_drill.py --lease-seconds 8

# 3) 清理
subst X: /D
Remove-Item -Recurse -Force tmp\pg, tmp\recovery-drill.json
```

脚本参数：`--port`（起始端口，默认 55432，会自动避开非本集群实例）、
`--lease-seconds`、`--keep`（保留集群）、`--skip-migrations`、`--child-claim` / `--child-execute`（子进程入口）。

## 6. 残留风险

1. 崩溃的 attempt 行永久保持 `running`；若后续要做「attempt 超时清理」，需与审计保留策略一起设计。
2. `billing_operations` 的 `reserve:*` 行若对应任务永远未到终态（既没成功也没取消），
   会停留在 `reserved`。当前只有 cancel/terminal 路径会结算或释放，无独立 reaper。
3. `fencing` 校验依赖调用方传入 token 或处于 `lease_scope` 内；不经 `execute_task` 的自定义脚本
   若显式传 `fencing_token` 才能被保护（这也是本次演练能复现缺陷的原因）。
4. 未覆盖 Redis/Celery/多节点，见 §4。
