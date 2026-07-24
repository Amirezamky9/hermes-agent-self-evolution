"""Self-Evolving Loop — PromptWizard-inspired self-improvement cycle.

Inspired by Microsoft's PromptWizard (3.9K stars): the LLM critiques its
own skill output and iteratively improves it.

Flow per iteration:
1. Score skill against test cases (BenchmarkRunner.score_single)
2. Ask LLM to critique failures
3. Ask LLM to generate improved skill
4. A/B benchmark old vs new
5. Keep the better version; repeat until convergence or max_iterations
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

import dspy

from evolution.core.config import EvolutionConfig
from evolution.core.benchmark_runner import BenchmarkRunner
from evolution.core.custom_provider import configure_dspy, LLMConfig

logger = logging.getLogger(__name__)


# ── YAML frontmatter helpers ────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n?", re.DOTALL)


def _strip_frontmatter(text: str) -> tuple[str, str]:
    """Return (body, frontmatter). frontmatter is empty string if absent."""
    m = _FRONTMATTER_RE.match(text)
    if m:
        return text[m.end():], m.group(1)
    return text, ""


def _attach_frontmatter(body: str, frontmatter: str) -> str:
    if frontmatter:
        return f"---\n{frontmatter}---\n{body}"
    return body


# ── DSPy signatures ────────────────────────────────────────────────

class _CritiqueSignature(dspy.Signature):
    """Given a skill and its test results, explain where and why it failed."""
    skill_text: str = dspy.InputField(desc="The skill instructions being evaluated")
    test_results: str = dspy.InputField(desc="JSON-encoded test case results with scores")
    critique: str = dspy.OutputField(desc="Specific analysis of failures and root causes")


class _ImproveSignature(dspy.Signature):
    """Given a skill and a critique, produce an improved version."""
    skill_text: str = dspy.InputField(desc="The current skill instructions")
    critique: str = dspy.OutputField(desc="The critique explaining what needs to change")
    improved_skill: str = dspy.OutputField(desc="The improved skill text")


# ── EvolveResult ────────────────────────────────────────────────────

@dataclass
class EvolveResult:
    """Outcome of a self-evolution loop."""
    original_text: str
    final_text: str
    original_score: float
    final_score: float
    improvement: float
    iterations: int
    converged: bool
    history: list[dict] = field(default_factory=list)


# ── SelfEvolver ─────────────────────────────────────────────────────

class SelfEvolver:
    """Iteratively critiques and improves a skill against test cases.

    Uses BenchmarkRunner.score_single for scoring and dspy.Predict for
    LLM calls (critique + improvement generation).
    """

    def __init__(self, config: Optional[EvolutionConfig] = None):
        self.config = config or EvolutionConfig()
        self._runner = BenchmarkRunner(self.config)
        self._critique_predictor = dspy.Predict(_CritiqueSignature)
        self._improve_predictor = dspy.Predict(_ImproveSignature)
        self._converge_threshold: float = 0.02  # stop if improvement < this

    def evolve(
        self,
        skill_text: str,
        test_cases: list[dict],
        max_iterations: int = 3,
    ) -> EvolveResult:
        """Run the self-evolving loop.

        Args:
            skill_text: Full skill text (may include YAML frontmatter).
            test_cases: List of {"task_input": str, "expected_behavior": str}.
            max_iterations: Max critique→improve→benchmark cycles (default 3).

        Returns:
            EvolveResult with best version found.
        """
        if not test_cases:
            return EvolveResult(
                original_text=skill_text,
                final_text=skill_text,
                original_score=0.0,
                final_score=0.0,
                improvement=0.0,
                iterations=0,
                converged=False,
                history=[],
            )

        # Configure DSPy for LLM calls — resolve provider from hermes config
        cfg = LLMConfig.resolve(model=self.config.eval_model)
        configure_dspy(cfg)

        # Separate frontmatter from body for LLM processing
        body, frontmatter = _strip_frontmatter(skill_text)

        current_text = body
        current_score = self._avg_score(current_text, test_cases)
        original_score = current_score

        history: list[dict] = []

        for iteration in range(1, max_iterations + 1):
            # Step 1: Score and collect per-test details
            test_results = self._score_details(current_text, test_cases)

            # Step 2: Critique
            critique = self._critique(current_text, test_results)
            logger.info(f"Iteration {iteration}: critique obtained ({len(critique)} chars)")

            # Step 3: Generate improvement
            improved_body = self._generate_improvement(current_text, critique)
            logger.info(f"Iteration {iteration}: improvement generated ({len(improved_body)} chars)")

            # Step 4: A/B benchmark
            new_score = self._avg_score(improved_body, test_cases)
            improvement = new_score - current_score

            # Step 5: Keep the better version
            if new_score > current_score:
                current_text = improved_body
                current_score = new_score
                action = "accepted"
            else:
                action = "rejected"

            history.append({
                "iteration": iteration,
                "score": current_score,
                "new_score_tested": new_score,
                "improvement": improvement,
                "critique": critique[:500],  # truncate for storage
                "action": action,
            })

            logger.info(
                f"Iteration {iteration}: score={current_score:.4f} "
                f"(tested {new_score:.4f}), action={action}"
            )

            # Convergence check
            if self._check_convergence(
                [h["score"] for h in history],
                current_score,
            ):
                logger.info(f"Converged at iteration {iteration}")
                return EvolveResult(
                    original_text=skill_text,
                    final_text=_attach_frontmatter(current_text, frontmatter),
                    original_score=original_score,
                    final_score=current_score,
                    improvement=current_score - original_score,
                    iterations=iteration,
                    converged=True,
                    history=history,
                )

        return EvolveResult(
            original_text=skill_text,
            final_text=_attach_frontmatter(current_text, frontmatter),
            original_score=original_score,
            final_score=current_score,
            improvement=current_score - original_score,
            iterations=max_iterations,
            converged=False,
            history=history,
        )

    def _critique(self, skill_text: str, test_results: list[dict]) -> str:
        """Ask LLM to critique the skill based on test results."""
        import json
        results_str = json.dumps(test_results, indent=2, default=str)
        result = self._critique_predictor(
            skill_text=skill_text,
            test_results=results_str,
        )
        return result.critique

    def _generate_improvement(self, skill_text: str, critique: str) -> str:
        """Ask LLM to produce an improved skill based on the critique."""
        result = self._improve_predictor(
            skill_text=skill_text,
            critique=critique,
        )
        return result.improved_skill

    def _check_convergence(self, history: list[float], current_score: float) -> bool:
        """Stop if the last two scores differ by less than threshold."""
        if len(history) < 2:
            return False
        return abs(history[-1] - history[-2]) < self._converge_threshold

    def _avg_score(self, skill_text: str, test_cases: list[dict]) -> float:
        """Score skill_text against all test cases and return average."""
        scores = []
        for tc in test_cases:
            try:
                result = self._runner.score_single(
                    skill_text=skill_text,
                    task_input=tc["task_input"],
                    expected_behavior=tc.get("expected_behavior", ""),
                )
                scores.append(result["score"])
            except Exception as e:
                logger.warning(f"Score failed for test: {e}")
                scores.append(0.0)
        return sum(scores) / max(1, len(scores))

    def _score_details(self, skill_text: str, test_cases: list[dict]) -> list[dict]:
        """Score each test case and return detailed results."""
        results = []
        for i, tc in enumerate(test_cases):
            try:
                score_result = self._runner.score_single(
                    skill_text=skill_text,
                    task_input=tc["task_input"],
                    expected_behavior=tc.get("expected_behavior", ""),
                )
                results.append({
                    "index": i,
                    "task_input": tc["task_input"],
                    "expected_behavior": tc.get("expected_behavior", ""),
                    "score": score_result["score"],
                    "accuracy": score_result["accuracy"],
                    "completeness": score_result["completeness"],
                    "conciseness": score_result["conciseness"],
                })
            except Exception as e:
                results.append({
                    "index": i,
                    "task_input": tc["task_input"],
                    "error": str(e),
                    "score": 0.0,
                })
        return results
