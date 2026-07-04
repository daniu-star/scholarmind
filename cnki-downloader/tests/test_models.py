"""Tests for data models."""

import json
import pytest

from models.enums import TaskStatus, Discipline, ErrorCategory, CAPTCHAType
from models.task import Task


class TestTaskModel:
    """Tests for the Task data model."""

    def test_task_creation_defaults(self):
        task = Task(discipline="新闻传播学")
        assert task.task_id
        assert len(task.task_id) == 36  # UUID4
        assert task.discipline == "新闻传播学"
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 0
        assert task.max_retries == 5
        assert task.created_at

    def test_task_to_dict(self):
        task = Task(
            task_id="test-001",
            discipline="新闻传播学",
            journal_name="国际新闻界",
            year=2024,
            status=TaskStatus.QUEUED,
        )
        d = task.to_dict()
        assert d["task_id"] == "test-001"
        assert d["discipline"] == "新闻传播学"
        assert d["status"] == "queued"

    def test_task_json_roundtrip(self):
        task = Task(
            discipline="人工智能",
            journal_name="自动化学报",
            year=2023,
            status=TaskStatus.PROCESSING,
        )
        json_str = task.to_json()
        decoded = Task.from_dict(json.loads(json_str))
        assert decoded.task_id == task.task_id
        assert decoded.discipline == task.discipline
        assert decoded.status == task.status

    def test_task_redis_hash_conversion(self):
        task = Task(
            task_id="test-redis-001",
            discipline="计算机科学",
            year=2025,
        )
        hash_data = task.to_redis_hash()
        assert hash_data["task_id"] == "test-redis-001"
        assert hash_data["discipline"] == "计算机科学"
        assert hash_data["year"] == "2025"


class TestEnums:
    """Tests for enum types."""

    def test_task_status_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.QUEUED.value == "queued"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"

    def test_discipline_values(self):
        assert Discipline.NEWS_COMM.value == "新闻传播学"
        assert Discipline.AI.value == "人工智能"
        assert len(list(Discipline)) == 5

    def test_error_category_values(self):
        assert ErrorCategory.NETWORK.value == "network"
        assert ErrorCategory.CAPTCHA.value == "captcha"
        assert ErrorCategory.RATE_LIMIT.value == "rate_limit"

    def test_captcha_type_values(self):
        assert CAPTCHAType.SLIDE.value == "slide"
        assert CAPTCHAType.CLICK.value == "click"
        assert CAPTCHAType.TEXT.value == "text"


class TestJournalConfig:
    """Tests for journal configuration."""

    def test_all_disciplines_have_4_journals(self):
        from config.journals import DISCIPLINE_JOURNALS, VALID_DISCIPLINES
        assert len(VALID_DISCIPLINES) == 5
        for discipline in VALID_DISCIPLINES:
            journals = DISCIPLINE_JOURNALS[discipline]
            assert len(journals) == 4, f"{discipline} should have 4 journals, got {len(journals)}"

    def test_journal_config_has_urls(self):
        from config.journals import get_all_journals
        journals = get_all_journals()
        assert len(journals) == 20  # 5 × 4
        for j in journals:
            assert j.name
            assert j.cnki_pcode
            assert j.navi_url
            assert "knavi" in j.navi_url

    def test_year_range_2016_to_2026(self):
        from config.journals import get_all_journals
        for j in get_all_journals():
            assert j.issues_per_year == 12
            assert j.year_range == (2016, 2026)
