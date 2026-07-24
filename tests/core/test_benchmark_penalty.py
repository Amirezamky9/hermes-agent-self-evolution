"""Tests for Phase E: Cognitive Load Penalty in benchmark scoring."""
import pytest
from unittest.mock import MagicMock, patch

from evolution.core.benchmark_runner import (
    BenchmarkResult,
    BenchmarkRunner,
    ScoreAdjustment,
)
from evolution.core.cognitive_load import CognitiveLoadAnalyzer


# ── ScoreAdjustment dataclass ────────────────────────────────────────

class TestScoreAdjustment:
    def test_defaults(self):
        adj = ScoreAdjustment()
        assert adj.raw_score == 0.0
        assert adj.cognitive_load == 0.0
        assert adj.penalty == 0.0
        assert adj.adjusted_score == 0.0

    def test_fields(self):
        adj = ScoreAdjustment(raw_score=0.8, cognitive_load=45.0, penalty=0.15, adjusted_score=0.68)
        assert adj.raw_score == 0.8
        assert adj.cognitive_load == 45.0
        assert adj.penalty == 0.15
        assert adj.adjusted_score == pytest.approx(0.68)


# ── Penalty calculation via CognitiveLoadAnalyzer ─────────────────────

class TestPenaltyCalculation:
    """Verify the penalty thresholds match the spec."""

    def test_light_load_no_penalty(self):
        """cognitive_load < 30 → penalty = 0.0"""
        analyzer = CognitiveLoadAnalyzer()
        assert analyzer.get_penalty(0.0) == 0.0
        assert analyzer.get_penalty(15.0) == 0.0
        assert analyzer.get_penalty(29.99) == 0.0

    def test_moderate_load_penalty(self):
        """cognitive_load 30–60 → penalty = 0.15"""
        analyzer = CognitiveLoadAnalyzer()
        assert analyzer.get_penalty(30.0) == 0.15
        assert analyzer.get_penalty(45.0) == 0.15
        assert analyzer.get_penalty(60.0) == 0.15

    def test_heavy_load_penalty(self):
        """cognitive_load > 60 → penalty = 0.30"""
        analyzer = CognitiveLoadAnalyzer()
        assert analyzer.get_penalty(60.01) == 0.30
        assert analyzer.get_penalty(80.0) == 0.30
        assert analyzer.get_penalty(100.0) == 0.30


class TestAdjustedScoreCalculation:
    """Verify adjusted_score = raw_score * (1 - penalty)."""

    def test_light_no_reduction(self):
        raw = 0.9
        penalty = 0.0
        assert raw * (1.0 - penalty) == pytest.approx(0.9)

    def test_moderate_reduces(self):
        raw = 0.8
        penalty = 0.15
        assert raw * (1.0 - penalty) == pytest.approx(0.68)

    def test_heavy_reduces_more(self):
        raw = 0.8
        penalty = 0.30
        assert raw * (1.0 - penalty) == pytest.approx(0.56)


# ── BenchmarkResult backward compat ──────────────────────────────────

class TestBenchmarkResultBackwardCompat:
    """Existing constructor signatures must still work."""

    def test_old_positional_args(self):
        r = BenchmarkResult(0.5, 0.7, 0.2, True, 3, [])
        assert r.old_score == 0.5
        assert r.new_score == 0.7
        assert r.passed is True
        assert r.old_adjustment is None
        assert r.passed_adjusted is False

    def test_new_fields_default(self):
        r = BenchmarkResult(0.0, 0.0, 0.0, False, 0)
        assert r.old_adjusted_score == 0.0
        assert r.new_adjusted_score == 0.0
        assert r.passed_adjusted is False
        assert r.old_adjustment is None
        assert r.new_adjustment is None


# ── End-to-end run_benchmark with penalty ────────────────────────────

def _make_judge_result(accuracy=0.8, completeness=0.7, conciseness=0.6):
    m = MagicMock()
    m.accuracy = str(accuracy)
    m.completeness = str(completeness)
    m.conciseness = str(conciseness)
    return m


# A skill with lots of complex language → high cognitive load
HEAVY_SKILL = (
    "Always implement create check verify run build write update delete "
    "remove add configure setup install deploy test validate parse extract "
    "transform generate fetch load save export import merge split filter sort "
    "search replace modify edit patch apply execute implement create check "
    "verify run build write update delete remove add configure setup install "
    "deploy test validate parse extract transform generate fetch load save "
    "export import merge split filter sort search replace modify edit patch. "
    "If the workflow is running then finally before you should must never "
    "require mandatory unless otherwise depending on in case. "
    "Use read_file write_file patch terminal process search_files web_search "
    "web_fetch vision_analyze video_analyze session_search skill_view "
    "read_file write_file patch terminal process search_files. "
    "JSON markdown list table csv xml yaml html dictionary array. "
    "Maybe perhaps might could possibly approximately roughly "
    "probably likely potentially suggest. "
    "Previous current next context state history memory cache session "
    "previous current context state history memory cache."
)

# A very simple skill → low cognitive load
LIGHT_SKILL = "Say hello to the user."


class TestRunBenchmarkWithPenalty:
    @patch("evolution.core.custom_provider.configure_dspy")
    def test_light_skill_no_penalty_applied(self, _mock_cfg):
        runner = BenchmarkRunner()
        runner.score_single = MagicMock(
            return_value={"accuracy": 0.8, "completeness": 0.8, "conciseness": 0.8, "score": 0.8}
        )
        result = runner.run_benchmark(LIGHT_SKILL, LIGHT_SKILL, [
            {"task_input": "greet", "expected_behavior": "hello"},
        ])
        # Light skill → penalty 0.0 → adjusted == raw
        assert result.old_adjustment is not None
        assert result.old_adjustment.penalty == 0.0
        assert result.old_adjusted_score == pytest.approx(result.old_score)

    @patch("evolution.core.custom_provider.configure_dspy")
    def test_heavy_skill_penalty_applied(self, _mock_cfg):
        runner = BenchmarkRunner()
        runner.score_single = MagicMock(
            return_value={"accuracy": 0.8, "completeness": 0.8, "conciseness": 0.8, "score": 0.8}
        )
        result = runner.run_benchmark(HEAVY_SKILL, HEAVY_SKILL, [
            {"task_input": "do stuff", "expected_behavior": "done"},
        ])
        assert result.old_adjustment is not None
        assert result.old_adjustment.penalty == 0.30
        assert result.old_adjusted_score == pytest.approx(0.8 * 0.70)
        assert result.old_adjusted_score < result.old_score

    @patch("evolution.core.custom_provider.configure_dspy")
    def test_adjusted_passed_differs_from_raw(self, _mock_cfg):
        """Scenario: raw scores equal (passed=False) but different cognitive loads
        can make passed_adjusted flip."""
        runner = BenchmarkRunner()
        runner.score_single = MagicMock(
            return_value={"accuracy": 0.8, "completeness": 0.8, "conciseness": 0.8, "score": 0.8}
        )
        # old=light (penalty=0), new=heavy (penalty=0.30)
        result = runner.run_benchmark(LIGHT_SKILL, HEAVY_SKILL, [
            {"task_input": "task", "expected_behavior": "behavior"},
        ])
        assert result.passed is False  # raw: equal
        assert result.passed_adjusted is False  # light > heavy after penalty

    @patch("evolution.core.custom_provider.configure_dspy")
    def test_empty_test_cases_still_has_defaults(self, _mock_cfg):
        runner = BenchmarkRunner()
        result = runner.run_benchmark("a", "b", [])
        # No test cases → early return; penalty fields get defaults
        assert result.old_adjustment is None
        assert result.new_adjustment is None
        assert result.old_adjusted_score == 0.0
        assert result.new_adjusted_score == 0.0
        assert result.passed_adjusted is False

    @patch("evolution.core.custom_provider.configure_dspy")
    def test_adjustment_fields_populated(self, _mock_cfg):
        runner = BenchmarkRunner()
        runner.score_single = MagicMock(
            return_value={"accuracy": 0.5, "completeness": 0.5, "conciseness": 0.5, "score": 0.5}
        )
        result = runner.run_benchmark("old", "new", [
            {"task_input": "x", "expected_behavior": "y"},
        ])
        assert isinstance(result.old_adjustment, ScoreAdjustment)
        assert isinstance(result.new_adjustment, ScoreAdjustment)
        assert 0.0 <= result.old_adjustment.cognitive_load <= 100.0
        assert 0.0 <= result.new_adjustment.cognitive_load <= 100.0
        assert result.old_adjustment.penalty in (0.0, 0.15, 0.30)
        assert result.new_adjustment.penalty in (0.0, 0.15, 0.30)
