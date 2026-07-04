"""Test fixtures for CNKI downloader system."""

import os
import sys
import pytest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_task():
    """Create a sample Task for testing."""
    from models.task import Task
    from models.enums import TaskStatus
    return Task(
        task_id="test-task-001",
        discipline="新闻传播学",
        journal_name="国际新闻界",
        journal_url="https://navi.cnki.net/knavi/journal/GJXW/detail",
        year=2024,
        issue_number="03",
        issue_url="https://navi.cnki.net/knavi/journal/GJXW/2024/03",
        paper_title="测试论文标题",
        paper_url="https://kns.cnki.net/kcms2/article/abstract?test=1",
        status=TaskStatus.PENDING,
    )


@pytest.fixture
def sample_paper():
    """Create a sample Paper for testing."""
    from models.paper import Paper
    from models.enums import TaskStatus
    return Paper(
        paper_id="test-paper-001",
        title="数字时代的新闻传播研究",
        authors=["张三", "李四"],
        year=2024,
        journal_name="国际新闻界",
        discipline="新闻传播学",
        issue_number="03",
        abstract="这是一篇关于数字时代新闻传播的学术论文摘要。",
        keywords=["数字时代", "新闻传播", "新媒体"],
        doi="10.1234/test.001",
        cnki_url="https://kns.cnki.net/kcms2/article/abstract?test=1",
        file_format="pdf",
        download_status=TaskStatus.PENDING,
    )


@pytest.fixture
def sample_journal():
    """Create a sample Journal for testing."""
    from models.journal import Journal
    return Journal(
        name="国际新闻界",
        discipline="新闻传播学",
        issn="1002-5685",
        cnki_pcode="GJXW",
        issues_per_year=12,
        year_range=(2016, 2026),
    )


@pytest.fixture
def journal_config():
    """Create a sample JournalConfig for testing."""
    from config.journals import JournalConfig
    return JournalConfig(
        name="国际新闻界",
        discipline="新闻传播学",
        issn="1002-5685",
        cnki_pcode="GJXW",
    )
