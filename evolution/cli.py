"""CLI for hermes-agent-self-evolution.

Commands:
    optimize    Run full optimization pipeline (session/synthetic modes)
    evolve      Evolve a skill using DSPy + GEPA (MIPROv2)
    nightly     Run nightly optimization for multiple skills
    versions    List versions of a skill
    rollback    Rollback a skill to a previous version
    benchmark   Run benchmark on a skill
    supervisor  Run full optimization pipeline with supervisor
    status      Show all skills + versions + last benchmark
"""

import click
from rich.console import Console
from rich.table import Table

from evolution.core.version_store import VersionStore
from evolution.core.rollback import RollbackManager
from evolution.core.custom_provider import LLMConfig, configure_dspy

console = Console()


@click.group()
@click.option("--model", default=None, help="LLM model name (default: from Hermes config)")
@click.option("--base-url", default=None, help="LLM API base URL (default: from Hermes config)")
@click.option("--api-key", default=None, help="LLM API key (default: from Hermes config)")
@click.pass_context
def cli(ctx, model, base_url, api_key):
    """Hermes Agent Self-Evolution — evolutionary skill optimization.

    Uses Hermes Agent's current LLM provider by default.
    Override with --model, --base-url, --api-key or env vars:
        EVOLUTION_MODEL, OPENAI_API_BASE, OPENAI_API_KEY
    """
    ctx.ensure_object(dict)
    ctx.obj["llm_config"] = LLMConfig.resolve(
        model=model, base_url=base_url, api_key=api_key
    )


def _get_llm_config(ctx) -> LLMConfig:
    """Get LLM config from click context."""
    return ctx.obj.get("llm_config") or LLMConfig.resolve()


# ── evolve ───────────────────────────────────────────────────────────
@cli.command()
@click.argument("skill")
@click.option("--iterations", default=10, help="Number of GEPA iterations")
@click.option("--eval-source", default="synthetic",
              type=click.Choice(["synthetic", "golden", "sessiondb"]),
              help="Source for evaluation dataset")
@click.option("--dataset-path", default=None, help="Path to eval dataset (JSONL)")
@click.option("--hermes-repo", default=None, help="Path to hermes-agent repo")
@click.option("--run-tests", is_flag=True, help="Run pytest as constraint gate")
@click.option("--dry-run", is_flag=True, help="Validate setup only")
@click.option("--mipro-auto", type=click.Choice(["light", "medium", "heavy"]),
              default="light", help="MIPROv2 optimization mode (light=fast, heavy=best)")
@click.option("--mode", type=click.Choice(["session", "synthetic"]), default="synthetic",
              help="Optimization mode: session (Pipeline with real failures) or synthetic (GEPA/MIPROv2)")
@click.pass_context
def evolve(ctx, skill, iterations, eval_source, dataset_path,
           hermes_repo, run_tests, dry_run, mipro_auto, mode):
    """Evolve a Hermes Agent skill using DSPy + GEPA optimization."""
    from evolution.skills.evolve_skill import evolve as do_evolve
    llm = _get_llm_config(ctx)
    console.print(f"[dim]Using model: {llm.model} @ {llm.base_url}[/dim]")
    do_evolve(
        skill_name=skill,
        iterations=iterations,
        eval_source=eval_source,
        dataset_path=dataset_path,
        optimizer_model=llm.model,
        eval_model=llm.model,
        hermes_repo=hermes_repo,
        run_tests=run_tests,
        dry_run=dry_run,
        mipro_auto=mipro_auto,
        mode=mode,
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
@click.pass_context
def benchmark(ctx, skill_name, skill_file, dataset, version_number):
    """Run benchmark on a skill against test tasks."""
    from pathlib import Path
    import json

    from evolution.core.config import EvolutionConfig

    llm = _get_llm_config(ctx)
    console.print(f"[dim]Using model: {llm.model}[/dim]")

    config = EvolutionConfig(eval_model=llm.model)
    evaluator = __import__("evolution.core.benchmark", fromlist=["BenchmarkEvaluator"]).BenchmarkEvaluator(config)

    with open(skill_file) as f:
        skill_text = f.read()

    if skill_text.strip().startswith("---"):
        parts = skill_text.split("---", 2)
        if len(parts) >= 3:
            skill_text = parts[2].strip()

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


# ── nightly ─────────────────────────────────────────────────────────
@cli.command()
@click.option("--skills", required=True, help="Comma-separated skill names to optimize")
@click.pass_context
def nightly(ctx, skills):
    """Run nightly optimization for multiple skills and print a report."""
    from evolution.core.cron_runner import CronRunner

    skill_list = [s.strip() for s in skills.split(",") if s.strip()]
    if not skill_list:
        console.print("[red]No skills specified[/red]")
        raise SystemExit(1)

    cr = CronRunner(skills=skill_list)
    report = cr.run_nightly()
    console.print(report.summary)


# ── supervisor ──────────────────────────────────────────────────────
@cli.command()
@click.argument("skill_name")
@click.option("--skill-file", required=True, type=click.Path(exists=True),
              help="Path to SKILL.md file")
@click.option("--iterations", default=10, help="Optimization iterations")
@click.option("--auto-rollback/--no-auto-rollback", default=True,
              help="Auto-rollback on regression")
@click.option("--min-improvement", default=0.02,
              help="Minimum improvement to deploy (default: 0.02)")
@click.option("--hermes-repo", default=None, help="Path to hermes-agent repo")
@click.option("--dry-run", is_flag=True, help="Validate setup only")
@click.pass_context
def supervisor(ctx, skill_name, skill_file, iterations,
               auto_rollback, min_improvement, hermes_repo, dry_run):
    """Run full optimization pipeline with supervisor."""
    from evolution.core.supervisor import Supervisor, SupervisorConfig

    llm = _get_llm_config(ctx)
    console.print(f"[dim]Using model: {llm.model}[/dim]")

    with open(skill_file) as f:
        skill_text = f.read()

    config = SupervisorConfig(
        hermes_repo=hermes_repo,
        iterations=iterations,
        optimizer_model=llm.model,
        eval_model=llm.model,
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


@cli.command()
@click.argument("skill")
@click.option("--mode", type=click.Choice(["session", "synthetic", "mipro"]),
              default="session",
              help="Optimization mode: session=real failures, synthetic=dataset, mipro=MIPROv2")
@click.option("--iterations", default=10, help="Number of optimization iterations")
@click.option("--eval-source", default="synthetic",
              type=click.Choice(["synthetic", "golden", "sessiondb"]),
              help="Source for evaluation dataset")
@click.option("--hermes-repo", default=None, help="Path to hermes-agent repo")
@click.option("--run-tests", is_flag=True, help="Run pytest as constraint gate")
@click.option("--dry-run", is_flag=True, help="Validate setup only")
@click.option("--mipro-auto", type=click.Choice(["light", "medium", "heavy"]),
              default="light", help="MIPROv2 optimization mode")
@click.pass_context
def optimize(ctx, skill, mode, iterations, eval_source, hermes_repo,
             run_tests, dry_run, mipro_auto):
    """Run the full optimization pipeline for a skill.

    Modes:
        session    Uses real session failures from SessionGrazer (default)
        synthetic  Uses synthetic dataset generation
        mipro      Uses MIPROv2 optimizer (old evolve flow)
    """
    from evolution.core.full_pipeline import FullPipeline

    llm = _get_llm_config(ctx)
    console.print(f"[dim]Using model: {llm.model}[/dim]")

    if mode == "mipro":
        # Delegate to existing evolve command with MIPRO flow
        from evolution.skills.evolve_skill import evolve as do_evolve
        do_evolve(
            skill_name=skill,
            iterations=iterations,
            eval_source=eval_source,
            hermes_repo=hermes_repo,
            run_tests=run_tests,
            dry_run=dry_run,
            mipro_auto=mipro_auto,
            mode="synthetic",
        )
        return

    fp = FullPipeline()
    with console.status(f"[bold green]Optimizing '{skill}' (mode={mode})..."):
        result = fp.run(skill, mode=mode)

    if result.error:
        console.print(f"\n[yellow]⚠ {result.error}[/yellow]")
        _print_pipeline_result(result)
        raise SystemExit(1)

    console.print(f"\n[bold green]✓ Skill '{skill}' optimized[/bold green]")
    _print_pipeline_result(result)


def _print_pipeline_result(result):
    """Print a summary table for a PipelineResult."""
    table = Table(title=f"Pipeline — {result.skill_name}")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Old Score", f"{result.old_score:.3f}")
    table.add_row("New Score", f"{result.new_score:.3f}")
    table.add_row("Improvement", f"{result.improvement:+.3f}")
    table.add_row("Failures Found", str(result.failures_found))
    table.add_row("Gaps Found", str(result.gaps_found))
    table.add_row("Patches", str(result.patches_generated))
    table.add_row("Safety", "✓" if result.safety_passed else "✗")
    table.add_row("Version", result.version_created or "—")
    table.add_row("Duration", f"{result.duration_seconds:.1f}s")
    console.print(table)


@cli.command()
@click.option("--db", default=None, help="Path to version database")
def status(db):
    """Show status of all tracked skills: versions, scores, last benchmark."""
    from evolution.core.full_pipeline import FullPipeline

    fp = FullPipeline()
    sys_status = fp.status()

    if not sys_status.skills:
        console.print("[yellow]No tracked skills found.[/yellow]")
        return

    table = Table(title="Skill Status")
    table.add_column("Skill", style="bold")
    table.add_column("Version", justify="right")
    table.add_column("Source")
    table.add_column("Score", justify="right")
    table.add_column("Constraints")
    table.add_column("Updated")

    for s in sys_status.skills:
        score_str = f"{s.last_score:.3f}" if s.last_score else "—"
        table.add_row(
            s.name,
            str(s.latest_version) if s.latest_version else "—",
            s.source or "—",
            score_str,
            "✓" if s.constraints_passed else "✗",
            s.created_at or "—",
        )

    console.print(table)
    console.print(f"\n[dim]{sys_status.total_skills} skill(s) tracked[/dim]")


if __name__ == "__main__":
    cli()
