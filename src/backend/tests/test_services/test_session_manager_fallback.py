"""Fallback conversation storage security and isolation tests."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from src.backend.services.agent import session_manager as session_module
from src.backend.services.agent.session_manager import SessionManager


def _manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionManager:
    monkeypatch.setattr(session_module, "CONVERSATIONS_DIR", tmp_path)
    return SessionManager()


def test_fallback_memory_is_scoped_by_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path, monkeypatch)
    session_id = "session_shared_01"

    user_one = manager.load_conversation(session_id, user_id=101)
    user_two = manager.load_conversation(session_id, user_id=202)
    user_one.append({"role": "user", "content": "private-one"})
    user_two.append({"role": "user", "content": "private-two"})

    assert manager.load_conversation(session_id, 101)[0]["content"] == "private-one"
    assert manager.load_conversation(session_id, 202)[0]["content"] == "private-two"


def test_fallback_files_are_scoped_and_reloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path, monkeypatch)
    session_id = "session_shared_02"
    manager.load_conversation(session_id, 101).append({"role": "user", "content": "user-101"})
    manager.load_conversation(session_id, 202).append({"role": "user", "content": "user-202"})
    manager.save_conversation(session_id, 101, agent_id="researcher")
    manager.save_conversation(session_id, 202, agent_id="reviewer")

    assert len(list(tmp_path.glob("*.json"))) == 2

    reloaded = _manager(tmp_path, monkeypatch)
    reloaded.load_all_conversations()
    assert reloaded.load_conversation(session_id, 101)[0]["content"] == "user-101"
    assert reloaded.load_conversation(session_id, 202)[0]["content"] == "user-202"


def test_fallback_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        manager.load_conversation("../../secrets", user_id=101)

    assert exc_info.value.status_code == 400
    assert list(tmp_path.iterdir()) == []
