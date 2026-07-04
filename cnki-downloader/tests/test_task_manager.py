"""Tests for task manager and scheduler."""

import pytest
import json

from models.task import Task
from models.enums import TaskStatus


class TestTaskSerialization:
    """Tests for task serialization/deserialization."""

    def test_roundtrip_json(self):
        task = Task(
            discipline="人工智能",
            journal_name="模式识别与人工智能",
            year=2023,
            issue_number="06",
            status=TaskStatus.QUEUED,
        )
        data = task.to_dict()
        restored = Task.from_dict(data)
        assert restored.task_id == task.task_id
        assert restored.discipline == "人工智能"
        assert restored.journal_name == "模式识别与人工智能"
        assert restored.year == 2023
        assert restored.status == TaskStatus.QUEUED

    def test_roundtrip_redis_hash(self):
        task = Task(
            discipline="化学",
            journal_name="化学学报",
            year=2025,
            status=TaskStatus.PROCESSING,
        )
        hash_data = task.to_redis_hash()
        # Simulate Redis bytes return
        bytes_hash = {
            k.encode(): v.encode()
            for k, v in hash_data.items()
        }
        restored = Task.from_redis_hash(bytes_hash)
        assert restored.task_id == task.task_id
        assert restored.discipline == "化学"
        assert restored.status == TaskStatus.PROCESSING

    def test_failed_task_serialization(self):
        task = Task(
            discipline="人类学",
            journal_name="人类学学报",
            year=2020,
            status=TaskStatus.FAILED,
            error_type="captcha",
            error_message="CAPTCHA could not be solved",
            retry_count=3,
        )
        data = task.to_dict()
        assert data["status"] == "failed"
        assert data["error_type"] == "captcha"
        assert data["retry_count"] == 3


class TestJournalConfig:
    """Tests for journal configuration module."""

    def test_all_disciplines_valid(self):
        from config.journals import VALID_DISCIPLINES, DISCIPLINE_JOURNALS
        assert "新闻传播学" in VALID_DISCIPLINES
        assert "人工智能" in VALID_DISCIPLINES
        assert "人类学" in VALID_DISCIPLINES
        assert "计算机科学" in VALID_DISCIPLINES
        assert "化学" in VALID_DISCIPLINES

    def test_get_journals_for_each_discipline(self):
        from config.journals import get_journals_for
        for disc_name in ["新闻传播学", "人工智能", "人类学", "计算机科学", "化学"]:
            journals = get_journals_for(disc_name)
            assert len(journals) == 4, f"{disc_name} has {len(journals)} journals"
            for j in journals:
                assert j.name
                assert j.cnki_pcode
                assert j.navi_url

    def test_journal_issn_format(self):
        from config.journals import get_all_journals
        for j in get_all_journals():
            if j.issn:
                assert "-" in j.issn


class TestSettings:
    """Tests for application settings."""

    def test_settings_defaults(self):
        from config.settings import settings
        assert settings.REDIS_URL == "redis://localhost:6379/0"
        assert settings.MASTER_PORT == 8100
        assert settings.THREAD_COUNT == 3
        assert settings.HEARTBEAT_INTERVAL == 10
        assert settings.HEARTBEAT_TIMEOUT == 30
        assert settings.BROWSER_HEADLESS is True
        assert settings.CB_FAILURE_THRESHOLD == 5


class TestRedisProtocol:
    """Tests for Redis protocol key schemas."""

    def test_queue_key_patterns(self):
        from master.protocols.redis_protocol import (
            TASK_QUEUE_KEY,
            TASK_DATA_KEY,
            WORKER_HEARTBEAT_KEY,
        )
        qk = TASK_QUEUE_KEY.format(discipline="新闻传播学")
        assert qk == "cnki:task:queue:新闻传播学"

        dk = TASK_DATA_KEY.format(task_id="abc-123")
        assert dk == "cnki:task:data:abc-123"

        hk = WORKER_HEARTBEAT_KEY.format(worker_id="worker-1")
        assert hk == "cnki:heartbeat:worker-1"

    def test_lua_scripts_are_valid(self):
        from master.protocols.redis_protocol import (
            LUA_TASK_ACQUIRE,
            LUA_TASK_COMPLETE,
        )
        assert "RPOP" in LUA_TASK_ACQUIRE
        assert "cjson.decode" in LUA_TASK_ACQUIRE
        assert "SREM" in LUA_TASK_COMPLETE
        assert "DEL" in LUA_TASK_COMPLETE
