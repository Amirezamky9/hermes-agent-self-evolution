"""CLI for hermes-agent-self-evolution.

Commands:
    evolve      Evolve a skill using DSPy + GEPA
    versions    List versions of a skill
    rollback    Rollback a skill to a previous version
    benchmark   Run benchmark on a skill
    supervisor  Run full optimization pipeline
"""

import click
from rich.console import Console
from rich.table import Table

from evolution.core.version_store import VersionStore
from evolution.core.rollback import RollbackManager
from evolution.core.benchmark import BenchmarkEvaluator
from evolution.core.supervisor import Supervisor, SupervisorConfig

console = Console()


@click.group()
def cli():
    """Hermes Agent Self-Evolution — evolutionary skill optimization."""
    pass


# ── evolve (existing, re-exported) ──────────────────────────────────
@cli.command()
@click.option("--skill", required=True, help="Name of the skill to evolve")
@click.option("--iterations", default=10, help="Number of GEPA iterations")
@click.option("--eval-source", default="synthetic",
              type=click.Choice(["synthetic", "golden", "sessiondb"]),
              help="Source for evaluation dataset")
@click.option("--dataset-path", default=None, help="Path to eval dataset (JSONL)")
@click.option("--optimizer-model", default="openai/gpt-4.1", help="Model for GEPA reflections")
@click.option("--eval-model", default="openai/gpt-4.1-mini", help="Model for evaluations")
@click.option("--hermes-repo", default=None, help="Path to hermes-agent repo")
@click.option("--run-tests", is_flag=True, help="Run pytest as constraint gate")
@click.option("--dry-run", is_flag=True, help="Validate setup only")
def evolve(skill, iterations, eval_source, dataset_path, optimizer_model,
           eval_model, hermes_repo, run_tests, dry_run):
    """Evolve a Hermes Agent skill using DSPy + GEPA optimization."""
    from evolution.skills.evolve_skill import evolve as do_evolve
    do_evolve(
        skill_name=skill,
        iterations=iterations,
        eval_source=eval_source,
        dataset_path=dataset_path,
        optimizer_model=optimizer_model,
        eval_model=eval_model,
        hermes_repo=hermes_repo,
        run_tests=run_tests,
        dry_run=dry_run,
    )


# ── versions ────────────────────────────────────────────────────────
@cli.command()
@click.argument("skill_name")
@click.option("--db", default=None, help="Path to version database")
def versions(skill_name, db):
    """List all versions of a skill."""
    store = VersionStore(db)
    version_list = store.list_versions(skill_name)

    if not version_list:
        console.print(f"[yellow]No versions found for '{skill_name}'[/yellow]")
        return

    table = Table(title=f"Versions — {skill_name}")
    table.add_column("Ver #", justify="right", style="bold")
    table.add_column("ID", justify="right")
    table.add_column("Source")
    table.add_column("Score")
    table.add_column("Constraints")
    table.add_column("Created")
    table.add_column("Notes")

    for v in version_list:
        score = v.metrics.get("evolved_score", v.metrics.get("baseline_score", ""))
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
        table.add_row(
            str(v.version_number),
            str(v.version_id),
            v.source,
            score_str,
            "✓" if v.constraints_passed else "✗",
            v.created_at[:19] if v.created_at else "—",
            v.notes[:40] if v.notes else "—",
        )

    console.print(table)


# ── rollback ────────────────────────────────────────────────────────
@cli.command()
@click.argument("skill_name")
@click.option("--to", "target_version", required=True, type=int,
              help="Version number to rollback to")
@click.option("--db", default=None, help="Path to version database")
@click.option("--force", is_flag=True, help="Skip constraint validation on target")
def rollback(skill_name, target_version, db, force):
    """Rollback a skill to a previous version."""
    store = VersionStore(db)
    mgr = RollbackManager(store)

    result = mgr.rollback_to_version(
        skill_name,
        target_version_number=target_version,
        validate=not force,
    )

    if result.success:
        console.print(f"[green]✓ {result.message}[/green]")
        console.print(f"  New version ID: {result.new_version_id}")
    else:
        console.print(f"[red]✗ {result.message}[/red]")
        raise SystemExit(1)


# ── benchmark ───────────────────────────────────────────────────────
@cli.command()
@click.argument("skill_name")
@click.option("--skill-file", required=True, type=click.Path(exists=True),
              help="Path to SKILL.md file")
@click.option("--dataset", required=True, type=click.Path(exists=True),
              help="Path to test tasks JSONL")
@click.option("--version", "version_number", default=1, type=int,
              help="Version number to record")
@click.option("--eval-model", default="openai/gpt-4.1-mini", help="Model for evaluation")
def benchmark(skill_name, skill_file, dataset, version_number, eval_model):
    """Run benchmark on a skill against test tasks."""
    from pathlib import Path
    import json

    from evolution.core.config import EvolutionConfig

    config = EvolutionConfig(eval_model=eval_model)
    evaluator = BenchmarkEvaluator(config)

    # Load skill
    with open(skill_file) as f:
        skill_text = f.read()

    # Strip frontmatter for body
    if skill_text.strip().startswith("---"):
        parts = skill_text.split("---", 2)
        if len(parts) >= 3:
            skill_text = parts[2].strip()

    # Load test tasks
    tasks = []
    with open(dataset) as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))

    console.print(f"[bold]Benchmarking '{skill_name}' (v{version_number})[/bold]")
    console.print(f"  {len(tasks)} test tasks")

    result = evaluator.evaluate(
        skill_name=skill_name,
        skill_text=skill_text,
        version_number=version_number,
        test_tasks=tasks,
    )

    table = Table(title=f"Benchmark — {skill_name} v{version_number}")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Score", f"{result.score:.3f}")
    table.add_row("Constraints", "✓" if result.constraint_pass else "✗")
    table.add_row("Examples", str(result.num_examples))
    table.add_row("Passed", "✓" if result.passed else "✗")

    console.print()
    console.print(table)


# ── supervisor ──────────────────────────────────────────────────────
@cli.command()
@click.argument("skill_name")
@click.option("--skill-file", required=True, type=click.Path(exists=True),
              help="Path to SKILL.md file")
@click.option("--iterations", default=10, help="Optimization iterations")
@click.option("--eval-model", default="openai/gpt-4.1-mini", help="Eval model")
@click.option("--optimizer-model", default="openai/gpt-4.1", help="Optimizer model")
@click.option("--auto-rollback/--no-auto-rollback", default=True,
              help="Auto-rollback on regression")
@click.option("--min-improvement", default=0.02,
              help="Minimum improvement to deploy (default: 0.02)")
@click.option("--hermes-repo", default=None, help="Path to hermes-agent repo")
@click.option("--dry-run", is_flag=True, help="Validate setup only")
def supervisor(skill_name, skill_file, iterations, eval_model, optimizer_model,
               auto_rollback, min_improvement, hermes_repo, dry_run):
    """Run full optimization pipeline with supervisor (versioning + benchmark + rollback)."""
    with open(skill_file) as f:
        skill_text = f.read()

    config = SupervisorConfig(
        hermes_repo=hermes_repo,
        iterations=iterations,
        optimizer_model=optimizer_model,
        eval_model=eval_model,
        auto_rollback=auto_rollback,
        min_improvement=min_improvement,
        dry_run=dry_run,
    )

    sup = Supervisor(config)
    result = sup.run(skill_name=skill_name, skill_text=skill_text)

    if result.error:
        console.print(f"\n[yellow]⚠ {result.error}[/yellow]")
    elif result.benchmark_verdict == "improved":
        console.print(f"\n[bold green]✓ Skill optimized successfully[/bold green]")
    else:
        console.print(f"\n[yellow]⚠ No improvement[/yellow]")


if __name__ == "__main__":
    cli()
