"""Benchmark evaluator for skill quality.

Runs skills against test tasks and measures:
- Task completion accuracy
- Response quality (LLM-as-judge)
- Constraint compliance
- Comparison baseline vs evolved
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import dspy
from rich.console import Console
from rich.table import Table

from evolution.core.config import EvolutionConfig
from evolution.core.fitness import LLMJudge, FitnessScore
from evolution.core.constraints import ConstraintValidator

console = Console()


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    skill_name: str
    version_number: int
    score: float
    accuracy: float
    quality: float
    constraint_pass: bool
    num_examples: int
    details: list[dict] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.constraint_pass and self.score >= 0.5


@dataclass
class BenchmarkComparison:
    """Comparison between baseline and evolved versions."""
    baseline: BenchmarkResult
    evolved: BenchmarkResult
    improvement: float = 0.0
    verdict: str = ""  # improved | no_change | regressed

    def __post_init__(self):
        self.improvement = self.evolved.score - self.baseline.score
        if self.improvement > 0.05:
            self.verdict = "improved"
        elif self.improvement < -0.05:
            self.verdict = "regressed"
        else:
            self.verdict = "no_change"


class BenchmarkEvaluator:
    """Evaluates skill quality against a test set."""

    def __init__(self, config: Optional[EvolutionConfig] = None):
        self.config = config or EvolutionConfig()
        self.judge = LLMJudge(self.config)
        self.validator = ConstraintValidator(self.config)

    def evaluate(
        self,
        skill_name: str,
        skill_text: str,
        version_number: int,
        test_tasks: list[dict],
    ) -> BenchmarkResult:
        """Run a skill against test tasks and score it.

        Args:
            skill_name: Name of the skill
            skill_text: The skill body text (markdown, no frontmatter)
            version_number: Version being evaluated
            test_tasks: List of {"task_input": str, "expected_behavior": str}

        Returns:
            BenchmarkResult with scores and details
        """
        if not test_tasks:
            return BenchmarkResult(
                skill_name=skill_name,
                version_number=version_number,
                score=0.0,
                accuracy=0.0,
                quality=0.0,
                constraint_pass=True,
                num_examples=0,
                error="No test tasks provided",
            )

        scores = []
        details = []

        for task in test_tasks:
            task_input = task["task_input"]
            expected = task.get("expected_behavior", "")

            # Simulate skill execution using the skill module
            try:
                score = self._evaluate_single(skill_text, task_input, expected)
                scores.append(score)
                details.append({
                    "task": task_input[:100],
                    "score": score,
                })
            except Exception as e:
                scores.append(0.0)
                details.append({
                    "task": task_input[:100],
                    "score": 0.0,
                    "error": str(e),
                })

        avg_score = sum(scores) / max(1, len(scores))

        # Check constraints
        constraints = self.validator.validate_all(skill_text, "skill")
        constraint_pass = all(c.passed for c in constraints)

        return BenchmarkResult(
            skill_name=skill_name,
            version_number=version_number,
            score=avg_score,
            accuracy=avg_score,
            quality=avg_score,
            constraint_pass=constraint_pass,
            num_examples=len(test_tasks),
            details=details,
        )

    def _evaluate_single(
        self,
        skill_text: str,
        task_input: str,
        expected_behavior: str,
    ) -> float:
        """Evaluate a single task using LLM-as-judge."""
        # Use the skill module to generate a response
        from evolution.skills.skill_module import SkillModule

        module = SkillModule(skill_text)
        from evolution.core.custom_provider import configure_dspy, LLMConfig
        configure_dspy(LLMConfig.resolve(model=self.config.eval_model))

        with dspy.context(lm=lm):
            prediction = module(task_input=task_input)

        # Score with LLM judge
        fitness = self.judge.score(
            task_input=task_input,
            expected_behavior=expected_behavior,
            agent_output=prediction.output or "",
            skill_text=skill_text,
        )
        return fitness.composite

    def compare(
        self,
        skill_name: str,
        baseline_text: str,
        evolved_text: str,
        test_tasks: list[dict],
        baseline_version: int = 1,
        evolved_version: int = 2,
    ) -> BenchmarkComparison:
        """Compare baseline vs evolved skill on the same test set."""
        console.print(f"[bold]Benchmarking baseline (v{baseline_version})...[/bold]")
        baseline_result = self.evaluate(
            skill_name=skill_name,
            skill_text=baseline_text,
            version_number=baseline_version,
            test_tasks=test_tasks,
        )

        console.print(f"[bold]Benchmarking evolved (v{evolved_version})...[/bold]")
        evolved_result = self.evaluate(
            skill_name=skill_name,
            skill_text=evolved_text,
            version_number=evolved_version,
            test_tasks=test_tasks,
        )

        comparison = BenchmarkComparison(
            baseline=baseline_result,
            evolved=evolved_result,
        )

        self._print_comparison(comparison)
        return comparison

    def _print_comparison(self, comp: BenchmarkComparison):
        """Pretty-print benchmark comparison."""
        table = Table(title="Benchmark Comparison")
        table.add_column("Metric", style="bold")
        table.add_column("Baseline", justify="right")
        table.add_column("Evolved", justify="right")
        table.add_column("Delta", justify="right")

        table.add_row(
            "Score",
            f"{comp.baseline.score:.3f}",
            f"{comp.evolved.score:.3f}",
            f"{comp.improvement:+.3f}",
        )
        table.add_row(
            "Constraints",
            "✓" if comp.baseline.constraint_pass else "✗",
            "✓" if comp.evolved.constraint_pass else "✗",
            "",
        )
        table.add_row(
            "Examples",
            str(comp.baseline.num_examples),
            str(comp.evolved.num_examples),
            "",
        )
        table.add_row(
            "Verdict",
            "",
            "",
            f"[bold]{comp.verdict}[/bold]",
        )

        console.print()
        console.print(table)

    def load_test_tasks(self, dataset_path: Path) -> list[dict]:
        """Load test tasks from a JSONL file."""
        tasks = []
        if dataset_path.exists():
            with open(dataset_path) as f:
                for line in f:
                    if line.strip():
                        tasks.append(json.loads(line))
        return tasks
