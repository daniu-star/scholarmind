"""
论文审稿优化 Pipeline 服务

将 cyclical-paper-review 技能（v1.7, 9 Agent 循环式论文审稿优化 Pipeline）
集成到 ScholarMind Agent 中。

设计策略：
1. 启动时尝试导入技能的 Pipeline 模块（需要 langgraph 等依赖）
2. 若导入失败 → start_review 直接抛错（不降级为模拟模式）
3. 状态持久化到 Redis（PipelineStateRepo），进程重启后可恢复查询
4. asyncio 任务引用保留在内存中，用于取消正在运行的审稿
5. 支持 6 种研究类型 + 4 种 CSSCI 期刊格式
"""
from __future__ import annotations

import os
import sys
import uuid
import asyncio
import structlog
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from ..db.pipeline_state_repo import get_pipeline_state_repo

logger = structlog.get_logger(__name__)

# P0 修复: 审稿 Pipeline 并发控制 + 超时
_REVIEW_SEMAPHORE = asyncio.Semaphore(2)
_REVIEW_TIMEOUT_SECONDS = 600
_REVIEW_ROUND_TIMEOUT_SECONDS = 120

# ── 技能目录路径（P4-T7：从环境变量读取，避免硬编码） ─────
_SKILLS_BASE = os.environ.get('SKILLS_DIR', str(Path.home() / ".trae-cn" / "skills"))
SKILL_DIR = Path(_SKILLS_BASE) / "cyclical-paper-review"
PIPELINE_DIR = SKILL_DIR / "pipeline"

# ── 研究类型映射（前端值 → Pipeline 值）──────────────────
RESEARCH_TYPE_MAP = {
    "quantitative": "quantitative",
    "qualitative": "qualitative",
    "mixed": "mixed",
    "computational": "computational",
    "theoretical": "theoretical",
    "interview_report": "interview_report",
    # 中文别名
    "量化研究": "quantitative",
    "质性研究": "qualitative",
    "混合方法": "mixed",
    "混合": "mixed",
    "计算社会科学": "computational",
    "理论论文": "theoretical",
    "访谈报告": "interview_report",
}

# ── 输出格式映射（前端值 → Pipeline 值）──────────────────
_OUTPUT_FORMAT_MAP = {
    "docx": "word",
    "word": "word",
    "markdown": "markdown",
    "md": "markdown",
    "txt": "markdown",
}

# ── 9 Agent 执行顺序（用于进度计算）──────────────────────
AGENT_EXECUTION_ORDER = [
    ("constraint_injector", "约束注入器", "注入风格约束 + 评审维度 + 期刊格式"),
    ("external_reviewer", "外审专家", "9 维度评分（G侧）"),
    ("adversarial_critic", "对抗评分者", "D侧挑刺评分（GAN）"),
    ("opinion_router", "意见路由", "将外审意见路由到对应修改者"),
    ("parallel_reviser", "并行修改者", "摘要/引言/综述/发现并行修改"),
    ("style_guard", "风格守卫", "节奏/多样性/声音一致性验证"),
    ("instruction_guard", "指令守卫", "防遗忘用户初始指令"),
    ("format_output", "格式输出", "Word/Markdown/TXT 格式化 + 评分对比"),
    ("human_intervention", "人工介入", "停滞/回滚超限时升级"),
]

PASS_THRESHOLD = 95  # 比 generation 的 90 更严格

# ── 尝试导入真实 Pipeline ─────────────────────────────────
_PIPELINE_AVAILABLE = False
_pipeline_create = None
_pipeline_run = None
_PipelineConfig = None


def _try_import_pipeline() -> bool:
    """尝试导入 cyclical-paper-review 的 Pipeline 模块

    修复历史 Bug：原代码导入 `create_review_pipeline, run_review_pipeline`，
    但技能实际导出 `create_pipeline, run_pipeline`，导致静默 ImportError
    永远降级为模拟模式。
    """
    global _PIPELINE_AVAILABLE, _pipeline_create, _pipeline_run, _PipelineConfig

    if _PIPELINE_AVAILABLE:
        return True

    if not PIPELINE_DIR.exists():
        logger.warning(f"Pipeline skill directory not found: {PIPELINE_DIR}")
        return False

    try:
        skill_path = str(SKILL_DIR)
        if skill_path not in sys.path:
            sys.path.insert(0, skill_path)

        import langgraph  # noqa: F401

        # 修复：技能实际导出的是 create_pipeline / run_pipeline（与生成 Pipeline 同名）
        from pipeline.loop_controller import create_pipeline, run_pipeline
        from pipeline.config import PipelineConfig

        _pipeline_create = create_pipeline
        _pipeline_run = run_pipeline
        _PipelineConfig = PipelineConfig
        _PIPELINE_AVAILABLE = True
        logger.info(f"cyclical_paper_review_pipeline_loaded version=v1.7 path={SKILL_DIR}")
        return True

    except ImportError as e:
        logger.warning(
            f"cyclical_paper_review_pipeline_unavailable reason=import_failed error={e} "
            f"hint=Install langgraph: pip install langgraph"
        )
        return False
    except Exception as e:
        logger.warning(
            f"cyclical_paper_review_pipeline_unavailable reason=unexpected_error error={e}"
        )
        return False


class ReviewUnavailableError(RuntimeError):
    """审稿 Pipeline 依赖未安装时抛出"""


class PaperReviewService:
    """论文审稿优化 Pipeline 服务"""

    def __init__(self):
        self._repo = get_pipeline_state_repo()
        # asyncio 任务引用：review_id → Task（仅用于取消运行中的任务）
        self._tasks: dict[str, asyncio.Task] = {}
        # 取消事件：review_id → threading.Event
        self._cancel_events: dict[str, threading.Event] = {}
        self._real_available = _try_import_pipeline()

    # ── 公开 API ──────────────────────────────────────────

    async def start_review(
        self,
        paper_text: str,
        research_type: Optional[str] = None,
        journal_style: Optional[str] = None,
        output_format: str = "docx",
        max_rounds: int = 5,
        session_id: Optional[str] = None,
        revision_focus: Optional[str] = None,
        reviewer_comments: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """启动一个论文审稿优化任务

        Returns:
            dict with keys: review_id, status, message, config

        Raises:
            ReviewUnavailableError: 真实 Pipeline 依赖未安装
        """
        if not self._real_available:
            raise ReviewUnavailableError(
                "论文审稿 Pipeline 依赖未安装，无法启动。请先安装：pip install langgraph"
            )

        review_id = str(uuid.uuid4())

        # 解析研究类型
        resolved_research_type = "qualitative"
        if research_type:
            resolved_research_type = RESEARCH_TYPE_MAP.get(
                research_type, RESEARCH_TYPE_MAP.get(research_type.lower(), "qualitative")
            )

        # 默认期刊格式
        if not journal_style:
            journal_style = "xwycbyj"

        # 输出格式映射
        pipeline_output_format = _OUTPUT_FORMAT_MAP.get(output_format.lower(), "word")

        # 构建配置
        config = {
            "review_id": review_id,
            "session_id": session_id,
            "user_id": user_id,
            "research_type": resolved_research_type,
            "journal_style": journal_style,
            "output_format": output_format,
            "max_rounds": max_rounds,
            "pass_threshold": PASS_THRESHOLD,
            "revision_focus": revision_focus or "全面优化",
            "reviewer_comments": reviewer_comments,
            "paper_length": len(paper_text),
        }

        # 初始化状态并持久化
        initial_state = {
            "review_id": review_id,
            "user_id": user_id,
            "session_id": session_id,
            "status": "pending",
            "config": config,
            "current_round": 0,
            "current_agent": None,
            "current_step": "初始化中",
            "score": None,
            "score_history": [],
            "logs": ["审稿任务已创建"],
            "error": None,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "result": None,
            "paper_text": paper_text,  # 原始论文文本
            "pipeline_output_format": pipeline_output_format,
        }
        await self._repo.save(review_id, initial_state, user_id=user_id)

        # 异步启动审稿
        task = asyncio.create_task(self._run_review_async(review_id, config, paper_text))
        self._tasks[review_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(review_id, None))

        return {
            "review_id": review_id,
            "status": "pending",
            "message": "审稿任务已启动，9 Agent 循环式优化即将开始",
            "config": config,
        }

    async def get_status(
        self, review_id: str, user_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """查询审稿状态

        P0 Task 3.3：若提供 user_id，校验审稿任务归属；不属于当前用户返回 None
        （Router 层映射为 404）。
        """
        r = await self._repo.get(review_id)
        if not r:
            return None
        if user_id is not None and str(r.get("user_id")) != str(user_id):
            return None

        max_rounds = r["config"].get("max_rounds", 5)
        current_round = r["current_round"]
        agent_count = len(AGENT_EXECUTION_ORDER)

        if r["status"] == "completed":
            progress = 100
        elif r["status"] == "failed":
            progress = 0
        else:
            current_agent_idx = 0
            if r.get("current_agent"):
                for i, (aid, _, _) in enumerate(AGENT_EXECUTION_ORDER):
                    if aid == r["current_agent"]:
                        current_agent_idx = i
                        break
            progress = min(
                99,
                int(((current_round * agent_count + current_agent_idx) / (max_rounds * agent_count)) * 100),
            )

        return {
            "review_id": review_id,
            "status": r["status"],
            "current_round": current_round,
            "max_rounds": max_rounds,
            "current_agent": r.get("current_agent"),
            "current_step": r.get("current_step"),
            "score": r.get("score"),
            "score_history": r.get("score_history", []),
            "progress": progress,
            "logs": r.get("logs", [])[-20:],
            "error": r.get("error"),
            "started_at": r.get("started_at"),
            "completed_at": r.get("completed_at"),
        }

    async def get_result(
        self, review_id: str, user_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """获取审稿最终结果

        P0 Task 3.3：若提供 user_id，校验审稿任务归属；不属于当前用户返回 None。
        """
        r = await self._repo.get(review_id)
        if not r:
            return None
        if user_id is not None and str(r.get("user_id")) != str(user_id):
            return None
        return {
            "review_id": review_id,
            "status": r["status"],
            "result": r.get("result"),
            "score": r.get("score"),
            "score_history": r.get("score_history", []),
            "config": r.get("config"),
            "logs": r.get("logs", []),
        }

    async def list_reviews(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """列出审稿任务（按 user_id 或 session_id 过滤）

        P0 Task 3.3：必须提供 user_id（强制鉴权后总有值）。
        """
        if user_id:
            states = await self._repo.list_by_user(user_id, limit=100)
        else:
            return []

        results = []
        for r in states:
            if session_id and r.get("config", {}).get("session_id") != session_id:
                continue
            results.append({
                "review_id": r["review_id"],
                "status": r.get("status"),
                "current_round": r.get("current_round", 0),
                "score": r.get("score"),
                "started_at": r.get("started_at"),
                "completed_at": r.get("completed_at"),
                "config": r.get("config"),
            })
        results.sort(key=lambda x: x["started_at"] or "", reverse=True)
        return results

    async def cancel_review(
        self, review_id: str, user_id: Optional[str] = None
    ) -> bool:
        """取消运行中的审稿任务

        P0 Task 3.3：若提供 user_id，校验审稿任务归属；不属于当前用户返回 False。
        """
        # 先校验归属
        r = await self._repo.get(review_id)
        if not r:
            return False
        if user_id is not None and str(r.get("user_id")) != str(user_id):
            return False

        # 设置取消事件（跨线程通知）
        cancel_event = self._cancel_events.get(review_id)
        if cancel_event:
            cancel_event.set()

        task = self._tasks.get(review_id)
        if task is None or task.done():
            return False
        task.cancel()
        await self._repo.update_status(
            review_id, "cancelled",
            completed_at=datetime.now().isoformat(),
            current_step="用户取消",
            current_agent=None,
        )
        await self._repo.append_log(review_id, "用户取消审稿任务")
        return True

    # ── 内部：异步执行 ────────────────────────────────────

    async def _run_review_async(self, review_id: str, config: dict, paper_text: str):
        """异步执行审稿任务（P0 修复: 并发控制 + 超时保护 + 取消支持）"""
        try:
            acquired = await asyncio.wait_for(
                _REVIEW_SEMAPHORE.acquire(), timeout=30.0
            )
        except asyncio.TimeoutError:
            await self._repo.update_status(review_id, "failed",
                error="审稿并发已达上限（2），请稍后重试")
            return

        cancel_event = threading.Event()
        self._cancel_events[review_id] = cancel_event

        try:
            await self._repo.update_status(
                review_id, "running", current_step="开始审稿优化",
            )
            await self._repo.append_log(review_id, "开始审稿优化")

            heartbeat_task = asyncio.create_task(
                self._review_heartbeat(review_id, cancel_event)
            )

            try:
                await asyncio.wait_for(
                    self._run_real_review(review_id, config, paper_text, cancel_event),
                    timeout=_REVIEW_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                cancel_event.set()
                await self._repo.update_status(
                    review_id, "failed",
                    error=f"审稿执行超时（{_REVIEW_TIMEOUT_SECONDS}s）",
                    completed_at=datetime.now().isoformat(),
                )
                await self._repo.append_log(review_id, "审稿执行超时")
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        except asyncio.CancelledError:
            cancel_event.set()
            await self._repo.append_log(review_id, "审稿任务被取消")
        except Exception as e:
            cancel_event.set()
            await self._repo.update_status(
                review_id, "failed",
                error=str(e),
                current_step=f"失败: {e}",
                completed_at=datetime.now().isoformat(),
            )
            await self._repo.append_log(review_id, f"❌ 审稿失败: {e}")
            logger.error(f"Review {review_id} failed: {e}", exc_info=True)
        finally:
            _REVIEW_SEMAPHORE.release()
            self._cancel_events.pop(review_id, None)

    async def _review_heartbeat(self, review_id: str, cancel_event: threading.Event):
        """心跳协程：每 15 秒更新一次时间戳"""
        while not cancel_event.is_set():
            await asyncio.sleep(15)
            try:
                state = await self._repo.get(review_id)
                if state and state.get("status") == "running":
                    state["updated_at"] = datetime.now().isoformat()
                    await self._repo.save(review_id, state, user_id=state.get("user_id"))
            except Exception:
                pass

    async def _run_real_review(self, review_id: str, config: dict, paper_text: str,
                               cancel_event: threading.Event):
        """运行真实 Pipeline（取消支持）"""
        await self._repo.append_log(review_id, "启动真实审稿 Pipeline (v1.7)")

        pipeline_output_format = _OUTPUT_FORMAT_MAP.get(
            config["output_format"].lower(), "word"
        )
        pipeline_config = _PipelineConfig(
            research_type=config["research_type"],
            journal_style=config["journal_style"],
            output_format=pipeline_output_format,
            max_rounds=config["max_rounds"],
            pass_threshold=config["pass_threshold"],
        )

        await self._repo.append_log(
            review_id,
            f"配置: 研究类型={config['research_type']} 期刊={config['journal_style']} 阈值={config['pass_threshold']}",
        )

        initial_state = {
            "paper_text": paper_text,
            "paper_content": paper_text,
            "research_type": config["research_type"],
            "journal_style": config["journal_style"],
            "revision_focus": config.get("revision_focus", "全面优化"),
            "reviewer_comments": config.get("reviewer_comments"),
            "round": 0,
            "scores": [],
            "revisions": [],
            "instructions": [config.get("revision_focus", "全面优化")],
        }

        await self._repo.update_status(
            review_id, current_round=1, current_step="运行真实 Pipeline",
        )

        # 在线程池中执行（传入 cancel_event）
        loop = asyncio.get_event_loop()
        final_state = await loop.run_in_executor(
            None,
            lambda: _pipeline_run(paper_text, pipeline_config, initial_state,
                                  cancel_event=cancel_event),
        )

        if final_state is None:
            return  # 被取消

        final_score = final_state.get("final_score") or (
            final_state.get("scores", [-1])[-1] if final_state.get("scores") else None
        )
        revised_paper = final_state.get("revised_paper") or final_state.get("final_paper", "")
        rounds_completed = final_state.get("round", config["max_rounds"])

        await self._repo.update_status(
            review_id, "completed",
            current_round=rounds_completed,
            current_agent=None,
            current_step="审稿优化完成",
            score=final_score,
            completed_at=datetime.now().isoformat(),
            result={
                "revised_paper": revised_paper,
                "final_score": final_score,
                "rounds_completed": rounds_completed,
                "score_history": final_state.get("scores", []),
                "output_format": config["output_format"],
                "revision_summary": final_state.get("revision_summary", ""),
            },
        )
        await self._repo.append_log(review_id, f"✅ 审稿完成，最终评分: {final_score}")


# ── 单例 ──────────────────────────────────────────────────
_paper_review_service: Optional[PaperReviewService] = None


def get_paper_review_service() -> PaperReviewService:
    """获取 PaperReviewService 单例"""
    global _paper_review_service
    if _paper_review_service is None:
        _paper_review_service = PaperReviewService()
    return _paper_review_service
