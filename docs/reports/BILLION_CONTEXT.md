# billion-context（ACP 上下文压缩代理）接入说明

> 结论先说：**已经接进代码、默认关闭、按需开启。它在本项目的当前流量下几乎不省 token（开销也≈0），
> 真正的价值是“越界保护”和“未来超长会话折叠”。对外不要写成“已节省 X% token”。**

- 代理：`billion-context` 0.1.216（本机随 DSH 安装在 `~/.dsh/profiles/web/node_modules/billion-context`）
- 角色：本地 HTTP 代理（ACP = Active Context Pruning），挡在应用与 DeepSeek 之间，按会话折叠历史消息
- 本项目改动：`config.py` 三个开关 + `llm_client` 代理分支 + 研究流水线任务级会话键 + 启动/自检脚本 + 单测

---

## 1. 它是怎么压缩的（决定收益边界）

billion-context **不是**被动改写请求的中间件。它做两件事：

1. **正常流量原样转发**：请求体不注入提示词、不重复历史、不改 `tools`（见 §5 实测）。
2. **接近窗口上限时才触发折叠**：向请求注入压缩工具与 nudge，由**模型主动调用** `compress` 等工具把旧历史换成摘要；
   若模型没机会调用（例如一次性请求、无工具调用能力、上下文本来就没超），就不会发生任何折叠。

因此收益成立的前提是：**多轮、有跨请求历史、且模型能调用工具的会话**。
本项目的研究流水线是“每个窗口独立 system+user、没有跨窗口历史”，聊天接口也只发单段上下文——
这两类流量都不满足折叠条件，所以当前收益≈0，而开销也≈0（原样转发）。

> 如果你的目标是“让长会话省钱”，需要的是把聊天做成携带历史的 agent 循环（模型可调用 compress 工具）。
> 这是产品形态改动，不是配置能解决的——本文件不夸大这一点。

---

## 2. 架构与接线

```
ScholarMind 后端
  └─ utils/llm_client.LLMClient           # 唯一 AsyncOpenAI 封装
        ├─ 未配置 LLM_PROXY_BASE_URL → 直连 https://api.deepseek.com/v1（历史行为）
        └─ 已配置 → http://127.0.0.1:8790/bili/https://api.deepseek.com/v1
                        └─ billion-context :8790 → DeepSeek
                             · 同一 x-acp-session 的请求共享压缩状态
```

会话键（`x-acp-session`）约定：**同一会话/任务共享，不同用户/任务必须不同**。

| 调用方 | 会话键 | 代码位置 |
| --- | --- | --- |
| 聊天 | `chat:{user_id}:{session_id}` | `src/backend/services/agent_service.py` |
| 研究任务（review/revision/export 等） | `research:{task_id}` | `src/backend/research/task_runner.py` |

为避免跨任务串上下文，会话键由调用方给出；`task_runner` 传 `get_client(snapshot, session_key=...)`，
`runtime.LlmClientAdapter` 只在键非空时才向下透传。

---

## 3. 开关（默认关闭）

`src/backend/config.py`：

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_PROXY_BASE_URL` | `None` | 留空=直连。填 `http://127.0.0.1:8790/bili/https://api.deepseek.com/v1` 即走代理 |
| `LLM_PROXY_SESSION_HEADER` | `x-acp-session` | 与代理配置的 `sessionHeader` 保持一致 |
| `LLM_PROXY_TIMEOUT_SECONDS` | `180.0` | 代理折叠历史时会发“侧请求”总结旧历史，单次调用会变慢；启用代理时客户端超时取 `max(LLM_TIMEOUT, 该值)` |

`.env` 里加两行即可（重启后端生效）：

```dotenv
LLM_PROXY_BASE_URL=http://127.0.0.1:8790/bili/https://api.deepseek.com/v1
LLM_PROXY_SESSION_HEADER=x-acp-session
```

不配置时：`LLMClient` 的 base_url、超时、请求头与接入前**完全一致**（有单测锁定）。

---

## 4. 启动与运维

```bash
# 启动（后台）：自动定位 billion-context 入口、检查端口、健康检查、打印 env
python scripts/start_bili_proxy.py --detach

# 查看状态（会打印 /__bili/health 的 JSON）
python scripts/start_bili_proxy.py --status

# 只打印要写进 .env 的两行
python scripts/start_bili_proxy.py --print-env

# 停止
python scripts/start_bili_proxy.py --stop
```

要点：

- 代理入口从 `~/.dsh/profiles/*/node_modules/billion-context/dist/index.js` 找，可用 `BILI_ENTRY` 覆盖；
- 会话数据目录**隔离在本项目** `tmp/bili-data`（通过 `XDG_DATA_HOME` 注入），
  不写 DSH 自己那套 `~/.local/share/billion-context`（那里已有约 900MB 库且可能被 DSH 实例占用导致只读报错）；
- 日志：`tmp/bili-proxy.log`；pid 文件：`tmp/bili-proxy.pid`；
- 端口默认 `8790`，被占用时脚本直接报错退出（不会静默抢占）。

配置文件：

| 文件 | 用途 |
| --- | --- |
| `config/billion-context.json` | 默认策略：按 1,048,576 窗口、`maxContextLimit=60%`、`emergencyThresholdPercent=92%`，只在真正接近上限时才折叠 |
| `config/billion-context.cost.json` | 成本优先：按 64K 窗口、`maxContextLimit=40%`、`emergencyThresholdPercent=60%`、`promptPack=lean`，更早折叠 |

切换策略：`python scripts/start_bili_proxy.py --config config/billion-context.cost.json --stop` 后重新启动。

---

## 5. 实测证据（2026-11-21，本机）

### 5.1 正常流量零注入（可复跑）

```bash
python scripts/bili_payload_probe.py --turns 6
# 直连：  {"n_messages": 14, "tools": [], "chars": 704, ...}
# 经代理：{"n_messages": 14, "tools": [], "chars": 704, ...}
# 结论：代理原样转发（零注入、零改写）
```

探针自建 mock OpenAI 上游，只记录上游实际收到的请求体，再比较“直连 vs 经代理”的 messages/tools/字符数。

### 5.2 经本项目代码走代理（真实模型）

```bash
# 先确认脚本已启动代理（健康检查 OK），再带 env 跑一次真实调用
LLM_PROXY_BASE_URL="http://127.0.0.1:8790/bili/https://api.deepseek.com/v1" \
python - <<'PY'
import asyncio
from src.backend.utils.llm_client import LLMClient, proxy_base_url

print("proxy_base_url =", proxy_base_url())
print(asyncio.run(LLMClient().chat("你是助手。", "只回复两个字：收到", max_tokens=32,
                                   session_key="smoke:proxy:1")).content)
PY
```

实测（2026-11-21 06:39）：日志出现
`llm_proxy_enabled base_url=http://127.0.0.1:8790/bili/https://api.deepseek.com/v1`，
返回正常，`prompt_tokens=38`、`completion_tokens=2` —— 就是 system+user 原文，没有额外提示包。

### 5.3 折叠只在越界时发生

- 18 轮历史（1,981 tokens）+ 人为压到 8,000 窗口：代理尝试预检折叠，但折叠用的“侧请求”自身超窗，
  返回 **413 `preflight_compress_failed`**（`The over-window payload was NOT forwarded.`）——诚实拒绝，不截断转发；
- 300 轮历史（42,928 tokens）对 65,536 窗口：**原样转发 42,928**，未折叠（该请求没有工具调用机会，模型无法主动压）。

结论：**没有工具调用机会 = 不会折叠**。这正是本项目当前流量的形态。

---

### 5.4 端到端：产品聊天链路真的走代理（实测）

起后端（`DATABASE_URL=sqlite+aiosqlite:///tmp/agent-proxy-e2e.db`、
`DISABLE_VECTOR_PREWARM=true`、`LLM_PROXY_BASE_URL=http://127.0.0.1:8790/bili/https://api.deepseek.com/v1`），
注册用户 → `POST /api/v1/agent/chat`（`agent_id=researcher`，`session_id=proxy-e2e-session`）→ **HTTP 200**。

三项证据：

1. 后端日志出现 `"event": "llm_proxy_enabled"`（说明 base_url 已切到代理）。
2. 代理日志出现 `[sess=chat:2:proxy-e2e-session] … forward POST → https://api.deepseek.com/v1/chat/completions`，
   即 `agent_service` 传下来的会话键原样落到了 `x-acp-session`，且 2 条消息（system+user）被转发。
3. 代理日志 `request: 2 msgs, inbound=19.6KiB, outbound=31.6KiB, local=165ms` + `[acp-usage] input=7732`，
   与「大 system prompt + 一句用户话」相符，没有额外的历史重复。

这也是「谁用哪个会话键」的验证：聊天是 `chat:{user_id}:{session_id}`，研究任务是 `research:{task_id}`，
两套键不会互相污染。

### 5.5 折叠到底怎么发生（客户端要不要实现工具？—— 不要）

先说结论：**客户端不需要实现压缩工具**。代理会把 `bili_compress` / `bili_decompress` /
`acp_*` 这几个工具**注入**到发往上游的请求里，模型调用后由代理在**服务端**执行折叠，
再把这些内部工具片段从流里过滤掉（`dist/index.js` 的 `PROXY_TOOL_SET` +
`filterRealToolFragments`）。所以我们的 `llm_client` 只要正常发 chat completion 即可。

有两条硬性前提，都是实测踩出来的：

1. **`max_tokens` 必须 > 200**。代理把 `max_tokens <= 200` 的请求当成「侧请求」：
   `side request (max_tokens<=200) → passthrough + tag strip only, kernel state untouched`，
   即不维护会话状态、不折叠。本项目各 agent 的 `max_tokens` 是 1536–2048，天然满足。
2. **请求必须真的携带增长的历史**。折叠靠「历史增长 + 接近窗口阈值」触发；
   每条消息都从零开始（无 history）的调用永远不会折叠。

本机实测（`tmp/bili-fold.json`：32K 窗口、40% 阈值、`nudgeGrowthTokens 4000`；
`tmp/fold_probe.py`：14 轮 × 约 1.7 万 tokens 历史、`max_tokens=600`）：

```text
[acp-proxy: compress requested 1 range(s): m00009–m00028]
[acp-proxy: ctx has 29 message(s), state has 29 ref(s) mapped]
[acp-proxy: refused out-of-recommendation compress — span(s) … (compress.requireRecommendation)]
[context-analysis] fold-probe-1 INJECT T1 @56% — 29 msgs / 34.2KiB ≈ 32K tok
                  · compression: 1 commit(s), ~9008 tok total
[nudge INJECT T1: usage=56% (17447/31400), reason="OVER-LIMIT T1: max effective pending 17151"]
```

读法：模型先提交了一个不在推荐范围内的折叠被**拒绝**（这是 `requireRecommendation: true`
的正常行为，不是故障），随后按推荐范围提交并**成功折叠 ≈9,008 tokens**（`1 commit`）。
同一轮里上游返回 `402 Insufficient Balance`，因此**「折叠后下一次请求的 prompt 降到多少」
这一步没测到**——报告里不许写“省了 X%”，只能说机制通了、绝对值待余额恢复后复测。

配置上也据此调了两处：成本档把 `requireRecommendation` 关掉（DeepSeek 不总按推荐范围提交，
关掉后允许任意在界内的折叠，仍受 `network.maxShrinkPerCompress: 0.5` 与预检约束），
并把 `nudgeGrowthTokens` 从默认 50,000 降到 12,000（成本档窗口 64K，40% 阈值约 26K tokens）。

### 5.6 离线复测：折叠到底能省多少（确定性 mock 上游，2026-11-21）

余额不足时无法用真实模型跑「折叠后 token 曲线」，改用**确定性 mock 上游**（`tmp/mock_upstream2.py`，
逐条记录代理实际转发的消息数与字符数）测**代理行为**本身。两套代理配置同窗口、同样例：

| 代理 | 端口 | 配置 |
| --- | --- | --- |
| 折叠 | 8794 | `tmp/bili-mock.json`：窗口 20,000、`maxContextLimit "40%"`、`emergencyThresholdPercent "60%"`、`preserveRecentMessages 4`、`minSummaryLength 120`、`requireRecommendation false` |
| 直通 | 8795 | `tmp/bili-pass.json`：同上 + `passthrough: true`（不注入、不折叠） |

**协议契约（挡了几轮才试出来，运维必看）**

1. `max_tokens <= 200` 会被当成**侧请求**：`passthrough + tag strip only, kernel state untouched`，不折叠。
2. mock 若上报 `prompt_tokens=1`，代理认为用量 0%，**永远不会 nudge**；要按字符估算上报。
3. 压缩工具参数是**单个 `content` 字符串**（首行 `m00009–m00028 主题`，其后摘要），
   不是 `{"ranges":[...]}`。
4. 范围 ref 必须**按数值升序**，否则报 `reversed range(s) in compress call`。
5. **单个范围至少 5,000 字符**才可折叠；摘要短于 `minSummaryLength` 被整批拒绝；
   一次只折叠一块时，块太碎就会连续失败。
6. 连续三次失败触发 `compress-loop circuit breaker`，之后所有回执都要求停手——**重启代理**才能继续测。

**三档实测**

| 场景 | 直通代理（转发字符） | 折叠代理（转发字符） | 读法 |
| --- | --- | --- | --- |
| 10 轮历史 + 6 次追问（约 9.7K 字符） | 9,693 → 9,722 → 9,751 → 9,780 → 9,809 → 9,838（每轮 +29） | 19,029 → 17,525 → 18,087 → 19,107 → 19,685 → 20,721 | 首轮即注入工具包（约 +9.3K 字符）；每轮成功折叠一块，但历史太小，**摘要开销 > 折叠收益**，累积净增 |
| 15.5K 字符 / 42 条消息，两轮 | #1 15,495；#2 15,526 | #1 26,231（含工具包）；#2 16,935 | 折叠确实砍掉约 9.3K 字符前缀，但**仍比直通同轮多 1,409 字符** |
| 46.6K 字符 / 122 条消息，首轮 | #1 46,575（mock 不拦） | **HTTP 502 `preflight_compress_failed`** | `context ~43,966 tokens exceeds the model window 19,400`；剩余可折叠 18,091 tokens 补不上 24,566 的缺口，三块还因不足 5,000 字符被拒；`The over-window payload was NOT forwarded.` |

**结论（对外可说 / 不可说）**

- 可说：**未接近窗口时零开销、逐字转发**；接近阈值时代理才注入工具包（约 1.4–2.9K tokens）并触发折叠；
  **首次接触就已远超窗口时，代理诚实拒绝、不转发**——这正好符合本项目的诚实失败原则。
- 可说：折叠必须**提前、连续地**发生（长会话里持续 nudge 才有效），**不能当兜底救援**；
  因此应用自己仍必须把单次请求压在上限内（研究流水线已按 100k tokens/任务预算切窗口）。
- 不可说：「接入代理已省 X% token」。本次离线复测里，短历史与中等历史都是**净增**；
  真实长会话的净收益要等余额恢复、用真实模型的折叠频率复测。

### 5.7 真实模型复测（2026-11-21 晚，余额恢复后，按成本最小化设计）

目标：用真实 `deepseek-v4-flash` 测「折叠前后 `prompt_tokens`」。为省钱，窗口故意压到 16,000 / 8,000，
`max_tokens=400`、关闭思维链，每轮只加一小段材料（12 轮设计、实际跑到 8 轮）。**结果：折叠没有触发**，
但必须如实报告两项实测开销与两道硬门槛：

**① 折叠能力是“常驻开销”，不是“用到了才付费”**

| 轮次 | 折叠配置（窗口 16,000）`prompt_tokens` | 直通配置同轮 | 说明 |
| --- | --- | --- | --- |
| 1 | 3,057 | 97 | 首轮差值≈2,960 token：代理注入压缩工具集 + lean pack |
| 2 | 3,300 | 216 | `cached=2944`（命中 89%） |
| 3 | 3,551 | 334 | `cached=3200`（命中 90%） |

即：只要配置成“可折叠”，**每次调用固定多付约 2.9–3.0K 输入 token**；靠 DeepSeek 前缀缓存能把这部分打到约 1/10 价，
但它仍然占用窗口、也仍然计入 usage。**这是接入折叠能力的真实代价，此前“零注入”的结论只适用于远离窗口、未武装的会话。**

**② 两道门槛让“短会话根本不折叠”**

- 增长门槛：`growth floor = max(20K, 0.45 × nudgeGrowthTokens)` 是绝对值。我们把 `nudgeGrowthTokens` 降到 2,000，
  门槛仍是 **20,000 tokens 增长**；8 轮只涨了 1,215 tokens，日志每条都是
  `nudge idle: … reason="max compressible 0 < threshold 2500; growth 1215 < floor 20000"`。
- 压力门槛：把窗口压到 8,000、阈值 25% 后 usage 早已越线，但 nudge 仍报 `max compressible 0`——
  短轮次（每轮一两百字符）在代理看来没有足够的可折叠质量，且单范围下限是 **5,000 字符**。
  要真触发，需要「一次会话里 ≥20K tokens 可折叠历史」；那样每次调用本身就 >20K 输入 tokens。

**结论（成本优先，据此定产品口径）**

- **成本换不来收益**：在真实 1M 窗口下，我们的聊天/研究任务都离触发线极远；为验证折叠去烧 20K+ tokens/轮的真实调用，
  与“用余额做真实质量评估”相比性价比极低，因此**不继续烧钱复测**。
- 对外只写：折叠机制在代理侧成立（§5.5 真实日志 + §5.6 mock 数据），**但接入会带来约 3K 输入 token/次的常驻开销，
  且在当前产品形态下不会触发，默认关闭是正确选择**；不写任何节省比例。
- 成本记录：本轮真实调用合计约 **41K tokens**（3 轮折叠探针 9.9K + 8 轮折叠探针 30.1K + 直通基线 0.6K + 连通性探测），
  基本都落在前缀缓存上，按 flash 价格折算不足 1 美分。

## 6. 单测与验收

```bash
python -m pytest src/backend/tests/test_llm_proxy.py -q            # 6 passed（无网络）
python -m pytest src/backend/tests/test_research -q                # 290 passed（确认未回归）
python scripts/bili_payload_probe.py --turns 6                     # 退出码 0 = 原样转发
```

覆盖：默认直连行为不变、base_url 切换、超时抬高、会话头仅在启用+有键时下发、
研究流水线 `session_key` 透传（并校验无键时不透传）。

---

## 7. 风险与注意事项

1. **不要把“接入代理”当成“省 token”对外宣传**。当前产品形态下开销≈0、收益≈0；
   若将来做成带历史的 agent 循环，才可能出现真实收益，届时需用真实长会话重新测。
2. **会话键必须按用户/任务隔离**：跨用户复用会把别人的上下文折叠进你的摘要（代码已按用户/任务生成键）。
3. **折叠会让单次调用变慢**：代理要发侧请求总结历史；`LLM_PROXY_TIMEOUT_SECONDS=180` 是为它留的余量。
4. **代理是可选组件**：不可用时最稳妥的做法是**去掉 env 直连**，而不是让请求失败——
   因此默认关闭、失败不重试代理。
5. 会话数据落在 `tmp/bili-data`（已随 `tmp/` 被 gitignore），不要把它当持久化存储。
6. **不要指望代理兜底超窗**：首次请求就已远超窗口时它返回 `preflight_compress_failed` 并
   **不转发**（§5.6 第三档实测）。应用侧必须自己保证单次 payload 在窗口内。

---

## 8. 最近一次结果（2026-11-21）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 代理单测 | `pytest src/backend/tests/test_llm_proxy.py -q` | 6 passed |
| 代理单测 + R0 回归 | `pytest src/backend/tests/test_llm_proxy.py src/backend/tests/test_research -q` | 296 passed（6 + 290） |
| R1 + R2 研究域回归 | `pytest src/backend/tests/test_research_r1 src/backend/tests/test_research_r2 -q` | 217 passed, 1 skipped |
| 零注入探针 | `python scripts/bili_payload_probe.py --turns 6` | exit 0，直连/经代理 payload 完全一致（14 条消息、704 字符、无 tools） |
| 真实调用 | 见 §5.2 | 正常返回，`prompt_tokens=38`（无注入） |
| 启停脚本 | `--detach` / `--status` / `--stop` | 均可用；端口占用时拒绝启动；数据目录隔离在 `tmp/bili-data` |
| 折叠行为（离线 mock） | `tmp/fold_measure.py`、`tmp/fold_series.py`、`tmp/fold_big.py` | 折叠成功（`[Compressed m00001–m00026 → 1 block(s)]`），单次转发从 19,026 → 17,488 字符（-8.1%）；短/中历史净增、超窗被诚实拒绝，结论见 §5.6 |
| 折叠行为（真实模型，32K 窗口） | `tmp/fold_probe.py` | `1 commit(s), ~9008 tok` 折叠成功；随后上游 402 |
| 折叠开销（真实模型） | 见 §5.7 | 可折叠配置下每次调用多付约 2.9–3.0K 输入 token（缓存命中 89–90%）；8 轮未触发折叠，实测合计约 41K tokens |
