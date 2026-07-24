#!/usr/bin/env python3
"""Phase J: Real-world validation — runs the full V3 pipeline on 3 real skills.

For each skill:
  1. Read SKILL.md
  2. CognitiveLoadAnalyzer.analyze()
  3. StructuralEnforcer.analyze()
  4. SelfEvolver.evolve() with 2 iterations (real LLM calls)
  5. Print summary table
"""

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evolution.core.cognitive_load import CognitiveLoadAnalyzer
from evolution.core.structural_enforcer import StructuralEnforcer
from evolution.core.self_evolver import SelfEvolver
from evolution.core.custom_provider import configure_dspy
from evolution.core.config import EvolutionConfig

# ── Configuration ───────────────────────────────────────────────────

SKILLS_DIR = Path.home() / ".hermes" / "skills"

# (display_name, subpath under SKILLS_DIR)
TARGET_SKILLS = [
    ("n8n-patterns", "n8n/n8n-patterns/SKILL.md"),
    ("research-manager", "research/research-manager/SKILL.md"),
    ("agent-reach", "agent-reach/SKILL.md"),
]

TEST_CASES = [
    {"task_input": "What does this skill do?", "expected_behavior": "Clear description"},
    {"task_input": "How to use this skill?", "expected_behavior": "Step by step instructions"},
]

MAX_EVOLVE_ITERATIONS = 1

OUTPUT_PATH = Path("/tmp/v3_validation_results.json")

# ── Helpers ─────────────────────────────────────────────────────────

def load_skill(name: str, subpath: str) -> str | None:
    """Read SKILL.md content or return None if missing."""
    full = SKILLS_DIR / subpath
    if not full.exists():
        return None
    return full.read_text(errors="replace")


def _sep(char="─", width=70):
    print(char * width)


def print_header(title: str):
    print()
    _sep("═")
    print(f"  {title}")
    _sep("═")


def print_cognitive(result):
    dims = [
        ("tasks", result.task_score),
        ("reasoning", result.reasoning_score),
        ("tools", result.tool_score),
        ("constraints", result.constraint_score),
        ("output", result.output_score),
        ("temporal", result.temporal_score),
        ("ambiguity", result.ambiguity_score),
        ("state", result.state_score),
        ("context", result.context_score),
    ]
    print(f"  {'Dimension':<16} {'Score':>6}")
    _sep()
    for label, score in dims:
        bar = "█" * int(score / 5)
        print(f"  {label:<16} {score:>5.1f}  {bar}")
    _sep()
    print(f"  {'TOTAL':<16} {result.total_score:>5.1f}")
    print(f"  {'Severity':<16} {result.severity}")
    print(f"  {'Penalty':<16} {result.penalty}")


def print_structural(report):
    patterns = [
        ("triggers", report.has_triggers),
        ("when_to_invoke", report.has_when_to_invoke),
        ("preamble", report.has_preamble),
        ("error_handling", report.has_error_handling),
        ("env_vars", report.has_env_vars),
        ("conditionals", report.has_conditionals),
        ("bash_blocks", report.has_bash_blocks),
        ("verification", report.has_verification),
        ("pitfalls", report.has_pitfalls),
        ("version", report.has_version),
    ]
    print(f"  {'Pattern':<20} {'Present':>8}")
    _sep()
    for label, present in patterns:
        mark = "  ✓" if present else "  ✗"
        print(f"  {label:<20} {mark}")
    _sep()
    print(f"  {'Completeness':<20} {report.completeness_score:>6.1f}%")
    if report.missing_patterns:
        print(f"  Missing: {', '.join(report.missing_patterns)}")


def print_evolve(result):
    print(f"  Original score : {result.original_score:.4f}")
    print(f"  Final score    : {result.final_score:.4f}")
    print(f"  Improvement    : {result.improvement:+.4f}")
    print(f"  Iterations     : {result.iterations}")
    print(f"  Converged      : {'Yes' if result.converged else 'No'}")
    if result.history:
        _sep()
        print(f"  {'Iter':>4} {'Score':>8} {'Tested':>8} {'Action':<10}")
        _sep()
        for h in result.history:
            print(
                f"  {h['iteration']:>4} {h['score']:>8.4f} "
                f"{h['new_score_tested']:>8.4f} {h['action']:<10}"
            )


# ── Main ────────────────────────────────────────────────────────────

def main():
    print_header("Phase J: اعتبارسنجی واقعی V3 Pipeline (Real-World Validation)")
    print(f"  مهارت‌ها: {', '.join(n for n, _ in TARGET_SKILLS)}")
    print(f"  تست کیس‌ها: {len(TEST_CASES)}")
    print(f"  حداکثر تکرار تکامل: {MAX_EVOLVE_ITERATIONS}")

    # Configure DSPy before any LLM calls
    print_header("پیکربندی LLM Provider")
    try:
        cfg = configure_dspy()
        print(f"  Model  : {cfg.model}")
        print(f"  Base   : {cfg.base_url}")
    except Exception as e:
        print(f"  ⚠ خطا در پیکربندی LLM: {e}")
        print("  ادامه با تحلیل‌های بدون LLM...")
        cfg = None

    # Initialize analyzers
    cognitive_analyzer = CognitiveLoadAnalyzer()
    structural_enforcer = StructuralEnforcer()
    evolver_cfg = EvolutionConfig()
    # Use a model that exists on the custom provider, not the default gpt-4.1-mini
    evolver_cfg.eval_model = "opencode200k"
    evolver = SelfEvolver(config=evolver_cfg)

    all_results = []

    for skill_name, subpath in TARGET_SKILLS:
        print_header(f"مهارت: {skill_name}")

        skill_text = load_skill(skill_name, subpath)
        if skill_text is None:
            print(f"  ⚠ فایل SKILL.md یافت نشد: {SKILLS_DIR / subpath}")
            print(f"  → رد شدن از این مهارت")
            all_results.append({"skill": skill_name, "status": "skipped", "reason": "file not found"})
            continue

        print(f"  اندازه: {len(skill_text):,} حرف | {len(skill_text.split()):,} کلمه")

        # 1) Cognitive Load Analysis
        print_header(f"  [1/3] تحلیل بار شناختی (Cognitive Load)")
        t0 = time.time()
        try:
            cog_result = cognitive_analyzer.analyze(skill_text)
            cog_time = time.time() - t0
            print_cognitive(cog_result)
            print(f"\n  ⏱ زمان: {cog_time:.1f}s")
        except Exception as e:
            print(f"  ⚠ خطا در تحلیل بار شناختی: {e}")
            cog_result = None

        # 2) Structural Analysis
        print_header(f"  [2/3] تحلیل ساختاری (Structural Patterns)")
        t0 = time.time()
        try:
            struct_report = structural_enforcer.analyze(skill_text)
            struct_time = time.time() - t0
            print_structural(struct_report)
            print(f"\n  ⏱ زمان: {struct_time:.1f}s")
        except Exception as e:
            print(f"  ⚠ خطا در تحلیل ساختاری: {e}")
            struct_report = None

        # 3) Self-Evolution (LLM calls)
        print_header(f"  [3/3] حلقه تکامل خود (Self-Evolution Loop)")
        evolve_result = None
        if cfg is not None:
            # Truncate large skills for LLM processing (keep first 4K chars)
            truncated_text = skill_text[:4000] if len(skill_text) > 4000 else skill_text
            t0 = time.time()
            try:
                evolve_result = evolver.evolve(
                    skill_text=truncated_text,
                    test_cases=TEST_CASES,
                    max_iterations=MAX_EVOLVE_ITERATIONS,
                )
                evolve_time = time.time() - t0
                print_evolve(evolve_result)
                print(f"\n  ⏱ زمان: {evolve_time:.1f}s")
            except Exception as e:
                print(f"  ⚠ خطا در حلقه تکامل: {e}")
        else:
            print("  → رد شدن (LLM پیکربندی نشده)")

        # Collect result
        skill_result = {
            "skill": skill_name,
            "status": "completed",
            "cognitive_load": {
                "total_score": cog_result.total_score if cog_result else None,
                "severity": cog_result.severity if cog_result else None,
                "penalty": cog_result.penalty if cog_result else None,
                "task_score": cog_result.task_score if cog_result else None,
                "reasoning_score": cog_result.reasoning_score if cog_result else None,
                "tool_score": cog_result.tool_score if cog_result else None,
            },
            "structural": {
                "completeness_score": struct_report.completeness_score if struct_report else None,
                "missing_patterns": struct_report.missing_patterns if struct_report else None,
            },
            "evolution": {
                "original_score": evolve_result.original_score if evolve_result else None,
                "final_score": evolve_result.final_score if evolve_result else None,
                "improvement": evolve_result.improvement if evolve_result else None,
                "iterations": evolve_result.iterations if evolve_result else None,
                "converged": evolve_result.converged if evolve_result else None,
            },
        }
        all_results.append(skill_result)

    # ── Final Comparison Table ───────────────────────────────────────
    print_header("جدول مقایسه نهایی (Final Comparison)")

    header = f"  {'Skill':<20} {'CogLoad':>8} {'Sev':>10} {'Struct%':>8} {'EvolStart':>10} {'EvolFinal':>10} {'Δ':>8}"
    print(header)
    _sep()
    for r in all_results:
        if r["status"] != "completed":
            print(f"  {r['skill']:<20} {'— SKIPPED':>30}")
            continue
        cog = r["cognitive_load"]["total_score"] or 0
        sev = r["cognitive_load"]["severity"] or "—"
        st = r["structural"]["completeness_score"] or 0
        ev_s = r["evolution"]["original_score"]
        ev_f = r["evolution"]["final_score"]
        delta = r["evolution"]["improvement"]
        ev_s_str = f"{ev_s:.4f}" if ev_s is not None else "—"
        ev_f_str = f"{ev_f:.4f}" if ev_f is not None else "—"
        delta_str = f"{delta:+.4f}" if delta is not None else "—"
        print(
            f"  {r['skill']:<20} {cog:>7.1f} {sev:>10} {st:>7.1f}% "
            f"{ev_s_str:>10} {ev_f_str:>10} {delta_str:>8}"
        )

    # ── Save JSON ────────────────────────────────────────────────────
    OUTPUT_PATH.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n  ✅ نتایج ذخیره شد: {OUTPUT_PATH}")
    print(_sep("═"))
    print("  اعتبارسنجی Phase J تمام شد!")
    print(_sep("═"))


if __name__ == "__main__":
    main()
