"""
ScholarMind 对话仓储
管理对话历史的 CRUD 操作

P0 Task 3.4：所有方法签名增加 `user_id: int` 参数，SQL WHERE 同时包含
`session_id` 与 `user_id`，阻断跨用户越权（IDOR）。不属于当前用户的
对象返回 None / 空列表 / 0（Router 层映射为 404）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, delete, desc, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseRepository
from ...models.orm import Conversation, AgentExecutionLog


class ConversationRepository(BaseRepository[Conversation]):
    """对话历史数据仓储"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Conversation)

    async def get_by_session(
        self, session_id: str, user_id: int, limit: int = 40
    ) -> Sequence[Conversation]:
        """按 session_id + user_id 获取对话历史（按时间正序，最近 N 条）

        P0 Task 3.4：WHERE 同时按 session_id 与 user_id 过滤；
        若 session 不属于当前用户，返回空列表（Router 层映射为 404）。
        """
        subq = (
            select(Conversation)
            .where(
                Conversation.session_id == session_id,
                Conversation.user_id == user_id,
            )
            .order_by(desc(Conversation.created_at))
            .limit(limit)
            .subquery()
        )
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id.in_(
                select(subq.c.id)
            ))
            .order_by(Conversation.created_at.asc())
        )
        return result.scalars().all()

    async def add_message(
        self,
        session_id: str,
        agent_id: str,
        role: str,
        content: str,
        user_id: int,
        title: Optional[str] = None,
    ) -> Conversation:
        """添加一条对话消息。若提供 title 且会话首条消息,则写入 title 字段。

        P0 Task 3.4：消息绑定到 user_id，确保会话归属当前用户。
        """
        # 若是新会话(尚无消息)且提供了 title,则写入 title
        if title:
            existing = await self.get_session_count(session_id, user_id)
            if existing == 0:
                msg = Conversation(
                    session_id=session_id,
                    agent_id=agent_id,
                    role=role,
                    content=content,
                    user_id=user_id,
                    title=title[:128] if title else None,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                return await self.create(msg)
        msg = Conversation(
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            content=content,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        return await self.create(msg)

    async def clear_session(self, session_id: str, user_id: int) -> int:
        """清空会话的所有消息（仅限当前用户的），返回删除数量

        P0 Task 3.4：WHERE 同时按 session_id + user_id 过滤；
        跨用户清空返回 0（不存在的对象不暴露存在性）。
        """
        result = await self.db.execute(
            delete(Conversation).where(
                Conversation.session_id == session_id,
                Conversation.user_id == user_id,
            )
        )
        await self.db.flush()
        return result.rowcount

    async def list_sessions(self, user_id: int) -> list[str]:
        """获取当前用户所有不重复的 session_id"""
        result = await self.db.execute(
            select(Conversation.session_id)
            .distinct()
            .where(Conversation.user_id == user_id)
        )
        return [row[0] for row in result.all()]

    async def list_sessions_with_meta(
        self, user_id: int, agent_id: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """返回当前用户的会话列表(含元数据): session_id, agent_id, title,
        message_count, last_message_at, created_at

        P0 Task 3.4：仅返回 user_id 名下的会话。
        """
        # 子查询: 当前用户的每个 session_id 的元数据聚合
        subq = (
            select(
                Conversation.session_id.label("sid"),
                Conversation.agent_id.label("aid"),
                func.max(Conversation.created_at).label("last_at"),
                func.min(Conversation.created_at).label("first_at"),
                func.count(Conversation.id).label("msg_count"),
            )
            .where(Conversation.user_id == user_id)
            .group_by(Conversation.session_id, Conversation.agent_id)
            .subquery()
        )

        # 主查询: 关联取 title(取首条 user 消息的 title 或 content 前 30 字)
        title_subq = (
            select(
                Conversation.session_id.label("sid"),
                Conversation.title.label("title"),
                Conversation.content.label("content"),
                Conversation.created_at.label("created_at"),
                Conversation.id.label("id"),
            )
            .where(
                Conversation.role == "user",
                Conversation.user_id == user_id,
            )
            .order_by(Conversation.session_id, Conversation.created_at.asc())
            .subquery()
        )

        # 取每个 session 的首条 user 消息(用于 title)
        first_user_msg = (
            select(
                title_subq.c.sid,
                title_subq.c.title,
                title_subq.c.content,
            )
            .distinct(title_subq.c.sid)
            .subquery()
        )

        query = (
            select(
                subq.c.sid,
                subq.c.aid,
                subq.c.last_at,
                subq.c.first_at,
                subq.c.msg_count,
                first_user_msg.c.title,
                first_user_msg.c.content,
            )
            .select_from(subq)
            .outerjoin(first_user_msg, subq.c.sid == first_user_msg.c.sid)
            .order_by(desc(subq.c.last_at))
            .limit(limit)
        )

        if agent_id:
            query = query.where(subq.c.aid == agent_id)

        result = await self.db.execute(query)
        rows = result.all()

        sessions = []
        for row in rows:
            # title 优先使用存储的 title,否则取首条 user 消息前 30 字
            title = row.title if row.title else (
                row.content[:30] + "..." if row.content and len(row.content) > 30
                else (row.content or "未命名会话")
            )
            sessions.append({
                "session_id": row.sid,
                "agent_id": row.aid,
                "title": title,
                "message_count": row.msg_count,
                "last_message_at": row.last_at.isoformat() if row.last_at else None,
                "created_at": row.first_at.isoformat() if row.first_at else None,
            })
        return sessions

    async def rename_session(self, session_id: str, user_id: int, title: str) -> bool:
        """重命名会话(仅当前用户的会话，更新该会话所有消息的 title 字段)

        P0 Task 3.4：WHERE 同时按 session_id + user_id 过滤；
        跨用户重命名返回 False（Router 层映射为 404）。
        """
        result = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.session_id == session_id,
                Conversation.user_id == user_id,
            )
            .values(title=title[:128])
        )
        await self.db.flush()
        return result.rowcount > 0

    async def delete_session(self, session_id: str, user_id: int) -> int:
        """物理删除整个会话(仅当前用户的，返回删除数量)

        P0 Task 3.4：WHERE 同时按 session_id + user_id 过滤；
        跨用户删除返回 0（Router 层映射为 404）。
        """
        result = await self.db.execute(
            delete(Conversation).where(
                Conversation.session_id == session_id,
                Conversation.user_id == user_id,
            )
        )
        await self.db.flush()
        return result.rowcount

    async def get_session_count(self, session_id: str, user_id: int) -> int:
        """获取某个会话的消息数量（仅当前用户的）"""
        result = await self.db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.session_id == session_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar() or 0

    # ── Task 26: 封装 AgentExecutionLog 写入 ──

    async def log_agent_execution(
        self,
        user_id: int,
        session_id: str,
        agent_id: str,
        model: str,
        token_usage: dict,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        """写入 AgentExecutionLog 用于成本分析、延迟监控与故障排查（Task 26）

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            agent_id: Agent 类型
            model: 使用的 LLM 模型名
            token_usage: dict，可含 prompt_tokens / completion_tokens
            duration_ms: 调用耗时（毫秒）
            error: 失败时错误消息（截断到 500 字符）；None 表示成功
        """
        try:
            prompt_tokens = token_usage.get("prompt_tokens") if isinstance(token_usage, dict) else None
            completion_tokens = token_usage.get("completion_tokens") if isinstance(token_usage, dict) else None
            status = "success" if error is None else "failed"
            log_entry = AgentExecutionLog(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=duration_ms,
                status=status,
                error_code=None if error is None else "LLM_API_FAILED",
                error_message=(error or "")[:500] if error else None,
            )
            self.db.add(log_entry)
            await self.db.commit()
        except Exception:
            # 写日志失败不应影响主流程
            from ...core.logging_config import get_logger
            _logger = get_logger(__name__)
            _logger.warning(f"agent_execution_log_persist_failed user={user_id} agent={agent_id}")
