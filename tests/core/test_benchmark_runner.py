"""Tests for benchmark_runner — mock LLM, no real API calls."""
import pytest
from unittest.mock import MagicMock, patch

from evolution.core.benchmark_runner import (
    BenchmarkRunner,
    BenchmarkResult,
    _parse_float,
)


# ── _parse_float ─────────────────────────────────────────────────────

class TestParseFloat:
    def test_float_passthrough(self):
        assert _parse_float(0.7) == 0.7

    def test_string_number(self):
        assert _parse_float("0.3") == 0.3

    def test_clamp_above_one(self):
        assert _parse_float(1.5) == 1.0

    def test_clamp_below_zero(self):
        assert _parse_float(-0.2) == 0.0

    def test_unparseable_returns_default(self):
        assert _parse_float("garbage") == 0.5

    def test_none_returns_default(self):
        assert _parse_float(None) == 0.5


# ── BenchmarkResult ──────────────────────────────────────────────────

class TestBenchmarkResult:
    def test_fields(self):
        r = BenchmarkResult(
            old_score=0.5, new_score=0.7, improvement=0.2,
            passed=True, num_tests=3, details=[],
        )
        assert r.old_score == 0.5
        assert r.new_score == 0.7
        assert r.improvement == 0.2
        assert r.passed is True
        assert r.num_tests == 3
        assert r.details == []

    def test_default_details(self):
        r = BenchmarkResult(
            old_score=0.0, new_score=0.0, improvement=0.0,
            passed=False, num_tests=0,
        )
        assert r.details == []


# ── Helpers ──────────────────────────────────────────────────────────

def _make_judge_result(accuracy=0.8, completeness=0.7, conciseness=0.6):
    """Build a mock result object that mimics DSPy Predict output."""
    m = MagicMock()
    m.accuracy = str(accuracy)
    m.completeness = str(completeness)
    m.conciseness = str(conciseness)
    return m


SAMPLE_SKILL_OLD = "Old skill text — do things the old way."
SAMPLE_SKILL_NEW = "New skill text — do things the new and improved way."
SAMPLE_TESTS = [
    {"task_input": "Run a workflow", "expected_behavior": "Workflow runs successfully"},
    {"task_input": "Deploy an app", "expected_behavior": "App is deployed to production"},
]


# ── score_single ─────────────────────────────────────────────────────

@patch("evolution.core.custom_provider.configure_dspy")
class TestScoreSingle:
    def test_returns_expected_keys(self, _mock_configure):
        runner = BenchmarkRunner()
        runner._judge = MagicMock(return_value=_make_judge_result(0.9, 0.8, 0.7))

        result = runner.score_single(SAMPLE_SKILL_OLD, "task", "expected")

        assert set(result.keys()) == {"accuracy", "completeness", "conciseness", "score"}
        assert 0.0 <= result["accuracy"] <= 1.0
        assert 0.0 <= result["score"] <= 1.0

    def test_score_weighted_composite(self, _mock_configure):
        runner = BenchmarkRunner()
        runner._judge = MagicMock(return_value=_make_judge_result(1.0, 0.0, 0.0))

        result = runner.score_single(SAMPLE_SKILL_OLD, "task", "expected")
        # score = 0.45*1.0 + 0.35*0.0 + 0.20*0.0 = 0.45
        assert result["score"] == pytest.approx(0.45)

    def test_all_dimensions_present(self, _mock_configure):
        runner = BenchmarkRunner()
        runner._judge = MagicMock(return_value=_make_judge_result(0.5, 0.6, 0.7))

        result = runner.score_single(SAMPLE_SKILL_OLD, "task", "expected")
        assert result["accuracy"] == pytest.approx(0.5)
        assert result["completeness"] == pytest.approx(0.6)
        assert result["conciseness"] == pytest.approx(0.7)
        assert result["score"] == pytest.approx(0.45 * 0.5 + 0.35 * 0.6 + 0.20 * 0.7)


# ── compare ──────────────────────────────────────────────────────────

class TestCompare:
    def test_improvement_positive(self):
        runner = BenchmarkRunner()
        old = [{"score": 0.5}, {"score": 0.4}]
        new = [{"score": 0.7}, {"score": 0.6}]
        result = runner.compare(old, new)
        assert result["passed"] is True
        assert result["improvement"] == pytest.approx(0.2)
        assert result["old_avg"] == pytest.approx(0.45)
        assert result["new_avg"] == pytest.approx(0.65)

    def test_improvement_negative(self):
        runner = BenchmarkRunner()
        old = [{"score": 0.8}]
        new = [{"score": 0.6}]
        result = runner.compare(old, new)
        assert result["passed"] is False
        assert result["improvement"] == pytest.approx(-0.2)

    def test_equal_scores(self):
        runner = BenchmarkRunner()
        old = [{"score": 0.5}, {"score": 0.5}]
        new = [{"score": 0.5}, {"score": 0.5}]
        result = runner.compare(old, new)
        assert result["passed"] is False  # new > old, not >=
        assert result["improvement"] == pytest.approx(0.0)

    def test_empty_scores(self):
        runner = BenchmarkRunner()
        result = runner.compare([], [])
        assert result["old_avg"] == 0.0
        assert result["new_avg"] == 0.0
        assert result["passed"] is False


# ── run_benchmark ────────────────────────────────────────────────────

class TestRunBenchmark:
    def test_empty_test_cases(self):
        runner = BenchmarkRunner()
        result = runner.run_benchmark("old", "new", [])
        assert result.num_tests == 0
        assert result.passed is False
        assert result.old_score == 0.0
        assert result.new_score == 0.0
        assert result.details == []

    def test_identical_skills_same_scores(self):
        """When old and new are identical, scores should be equal, passed=False."""
        runner = BenchmarkRunner()
        runner.score_single = MagicMock(
            return_value={"accuracy": 0.7, "completeness": 0.7, "conciseness": 0.7, "score": 0.7}
        )

        result = runner.run_benchmark(SAMPLE_SKILL_OLD, SAMPLE_SKILL_OLD, SAMPLE_TESTS)

        assert result.num_tests == len(SAMPLE_TESTS)
        assert result.old_score == pytest.approx(result.new_score)
        assert result.passed is False  # not strictly greater
        assert len(result.details) == len(SAMPLE_TESTS)

    def test_new_better_than_old(self):
        runner = BenchmarkRunner()
        old_score = {"accuracy": 0.5, "completeness": 0.5, "conciseness": 0.5, "score": 0.5}
        new_score = {"accuracy": 0.9, "completeness": 0.9, "conciseness": 0.9, "score": 0.9}

        call_count = 0

        def fake_score(skill_text, task_input, expected_behavior):
            nonlocal call_count
            call_count += 1
            # Odd calls = old skill (1, 3), even = new (2, 4)
            return old_score if call_count % 2 == 1 else new_score

        runner.score_single = MagicMock(side_effect=fake_score)
        result = runner.run_benchmark(SAMPLE_SKILL_OLD, SAMPLE_SKILL_NEW, SAMPLE_TESTS)

        assert result.passed is True
        assert result.new_score > result.old_score
        assert result.improvement > 0

    def test_details_populated(self):
        runner = BenchmarkRunner()
        runner.score_single = MagicMock(
            return_value={"accuracy": 0.6, "completeness": 0.6, "conciseness": 0.6, "score": 0.6}
        )

        result = runner.run_benchmark(SAMPLE_SKILL_OLD, SAMPLE_SKILL_NEW, SAMPLE_TESTS)

        assert len(result.details) == 2
        for d in result.details:
            assert "test_index" in d
            assert "task_input" in d
            assert "old_score" in d
            assert "new_score" in d

    def test_exception_in_scoring_gracefully_handled(self):
        runner = BenchmarkRunner()
        call_count = 0

        def fake_score(skill_text, task_input, expected_behavior):
            nonlocal call_count
            call_count += 1
            # First call (old skill, test 0) raises
            if call_count == 1:
                raise RuntimeError("LLM timeout")
            return {"accuracy": 0.8, "completeness": 0.8, "conciseness": 0.8, "score": 0.8}

        runner.score_single = MagicMock(side_effect=fake_score)

        result = runner.run_benchmark("old", "new", SAMPLE_TESTS)
        # First test: old scores 0.0 (error), new scores 0.8
        # Second test: both score 0.8
        assert result.num_tests == 2
        assert result.old_score < result.new_score

    def test_returns_benchmark_result_type(self):
        runner = BenchmarkRunner()
        runner.score_single = MagicMock(
            return_value={"accuracy": 0.5, "completeness": 0.5, "conciseness": 0.5, "score": 0.5}
        )
        result = runner.run_benchmark("old", "new", SAMPLE_TESTS)
        assert isinstance(result, BenchmarkResult)
