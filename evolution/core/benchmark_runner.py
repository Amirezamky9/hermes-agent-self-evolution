"""Benchmark Runner — A/B comparison of old vs new skill versions.

Runs each skill text against a set of test cases using LLM-as-judge,
scores accuracy/completeness/conciseness, and determines if the new
version is an improvement.
"""
from dataclasses import dataclass, field
from typing import Optional

import dspy

from evolution.core.config import EvolutionConfig
from evolution.core.cognitive_load import CognitiveLoadAnalyzer


def _parse_float(value) -> float:
    """Clamp a value to [0, 1]."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (ValueError, TypeError):
        return 0.5


# ── DSPy signature for scoring ──────────────────────────────────────

class _SkillScoreSignature(dspy.Signature):
    """Evaluate a skill's effectiveness for a given task.

    Score on three dimensions (0.0–1.0):
    1. accuracy — Did applying the skill produce a correct response?
    2. completeness — Does the skill cover all aspects of the task?
    3. conciseness — Is the skill appropriately concise (no bloat)?
    """
    skill_text: str = dspy.InputField(desc="The skill instructions")
    task_input: str = dspy.InputField(desc="The task given to the agent")
    expected_behavior: str = dspy.InputField(desc="Rubric for a good response")
    accuracy: float = dspy.OutputField(desc="0.0–1.0 accuracy score")
    completeness: float = dspy.OutputField(desc="0.0–1.0 completeness score")
    conciseness: float = dspy.OutputField(desc="0.0–1.0 conciseness score")


# ── ScoreAdjustment ───────────────────────────────────────────────────

@dataclass
class ScoreAdjustment:
    """Adjusted score after applying cognitive load penalty."""
    raw_score: float = 0.0
    cognitive_load: float = 0.0
    penalty: float = 0.0
    adjusted_score: float = 0.0


# ── BenchmarkResult ──────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Result of an A/B benchmark comparing old vs new skill."""
    old_score: float
    new_score: float
    improvement: float
    passed: bool  # new > old
    num_tests: int
    details: list = field(default_factory=list)
    old_adjustment: Optional[ScoreAdjustment] = None
    new_adjustment: Optional[ScoreAdjustment] = None
    old_adjusted_score: float = 0.0
    new_adjusted_score: float = 0.0
    passed_adjusted: bool = False  # new_adjusted > old_adjusted


# ── BenchmarkRunner ──────────────────────────────────────────────────

class BenchmarkRunner:
    """Compares old and new skill texts across test cases via LLM-as-judge."""

    def __init__(self, config: Optional[EvolutionConfig] = None):
        self.config = config or EvolutionConfig()
        self._judge = dspy.Predict(_SkillScoreSignature)

    def score_single(
        self, skill_text: str, task_input: str, expected_behavior: str,
    ) -> dict:
        """Score one skill against one test case.

        Returns dict with keys: accuracy, completeness, conciseness, score.
        """
        from evolution.core.custom_provider import configure_dspy, LLMConfig
        cfg = LLMConfig.resolve(model=self.config.eval_model)
        configure_dspy(cfg)

        result = self._judge(
            skill_text=skill_text,
            task_input=task_input,
            expected_behavior=expected_behavior,
        )

        accuracy = _parse_float(result.accuracy)
        completeness = _parse_float(result.completeness)
        conciseness = _parse_float(result.conciseness)
        # Weighted composite: accuracy matters most
        score = 0.45 * accuracy + 0.35 * completeness + 0.20 * conciseness

        return {
            "accuracy": accuracy,
            "completeness": completeness,
            "conciseness": conciseness,
            "score": score,
        }

    def compare(
        self, old_scores: list[dict], new_scores: list[dict],
    ) -> dict:
        """Compare two sets of per-test scores.

        Returns dict with: improvement, passed, old_avg, new_avg.
        """
        if not old_scores and not new_scores:
            return {"improvement": 0.0, "passed": False, "old_avg": 0.0, "new_avg": 0.0}

        old_avg = sum(s["score"] for s in old_scores) / max(1, len(old_scores))
        new_avg = sum(s["score"] for s in new_scores) / max(1, len(new_scores))
        improvement = new_avg - old_avg

        return {
            "improvement": improvement,
            "passed": new_avg > old_avg,
            "old_avg": old_avg,
            "new_avg": new_avg,
        }

    def run_benchmark(
        self,
        old_skill: str,
        new_skill: str,
        test_cases: list[dict],
    ) -> BenchmarkResult:
        """Run both skills against all test cases and compare.

        Args:
            old_skill: Text of the old skill.
            new_skill: Text of the new skill.
            test_cases: List of dicts with 'task_input' and 'expected_behavior'.

        Returns:
            BenchmarkResult with old_score, new_score, improvement, passed,
            num_tests, details.
        """
        if not test_cases:
            return BenchmarkResult(
                old_score=0.0,
                new_score=0.0,
                improvement=0.0,
                passed=False,
                num_tests=0,
                details=[],
            )

        old_scores = []
        new_scores = []
        details = []

        for i, tc in enumerate(test_cases):
            task_input = tc["task_input"]
            expected = tc.get("expected_behavior", "")

            try:
                old_s = self.score_single(old_skill, task_input, expected)
            except Exception as e:
                old_s = {"accuracy": 0.0, "completeness": 0.0, "conciseness": 0.0, "score": 0.0, "error": str(e)}

            try:
                new_s = self.score_single(new_skill, task_input, expected)
            except Exception as e:
                new_s = {"accuracy": 0.0, "completeness": 0.0, "conciseness": 0.0, "score": 0.0, "error": str(e)}

            old_scores.append(old_s)
            new_scores.append(new_s)
            details.append({
                "test_index": i,
                "task_input": task_input[:100],
                "old_score": old_s["score"],
                "new_score": new_s["score"],
            })

        cmp = self.compare(old_scores, new_scores)

        # ── Cognitive load penalty (Phase E) ────────────────────────
        analyzer = CognitiveLoadAnalyzer()
        old_cl = analyzer.analyze(old_skill)
        new_cl = analyzer.analyze(new_skill)
        old_adjustment = ScoreAdjustment(
            raw_score=cmp["old_avg"],
            cognitive_load=old_cl.total_score,
            penalty=old_cl.penalty,
            adjusted_score=cmp["old_avg"] * (1.0 - old_cl.penalty),
        )
        new_adjustment = ScoreAdjustment(
            raw_score=cmp["new_avg"],
            cognitive_load=new_cl.total_score,
            penalty=new_cl.penalty,
            adjusted_score=cmp["new_avg"] * (1.0 - new_cl.penalty),
        )

        return BenchmarkResult(
            old_score=cmp["old_avg"],
            new_score=cmp["new_avg"],
            improvement=cmp["improvement"],
            passed=cmp["passed"],
            num_tests=len(test_cases),
            details=details,
            old_adjustment=old_adjustment,
            new_adjustment=new_adjustment,
            old_adjusted_score=old_adjustment.adjusted_score,
            new_adjusted_score=new_adjustment.adjusted_score,
            passed_adjusted=new_adjustment.adjusted_score > old_adjustment.adjusted_score,
        )
