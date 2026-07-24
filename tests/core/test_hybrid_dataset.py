"""Tests for HybridDatasetBuilder — pure logic, no real LLM or DB calls."""
import json

import pytest

from evolution.core.hybrid_dataset import HybridDatasetBuilder


def _make_synthetic(prefix: str = "synth", count: int = 5) -> list[dict]:
    return [
        {
            "task_input": f"{prefix}-input-{i}",
            "expected_behavior": f"synthetic expected {i}",
            "source": "synthetic",
        }
        for i in range(count)
    ]


def _make_session(skill: str = "my-skill", count: int = 3) -> list[dict]:
    return [
        {
            "task_input": f"session-input-{i}",
            "expected_behavior": f"Handles the error gracefully. Context: error_{i}",
            "source": "session",
        }
        for i in range(count)
    ]


class TestBuild:
    def test_no_grazer_result(self):
        """Build returns only synthetic when grazer_result is None."""
        builder = HybridDatasetBuilder()
        # No synthetic_builder set -> empty when no session data
        result = builder.build("any-skill")
        assert result == []

    def test_only_synthetic_without_session(self):
        """When grazer_result has no failures, returns synthetic only."""
        builder = HybridDatasetBuilder()
        result = builder.build("any-skill", grazer_result={"failures": []})
        assert result == []

    def test_combines_both_sources(self):
        """Session cases appear before synthetic in the merged result."""
        builder = HybridDatasetBuilder()
        synth = _make_synthetic(count=3)
        session = _make_session(count=2)

        # Directly test via internal methods to avoid LLM dependency
        merged = builder._merge(synth, session)
        assert len(merged) == 5
        assert merged[0]["source"] == "session"
        assert merged[-1]["source"] == "synthetic"


class TestGetSessionCases:
    def test_extracts_failures_for_skill(self):
        result = HybridDatasetBuilder._get_session_cases(
            {
                "failures": [
                    {"skill_name": "my-skill", "task_input": "load skill", "error_type": "tool_error", "error_message": "not found"},
                    {"skill_name": "other-skill", "task_input": "other", "error_type": "tool_error", "error_message": ""},
                ]
            },
            "my-skill",
        )
        assert len(result) == 1
        assert result[0]["task_input"] == "load skill"
        assert result[0]["source"] == "session"

    def test_no_matching_skill_returns_empty(self):
        result = HybridDatasetBuilder._get_session_cases(
            {"failures": [{"skill_name": "other", "task_input": "x", "error_type": "fail", "error_message": ""}]},
            "my-skill",
        )
        assert result == []

    def test_empty_grazer_result(self):
        assert HybridDatasetBuilder._get_session_cases(None, "any") == []
        assert HybridDatasetBuilder._get_session_cases({}, "any") == []


class TestMerge:
    def test_session_first(self):
        synth = _make_synthetic()
        sess = _make_session()
        merged = HybridDatasetBuilder._merge(synth, sess)
        assert merged[0]["source"] == "session"
        assert merged[-1]["source"] == "synthetic"

    def test_empty_synthetic(self):
        merged = HybridDatasetBuilder._merge([], _make_session(count=2))
        assert len(merged) == 2

    def test_empty_session(self):
        merged = HybridDatasetBuilder._merge(_make_synthetic(count=3), [])
        assert len(merged) == 3


class TestDeduplicate:
    def test_identical_inputs_deduped(self):
        cases = [
            {"task_input": "a", "source": "session"},
            {"task_input": "a", "source": "synthetic"},
        ]
        deduped = HybridDatasetBuilder._deduplicate(cases)
        assert len(deduped) == 1
        # Session wins when both have same key
        assert deduped[0]["source"] == "session"

    def test_case_insensitive_dedup(self):
        cases = [
            {"task_input": "Hello World", "source": "session"},
            {"task_input": "hello world", "source": "synthetic"},
        ]
        deduped = HybridDatasetBuilder._deduplicate(cases)
        assert len(deduped) == 1

    def test_whitespace_insensitive(self):
        cases = [
            {"task_input": "  load skill  ", "source": "session"},
            {"task_input": "load skill", "source": "synthetic"},
        ]
        deduped = HybridDatasetBuilder._deduplicate(cases)
        assert len(deduped) == 1

    def test_no_duplicates_preserves_all(self):
        cases = _make_synthetic(count=3) + _make_session(count=2)
        deduped = HybridDatasetBuilder._deduplicate(cases)
        assert len(deduped) == 5

    def test_empty_task_input_skipped(self):
        cases = [
            {"task_input": "", "source": "session"},
            {"task_input": "real", "source": "synthetic"},
        ]
        deduped = HybridDatasetBuilder._deduplicate(cases)
        assert len(deduped) == 1


class TestBalance:
    def test_enough_session_returns_all(self):
        cases = _make_session(count=7) + _make_synthetic(count=3)
        balanced = HybridDatasetBuilder._balance(cases, ratio=0.4)
        # 7/10 = 0.7 >= 0.4 so all returned
        assert len(balanced) == 10

    def test_boosts_session_to_ratio(self):
        cases = _make_session(count=2) + _make_synthetic(count=8)
        balanced = HybridDatasetBuilder._balance(cases, ratio=0.4)
        # 2 session / total >= 0.4  -> total <= 5, so trim synthetic to 3
        assert 2 / len(balanced) >= 0.4
        assert sum(1 for c in balanced if c["source"] == "session") == 2

    def test_empty_cases(self):
        assert HybridDatasetBuilder._balance([]) == []

    def test_no_session_cases_returns_all_synthetic(self):
        cases = _make_synthetic(count=5)
        balanced = HybridDatasetBuilder._balance(cases, ratio=0.4)
        assert len(balanced) == 5
        assert all(c["source"] == "synthetic" for c in balanced)

    def test_session_always_preserved(self):
        """Balance never drops session cases, only trims synthetic."""
        cases = _make_session(count=4) + _make_synthetic(count=30)
        balanced = HybridDatasetBuilder._balance(cases, ratio=0.5)
        session_count = sum(1 for c in balanced if c["source"] == "session")
        assert session_count == 4
        assert 4 / len(balanced) >= 0.5


class TestDeduplicateOrder:
    def test_preserves_session_when_first_in_order(self):
        cases = [
            {"task_input": "shared", "source": "synthetic"},
            {"task_input": "shared", "source": "session"},
        ]
        deduped = HybridDatasetBuilder._deduplicate(cases)
        assert deduped[0]["source"] == "session"

    def test_session_second_also_wins(self):
        cases = [
            {"task_input": "shared", "source": "session"},
            {"task_input": "shared", "source": "synthetic"},
        ]
        deduped = HybridDatasetBuilder._deduplicate(cases)
        assert deduped[0]["source"] == "session"
