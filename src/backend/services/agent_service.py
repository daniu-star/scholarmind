from __future__ import annotations

import asyncio
from typing import Optional, Any, TYPE_CHECKING
import json
import structlog
import re
import uuid
import time
from pathlib import Path
from datetime import datetime

from ..services.skills_service import SkillsService
from ..services import chart_service
from ..config import settings
from ..utils.file_parser import extract_pdf, extract_docx
from ..utils.cache import cache_result
from ..utils.llm_client import llm_client
from ..core.exceptions import AgentChatFailedError, LLMTruncatedError
from .interfaces import IAgentService

# ── 从 agent 子包导入拆分后的模块（agent_service.py 拆分 → 5 模块） ──
from .agent.prompt_builder import (
    _get_agent_llm_config, CONTEXT_TEMPLATES, VALID_AGENTS,
)
from .agent.skill_router import SkillRouter
from .agent.session_manager import SessionManager

if TYPE_CHECKING:
    from ..db.repository.conversation import ConversationRepository
    from ..db.repository.chart import ChartRepository
    from ..services.cnki_service import CNKIService

logger = structlog.get_logger(__name__)

# ── Prompt/config 从 agent 子包导入（prompt_builder.py 统一管理） ──
# AGENT_PROMPTS, CONTEXT_TEMPLATES, VALID_AGENTS 等均已从 prompt_builder 导入（第 21-24 行）。
# 本文件不再重复定义，避免双源维护不一致。
# 文件模式下的路径常量使用 settings 中的配置。
_CONVERSATIONS_DIR = Path(settings.CONVERSATIONS_DIR)
_UPLOADS_DIR = Path(settings.UPLOAD_DIR)

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".r", ".bib"}
BINARY_EXTENSIONS = {".pdf", ".docx"}


def _classify_llm_error(exc: Exception) -> str:
    """将 LLM 调用异常分类为可操作的中文错误描述。

    用于 Mock 降级前缀，让用户知道具体失败原因（余额不足/认证失败/网络不可达等），
    而非泛化的 error_type（如 APIStatusError）。
    """
    # OpenAI SDK 的 APIStatusError 有 status_code 属性
    status_code = getattr(exc, "status_code", None)
    err_msg = str(exc).lower()

    # HTTP 402 余额不足（DeepSeek 特有）
    if status_code == 402 or "insufficient balance" in err_msg or "余额不足" in err_msg:
        return "DeepSeek API 余额不足（HTTP 402），请前往 platform.deepseek.com 充值"

    # HTTP 401 认证失败
    if status_code == 401 or "authentication" in err_msg or "invalid api key" in err_msg:
        return "DeepSeek API 认证失败（HTTP 401），请检查 API Key 配置"

    # HTTP 429 限流
    if status_code == 429 or "rate limit" in err_msg:
        return "DeepSeek API 请求频率超限（HTTP 429），请稍后重试"

    # 连接/超时错误（无 status_code）
    exc_type_name = type(exc).__name__
    if exc_type_name in ("APIConnectionError", "APITimeoutError") or "timeout" in err_msg or "connection" in err_msg:
        return f"DeepSeek API 网络不可达（{exc_type_name}），请检查网络连通性"

    # 兜底
    return f"DeepSeek API 调用失败（{exc_type_name}）"


class AgentService(IAgentService):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        conversation_repo: ConversationRepository | None = None,
        skills_service: SkillsService | None = None,
        cnki_service: CNKIService | None = None,
        chart_repo: ChartRepository | None = None,
    ):
        # P0 修复: 不再自建 AsyncOpenAI 客户端，统一使用 llm_client 单例
        # （走 tenacity 重试 + 超时 + deepseek_circuit_breaker 熔断器保护）
        # api_key/base_url 参数保留以维持向后兼容，由 llm_client 从 settings 读取
        self.model = model
        self.conversation_repo = conversation_repo
        self.skills_service = skills_service or SkillsService()
        self.cnki_service = cnki_service
        self.chart_repo = chart_repo

        # ── 拆分后模块实例化 ──
        self._sessions = SessionManager(conversation_repo)
        self._skills = SkillRouter(skills_service=self.skills_service, cnki_service=cnki_service, chart_repo=chart_repo)

        self.conversations = self._sessions.conversations
        self._use_db = self._sessions._use_db

        # 延迟初始化 RAG（避免阻塞 AgentService 构造）
        self.rag_service = None
        self._rag_warmed_up = False

        # 性能缓存
        self._prompt_cache: dict[str, tuple[str, str]] = {}
        self._skills_cache: dict[str, tuple[str, list[dict]]] = {}

        # 只在文件模式下加载持久化的对话
        if not self._use_db:
            self._load_all_conversations()

    # ── Conversation persistence ──────────────────────────

    def _load_all_conversations(self) -> None:
        """Load all persisted conversations from data/conversations/"""
        _CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
        for fp in _CONVERSATIONS_DIR.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                session_id = fp.stem
                self.conversations[session_id] = data.get("messages", [])
            except Exception as e:
                logger.warning(f"Failed to load conversation {fp.name}: {e}")

    def _save_conversation(self, session_id: str) -> None:
        """Persist a single conversation to data/conversations/{session_id}.json"""
        _CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = _CONVERSATIONS_DIR / f"{session_id}.json"
        try:
            payload = {
                "session_id": session_id,
                "updated_at": datetime.now().isoformat(),
                "messages": self.conversations.get(session_id, []),
            }
            filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save conversation {session_id}: {e}")

    # ── Context preparation (shared by chat & stream_chat) ──

    async def _prepare_context(
        self,
        user_id: int,
        session_id: str,
        message: str,
        agent_id: Optional[str] = None,
        uploads: Optional[list] = None,
        context: Optional[dict] = None,
    ) -> tuple[list, str, list]:
        """Task 7: 抽取 chat() / stream_chat() 公共上下文准备逻辑。

        封装以下职责（消除两处重复代码块）：
        - 加载对话历史（DB 模式走 conversation_repo.get_by_session(session_id, user_id)
          实现用户隔离；文件模式走内存字典）
        - 构建 system prompt（含技能注入、RAG 上下文；由 _build_system_prompt 完成）
        - 加载上传文件上下文（_load_upload_context，session_id 维度；uploads 参数预留）
        - 组装 LLM 调用所需的 messages 列表（system + history + user_content）

        Args:
            user_id: 用户 ID（DB 隔离用）
            session_id: 会话 ID
            message: 用户消息原文
            agent_id: Agent 标识（用于 system prompt 构建）
            uploads: 预留参数（当前未使用，上传上下文由 session_id 自动加载）
            context: 模板变量字典（若 None 则初始化为空 dict）

        Returns:
            (messages, system_prompt, history) — history 引用保留以便调用方
            后续 append 用户/助手消息（chat 直写、stream_chat 走 _post_process_async）。
        """
        # Get or create conversation history (with user_id isolation)
        if self._use_db:
            db_history = await self.conversation_repo.get_by_session(session_id, user_id)
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in db_history
            ]
        else:
            if session_id not in self.conversations:
                self.conversations[session_id] = []
            history = self.conversations[session_id]

        # Build system prompt (with skills injection)
        if context is None:
            context = {}
        context["last_message"] = message
        system_prompt = await self._build_system_prompt(agent_id, context)

        # Load file upload context (P0: path_safety applied)
        upload_context = self._load_upload_context(session_id)
        user_content = message
        if upload_context:
            user_content = f"{message}\n\n---\n📎 用户上传的文件内容摘要：\n{upload_context}"

        # Build messages list for API call
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        return messages, system_prompt, history

    # ── Main chat method ──────────────────────────────────

    async def chat(
        self,
        message: str,
        agent_id: str,
        session_id: str,
        context: Optional[dict] = None,
        user_id: int = 0,
        model: Optional[str] = None,
    ) -> dict:
        """Send message to agent and get response

        P0: user_id 透传至 Repository 实现用户数据隔离；
            model 由 Router 层 model_policy 解析后传入，覆盖默认模型。

        Returns:
            dict with keys: reply, options, skills_used, chart_info, cnki_results, skill_hint
        """
        if agent_id not in VALID_AGENTS:
            return {
                "reply": f"未知的Agent类型：{agent_id}。可用的Agent有：{', '.join(VALID_AGENTS)}",
                "options": [],
                "skills_used": [],
                "chart_info": None,
                "cnki_results": None,
                "skill_hint": None,
            }

        if not settings.DEEPSEEK_API_KEY:
            raise AgentChatFailedError("DeepSeek API key not configured")

        llm_model = model or self.model

        # Task 7: 抽取公共上下文准备逻辑（历史加载、Prompt 构建、上传上下文加载、messages 组装）
        messages, system_prompt, history = await self._prepare_context(
            user_id=user_id, session_id=session_id, message=message,
            agent_id=agent_id, context=context,
        )

        # P1: 使用统一 LLM 客户端（tenacity 重试 + 超时 + 熔断器保护）
        # 使用 per-agent 配置的 temperature/max_tokens
        _llm = llm_client
        agent_cfg = _get_agent_llm_config(agent_id)
        llm_start = time.monotonic()
        try:
            response = await _llm.chat_messages(
                messages=messages,
                temperature=agent_cfg["temperature"],
                max_tokens=agent_cfg["max_tokens"],
                model=llm_model,
            )
            reply = response.content
            latency_ms = int((time.monotonic() - llm_start) * 1000)
            # P1: 记录 LLM 调用成功日志
            await self._log_agent_execution(
                user_id=user_id, agent_id=agent_id, session_id=session_id,
                model=llm_model, status="success", latency_ms=latency_ms,
                prompt_tokens=getattr(response.raw, "usage", None) and getattr(response.raw.usage, "prompt_tokens", None) if response.raw else None,
                completion_tokens=getattr(response.raw, "usage", None) and getattr(response.raw.usage, "completion_tokens", None) if response.raw else None,
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - llm_start) * 1000)
            error_type = type(e).__name__
            error_reason = _classify_llm_error(e)
            logger.error(f"DeepSeek API call failed: {e} reason={error_reason}")
            await self._log_agent_execution(
                user_id=user_id, agent_id=agent_id, session_id=session_id,
                model=llm_model, status="failed", latency_ms=latency_ms,
                error_code="LLM_API_FAILED", error_message=f"{error_reason}: {e}",
            )
            # P0 修复: LLM 调用失败时降级到 Mock 模式，而非抛出 AgentChatFailedError(500)
            # Task 9: 精细化披露失败原因（余额不足/认证失败/网络不可达等）
            mock_content = self._generate_mock_reply(
                message=message, agent_id=agent_id, session_id=session_id, context=context,
            )
            reply = f"⚠️ {error_reason}，已降级为离线引导模式\n\n{mock_content}"
            logger.info(
                f"LLM degraded to mock mode session={session_id} agent={agent_id} "
                f"error_type={error_type} reason={error_reason} reply_len={len(reply)}"
            )

        # Update conversation history
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})

        if self._use_db:
            await self.conversation_repo.add_message(session_id, agent_id, "user", message, user_id)
            await self.conversation_repo.add_message(session_id, agent_id, "assistant", reply, user_id)
        else:
            # Task 24.5: 从 config 读取 MAX_HISTORY_MESSAGES
            max_history_messages = settings.MAX_HISTORY_MESSAGES
            if len(history) > max_history_messages:
                self.conversations[session_id] = history[-max_history_messages:]
            self._save_conversation(session_id)

        # Parse options from reply
        options = self._skills.parse_options(reply)

        # Detect skills that could be used based on reply content
        skills_used = self._skills.detect_skills(reply, message)

        # Execute chart generation skill if detected
        chart_info = None
        if "chart_generation" in skills_used:
            chart_info = await self._execute_chart_skill(message, reply, session_id)

        # Execute CNKI search skill if detected
        cnki_results = None
        if "cnki_search" in skills_used:
            cnki_results = await self._execute_cnki_skill(message, session_id)

        # Detect skill hint for unmatched needs
        skill_hint = self._detect_skill_hint(reply, message, skills_used)

        return {
            "reply": reply,
            "options": options,
            "skills_used": skills_used,
            "chart_info": chart_info,
            "cnki_results": cnki_results,
            "skill_hint": skill_hint,
        }

    # ── Stream chat method (WebSocket) ───────────────────

    async def stream_chat(
        self,
        message: str,
        agent_id: str,
        session_id: str,
        context: Optional[dict] = None,
        user_id: int = 0,
        model: Optional[str] = None,
    ):
        """流式对话：逐token生成回复，通过 async generator 返回

        P0: user_id 透传至 Repository 实现用户数据隔离；
            model 由 Router 层 model_policy 解析后传入，覆盖默认模型。

        Yields:
            dict with keys: type, content, index, skills_used, options, chart_info, cnki_results
        """
        if agent_id not in VALID_AGENTS:
            yield {
                "type": "error",
                "message": f"未知的Agent类型：{agent_id}。可用的Agent有：{', '.join(VALID_AGENTS)}",
            }
            return

        if not settings.DEEPSEEK_API_KEY:
            yield {
                "type": "error",
                "message": "DeepSeek API key not configured",
            }
            return

        llm_model = model or self.model

        # Task 7: 抽取公共上下文准备逻辑（历史加载、Prompt 构建、上传上下文加载、messages 组装）
        messages, system_prompt, history = await self._prepare_context(
            user_id=user_id, session_id=session_id, message=message,
            agent_id=agent_id, context=context,
        )

        # P1: 使用统一 LLM 客户端流式调用（熔断器保护，无重试因流已在进行中）
        # P0 修复: llm_client 顶层已导入为 llm_client；此处保留局部别名以最小化改动
        _llm = llm_client
        full_reply = ""
        degraded = False
        llm_start = time.monotonic()
        try:
            # 使用 per-agent 配置的 temperature/max_tokens
            agent_cfg = _get_agent_llm_config(agent_id)
            async for token in _llm.chat_messages(
                messages=messages,
                temperature=agent_cfg["temperature"],
                max_tokens=agent_cfg["max_tokens"],
                model=llm_model,
                stream=True,
            ):
                # P0 修复: 防御性类型检查，避免 yield dict 时 TypeError
                if isinstance(token, str):
                    full_reply += token
                    yield {"type": "token", "content": token}
        except LLMTruncatedError:
            # P0 修复: 流式因 max_tokens 截断时优雅结束（不抛 TypeError，已收到的部分回复有效）
            logger.info(f"stream_truncated session={session_id} agent={agent_id} reply_len={len(full_reply)}")
        except Exception as e:
            latency_ms = int((time.monotonic() - llm_start) * 1000)
            error_type = type(e).__name__
            error_reason = _classify_llm_error(e)
            logger.error(f"DeepSeek stream API failed: {e} reason={error_reason}")
            await self._log_agent_execution(
                user_id=user_id, agent_id=agent_id, session_id=session_id,
                model=llm_model, status="failed", latency_ms=latency_ms,
                error_code="LLM_STREAM_FAILED", error_message=f"{error_reason}: {e}",
            )
            # P0 修复: 流式 LLM 调用失败时降级到 Mock 模式，而非 yield 裸错误后 return
            # Task 9: 精细化披露失败原因（余额不足/认证失败/网络不可达等）
            mock_content = self._generate_mock_reply(
                message=message, agent_id=agent_id, session_id=session_id, context=context,
            )
            full_reply = f"⚠️ {error_reason}，已降级为离线引导模式\n\n{mock_content}"
            # 将降级回复作为 token 事件流式输出（单次 yield，保证前端按 token 渲染）
            yield {"type": "token", "content": full_reply}
            degraded = True
            logger.info(
                f"LLM stream degraded to mock mode session={session_id} agent={agent_id} "
                f"error_type={error_type} reason={error_reason} reply_len={len(full_reply)}"
            )

        # P1: 记录流式 LLM 调用成功日志（降级模式已在 except 内记录 failed，跳过 success 日志）
        if not degraded:
            latency_ms = int((time.monotonic() - llm_start) * 1000)
            await self._log_agent_execution(
                user_id=user_id, agent_id=agent_id, session_id=session_id,
                model=llm_model, status="success", latency_ms=latency_ms,
            )

        # ═══ 同步保存对话历史（DB 写入 < 10ms），然后立即发送 done ═══
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": full_reply})
        if self._use_db:
            await self.conversation_repo.add_message(
                session_id, agent_id, "user", message, user_id)
            await self.conversation_repo.add_message(
                session_id, agent_id, "assistant", full_reply, user_id)
        else:
            max_history_messages = 40
            if len(history) > max_history_messages:
                self.conversations[session_id] = history[-max_history_messages:]
            self._save_conversation(session_id)

        # 快速检测技能（纯 CPU，不阻塞）
        skills_used = self._skills.detect_skills(full_reply, message)

        yield {
            "type": "done",
            "skills_used": skills_used,
            "options": self._skills.parse_options(full_reply),
            "chart_info": None,
            "cnki_results": None,
            "skill_hint": self._detect_skill_hint(full_reply, message, skills_used),
        }

        # ── 仅延迟慢操作（图表/CNKI 需要额外 LLM 调用）到后台 ──
        if "chart_generation" in skills_used or "cnki_search" in skills_used:
            asyncio.create_task(self._deferred_skills(
                message=message, full_reply=full_reply, session_id=session_id,
                skills_used=skills_used,
            ))

    async def _deferred_skills(
        self, *, message: str, full_reply: str, session_id: str,
        skills_used: list[str],
    ) -> None:
        """后台执行慢技能（图表生成/CNKI 检索需额外 LLM 调用），不影响用户交互"""
        try:
            if "chart_generation" in skills_used:
                await self._execute_chart_skill(message, full_reply, session_id)
            if "cnki_search" in skills_used:
                await self._execute_cnki_skill(message, session_id)
        except Exception as e:
            logger.warning(f"deferred_skills_failed session={session_id} error={e}")

    # ── 旧 _post_process_async 已移除，替换为上述同步+延迟方案 ──

    # ── Post-processing (fire-and-forget, does not block user response) ──

    async def _post_process_async(
        self, *, message: str, full_reply: str, agent_id: str,
        session_id: str, user_id: int, history: list[dict],
    ) -> None:
        """后台异步后处理：保存历史、检测技能、执行图表/CNKI 技能。

        与 stream_chat 的 token 流并行拆分：token 流结束后立即发送 done 事件，
        DB 写入与技能执行在后台异步完成，不阻塞用户交互。
        """
        try:
            # 1. 保存对话历史到 DB（容错：失败不影响其他后处理）
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": full_reply})
            if self._use_db:
                try:
                    await self.conversation_repo.add_message(session_id, agent_id, "user", message, user_id)
                    await self.conversation_repo.add_message(session_id, agent_id, "assistant", full_reply, user_id)
                except Exception as e:
                    logger.warning(f"Failed to save conversation to DB: {e}")
            else:
                # Task 24.5: 从 config 读取 MAX_HISTORY_MESSAGES
                max_history_messages = settings.MAX_HISTORY_MESSAGES
                if len(history) > max_history_messages:
                    self.conversations[session_id] = history[-max_history_messages:]
                self._save_conversation(session_id)

            # 2. 解析选项和检测技能（纯 CPU，不阻塞）
            self._skills.parse_options(full_reply)
            skills_used = self._skills.detect_skills(full_reply, message)
            self._detect_skill_hint(full_reply, message, skills_used)

            # 3. 执行图表/CNKI 技能（可能较慢，但不影响用户交互）
            chart_info = None
            cnki_results = None
            if "chart_generation" in skills_used:
                chart_info = await self._execute_chart_skill(message, full_reply, session_id)
            if "cnki_search" in skills_used:
                cnki_results = await self._execute_cnki_skill(message, session_id)

            logger.info(
                f"post_process_complete session={session_id} agent={agent_id} "
                f"reply_len={len(full_reply)} skills={skills_used} "
                f"has_chart={chart_info is not None} has_cnki={cnki_results is not None}"
            )
        except Exception as e:
            # P1 Task 8.3：补全 user_id/session_id 上下文 + exc_info 输出堆栈
            logger.error(
                f"post_process_failed user_id={user_id} session_id={session_id} exc={e}",
                exc_info=True,
            )

    # ── System prompt building with skills injection ──────

    async def _build_system_prompt(
        self, agent_id: str, context: Optional[dict] = None
    ) -> str:
        """Build system prompt for the agent using Jinja2 template engine.

        性能优化：
        - base prompt 按 agent_id 缓存（仅首次或模板文件变化时重新加载）
        - RAG 上下文检索延迟到首次需要时，且使用轻量查询

        Task 27 修复：改为 async 以正确 await 异步的 _load_skills_for_agent
        （原 sync 版本调用 async SkillsService.list_all() 返回 coroutine 导致
        'coroutine' object is not iterable）
        """
        from .agent.prompt_builder import get_prompt_builder

        builder = get_prompt_builder(auto_reload=settings.DEBUG)

        # ── 构建模板变量 ──
        context_info = ""
        if context:
            parts = []
            for key, template in CONTEXT_TEMPLATES.items():
                value = context.get(key)
                if value:
                    parts.append(template.format(value=value))
            context_info = "\n".join(parts)

        # 技能规则（带缓存，减少 DB 查询）
        # Task 27: 调用合并后的 _load_skills_for_agent（缓存由 @cache_result 装饰器实现）
        skills_rules_text = ""
        skills_list = await self._load_skills_for_agent(agent_id)
        if skills_list:
            skills_parts = []
            for skill in skills_list:
                skill_text = f"【技能：{skill['display_name']}】"
                if skill.get("rules"):
                    skill_text += f"\n{skill['rules']}"
                skills_parts.append(skill_text)
            skills_rules_text = "\n".join(skills_parts)

        # RAG 上下文延迟初始化（fire-and-forget，不阻塞首 token）
        rag_text = ""
        if context and context.get("last_message"):
            try:
                if not self._rag_warmed_up:
                    from .rag_service import get_rag_service
                    self.rag_service = get_rag_service()
                    self._rag_warmed_up = True
                if self.rag_service:
                    rag_text = self.rag_service.build_context(
                        query=context["last_message"],
                        agent_id=agent_id,
                        top_k=min(3, settings.RAG_TOP_K),
                    )
            except Exception as e:
                logger.warning(f"RAG context injection failed: {e}")

        # ── 模板渲染 ──
        return builder.build_with_academic_features(
            agent_id=agent_id,
            context_info=context_info,
            guidance_info="",
            user_core_context="",
            style_features="",
            skills_rules=skills_rules_text,
            rag_context=rag_text,
            cot_instruction="",
        )

    @cache_result(ttl=300)
    async def _load_skills_for_agent(self, agent_id: str) -> list[dict]:
        """Load enabled skills associated with the given agent_id

        Task 27: 合并原 `_load_skills_for_agent_cached` 与 `_load_skills_for_agent`，
        缓存由 `@cache_result` 装饰器统一实现（共享 default_cache LRU+TTL）。

        注意：原 sync 版本误将 async 的 SkillsService.list_all() 当成同步调用，
        返回 coroutine 导致 'coroutine' object is not iterable。改为 async 后正确 await。
        """
        all_skills = await self.skills_service.list_all()
        matched = []
        for skill in all_skills:
            if not skill.get("enabled", False):
                continue
            agents = skill.get("agents", [])
            if agent_id in agents:
                matched.append(skill)
        return matched

    # ── File upload context ───────────────────────────────

    def _load_upload_context(self, session_id: str) -> str:
        """Read uploaded files for the session and return a summary string

        P0: 使用 safe_session_path 防御路径穿越攻击。
        """
        from ..core.path_safety import validate_session_id, safe_session_path
        try:
            safe_sid = validate_session_id(session_id)
            upload_dir = safe_session_path(Path(settings.UPLOAD_DIR), safe_sid)
        except Exception:
            logger.warning(f"Invalid session_id for upload context: {session_id[:32]!r}")
            return ""
        if not upload_dir.exists():
            return ""

        summaries = []
        for fp in sorted(upload_dir.iterdir()):
            if fp.is_file():
                try:
                    content = self._extract_file_content(fp)
                    if content:
                        # Truncate to avoid overwhelming the context
                        max_chars = 2000
                        if len(content) > max_chars:
                            content = content[:max_chars] + "\n...（内容已截断）"
                        summaries.append(f"文件：{fp.name}\n{content}")
                except Exception as e:
                    logger.warning(f"Failed to extract content from {fp.name}: {e}")
                    summaries.append(f"文件：{fp.name}（无法读取内容：{e}）")

        if not summaries:
            return ""

        return "\n\n".join(summaries)

    def _extract_file_content(self, fp: Path) -> str:
        """Extract text content from a supported file"""
        ext = fp.suffix.lower()

        if ext in TEXT_EXTENSIONS:
            return fp.read_text(encoding="utf-8", errors="replace")

        if ext == ".pdf":
            # Task 27: 改用 utils/file_parser.py 公共实现
            return extract_pdf(fp)

        if ext == ".docx":
            # Task 27: 改用 utils/file_parser.py 公共实现
            return extract_docx(fp)

        return ""

    # ── Chart generation skill ────────────────────────────

    async def _execute_chart_skill(
        self, message: str, reply: str, session_id: str
    ) -> Optional[dict]:
        """When chart_generation skill is detected, use DeepSeek to recommend chart type
        and generate the chart via chart_service."""
        try:
            # Ask DeepSeek to analyze the conversation and recommend a chart type
            chart_types_desc = "\n".join(
                f"- {k}: {chart_service.CHART_NAMES.get(k, k)} — {chart_service.CHART_DESCRIPTIONS.get(k, '')}"
                for k in chart_service.CHART_FUNCTIONS
            )

            analysis_prompt = f"""根据以下用户消息和AI回复，分析用户需要什么类型的学术图表，并推荐最合适的图表类型。

用户消息：{message}
AI回复：{reply}

可选图表类型：
{chart_types_desc}

请仅返回一个JSON对象，格式如下：
{{"chart_type": "图表类型key", "title": "图表标题", "x_label": "X轴标签", "y_label": "Y轴标签", "data_description": "数据格式说明"}}
"""

            analysis_response = await llm_client.chat(
                system="",
                user=analysis_prompt,
                temperature=0.3,
                max_tokens=512,
                model=self.model,
            )
            analysis_text = analysis_response.content.strip()

            # Parse the JSON from the analysis
            # Try to extract JSON from the response (may be wrapped in markdown code block)
            json_match = re.search(r'\{[\s\S]*\}', analysis_text)
            if not json_match:
                logger.warning("Failed to parse chart analysis response as JSON")
                return None

            json_str = json_match.group()
            try:
                chart_config = json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode chart analysis JSON: {json_str[:200]}")
                return None
            chart_type = chart_config.get("chart_type", "")
            title = chart_config.get("title", "学术研究图表")
            x_label = chart_config.get("x_label", "")
            y_label = chart_config.get("y_label", "")

            if chart_type not in chart_service.CHART_FUNCTIONS:
                logger.warning(f"Invalid chart type recommended: {chart_type}")
                return None

            # Generate sample/demonstration data for the chart
            # In a real scenario, the user would provide data; here we generate placeholder data
            sample_data = self._generate_sample_data(chart_type)

            # Generate chart
            chart_bytes = chart_service.generate_chart(
                chart_type=chart_type,
                data=sample_data,
                title=title,
                x_label=x_label,
                y_label=y_label,
            )

            # Save chart to file
            chart_id = str(uuid.uuid4())
            charts_dir = Path(settings.CHARTS_DIR)
            charts_dir.mkdir(parents=True, exist_ok=True)
            chart_filename = f"{chart_id}.png"
            chart_filepath = charts_dir / chart_filename
            chart_filepath.write_bytes(chart_bytes)

            chart_url = f"/api/v1/charts/{chart_filename}"

            # 持久化图表记录到数据库
            if self.chart_repo is not None:
                try:
                    await self.chart_repo.save_record(
                        chart_id=chart_id,
                        chart_type=chart_type,
                        title=title,
                        filepath=str(chart_filepath),
                        session_id=session_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist chart record to DB: {e}")

            return {
                "chart_id": chart_id,
                "chart_url": chart_url,
                "chart_type": chart_type,
                "chart_name": chart_service.CHART_NAMES.get(chart_type, chart_type),
                "title": title,
            }

        except Exception as e:
            logger.error(f"Chart generation failed: {e}")
            return None

    def _generate_sample_data(self, chart_type: str) -> Any:
        """Generate sample demonstration data for a given chart type"""
        import numpy as np

        if chart_type in ("ribbon",):
            x = list(range(10))
            return [(x, [i * 2 + j for j in range(3)]) for i in range(3)]

        if chart_type in ("violin", "swarm"):
            return {
                "组A": list(np.random.normal(50, 10, 30)),
                "组B": list(np.random.normal(60, 12, 30)),
                "组C": list(np.random.normal(45, 8, 30)),
            }

        if chart_type in ("alluvial", "chord"):
            return [
                ("类别A", "类别X", 30),
                ("类别A", "类别Y", 20),
                ("类别B", "类别X", 15),
                ("类别B", "类别Z", 25),
                ("类别C", "类别Y", 10),
            ]

        if chart_type in ("bubble_kde",):
            return [(x, x * 2 + np.random.randn() * 5, abs(np.random.randn()) * 30 + 10)
                    for x in np.linspace(0, 50, 30)]

        if chart_type in ("gradient_area",):
            x = list(np.linspace(0, 10, 50))
            y = list(np.sin(x) * 10 + 20 + np.random.randn(50) * 2)
            return list(zip(x, y))

        if chart_type in ("surface3d", "contour"):
            return np.random.rand(10, 10).tolist()

        if chart_type in ("parallel",):
            return {
                "class": ["A"] * 5 + ["B"] * 5,
                "特征1": list(np.random.rand(10) * 100),
                "特征2": list(np.random.rand(10) * 100),
                "特征3": list(np.random.rand(10) * 100),
            }

        if chart_type in ("scatter_density",):
            return [(np.random.randn(), np.random.randn()) for _ in range(200)]

        if chart_type in ("heatmap_dendro",):
            return np.random.rand(8, 8).tolist()

        # Default fallback
        return [(i, i * 2) for i in range(10)]

    # ── CNKI search skill ─────────────────────────────────

    async def _execute_cnki_skill(
        self, message: str, session_id: str
    ) -> Optional[list]:
        """When cnki_search skill is detected, extract keywords and search CNKI"""
        try:
            # Extract search keywords from the message using DeepSeek
            keyword_prompt = f"""从以下用户消息中提取学术文献检索关键词，返回一个JSON对象。

用户消息：{message}

返回格式：{{"keywords": "检索关键词", "year_filter": ""}}

year_filter格式示例："2020-2024" 或 "2024" 或 ""（不限年份）
仅返回JSON，不要其他内容。"""

            keyword_response = await llm_client.chat(
                system="",
                user=keyword_prompt,
                temperature=0.2,
                max_tokens=256,
                model=self.model,
            )
            keyword_text = keyword_response.content.strip()

            # Parse JSON
            json_match = re.search(r'\{[\s\S]*\}', keyword_text)
            if not json_match:
                logger.warning("Failed to parse keyword extraction response")
                return None

            json_str = json_match.group()
            try:
                keyword_config = json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode keyword JSON: {json_str[:200]}")
                return None
            keywords = keyword_config.get("keywords", "")
            year_filter = keyword_config.get("year_filter", "")

            if not keywords:
                return None

            # Execute CNKI search using injected service (with cache + circuit breaker)
            if self.cnki_service is not None:
                results = await self.cnki_service.search(query=keywords, year_filter=year_filter, count=10)
            else:
                # Fallback: create standalone instance (no cache/circuit breaker)
                from ..services.cnki_service import CNKIService
                cnki = CNKIService()
                results = await cnki.search(query=keywords, year_filter=year_filter, count=10)
                await cnki.close()

            # Convert results to dict list
            return [r.to_dict() for r in results]

        except Exception as e:
            logger.error(f"CNKI search failed: {e}")
            return None

    # ── Skill hint detection ──────────────────────────────

    def _detect_skill_hint(
        self, reply: str, user_message: str, skills_used: list[str]
    ) -> Optional[str]:
        """对未匹配技能的需求提供提示建议。

        ⚠ 此方法与 SkillRouter.detect_skill_hint 签名不同（多接受 skills_used 参数），
        暂时保留。后续应统一到 SkillRouter。
        """
        unmatched_keywords = {
            "翻译": "学术翻译",
            "格式": "论文格式化",
            "投稿": "投稿指导",
            "答辩": "答辩准备",
            "实验设计": "实验设计",
            "问卷": "问卷设计",
            "量表": "量表开发",
            "编码": "质性编码",
            "扎根理论": "扎根理论分析",
            "元分析": "元分析/Meta分析",
            "案例研究": "案例研究方法",
            "田野调查": "田野调查方法",
        }

        combined = reply + user_message
        for keyword, skill_name in unmatched_keywords.items():
            if keyword in combined:
                if not any(s in skills_used for s in ["cnki_search", "chart_generation", "polish", "literature_review", "architecture"]):
                    return f"检测到您可能需要「{skill_name}」相关功能，当前暂无对应技能。您可以在技能管理中创建自定义技能来满足此需求。"

        return None

    # ── Mock degradation reply (LLM unavailable fallback) ──

    def _generate_mock_reply(
        self,
        *,
        message: str,
        agent_id: str,
        session_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> str:
        """LLM 不可用时生成离线引导回复（Mock 降级模式）。

        项目要求：LLM 调用失败时必须降级到 Mock 模式，避免向用户抛出裸错误。
        本方法根据 agent_id 提供针对性的引导话术，确保用户在 AI 服务异常时
        仍能获得可用的交互体验。

        Args:
            message: 用户原始消息（用于在回复中确认已收到）
            agent_id: Agent 标识（决定引导话术内容）
            session_id: 会话 ID（预留，当前未使用）
            context: 模板变量字典（预留，当前未使用）

        Returns:
            离线引导回复正文（不含降级提示前缀，前缀由调用方拼接）
        """
        guidance: dict[str, str] = {
            "researcher": (
                "我目前无法连接到 AI 服务，但可以为您提供研究选题的离线引导：\n"
                "1. 请描述您的研究领域和感兴趣的方向\n"
                "2. 说明您目前处于选题的哪个阶段（初探/聚焦/细化）\n"
                "3. 提供您已关注的关键文献或研究空白\n\n"
                "您可以将这些信息留在此处，待服务恢复后我会继续协助您建构研究问题。"
            ),
            "reviewer": (
                "我目前无法连接到 AI 服务，但可以为您提供研究方案审查的离线引导：\n"
                "1. 请简要描述您的研究问题与假设\n"
                "2. 说明您采用的研究方法与数据来源\n"
                "3. 列出您目前的主要顾虑或待审查环节\n\n"
                "待服务恢复后，我将从理论依据、方法严谨性、可行性、创新性四个维度为您审查。"
            ),
            "architect": (
                "我目前无法连接到 AI 服务，但可以为您提供论文架构优化的离线引导：\n"
                "1. 请粘贴您当前的论文大纲或章节标题\n"
                "2. 说明各章节的核心论点\n"
                "3. 指出您感觉逻辑不连贯的位置\n\n"
                "待服务恢复后，我将评估章节完整性、论证链路与逻辑连贯性。"
            ),
            "synthesizer": (
                "我目前无法连接到 AI 服务，但可以为您提供文献综述的离线引导：\n"
                "1. 请列出您已收集的关键文献（标题/作者/年份）\n"
                "2. 说明您的综述主题与逻辑框架\n"
                "3. 指出希望突出的对比维度或研究脉络\n\n"
                "待服务恢复后，我将协助您完成综述撰写与文献筛选。"
            ),
            "polisher": (
                "我目前无法连接到 AI 服务，但可以为您提供学术润色的离线引导：\n"
                "1. 请粘贴需要润色的段落\n"
                "2. 说明目标期刊/学位层次与语言（中/英）\n"
                "3. 指出您关心的重点（学术规范/AIGC降重/表达流畅）\n\n"
                "待服务恢复后，我将为您提供规范的学术语言润色建议。"
            ),
            "external_reviewer": (
                "我目前无法连接到 AI 服务，但可以为您提供外审意见的离线引导：\n"
                "1. 请粘贴论文摘要或关键章节\n"
                "2. 说明评审场景（期刊外审/学位论文/基金评审）\n"
                "3. 指出希望重点关注的维度\n\n"
                "待服务恢复后，我将为您生成专业、建设性的外审意见。"
            ),
            "computational": (
                "我目前无法连接到 AI 服务，但可以为您提供计算传播研究的离线引导：\n"
                "1. 请描述您的研究问题与可用数据规模\n"
                "2. 说明您考虑采用的分析方法（网络分析/文本挖掘/机器学习等）\n"
                "3. 指出您在方法选型或实现上的困惑\n\n"
                "待服务恢复后，我将协助您完成方法设计与可复现流程。"
            ),
            "custom": (
                "我目前无法连接到 AI 服务，但可以为您提供离线引导：\n"
                "1. 请详细描述您的需求与背景\n"
                "2. 提供您已尝试的方案或思路\n"
                "3. 说明期望的输出形式\n\n"
                "待服务恢复后，我将根据您的具体场景继续协助。"
            ),
        }

        base = guidance.get(agent_id, guidance["custom"])

        # 若用户消息非空，附上确认已收到的提示（截断超长消息）
        user_hint = ""
        if message and message.strip():
            snippet = message.strip()[:80]
            ellipsis = "…" if len(message.strip()) > 80 else ""
            user_hint = f"\n\n—— 已收到您的消息：「{snippet}{ellipsis}」，将在服务恢复后处理。"

        return f"{base}{user_hint}"

    # ── _parse_options / _detect_skills 已委托给 SkillRouter ──
    # 调用 self._skills.parse_options() / self._skills.detect_skills()

    # ── Conversation management (delegating to SessionManager) ──

    async def clear_conversation(self, session_id: str, user_id: int = 0) -> bool:
        return await self._sessions.clear_conversation(session_id, user_id)

    async def get_conversation_history(self, session_id: str, user_id: int = 0) -> list[dict]:
        return await self._sessions.get_conversation_history(session_id, user_id)

    async def list_sessions_with_meta(self, user_id: int = 0, agent_id: str | None = None, limit: int = 50) -> list[dict]:
        return await self._sessions.list_sessions_with_meta(user_id, agent_id, limit)

    async def rename_session(self, session_id: str, title: str, user_id: int = 0) -> bool:
        return await self._sessions.rename_session(session_id, title, user_id)

    async def delete_session(self, session_id: str, user_id: int = 0) -> int:
        return await self._sessions.delete_session(session_id, user_id)

    async def _log_agent_execution(
        self, *, user_id: int, agent_id: str, session_id: str,
        model: str, status: str, latency_ms: int = 0,
        prompt_tokens: int | None = None, completion_tokens: int | None = None,
        error_code: str | None = None, error_message: str | None = None,
    ) -> None:
        """P1: 写入 AgentExecutionLog 用于成本分析、延迟监控与故障排查。

        Task 26: 通过 ConversationRepository.log_agent_execution 封装，
        不再直接访问 self.conversation_repo.db.add(...)。
        """
        if not self._use_db or user_id <= 0:
            return
        if self.conversation_repo is None:
            return
        try:
            # 失败语义：error_message 非空（或 status != success）
            error = error_message if status != "success" else None
            token_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
            await self.conversation_repo.log_agent_execution(
                user_id=user_id,
                session_id=session_id,
                agent_id=agent_id,
                model=model,
                token_usage=token_usage,
                duration_ms=latency_ms,
                error=error,
            )
        except Exception as e:
            logger.warning(f"Failed to write agent execution log: {e}")

    def list_agents(self) -> list[dict]:
        """List all available agents with their descriptions"""
        agent_info = {
            "researcher": {
                "id": "researcher",
                "name": "研究员",
                "description": "学术选题与问题建构专家，帮助明确研究方向、建构问题边界、发现研究空白",
                "icon": "🔬",
            },
            "reviewer": {
                "id": "reviewer",
                "name": "审查员",
                "description": "研究思路审查与优化专家，从4个维度评估研究方案并给出改进建议",
                "icon": "📋",
            },
            "architect": {
                "id": "architect",
                "name": "架构师",
                "description": "论文架构审查与优化专家，评估逻辑连贯性、章节完整性、论证链路",
                "icon": "🏗️",
            },
            "synthesizer": {
                "id": "synthesizer",
                "name": "综述员",
                "description": "文献综述撰写专家，辅助文献检索、筛选与综述撰写",
                "icon": "📚",
            },
            "polisher": {
                "id": "polisher",
                "name": "润色员",
                "description": "学术语言润色与AIGC降重专家，确保学术写作规范",
                "icon": "✨",
            },
        }
        return list(agent_info.values())
