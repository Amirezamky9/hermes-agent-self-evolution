"""Tests for gap_analyzer — uses mock grazer output, no real DB needed."""
import pytest

from evolution.core.gap_analyzer import SkillGapAnalyzer, _classify_severity, _extract_description


# --- Fixtures ---


def _make_grazer_result(
    skill_usages=None,
    failures=None,
    skill_counts=None,
    failure_counts=None,
):
    """Build a grazer_result dict from minimal inputs."""
    usages = skill_usages or []
    fails = failures or []
    s_counts = skill_counts or {}
    f_counts = failure_counts or {}
    return {
        "skill_usages": usages,
        "failures": fails,
        "skill_counts": s_counts,
        "failure_counts": f_counts,
    }


def _usage(skill_name, error_type="", error_message="", task_input="test task"):
    return {
        "skill_name": skill_name,
        "error_type": error_type,
        "error_message": error_message,
        "task_input": task_input,
        "response": "ok",
        "session_id": "s1",
        "timestamp": 1700000000.0,
    }


@pytest.fixture
def analyzer(tmp_path):
    return SkillGapAnalyzer(hermes_path=str(tmp_path))


# --- Test classify_severity ---


class TestClassifySeverity:
    def test_critical_at_3(self):
        assert _classify_severity(3) == "critical"

    def test_critical_above_3(self):
        assert _classify_severity(10) == "critical"

    def test_warning_at_1(self):
        assert _classify_severity(1) == "warning"

    def test_warning_at_2(self):
        assert _classify_severity(2) == "warning"

    def test_info_at_0(self):
        assert _classify_severity(0) == "info"


# --- Test extract_description ---


class TestExtractDescription:
    def test_frontmatter_description(self):
        content = '---\nname: my-skill\ndescription: Does cool stuff\n---\n# Title'
        assert _extract_description(content) == "Does cool stuff"

    def test_heading_after_frontmatter(self):
        content = "---\nname: x\n---\n# My Great Skill"
        assert _extract_description(content) == "My Great Skill"

    def test_paragraph_after_frontmatter(self):
        content = "---\nname: x\n---\n\nThis skill does things."
        assert _extract_description(content) == "This skill does things."

    def test_empty_content(self):
        assert _extract_description("") == ""


# --- Test SkillGapAnalyzer ---


class TestAnalyze:
    def test_no_failures_returns_empty(self, analyzer):
        result = analyzer.analyze(_make_grazer_result())
        assert result == []

    def test_single_failure(self, analyzer):
        usages = [_usage("my-skill", error_type="tool_error", error_message="not found")]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=usages,
            failures=usages,
            failure_counts={"my-skill": 1},
        ))
        assert len(result) == 1
        gap = result[0]
        assert gap["skill_name"] == "my-skill"
        assert gap["failure_count"] == 1
        assert gap["severity"] == "warning"
        assert gap["error_types"] == {"tool_error": 1}

    def test_critical_severity(self, analyzer):
        failures = [_usage("bad-skill", error_type="tool_error", error_message=f"err{i}") for i in range(5)]
        usages = failures + [_usage("bad-skill")] * 3
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=usages,
            failures=failures,
            skill_counts={"bad-skill": 8},
            failure_counts={"bad-skill": 5},
        ))
        assert result[0]["severity"] == "critical"
        assert result[0]["failure_count"] == 5

    def test_multiple_skills_sorted_by_severity(self, analyzer):
        usages = (
            [_usage("ok-skill")] * 10
            + [_usage("warn-skill", error_type="lint_error")] * 1
            + [_usage("crit-skill", error_type="timeout")] * 4
        )
        failures = [u for u in usages if u["error_type"]]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=usages,
            failures=failures,
            skill_counts={"ok-skill": 10, "warn-skill": 1, "crit-skill": 4},
            failure_counts={"warn-skill": 1, "crit-skill": 4},
        ))
        assert result[0]["skill_name"] == "crit-skill"
        assert result[0]["severity"] == "critical"
        assert result[1]["skill_name"] == "warn-skill"
        assert result[1]["severity"] == "warning"

    def test_sample_failures_capped_at_5(self, analyzer):
        failures = [_usage("x", error_type="tool_error", error_message=f"e{i}") for i in range(10)]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=failures,
            failures=failures,
            failure_counts={"x": 10},
        ))
        assert len(result[0]["sample_failures"]) == 5

    def test_disabled_skill_recommendation(self, analyzer):
        failures = [_usage("x", error_type="tool_error", error_message="Skill 'x' is disabled.")]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=failures, failures=failures, failure_counts={"x": 1},
        ))
        assert "disabled" in result[0]["recommendation"].lower()

    def test_lint_error_recommendation(self, analyzer):
        failures = [_usage("x", error_type="lint_error", error_message="SyntaxError")]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=failures, failures=failures, failure_counts={"x": 1},
        ))
        assert "lint" in result[0]["recommendation"].lower() or "syntax" in result[0]["recommendation"].lower()

    def test_total_invocations_from_skill_counts(self, analyzer):
        usages = [_usage("x", error_type="tool_error")] * 2 + [_usage("x")] * 8
        failures = [u for u in usages if u["error_type"]]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=usages,
            failures=failures,
            skill_counts={"x": 10},
            failure_counts={"x": 2},
        ))
        assert result[0]["total_invocations"] == 10


class TestGetTopGaps:
    def test_returns_n_items(self, analyzer):
        failures_a = [_usage("a", error_type="tool_error")] * 4
        failures_b = [_usage("b", error_type="lint_error")] * 1
        failures_c = [_usage("c", error_type="timeout")] * 3
        usages = failures_a + failures_b + failures_c
        all_fails = [u for u in usages if u["error_type"]]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=usages,
            failures=all_fails,
            failure_counts={"a": 4, "b": 1, "c": 3},
        ))
        top2 = analyzer.get_top_gaps(result, n=2)
        assert len(top2) == 2
        assert top2[0]["severity"] == "critical"

    def test_empty_gaps(self, analyzer):
        assert analyzer.get_top_gaps([], n=5) == []


class TestToReport:
    def test_empty_report(self, analyzer):
        report = analyzer.to_report([])
        assert "No skill gaps" in report

    def test_report_contains_skill_names(self, analyzer):
        failures = [_usage("my-skill", error_type="tool_error", error_message="fail")]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=failures, failures=failures, failure_counts={"my-skill": 1},
        ))
        report = analyzer.to_report(result)
        assert "my-skill" in report
        assert "Skill Gap Report" in report

    def test_report_shows_severity_icons(self, analyzer):
        failures_crit = [_usage("crit", error_type="timeout")] * 3
        failures_warn = [_usage("warn", error_type="tool_error")]
        usages = failures_crit + failures_warn
        all_fails = [u for u in usages if u["error_type"]]
        result = analyzer.analyze(_make_grazer_result(
            skill_usages=usages,
            failures=all_fails,
            failure_counts={"crit": 3, "warn": 1},
        ))
        report = analyzer.to_report(result)
        assert "Critical" in report or "🔴" in report
        assert "Warning" in report or "🟡" in report

    def test_report_with_skill_description(self, analyzer, tmp_path):
        skills_dir = tmp_path / "skills" / "test-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\ndescription: A test skill\n---\n# Test\n")

        a = SkillGapAnalyzer(hermes_path=str(tmp_path))
        failures = [_usage("test-skill", error_type="tool_error", error_message="bad")]
        result = a.analyze(_make_grazer_result(
            skill_usages=failures, failures=failures, failure_counts={"test-skill": 1},
        ))
        report = a.to_report(result)
        assert "test skill" in report.lower() or "A test skill" in report
