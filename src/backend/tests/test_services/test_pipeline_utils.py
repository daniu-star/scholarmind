"""Pipeline 公共工具模块测试（pipeline_utils.py）

覆盖：
- check_pipeline_ownership: 用户所有权校验
- resolve_research_type: 研究类型映射（含中文别名）
- resolve_journal_style: 期刊格式推断
- calculate_pipeline_progress: 进度计算
"""
from __future__ import annotations

import pytest

from ...services.pipeline_utils import (
    check_pipeline_ownership,
    resolve_research_type,
    resolve_journal_style,
    resolve_output_format,
    calculate_pipeline_progress,
    RESEARCH_TYPE_MAP,
    DISCIPLINE_TO_JOURNAL,
    OUTPUT_FORMAT_MAP,
)


class TestPipelineOwnership:
    """Pipeline 所有权校验（IDOR 防护）"""

    def test_none_state_returns_false(self):
        """pipeline 不存在 → 拒绝访问"""
        assert check_pipeline_ownership(None, "user-1") is False

    def test_wrong_user_returns_false(self):
        """user_id 不匹配 → 拒绝访问"""
        state = {"user_id": "user-2"}
        assert check_pipeline_ownership(state, "user-1") is False

    def test_correct_user_returns_true(self):
        """user_id 匹配 → 允许访问"""
        state = {"user_id": "user-1"}
        assert check_pipeline_ownership(state, "user-1") is True

    def test_int_user_id_matches_string(self):
        """int 与 str 类型互转后仍能匹配"""
        state = {"user_id": 42}
        assert check_pipeline_ownership(state, "42") is True

    def test_no_user_id_filter_allows_all(self):
        """未传 user_id 时不校验所有权（内部调用）"""
        state = {"user_id": "user-1"}
        assert check_pipeline_ownership(state, None) is True


class TestResearchTypeMapping:
    """研究类型映射"""

    def test_english_types(self):
        assert resolve_research_type("quantitative") == "quantitative"
        assert resolve_research_type("qualitative") == "qualitative"
        assert resolve_research_type("mixed") == "mixed"
        assert resolve_research_type("computational") == "computational"

    def test_chinese_aliases(self):
        assert resolve_research_type("量化研究") == "quantitative"
        assert resolve_research_type("质性研究") == "qualitative"
        assert resolve_research_type("混合方法") == "mixed"

    def test_null_defaults_to_mixed(self):
        assert resolve_research_type(None) == "mixed"

    def test_unknown_passthrough(self):
        """未知值直接透传"""
        assert resolve_research_type("unknown_type") == "unknown_type"


class TestJournalStyle:
    """期刊格式解析"""

    def test_explicit_style_priority(self):
        """显式 journal_style 优先于 discipline 推断"""
        assert resolve_journal_style("communication", "gjxwj") == "gjxwj"

    def test_discipline_inference(self):
        assert resolve_journal_style("communication", None) == "xwycbyj"
        assert resolve_journal_style("sociology", None) == "shxyj"
        assert resolve_journal_style("literature", None) == "gjxwj"

    def test_unknown_discipline_default(self):
        assert resolve_journal_style("unknown", None) == "xwycbyj"

    def test_none_discipline_default(self):
        assert resolve_journal_style(None, None) == "xwycbyj"


class TestOutputFormat:
    """输出格式映射"""

    def test_docx_to_word(self):
        assert resolve_output_format("docx") == "word"

    def test_markdown_passthrough(self):
        assert resolve_output_format("markdown") == "markdown"

    def test_null_default(self):
        assert resolve_output_format(None) == "word"


class TestProgressCalculation:
    """进度计算"""

    AGENT_ORDER = [
        ("agent_a", "A", "desc"),
        ("agent_b", "B", "desc"),
        ("agent_c", "C", "desc"),
    ]

    def test_completed_is_full(self):
        state = {"status": "completed", "config": {"max_rounds": 5}}
        assert calculate_pipeline_progress(state, self.AGENT_ORDER) == 1.0

    def test_failed_is_zero(self):
        state = {"status": "failed", "config": {"max_rounds": 5}}
        assert calculate_pipeline_progress(state, self.AGENT_ORDER) == 0.0

    def test_cancelled_is_zero(self):
        state = {"status": "cancelled", "config": {"max_rounds": 5}}
        assert calculate_pipeline_progress(state, self.AGENT_ORDER) == 0.0

    def test_running_with_agent_position(self):
        state = {
            "status": "running",
            "current_round": 1,
            "current_agent": "agent_b",
            "config": {"max_rounds": 3},
        }
        progress = calculate_pipeline_progress(state, self.AGENT_ORDER)
        # round 1 of 3, agent index 1 of 3 → (1*3+1)/(3*3) = 4/9 ≈ 0.4444
        assert progress == pytest.approx(0.4444, abs=0.01)

    def test_capped_at_99_percent(self):
        state = {
            "status": "running",
            "current_round": 3,
            "current_agent": "agent_c",
            "config": {"max_rounds": 3},
        }
        progress = calculate_pipeline_progress(state, self.AGENT_ORDER)
        # Should be capped at 0.99 even if calculation exceeds it
        assert progress <= 0.99
