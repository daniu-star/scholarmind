"""
SessionManager — 对话持久化与会话 CRUD
从 agent_service.py 拆分，负责所有会话读写操作。
"""
from __future__ import annotations

import json
from pathlib import Path

from ...config import settings
from ...core.logging_config import get_logger

if __import__('typing').TYPE_CHECKING:
    pass

logger = get_logger(__name__)

CONVERSATIONS_DIR = Path(settings.CONVERSATIONS_DIR)


class SessionManager:
    """会话管理器：DB 模式（ConversationRepository）或文件模式（JSON）"""

    def __init__(self, conversation_repo=None):
        self.conversation_repo = conversation_repo
        self.conversations: dict[str, list[dict]] = {}
        self._use_db = conversation_repo is not None

    def _load_conversation(self, session_id: str) -> list[dict]:
        """按需加载对话历史（内存 → 文件 → DB）"""
        if session_id in self.conversations:
            return self.conversations[session_id]
        if self._use_db:
            return []  # DB mode: loaded by repository caller
        filepath = CONVERSATIONS_DIR / f'{session_id}.json'
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text(encoding='utf-8'))
                messages = data if isinstance(data, list) else data.get('messages', [])
                self.conversations[session_id] = messages
                return messages
            except Exception as e:
                logger.warning(f'Failed to load conversation {session_id}: {e}')
        self.conversations[session_id] = []
        return []

    def _save_conversation(self, session_id: str) -> None:
        """持久化对话历史"""
        if self._use_db:
            return  # DB mode: persisted by repository caller
        if session_id in self.conversations:
            CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
            filepath = CONVERSATIONS_DIR / f'{session_id}.json'
            try:
                msgs = self.conversations[session_id][-40:]  # keep last 40 messages
                filepath.write_text(json.dumps(msgs, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as e:
                logger.warning(f'Failed to save conversation {session_id}: {e}')

    async def clear_conversation(self, session_id: str, user_id: int = 0) -> bool:
        if self._use_db:
            deleted = await self.conversation_repo.clear_session(session_id, user_id)
            return deleted > 0
        if session_id in self.conversations:
            del self.conversations[session_id]
            filepath = CONVERSATIONS_DIR / f'{session_id}.json'
            if filepath.exists():
                try:
                    filepath.unlink()
                except Exception as e:
                    logger.warning(f'Failed to delete: {e}')
            return True
        return False

    async def get_conversation_history(self, session_id: str, user_id: int = 0) -> list[dict]:
        if self._use_db:
            db_history = await self.conversation_repo.get_by_session(session_id, user_id)
            return [{'role': msg.role, 'content': msg.content} for msg in db_history]
        return self.conversations.get(session_id, [])

    async def list_sessions_with_meta(self, user_id: int = 0, agent_id: str | None = None, limit: int = 50) -> list[dict]:
        if self._use_db:
            return await self.conversation_repo.list_sessions_with_meta(user_id, agent_id, limit)
        sessions = []
        for sid, msgs in self.conversations.items():
            if not msgs:
                continue
            first_msg = msgs[0] if msgs else {}
            title = first_msg.get('content', 'Unnamed')[:30]
            sessions.append({'session_id': sid, 'agent_id': 'unknown', 'title': title, 'message_count': len(msgs), 'last_message_at': None, 'created_at': None})
        return sessions[:limit]

    async def rename_session(self, session_id: str, title: str, user_id: int = 0) -> bool:
        if self._use_db:
            return await self.conversation_repo.rename_session(session_id, user_id, title)
        return True

    async def delete_session(self, session_id: str, user_id: int = 0) -> int:
        if self._use_db:
            return await self.conversation_repo.delete_session(session_id, user_id)
        if session_id in self.conversations:
            msg_count = len(self.conversations[session_id])
            del self.conversations[session_id]
            filepath = CONVERSATIONS_DIR / f'{session_id}.json'
            if filepath.exists():
                try:
                    filepath.unlink()
                except Exception as e:
                    logger.warning(f'Failed to delete: {e}')
            return msg_count
        return 0
