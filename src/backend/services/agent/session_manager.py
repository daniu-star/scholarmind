"""
SessionManager — 对话持久化与会话 CRUD
从 agent_service.py 拆分，负责所有会话读写操作。
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from ...config import settings
from ...core.logging_config import get_logger
from ...core.path_safety import validate_session_id

if __import__("typing").TYPE_CHECKING:
    pass

logger = get_logger(__name__)

CONVERSATIONS_DIR = Path(settings.CONVERSATIONS_DIR)


class SessionManager:
    """会话管理器：DB 模式（ConversationRepository）或文件模式（JSON）"""

    def __init__(self, conversation_repo=None):
        self.conversation_repo = conversation_repo
        self.conversations: dict[str, list[dict]] = {}
        self._session_meta: dict[str, dict] = {}
        self._use_db = conversation_repo is not None

    @staticmethod
    def _conversation_key(session_id: str, user_id: int) -> str:
        """Return a user-scoped in-memory key."""
        validate_session_id(session_id)
        return f"{user_id}:{session_id}"

    @staticmethod
    def _conversation_path(session_id: str, user_id: int) -> Path:
        """Return a traversal-safe, user-scoped persistence path."""
        key = SessionManager._conversation_key(session_id, user_id)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return CONVERSATIONS_DIR / f"{digest}.json"

    def load_all_conversations(self) -> None:
        """Load user-scoped fallback conversations from disk."""
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
        for filepath in CONVERSATIONS_DIR.glob("*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                session_id = str(data.get("session_id") or "")
                user_id = int(data.get("user_id") or 0)
                key = self._conversation_key(session_id, user_id)
                messages = data.get("messages", [])
                if not isinstance(messages, list):
                    continue
                self.conversations[key] = messages
                self._session_meta[key] = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "agent_id": data.get("agent_id", "unknown"),
                    "title": data.get("title"),
                    "updated_at": data.get("updated_at"),
                }
            except Exception as exc:
                logger.warning(f"conversation_fallback_load_failed file={filepath.name} error={exc}")

    def load_conversation(self, session_id: str, user_id: int) -> list[dict]:
        """按需加载对话历史（内存 → 文件 → DB）"""
        key = self._conversation_key(session_id, user_id)
        if key in self.conversations:
            return self.conversations[key]
        if self._use_db:
            return []  # DB mode: loaded by repository caller
        filepath = self._conversation_path(session_id, user_id)
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                messages = data if isinstance(data, list) else data.get("messages", [])
                self.conversations[key] = messages
                return messages
            except Exception as e:
                logger.warning(f"Failed to load conversation {session_id}: {e}")
        self.conversations[key] = []
        return self.conversations[key]

    def save_conversation(
        self,
        session_id: str,
        user_id: int,
        *,
        agent_id: str = "unknown",
    ) -> None:
        """持久化对话历史"""
        if self._use_db:
            return  # DB mode: persisted by repository caller
        key = self._conversation_key(session_id, user_id)
        if key in self.conversations:
            CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
            filepath = self._conversation_path(session_id, user_id)
            try:
                msgs = self.conversations[key][-40:]
                meta = self._session_meta.get(key, {})
                payload = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "title": meta.get("title"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "messages": msgs,
                }
                filepath.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._session_meta[key] = payload
            except Exception as e:
                logger.warning(f"Failed to save conversation {session_id}: {e}")

    async def clear_conversation(self, session_id: str, user_id: int = 0) -> bool:
        if self._use_db:
            deleted = await self.conversation_repo.clear_session(session_id, user_id)
            return deleted > 0
        key = self._conversation_key(session_id, user_id)
        if key in self.conversations:
            del self.conversations[key]
            self._session_meta.pop(key, None)
            filepath = self._conversation_path(session_id, user_id)
            if filepath.exists():
                try:
                    filepath.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete: {e}")
            return True
        return False

    async def get_conversation_history(self, session_id: str, user_id: int = 0) -> list[dict]:
        if self._use_db:
            db_history = await self.conversation_repo.get_by_session(session_id, user_id)
            return [{"role": msg.role, "content": msg.content} for msg in db_history]
        return list(self.load_conversation(session_id, user_id))

    async def list_sessions_with_meta(
        self, user_id: int = 0, agent_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        if self._use_db:
            return await self.conversation_repo.list_sessions_with_meta(user_id, agent_id, limit)
        sessions = []
        for key, msgs in self.conversations.items():
            if not msgs:
                continue
            meta = self._session_meta.get(key, {})
            if int(meta.get("user_id", -1)) != user_id:
                continue
            if agent_id and meta.get("agent_id") != agent_id:
                continue
            sid = str(meta.get("session_id") or key.split(":", 1)[-1])
            first_msg = msgs[0] if msgs else {}
            title = meta.get("title") or first_msg.get("content", "Unnamed")[:30]
            sessions.append(
                {
                    "session_id": sid,
                    "agent_id": meta.get("agent_id", "unknown"),
                    "title": title,
                    "message_count": len(msgs),
                    "last_message_at": meta.get("updated_at"),
                    "created_at": None,
                }
            )
        return sessions[:limit]

    async def rename_session(self, session_id: str, title: str, user_id: int = 0) -> bool:
        if self._use_db:
            return await self.conversation_repo.rename_session(session_id, user_id, title)
        key = self._conversation_key(session_id, user_id)
        if key not in self.conversations:
            return False
        self._session_meta.setdefault(key, {"session_id": session_id, "user_id": user_id})["title"] = title[:128]
        self.save_conversation(
            session_id,
            user_id,
            agent_id=self._session_meta[key].get("agent_id", "unknown"),
        )
        return True

    async def delete_session(self, session_id: str, user_id: int = 0) -> int:
        if self._use_db:
            return await self.conversation_repo.delete_session(session_id, user_id)
        key = self._conversation_key(session_id, user_id)
        if key in self.conversations:
            msg_count = len(self.conversations[key])
            del self.conversations[key]
            self._session_meta.pop(key, None)
            filepath = self._conversation_path(session_id, user_id)
            if filepath.exists():
                try:
                    filepath.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete: {e}")
            return msg_count
        return 0
