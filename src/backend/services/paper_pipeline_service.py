"""
论文生成 Pipeline 服务

将 cyclical-paper-generation 技能（v7.4.0, 13 Agent 循环式论文生成 Pipeline）
集成到 ScholarMind Agent 中。

设计策略：
1. 启动时尝试导入技能的 Pipeline 模块（需要 langgraph 等依赖）
2. 若导入失败 → start_pipeline 直接抛错（不降级为模拟模式，避免假装成功）
3. 状态持久化到 Redis（PipelineStateRepo），进程重启后可恢复查询
4. asyncio 任务引用保留在内存中，用于取消正在运行的 Pipeline
5. 学科 → 期刊格式自动映射
"""

from __future__ import annotations

import sys
import os
import uuid
import asyncio
import structlog
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from ..config import settings
from ..db.pipeline_state_repo import get_pipeline_state_repo
from ..core.exceptions import AppException
from ..models.error_codes import ErrorCode
from .pipeline_utils import (
    RESEARCH_TYPE_MAP,
    DISCIPLINE_TO_JOURNAL,
    check_pipeline_ownership,
    calculate_pipeline_progress,
)

logger = structlog.get_logger(__name__)

# P0 修复: Pipeline 并发控制（最多 3 个同时执行，防止 LLM API 429）
_PIPELINE_SEMAPHORE = asyncio.Semaphore(settings.PIPELINE_MAX_CONCURRENCY)
_PIPELINE_TIMEOUT_SECONDS = settings.PIPELINE_TIMEOUT_SECONDS
_PIPELINE_ROUND_TIMEOUT_SECONDS = settings.PIPELINE_ROUND_TIMEOUT_SECONDS
_PIPELINE_HEARTBEAT_INTERVAL_SECONDS = settings.PIPELINE_HEARTBEAT_INTERVAL_SECONDS
_PIPELINE_PROGRESS_SYNC_INTERVAL_SECONDS = settings.PIPELINE_PROGRESS_SYNC_INTERVAL_SECONDS

# ── 技能目录路径（P4-T7：从环境变量读取，避免硬编码） ─────
# 主目录：可能被 Railway volume 挂载覆盖
_SKILLS_BASE = os.environ.get("SKILLS_DIR", str(Path.home() / ".trae-cn" / "skills"))
SKILL_DIR = Path(_SKILLS_BASE) / "cyclical-paper-generation"
PIPELINE_DIR = SKILL_DIR / "pipeline"

# 备用目录：Docker 构建时复制到 /app/skills_builtin/，不会被 volume 覆盖
_SKILLS_BUILTIN = os.environ.get("SKILLS_BUILTIN_DIR", "")
if _SKILLS_BUILTIN:
    _BUILTIN_SKILL_DIR = Path(_SKILLS_BUILTIN) / "cyclical-paper-generation"
    _BUILTIN_PIPELINE_DIR = _BUILTIN_SKILL_DIR / "pipeline"
else:
    _BUILTIN_SKILL_DIR = None
    _BUILTIN_PIPELINE_DIR = None

# ── 13 Agent 执行顺序（用于进度计算）──────────────────────
AGENT_EXECUTION_ORDER = [
    ("constraint_injector", "约束注入器", "注入风格约束 + 违规回灌"),
    ("polisher", "润色者", "声音锚点/改写原则/节奏多样性"),
    ("style_validator", "风格守卫", "程序化风格约束验证"),
    ("visualizer", "可视化者", "4表+4图+英文摘要"),
    ("methodologist", "方法论专家", "方法论审核（量/质/计算）"),
    ("literature_curator", "文献策展人", "文献验证/中文补充/格式统一"),
    ("expert", "内容专家", "论证逻辑/理论对话/概念定义"),
    ("word_count_controller", "字数控制器", "逐节字数审计+超标压缩"),
    ("narrator", "叙事连贯性主编", "叙事弧线/段落过渡/朗读测试"),
    ("orchestrator", "编排者", "执行策略/趋势监控/资源分配"),
    ("reviewer", "审稿人", "9维度评分+否思+编码优化"),
    ("adversarial_critic", "对抗评分者", "GAN D侧挑刺评分"),
    ("word_format_validator", "Word格式验证", "脚注/引号字体/文档完整性"),
]

# ── 尝试导入真实 Pipeline ─────────────────────────────────
_PIPELINE_AVAILABLE = False
_pipeline_create = None
_pipeline_run = None
_PipelineConfig = None
_PIPELINE_INIT_ERROR: str | None = None  # 记录初始化失败的具体原因


def _try_import_pipeline() -> bool:
    """尝试导入 cyclical-paper-generation 的 Pipeline 模块

    使用 importlib 直接加载技能目录中的模块，避免与 cyclical-paper-review
    的 pipeline.loop_controller 发生模块名冲突。
    """
    global _PIPELINE_AVAILABLE, _pipeline_create, _pipeline_run, _PipelineConfig, _PIPELINE_INIT_ERROR

    if _PIPELINE_AVAILABLE:
        return True

    # 选择有效的技能目录：优先主目录，不存在时回退到内置目录
    _active_skill_dir = SKILL_DIR
    _active_pipeline_dir = PIPELINE_DIR
    if not _active_pipeline_dir.exists() and _BUILTIN_PIPELINE_DIR is not None and _BUILTIN_PIPELINE_DIR.exists():
        logger.warning(f"Primary pipeline dir not found, falling back to builtin: {_BUILTIN_PIPELINE_DIR}")
        _active_skill_dir = _BUILTIN_SKILL_DIR
        _active_pipeline_dir = _BUILTIN_PIPELINE_DIR

    if not _active_pipeline_dir.exists():
        _PIPELINE_INIT_ERROR = f"Pipeline skill directory not found: {PIPELINE_DIR} (SKILLS_DIR={_SKILLS_BASE}), builtin fallback also not found: {_BUILTIN_PIPELINE_DIR}"
        logger.warning(_PIPELINE_INIT_ERROR)
        return False

    try:
        import langgraph  # noqa: F401
        import importlib.util

        # 保存并清空 pipeline.* 模块缓存
        _saved_path = list(sys.path)
        _cleared = {}
        for k in list(sys.modules.keys()):
            if k.startswith("pipeline."):
                _cleared[k] = sys.modules.pop(k)

        # 将正确目录插入 sys.path
        skill_path = str(_active_skill_dir)
        sys.path.insert(0, skill_path)

        # 从正确目录预加载所有子模块（注册为 pipeline.xxx）
        _pipeline_mods = [
            "llm_executor",
            "style_constraints",
            "word_validation",
            "gan_scorer",
            "shared_learning",
            "voice_extractor",
        ]
        for _mod_name in _pipeline_mods:
            _f = _active_pipeline_dir / f"{_mod_name}.py"
            if _f.exists():
                _spec = importlib.util.spec_from_file_location(f"pipeline.{_mod_name}", str(_f))
                if _spec and _spec.loader:
                    _mod = importlib.util.module_from_spec(_spec)
                    sys.modules[f"pipeline.{_mod_name}"] = _mod
                    _spec.loader.exec_module(_mod)

        # now from . import xxx will find the correct modules
        from pipeline.loop_controller import create_pipeline, run_pipeline
        from pipeline.config import PipelineConfig

        _pipeline_create = create_pipeline
        _pipeline_run = run_pipeline
        _PipelineConfig = PipelineConfig

        # 恢复 sys.path（保留 pipeline.* 在 sys.modules 中，
        # 确保运行时 from . import xxx 始终找到正确的模块）
        sys.path[:] = _saved_path
        _PIPELINE_AVAILABLE = True
        logger.info(f"cyclical_paper_pipeline_loaded version=v7.4.0 path={_active_skill_dir}")
        return True

    except ImportError as e:
        _PIPELINE_INIT_ERROR = f"ImportError: {e} (hint: pip install langgraph)"
        logger.warning(
            f"cyclical_paper_pipeline_unavailable reason=import_failed error={e} "
            f"hint=Install langgraph: pip install langgraph"
        )
        return False
    except Exception as e:
        _PIPELINE_INIT_ERROR = f"{type(e).__name__}: {e}"
        logger.warning(f"cyclical_paper_pipeline_unavailable reason=unexpected_error error={e}")
        return False


class PipelineUnavailableError(RuntimeError):
    """Pipeline 依赖未安装时抛出"""


# ── 线程安全：同步 Pipeline 执行包装器 ─────────────────────


def _run_pipeline_with_cancel(
    paper_content: str,
    config: Any,
    *,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[callable] = None,
) -> Optional[dict]:
    """在同步线程中运行 Pipeline，支持取消和进度回调

    供 PaperPipelineService._run_real_pipeline 在线程池中调用。
    当 cancel_event 被设置时，Pipeline 抛出 RuntimeError 退出，此函数返回 None。
    """
    try:
        return _pipeline_run(
            paper_content=paper_content,
            config=config,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
    except RuntimeError as e:
        if "cancelled" in str(e).lower() or "cancel" in str(e).lower():
            return None
        raise


class PaperPipelineService:
    """论文生成 Pipeline 服务"""

    def __init__(self):
        # 状态持久化仓库（Redis 优先，内存降级）
        self._repo = get_pipeline_state_repo()
        # asyncio 任务引用：pipeline_id → Task（仅用于取消运行中的任务）
        # 注意：任务引用不持久化，进程重启后无法取消旧任务，但仍可查询状态
        self._tasks: dict[str, asyncio.Task] = {}
        # 取消事件：pipeline_id → threading.Event（跨线程通信）
        self._cancel_events: dict[str, threading.Event] = {}
        # 尝试加载真实 Pipeline
        self._real_available = _try_import_pipeline()

    # ── 公开 API ──────────────────────────────────────────

    async def start_pipeline(
        self,
        session_id: str,
        agent_id: str,
        guidance_data: dict[str, Any],
        discipline: Optional[str] = None,
        research_type: Optional[str] = None,
        journal_style: Optional[str] = None,
        max_rounds: int = 5,
        pass_threshold: int = 90,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """启动一个论文生成 Pipeline 实例

        Returns:
            dict with keys: pipeline_id, status, message, config

        Raises:
            PipelineUnavailableError: 真实 Pipeline 依赖未安装
        """
        if not self._real_available:
            reason = _PIPELINE_INIT_ERROR or "unknown reason"
            raise PipelineUnavailableError(f"论文生成 Pipeline 依赖未安装，无法启动。原因：{reason}")

        pipeline_id = str(uuid.uuid4())

        # 解析期刊格式
        if not journal_style:
            journal_style = DISCIPLINE_TO_JOURNAL.get(discipline or "", "xwycbyj")

        # 解析研究类型
        resolved_research_type = "qualitative"
        if research_type:
            resolved_research_type = RESEARCH_TYPE_MAP.get(
                research_type, RESEARCH_TYPE_MAP.get(research_type.lower(), "qualitative")
            )
        if "method" in guidance_data:
            method_str = str(guidance_data["method"]).lower()
            for key, val in RESEARCH_TYPE_MAP.items():
                if key in method_str:
                    resolved_research_type = val
                    break

        # 构建配置
        config = {
            "pipeline_id": pipeline_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "discipline": discipline,
            "research_type": resolved_research_type,
            "journal_style": journal_style,
            "max_rounds": max_rounds,
            "pass_threshold": pass_threshold,
            "guidance_data": guidance_data,
        }

        # 初始化状态并持久化
        initial_state = {
            "pipeline_id": pipeline_id,
            "user_id": user_id,
            "session_id": session_id,
            "status": "pending",
            "config": config,
            "current_round": 0,
            "current_agent": None,
            "current_step": "初始化中",
            "score": None,
            "score_history": [],
            "logs": ["Pipeline 已创建"],
            "error": None,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "result": None,
            "simulation_mode": False,
        }
        await self._repo.save(pipeline_id, initial_state, user_id=user_id)

        # 异步启动 Pipeline 执行（保留 task 引用用于取消）
        task = asyncio.create_task(self._run_pipeline_async(pipeline_id, config))
        self._tasks[pipeline_id] = task
        # 任务结束后自动清理引用
        task.add_done_callback(lambda _t: self._tasks.pop(pipeline_id, None))

        return {
            "pipeline_id": pipeline_id,
            "status": "pending",
            "message": "Pipeline 已启动，13 Agent 循环式论文生成即将开始",
            "config": config,
        }

    async def get_status(self, pipeline_id: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """查询 Pipeline 状态

        P0 Task 3.3：若提供 user_id，校验 pipeline 归属；不属于当前用户返回 None
        （Router 层映射为 404，不暴露对象存在性）。
        """
        p = await self._repo.get(pipeline_id)
        if not p:
            return None
        # 所有权校验：state["user_id"] 与请求 user_id 必须一致
        if not check_pipeline_ownership(p, user_id):
            return None

        max_rounds = p["config"].get("max_rounds", 5)
        current_round = p["current_round"]
        progress = calculate_pipeline_progress(p, AGENT_EXECUTION_ORDER)

        return {
            "pipeline_id": pipeline_id,
            "status": p["status"],
            "current_round": current_round,
            "max_rounds": max_rounds,
            "current_agent": p.get("current_agent"),
            "current_step": p.get("current_step"),
            "score": p.get("score"),
            "pass_threshold": p["config"].get("pass_threshold", 90),
            "score_history": p.get("score_history", []),
            "progress": round(progress, 4),
            "logs": p.get("logs", [])[-50:],
            "error": p.get("error"),
            "started_at": p.get("started_at"),
            "completed_at": p.get("completed_at"),
            "simulation_mode": p.get("simulation_mode", False),
        }

    async def get_result(self, pipeline_id: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """获取 Pipeline 最终结果

        P0 Task 3.3：若提供 user_id，校验 pipeline 归属；不属于当前用户返回 None。
        """
        p = await self._repo.get(pipeline_id)
        if not p:
            return None
        if not check_pipeline_ownership(p, user_id):
            return None

        result = p.get("result") or {}
        return {
            "pipeline_id": pipeline_id,
            "status": p["status"],
            "final_score": result.get("final_score") or p.get("score"),
            "total_rounds": p["current_round"],
            "paper_title": result.get("paper_title"),
            "paper_content": result.get("paper_content"),
            "dimension_scores": result.get("dimension_scores", {}),
            "review_report": result.get("review_report"),
            "output_path": result.get("output_path"),
            "version_history": result.get("version_history", []),
            "message": "Pipeline 结果获取成功" if p["status"] == "completed" else "Pipeline 尚未完成",
        }

    async def list_pipelines(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """列出 Pipeline（按 user_id 或 session_id 过滤）

        P0 Task 3.3：必须提供 user_id（强制鉴权后总有值）；
        未提供 user_id 时返回空列表（不再允许匿名遍历所有）。
        """
        if user_id:
            states = await self._repo.list_by_user(user_id, limit=100)
        else:
            # Task 24.2: 注释修正——无 user_id 时返回空列表（与实际 return [] 一致）
            # 内存降级场景下没有全局索引，直接返回空列表
            # 真实生产应使用 Redis SCAN，此处保持简单
            return []

        result = []
        for p in states:
            if session_id and p.get("config", {}).get("session_id") != session_id:
                continue
            cfg = {k: v for k, v in p.get("config", {}).items() if k != "guidance_data"}
            result.append(
                {
                    "pipeline_id": p["pipeline_id"],
                    "status": p.get("status"),
                    "current_round": p.get("current_round", 0),
                    "score": p.get("score"),
                    "started_at": p.get("started_at"),
                    "completed_at": p.get("completed_at"),
                    "config": cfg,
                }
            )
        result.sort(key=lambda x: x["started_at"] or "", reverse=True)
        return result

    async def cancel_pipeline(self, pipeline_id: str, user_id: Optional[str] = None) -> bool:
        """取消运行中的 Pipeline

        P0 Task 3.3：若提供 user_id，校验 pipeline 归属；不属于当前用户返回 False
        （Router 层映射为 404）。

        Returns:
            True 表示已发送取消信号；False 表示任务已结束或不存在或不属于当前用户
        """
        # 先校验归属
        p = await self._repo.get(pipeline_id)
        if not p:
            return False
        if not check_pipeline_ownership(p, user_id):
            return False

        # 设置取消事件（跨线程通知）
        cancel_event = self._cancel_events.get(pipeline_id)
        if cancel_event:
            cancel_event.set()

        # 取消 asyncio Task（会触发 CancelledError）
        task = self._tasks.get(pipeline_id)
        if task is None or task.done():
            return False
        task.cancel()
        # 更新状态
        await self._repo.update_status(
            pipeline_id,
            "cancelled",
            completed_at=datetime.now().isoformat(),
            current_step="用户取消",
            current_agent=None,
        )
        await self._repo.append_log(pipeline_id, "用户取消 Pipeline")
        return True

    # ── 内部：Pipeline 执行 ────────────────────────────────

    async def _run_pipeline_async(self, pipeline_id: str, config: dict[str, Any]):
        """异步执行 Pipeline（P0 修复: 增加并发控制 + 超时保护 + 取消支持）"""
        # P0 修复: Semaphore.acquire() 永远返回 True，原 if not acquired 分支为死代码；
        # 改为 try/except asyncio.TimeoutError 抛 AppException(503)，让客户端可重试。
        # 注意：超时分支不持有信号量，不可进入下面的 finally release()。
        acquire_timeout = (
            settings.PIPELINE_ACQUIRE_TIMEOUT_SECONDS if hasattr(settings, "PIPELINE_ACQUIRE_TIMEOUT_SECONDS") else 30.0
        )
        try:
            await asyncio.wait_for(_PIPELINE_SEMAPHORE.acquire(), timeout=acquire_timeout)
        except asyncio.TimeoutError:
            # 标记 pipeline 失败状态（避免状态机停在 pending），然后抛 503
            await self._repo.update_status(
                pipeline_id,
                "failed",
                error="Pipeline 并发已达上限，请稍后重试",
                completed_at=datetime.now().isoformat(),
            )
            raise AppException(
                message="Pipeline concurrency limit reached, please retry later",
                code=ErrorCode.PIPELINE_CONCURRENCY_FULL,
                status_code=503,
            )

        # 取消事件：用于跨线程通信（asyncio Task.cancel → threading.Event.set）
        cancel_event = threading.Event()
        self._cancel_events[pipeline_id] = cancel_event

        try:
            await self._repo.update_status(
                pipeline_id,
                "running",
                current_step="Pipeline 开始执行",
            )
            await self._repo.append_log(pipeline_id, "Pipeline 开始执行")

            # 启动心跳协程：每 15 秒更新一次心跳，确保前端知道 Pipeline 未卡死
            heartbeat_task = asyncio.create_task(self._heartbeat(pipeline_id, cancel_event))

            try:
                await asyncio.wait_for(
                    self._run_real_pipeline(pipeline_id, config, cancel_event),
                    timeout=_PIPELINE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                cancel_event.set()
                await self._repo.update_status(
                    pipeline_id,
                    "failed",
                    error=f"Pipeline 执行超时（{_PIPELINE_TIMEOUT_SECONDS}s）",
                    completed_at=datetime.now().isoformat(),
                )
                await self._repo.append_log(pipeline_id, "Pipeline 执行超时")
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        except asyncio.CancelledError:
            cancel_event.set()
            await self._repo.append_log(pipeline_id, "Pipeline 被取消")
            # 不 reraise — 状态已在 cancel_pipeline() 中更新
        except Exception as e:
            cancel_event.set()
            await self._repo.update_status(
                pipeline_id,
                "failed",
                error=str(e),
                completed_at=datetime.now().isoformat(),
                current_step=f"失败: {e}",
            )
            await self._repo.append_log(pipeline_id, f"Pipeline 失败: {e}")
            logger.error(f"Pipeline {pipeline_id} failed: {e}", exc_info=True)
        finally:
            _PIPELINE_SEMAPHORE.release()
            self._cancel_events.pop(pipeline_id, None)

    async def _heartbeat(self, pipeline_id: str, cancel_event: threading.Event):
        """心跳协程：每 N 秒更新一次日志时间戳，防止前端认为 Pipeline 卡死"""
        count = 0
        interval = _PIPELINE_HEARTBEAT_INTERVAL_SECONDS
        while not cancel_event.is_set():
            await asyncio.sleep(interval)
            count += 1
            count * interval
            try:
                state = await self._repo.get(pipeline_id)
                if state and state.get("status") == "running":
                    state["updated_at"] = datetime.now().isoformat()
                    await self._repo.save(pipeline_id, state, user_id=state.get("user_id"))
            except Exception as e:
                # P1 Task 8.1：心跳失败不影响主流程，但需记录便于排查
                logger.error(f"heartbeat failed task_id={pipeline_id} exc={e}")

    async def _run_real_pipeline(self, pipeline_id: str, config: dict[str, Any], cancel_event: threading.Event):
        """运行真实 Pipeline（需要 langgraph 等依赖）

        在线程池中运行 Pipeline，通过 cancel_event 支持取消。
        Pipeline 每执行一个 LangGraph 节点后检查取消标志。
        """
        pc = _PipelineConfig(
            max_rounds=config["max_rounds"],
            pass_threshold=config["pass_threshold"],
            journal_style=config["journal_style"],
            research_type=config["research_type"],
        )

        guidance = config.get("guidance_data", {})
        paper_content = self._build_initial_paper(guidance, config)

        await self._repo.append_log(
            pipeline_id,
            f"调用 cyclical-paper-generation v7.4.0 Pipeline | 期刊={config['journal_style']} 研究类型={config['research_type']}",
        )

        # 使用共享字典跨线程传递进度信息
        progress_shared = {"current_node": "", "current_round": 1, "score": None}

        def progress_callback(node_name: str, node_state: dict):
            progress_shared["current_node"] = node_name
            if node_state.get("round_number"):
                progress_shared["current_round"] = node_state["round_number"]
            if node_state.get("review_score") is not None:
                progress_shared["score"] = node_state["review_score"]

        # 在独立线程中运行 Pipeline（通过 run_in_executor）
        loop = asyncio.get_event_loop()

        # 启动进度同步协程：每 N 秒将线程中的进度写入 Redis（Task 24.3: 配置化）
        async def sync_progress():
            while not cancel_event.is_set():
                await asyncio.sleep(_PIPELINE_PROGRESS_SYNC_INTERVAL_SECONDS)
                try:
                    node = progress_shared["current_node"]
                    rnd = progress_shared["current_round"]
                    score = progress_shared["score"]
                    if node:
                        await self._repo.update_status(
                            pipeline_id,
                            "running",
                            current_round=rnd,
                            current_agent=node,
                            current_step=f"执行中: {node} (第 {rnd} 轮)",
                            score=score,
                        )
                except Exception:
                    pass

        sync_task = asyncio.create_task(sync_progress())

        try:
            result = await loop.run_in_executor(
                None,
                lambda: _run_pipeline_with_cancel(
                    paper_content=paper_content,
                    config=pc,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                ),
            )

            if result is None:
                # 被取消 — 不要覆盖状态
                return

            update = {
                "current_round": result.get("round_number", config["max_rounds"]),
                "score": result.get("review_score"),
                "score_history": result.get("score_history", []),
                "completed_at": datetime.now().isoformat(),
                "current_step": "已完成",
                "current_agent": None,
                "result": {
                    "final_score": result.get("review_score"),
                    "paper_title": result.get("paper_title", ""),
                    "paper_content": result.get("paper_content", ""),
                    "dimension_scores": result.get("dimension_scores", {}),
                    "review_report": result.get("review_report", ""),
                    "output_path": result.get("output_path"),
                    "version_history": result.get("version_history", []),
                },
            }
            await self._repo.update_status(pipeline_id, "completed", **update)
            await self._repo.append_log(pipeline_id, f"✅ Pipeline 完成，最终评分: {update['score']}")
        finally:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass

    def _build_initial_paper(self, guidance_data: dict, config: dict) -> str:
        """从引导数据构建初始论文内容（供真实 Pipeline 使用）"""
        topic = guidance_data.get("topic", "未指定主题")
        angle = guidance_data.get("angle", "未指定角度")
        subject = guidance_data.get("subject", "未指定对象")
        method = guidance_data.get("method", "未指定方法")
        discipline = config.get("discipline", "未指定")
        research_type = config.get("research_type", "qualitative")

        return f"""# {topic}

## 研究构想
- 研究现象：{topic}
- 研究角度：{angle}
- 研究对象：{subject}
- 研究方法：{method}
- 学科领域：{discipline}
- 研究类型：{research_type}

## 摘要
（待生成）

## 引言
（待生成）

## 文献综述
（待生成）

## 研究设计与方法
（待生成）

## 研究发现
（待生成）

## 讨论
（待生成）

## 结论
（待生成）
"""


# ── 单例 ──────────────────────────────────────────────────
_service_instance: Optional[PaperPipelineService] = None


def get_paper_pipeline_service() -> PaperPipelineService:
    """获取 PaperPipelineService 单例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = PaperPipelineService()
    return _service_instance
