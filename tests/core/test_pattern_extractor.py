"""Tests for PatternExtractor."""
import math

from evolution.core.pattern_extractor import PatternExtractor, PatternReport


def _make_failure(skill="test-skill", error_type="tool_error", input_len=20, msg="fail"):
    return {
        "skill_name": skill,
        "task_input": "x" * input_len,
        "error_type": error_type,
        "error_message": msg,
    }


def test_empty_failures():
    r = PatternExtractor().extract_patterns([])
    assert r.total_patterns == 0
    assert r.common_keywords == []
    assert r.error_distribution == {}


def test_error_distribution():
    failures = [
        _make_failure(error_type="tool_error"),
        _make_failure(error_type="tool_error"),
        _make_failure(error_type="timeout"),
    ]
    dist = PatternExtractor().get_error_distribution(failures)
    assert dist == {"tool_error": 2, "timeout": 1}


def test_common_keywords():
    failures = [
        _make_failure(input_len=0),  # "task_input" overridden below
        _make_failure(input_len=0),
    ]
    failures[0]["task_input"] = "deploy docker container"
    failures[1]["task_input"] = "deploy kubernetes pod"
    kw = PatternExtractor().get_common_keywords(failures)
    kw_dict = dict(kw)
    assert kw_dict["deploy"] == 2


def test_correlation():
    # Longer inputs first → positive correlation with index
    failures = [_make_failure(input_len=100), _make_failure(input_len=10)]
    corr = PatternExtractor().get_correlation(failures)
    assert corr["correlation"] < 0  # index 0 has long, index 1 has short
    assert corr["avg_input_length"] == 55.0


def test_per_skill_patterns():
    failures = [
        _make_failure(skill="a", error_type="tool_error", msg="bad tool"),
        _make_failure(skill="a", error_type="timeout"),
        _make_failure(skill="b", error_type="tool_error"),
    ]
    per = PatternExtractor()._get_per_skill(failures)
    assert set(per) == {"a", "b"}
    assert len(per["a"]) == 2
    assert len(per["b"]) == 1


def test_full_extract_patterns():
    failures = [_make_failure(error_type="tool_error") for _ in range(5)]
    failures += [_make_failure(error_type="timeout") for _ in range(2)]
    report = PatternExtractor().extract_patterns(failures)
    assert isinstance(report, PatternReport)
    assert report.total_patterns > 0
    assert len(report.recommendations) > 0
    assert report.avg_input_length == 20.0


def test_recommendations_dominant_error():
    failures = [_make_failure(error_type="timeout") for _ in range(10)]
    report = PatternExtractor().extract_patterns(failures)
    assert any("timeout" in r for r in report.recommendations)


def test_recommendations_long_inputs():
    # Long inputs at high indices → positive correlation
    failures = [_make_failure(input_len=10) for _ in range(5)]
    failures += [_make_failure(input_len=200) for _ in range(5)]
    report = PatternExtractor().extract_patterns(failures)
    # Should mention correlation since it's > 0.3
    assert any("correlation" in r.lower() for r in report.recommendations)
