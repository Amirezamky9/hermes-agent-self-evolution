"""Supervisor workflow for auto skill optimization.

Orchestrates the full optimization loop:
1. Load skill
2. Build eval dataset
3. Run optimization (GEPA/MIPROv2)
4. Benchmark before/after
5. Version the result
6. Rollback if regressed

Can run standalone or be called from a subagent.
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from evolution.core.config import EvolutionConfig, resolve_hermes_agent_path
from evolution.core.version_store import VersionStore, SkillVersion
from evolution.core.rollback import RollbackManager
from evolution.core.benchmark import BenchmarkEvaluator, BenchmarkComparison
from evolution.core.constraints import ConstraintValidator
from evolution.core.dataset_builder import SyntheticDatasetBuilder, EvalDataset

console = Console()


@dataclass
class OptimizationRun:
    """Record of a single optimization run."""
    skill_name: str
    start_time: str = ""
    end_time: str = ""
    iterations: int = 0
    baseline_score: float = 0.0
    evolved_score: float = 0.0
    improvement: float = 0.0
    benchmark_verdict: str = ""  # improved | no_change | regressed
    rollback_triggered: bool = False
    version_id: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "iterations": self.iterations,
            "baseline_score": self.baseline_score,
            "evolved_score": self.evolved_score,
            "improvement": self.improvement,
            "benchmark_verdict": self.benchmark_verdict,
            "rollback_triggered": self.rollback_triggered,
            "version_id": self.version_id,
            "error": self.error,
        }


@dataclass
class SupervisorConfig:
    """Configuration for the supervisor workflow."""
    hermes_repo: Optional[str] = None
    iterations: int = 10
    optimizer_model: str = "openai/gpt-4.1"
    eval_model: str = "openai/gpt-4.1-mini"
    eval_source: str = "synthetic"
    dataset_path: Optional[str] = None
    auto_rollback: bool = True  # rollback if benchmark regresses
    min_improvement: float = 0.02  # minimum improvement to deploy (2%)
    db_path: Optional[Path] = None
    dry_run: bool = False
    run_tests: bool = False


class Supervisor:
    """Orchestrates the full skill optimization pipeline.

    Designed to be called from a subagent or CLI. Handles:
    - Version tracking
    - Benchmark gating
    - Automatic rollback on regression
    - Full audit trail
    """

    def __init__(self, config: SupervisorConfig):
        self.config = config
        self.evolution_config = EvolutionConfig(
            hermes_agent_path=resolve_hermes_agent_path(config.hermes_repo),
            iterations=config.iterations,
            optimizer_model=config.optimizer_model,
            eval_model=config.eval_model,
            run_pytest=config.run_tests,
        )
        self.store = VersionStore(config.db_path)
        self.rollback_mgr = RollbackManager(self.store)
        self.benchmark = BenchmarkEvaluator(self.evolution_config)
        self.validator = ConstraintValidator(self.evolution_config)

    def run(
        self,
        skill_name: str,
        skill_text: str,
    ) -> OptimizationRun:
        """Run the full optimization pipeline for a skill.

        Args:
            skill_name: Name of the skill to optimize
            skill_text: Current SKILL.md content (full file)

        Returns:
            OptimizationRun with results
        """
        run = OptimizationRun(
            skill_name=skill_name,
            start_time=datetime.now(timezone.utc).isoformat(),
            iterations=self.config.iterations,
        )

        try:
            # 1. Record baseline version
            existing = self.store.get_latest(skill_name)
            if existing:
                baseline_version_id = existing.version_id
                baseline_version_num = existing.version_number
                current_text = existing.skill_text
            else:
                baseline_version_id = self.store.record_baseline(skill_name, skill_text)
                baseline_version_num = 1
                current_text = skill_text

            # 2. Extract skill body (strip frontmatter for optimization)
            from evolution.skills.skill_module import load_skill
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write(skill_text)
                f.flush()
                skill_data = load_skill(Path(f.name))

            skill_body = skill_data["body"]
            frontmatter = skill_data["frontmatter"]

            # 3. Build evaluation dataset
            console.print(f"\n[bold cyan]🤖 Supervisor: Optimizing '{skill_name}'[/bold cyan]\n")

            if self.config.dry_run:
                console.print("[yellow]DRY RUN — would optimize and benchmark[/yellow]")
                run.end_time = datetime.now(timezone.utc).isoformat()
                return run

            # 4. Build eval dataset
            console.print("[bold]Step 1: Building evaluation dataset[/bold]")
            if self.config.dataset_path:
                dataset = EvalDataset.load(Path(self.config.dataset_path))
            else:
                builder = SyntheticDatasetBuilder(self.evolution_config)
                dataset = builder.generate(
                    artifact_text=skill_body,
                    artifact_type="skill",
                )
            console.print(f"  {len(dataset.all_examples)} examples "
                          f"({len(dataset.train)} train / {len(dataset.val)} val / "
                          f"{len(dataset.holdout)} holdout)")

            # 5. Run optimization
            console.print("\n[bold]Step 2: Running optimization[/bold]")
            evolved_body, optimization_metrics = self._run_optimization(
                skill_body, dataset
            )

            # 6. Validate constraints
            console.print("\n[bold]Step 3: Validating constraints[/bold]")
            constraints = self.validator.validate_all(evolved_body, "skill")
            all_pass = True
            for c in constraints:
                icon = "✓" if c.passed else "✗"
                color = "green" if c.passed else "red"
                console.print(f"  [{color}]{icon} {c.constraint_name}[/{color}]: {c.message}")
                if not c.passed:
                    all_pass = False

            if not all_pass:
                console.print("[red]✗ Constraints failed — not deploying evolved version[/red]")
                run.error = "Constraints failed"
                run.end_time = datetime.now(timezone.utc).isoformat()
                return run

            # 7. Benchmark comparison
            console.print("\n[bold]Step 4: Benchmarking[/bold]")
            test_tasks = dataset.to_dspy_examples("holdout")
            test_dicts = [
                {"task_input": ex.task_input, "expected_behavior": ex.expected_behavior}
                for ex in dataset.holdout
            ]

            comparison = self.benchmark.compare(
                skill_name=skill_name,
                baseline_text=skill_body,
                evolved_text=evolved_body,
                test_tasks=test_dicts,
                baseline_version=baseline_version_num,
                evolved_version=baseline_version_num + 1,
            )

            run.baseline_score = comparison.baseline.score
            run.evolved_score = comparison.evolved.score
            run.improvement = comparison.improvement
            run.benchmark_verdict = comparison.verdict

            # 8. Decide: deploy or rollback
            if comparison.verdict == "improved":
                # Check minimum improvement threshold
                if comparison.improvement >= self.config.min_improvement:
                    console.print(f"\n[bold green]✓ Improvement: {comparison.improvement:+.3f} "
                                  f"(above threshold {self.config.min_improvement})[/bold green]")

                    # Reassemble full SKILL.md
                    from evolution.skills.skill_module import reassemble_skill
                    evolved_full = reassemble_skill(frontmatter, evolved_body)

                    # Record evolved version
                    version_id = self.store.record_evolved(
                        skill_name=skill_name,
                        skill_text=evolved_full,
                        parent_version=baseline_version_id,
                        metrics=optimization_metrics,
                        constraints_passed=True,
                        notes=f"Improved by {comparison.improvement:+.3f}",
                    )
                    run.version_id = version_id
                else:
                    console.print(f"\n[yellow]⚠ Improvement {comparison.improvement:+.3f} "
                                  f"below threshold {self.config.min_improvement} — not deploying[/yellow]")
                    run.error = "Below improvement threshold"

            elif comparison.verdict == "regressed":
                console.print(f"\n[red]✗ Regression: {comparison.improvement:+.3f}[/red]")
                if self.config.auto_rollback:
                    console.print("[yellow]Auto-rollback triggered[/yellow]")
                    run.rollback_triggered = True
                    run.error = f"Regressed by {comparison.improvement:+.3f}, auto-rolled back"
                else:
                    run.error = f"Regressed by {comparison.improvement:+.3f}, no auto-rollback"

            else:  # no_change
                console.print(f"\n[yellow]⚠ No significant change: {comparison.improvement:+.3f}[/yellow]")
                run.error = "No significant improvement"

            run.end_time = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            run.error = str(e)
            run.end_time = datetime.now(timezone.utc).isoformat()
            console.print(f"\n[red]✗ Error: {e}[/red]")

        # Print summary
        self._print_summary(run)
        return run

    def _run_optimization(
        self,
        skill_body: str,
        dataset: EvalDataset,
    ) -> tuple[str, dict]:
        """Run the actual optimization. Returns (evolved_text, metrics)."""
        from evolution.skills.skill_module import SkillModule
        from evolution.core.fitness import skill_fitness_metric

        import dspy

        # Configure DSPy
        lm = dspy.LM(self.config.eval_model)
        dspy.configure(lm=lm)

        baseline_module = SkillModule(skill_body)
        trainset = dataset.to_dspy_examples("train")
        valset = dataset.to_dspy_examples("val")

        start_time = time.time()

        try:
            optimizer = dspy.GEPA(
                metric=skill_fitness_metric,
                max_steps=self.config.iterations,
            )
            optimized = optimizer.compile(
                baseline_module,
                trainset=trainset,
                valset=valset,
            )
        except Exception as e:
            console.print(f"[yellow]GEPA unavailable ({e}), using MIPROv2[/yellow]")
            optimizer = dspy.MIPROv2(
                metric=skill_fitness_metric,
                auto="light",
            )
            optimized = optimizer.compile(
                baseline_module,
                trainset=trainset,
            )

        elapsed = time.time() - start_time
        evolved_body = optimized.skill_text

        metrics = {
            "iterations": self.config.iterations,
            "elapsed_seconds": elapsed,
            "train_examples": len(trainset),
            "val_examples": len(valset),
        }

        console.print(f"  Optimization completed in {elapsed:.1f}s")
        return evolved_body, metrics

    def _print_summary(self, run: OptimizationRun):
        """Print final run summary."""
        table = Table(title=f"Supervisor Summary — {run.skill_name}")
        table.add_column("Field", style="bold")
        table.add_column("Value")

        table.add_row("Baseline Score", f"{run.baseline_score:.3f}")
        table.add_row("Evolved Score", f"{run.evolved_score:.3f}")
        table.add_row("Improvement", f"{run.improvement:+.3f}")
        table.add_row("Verdict", run.benchmark_verdict)
        table.add_row("Rollback", "Yes" if run.rollback_triggered else "No")
        table.add_row("Version ID", str(run.version_id) if run.version_id else "N/A")
        if run.error:
            table.add_row("Error", f"[red]{run.error}[/red]")
        table.add_row("Duration", f"{run.start_time} → {run.end_time}")

        console.print()
        console.print(table)

    def list_versions(self, skill_name: str) -> list[SkillVersion]:
        """List all versions for a skill."""
        return self.store.list_versions(skill_name)

    def rollback(self, skill_name: str, to_version: int):
        """Rollback a skill to a specific version."""
        result = self.rollback_mgr.rollback_to_version(skill_name, to_version)
        if result.success:
            console.print(f"[green]✓ {result.message}[/green]")
        else:
            console.print(f"[red]✗ {result.message}[/red]")
        return result
