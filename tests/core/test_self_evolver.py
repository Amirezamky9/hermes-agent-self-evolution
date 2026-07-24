"""Tests for self_evolver — mock all LLM calls, no real API."""
import json
import pytest
from unittest.mock import MagicMock, patch

from evolution.core.self_evolver import (
    SelfEvolver,
    EvolveResult,
    _strip_frontmatter,
    _attach_frontmatter,
)
from evolution.core.config import EvolutionConfig


# ── Frontmatter helpers ─────────────────────────────────────────────

class TestStripFrontmatter:
    def test_no_frontmatter(self):
        body, fm = _strip_frontmatter("# Skill\nSome content")
        assert body == "# Skill\nSome content"
        assert fm == ""

    def test_with_frontmatter(self):
        text = "---\nname: test\nversion: 1\n---\n# Skill\nContent"
        body, fm = _strip_frontmatter(text)
        assert fm == "name: test\nversion: 1\n"
        assert body == "# Skill\nContent"

    def test_multiline_frontmatter(self):
        text = "---\nname: test\ndescription: |\n  multi\n  line\n---\nBody"
        body, fm = _strip_frontmatter(text)
        assert "name: test" in fm
        assert body == "Body"


class TestAttachFrontmatter:
    def test_with_frontmatter(self):
        result = _attach_frontmatter("Body", "name: test\n")
        assert result == "---\nname: test\n---\nBody"

    def test_empty_frontmatter(self):
        result = _attach_frontmatter("Body", "")
        assert result == "Body"


# ── EvolveResult ────────────────────────────────────────────────────

class TestEvolveResult:
    def test_fields(self):
        r = EvolveResult(
            original_text="orig",
            final_text="final",
            original_score=0.5,
            final_score=0.7,
            improvement=0.2,
            iterations=2,
            converged=True,
            history=[{"iteration": 1, "score": 0.6}],
        )
        assert r.original_score == 0.5
        assert r.final_score == 0.7
        assert r.improvement == 0.2
        assert r.converged is True
        assert len(r.history) == 1

    def test_default_history(self):
        r = EvolveResult(
            original_text="", final_text="",
            original_score=0, final_score=0,
            improvement=0, iterations=0, converged=False,
        )
        assert r.history == []


# ── Mock helpers ────────────────────────────────────────────────────

def _mock_score(skill_text, task_input, expected_behavior):
    """Deterministic mock: newer skill text → higher score."""
    # Score based on whether "improved" or "v2" appears in the text
    base = 0.5
    if "improved" in skill_text.lower() or "v2" in skill_text.lower():
        base = 0.8
    if "better" in skill_text.lower():
        base = 0.9
    return {"accuracy": base, "completeness": base, "conciseness": base, "score": base}


def _make_critique_return(critique_text="The skill is missing error handling"):
    mock = MagicMock()
    mock.critique = critique_text
    return mock


def _make_improve_return(improved_text="Improved skill v2 with error handling"):
    mock = MagicMock()
    mock.improved_skill = improved_text
    return mock


SAMPLE_SKILL = "# My Skill\nDo things the old way."
SAMPLE_TESTS = [
    {"task_input": "Deploy an app", "expected_behavior": "App deployed"},
    {"task_input": "Run tests", "expected_behavior": "Tests pass"},
]
IMPROVED_SKILL = "# My Skill v2\nDo things the improved way with error handling."


# ── SelfEvolver ─────────────────────────────────────────────────────

@patch("evolution.core.self_evolver.configure_dspy")
class TestSelfEvolverEvolve:
    def test_empty_test_cases_returns_immediately(self, _mock_cfg):
        evolver = SelfEvolver()
        result = evolver.evolve("skill text", [], max_iterations=3)
        assert result.iterations == 0
        assert result.original_score == 0.0
        assert result.final_text == "skill text"
        assert result.history == []

    def test_single_iteration_accepted(self, _mock_cfg):
        """New version scores higher → accepted."""
        evolver = SelfEvolver()
        evolver._runner.score_single = MagicMock(side_effect=_mock_score)

        # Critique returns critique, improve returns text with "v2"
        evolver._critique_predictor = MagicMock(
            return_value=_make_critique_return("Needs improvement")
        )
        evolver._improve_predictor = MagicMock(
            return_value=_make_improve_return(IMPROVED_SKILL)
        )

        result = evolver.evolve(SAMPLE_SKILL, SAMPLE_TESTS, max_iterations=1)

        assert result.iterations == 1
        assert result.final_score > result.original_score
        assert result.improvement > 0
        assert len(result.history) == 1
        assert result.history[0]["action"] == "accepted"
        assert "v2" in result.final_text

    def test_rejected_version_keeps_old(self, _mock_cfg):
        """New version scores same or worse → rejected."""
        evolver = SelfEvolver()

        # Both old and new score the same (0.5) — no improvement
        static_score = {"accuracy": 0.5, "completeness": 0.5, "conciseness": 0.5, "score": 0.5}
        evolver._runner.score_single = MagicMock(return_value=static_score)
        evolver._critique_predictor = MagicMock(
            return_value=_make_critique_return("No issues found")
        )
        evolver._improve_predictor = MagicMock(
            return_value=_make_improve_return("Same skill, no real changes")
        )

        result = evolver.evolve(SAMPLE_SKILL, SAMPLE_TESTS, max_iterations=1)

        assert result.iterations == 1
        assert result.history[0]["action"] == "rejected"
        assert result.improvement == pytest.approx(0.0)
        # Final text should be unchanged (body)
        assert "v2" not in result.final_text

    def test_convergence_stops_early(self, _mock_cfg):
        """Stops when improvement < threshold."""
        evolver = SelfEvolver()
        evolver._converge_threshold = 0.05

        call_count = 0
        def progress_score(skill_text, task_input, expected_behavior):
            nonlocal call_count
            call_count += 1
            # First call: score old → 0.50
            # Then: old=0.50, new=0.53 (accepted, improvement 0.03 < 0.05)
            if call_count <= 2:  # first two: test old skill (2 test cases)
                return {"accuracy": 0.5, "completeness": 0.5, "conciseness": 0.5, "score": 0.5}
            elif call_count <= 4:  # test new skill (iteration 1)
                return {"accuracy": 0.53, "completeness": 0.53, "conciseness": 0.53, "score": 0.53}
            else:  # iteration 2: test current (which is now 0.53)
                return {"accuracy": 0.53, "completeness": 0.53, "conciseness": 0.53, "score": 0.53}

        evolver._runner.score_single = MagicMock(side_effect=progress_score)
        evolver._critique_predictor = MagicMock(
            return_value=_make_critique_return("Minor tweaks")
        )
        evolver._improve_predictor = MagicMock(
            return_value=_make_improve_return("Slightly improved skill")
        )

        result = evolver.evolve(SAMPLE_SKILL, SAMPLE_TESTS, max_iterations=3)
        # Should stop before max_iterations because convergence detected
        assert result.iterations < 3
        assert result.converged is True

    def test_max_iterations_respected(self, _mock_cfg):
        """Runs exactly max_iterations when no convergence."""
        evolver = SelfEvolver()
        evolver._converge_threshold = 0.001  # very tight, won't converge

        # Each iteration improves by a tiny bit (above threshold)
        iteration = [0]
        def improving_score(skill_text, task_input, expected_behavior):
            iteration[0] += 1
            # Steady increase: 0.5, 0.6, 0.7, 0.8, 0.9
            # But these are per-call scores, not per-iteration
            base = min(0.5 + iteration[0] * 0.05, 0.95)
            return {"accuracy": base, "completeness": base, "conciseness": base, "score": base}

        evolver._runner.score_single = MagicMock(side_effect=improving_score)
        evolver._critique_predictor = MagicMock(
            return_value=_make_critique_return("Keep improving")
        )
        evolver._improve_predictor = MagicMock(
            return_value=_make_improve_return("Better skill")
        )

        result = evolver.evolve(SAMPLE_SKILL, SAMPLE_TESTS, max_iterations=2)
        assert result.iterations == 2

    def test_frontmatter_preserved(self, _mock_cfg):
        """YAML frontmatter is stripped before LLM, reattached after."""
        skill_with_fm = "---\nname: my-skill\nversion: 1\n---\n# Skill\nDo stuff."
        evolver = SelfEvolver()
        evolver._runner.score_single = MagicMock(side_effect=_mock_score)
        evolver._critique_predictor = MagicMock(
            return_value=_make_critique_return("Needs work")
        )
        evolver._improve_predictor = MagicMock(
            return_value=_make_improve_return("# Skill v2\nDo stuff better.")
        )

        result = evolver.evolve(skill_with_fm, SAMPLE_TESTS, max_iterations=1)

        # Final text should have frontmatter reattached
        assert result.final_text.startswith("---\n")
        assert "name: my-skill" in result.final_text
        # But the LLM should have received body only (no frontmatter)
        call_args = evolver._critique_predictor.call_args
        assert "name: my-skill" not in call_args.kwargs.get("skill_text", "")

    def test_score_exception_handled(self, _mock_cfg):
        """Exceptions in scoring produce 0.0 score, not crash."""
        evolver = SelfEvolver()

        def flaky_score(skill_text, task_input, expected_behavior):
            raise RuntimeError("LLM timeout")

        evolver._runner.score_single = MagicMock(side_effect=flaky_score)
        evolver._critique_predictor = MagicMock(
            return_value=_make_critique_return("All tests failed")
        )
        evolver._improve_predictor = MagicMock(
            return_value=_make_improve_return("Fixed skill")
        )

        result = evolver.evolve(SAMPLE_SKILL, SAMPLE_TESTS, max_iterations=1)
        assert result.original_score == 0.0
        assert result.final_score == 0.0
        assert result.iterations == 1

    def test_history_contains_critique(self, _mock_cfg):
        """Each iteration records critique in history."""
        evolver = SelfEvolver()
        evolver._runner.score_single = MagicMock(side_effect=_mock_score)
        evolver._critique_predictor = MagicMock(
            return_value=_make_critique_return("Missing edge cases in deployment logic")
        )
        evolver._improve_predictor = MagicMock(
            return_value=_make_improve_return(IMPROVED_SKILL)
        )

        result = evolver.evolve(SAMPLE_SKILL, SAMPLE_TESTS, max_iterations=1)

        assert len(result.history) == 1
        h = result.history[0]
        assert "critique" in h
        assert "Missing edge cases" in h["critique"]
        assert "score" in h
        assert "action" in h


# ── _check_convergence ──────────────────────────────────────────────

class TestCheckConvergence:
    def test_not_enough_history(self):
        evolver = SelfEvolver()
        assert evolver._check_convergence([0.5], 0.5) is False

    def test_converged(self):
        evolver = SelfEvolver()
        evolver._converge_threshold = 0.05
        assert evolver._check_convergence([0.5, 0.51], 0.51) is True

    def test_not_converged(self):
        evolver = SelfEvolver()
        evolver._converge_threshold = 0.05
        assert evolver._check_convergence([0.5, 0.6], 0.6) is False

    def test_exact_threshold_not_converged(self):
        evolver = SelfEvolver()
        evolver._converge_threshold = 0.05
        # diff == threshold → NOT converged (uses <, not <=)
        assert evolver._check_convergence([0.5, 0.55], 0.55) is False
