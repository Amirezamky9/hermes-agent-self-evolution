"""Pipeline — orchestrates the full self-evolution optimization flow (V3).

Steps:
1. SessionGrazer → find failures for this skill
2. [hybrid] HybridDatasetBuilder → merge synthetic + session data
3. SkillGapAnalyzer → analyze gaps
4. PatchEngine → generate patches (or SelfEvolver when self_evolve=True)
5. StructuralEnforcer → check/enforce structural completeness
6. BenchmarkRunner → A/B test old vs new
7. SafetyNet → validate patch
8. VersionManager → save version (if passed)
9. SafetyNet.check_drift → monitor for drift
10. [report] Reporter → format and deliver output
"""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from evolution.core.config import EvolutionConfig, resolve_hermes_agent_path
from evolution.core.session_grazer import SessionGrazer, SkillUsage
from evolution.core.gap_analyzer import SkillGapAnalyzer
from evolution.core.patch_engine import PatchEngine
from evolution.core.benchmark_runner import BenchmarkRunner
from evolution.core.safety_net import SafetyNet, ValidationResult
from evolution.core.version_manager import VersionManager
from evolution.core.cognitive_load import CognitiveLoadAnalyzer
from evolution.core.structural_enforcer import StructuralEnforcer
from evolution.core.hybrid_dataset import HybridDatasetBuilder
from evolution.core.self_evolver import SelfEvolver
# Reporter imported lazily in __init__ to avoid circular import
# (pipeline → reporter → cron_runner → pipeline)


@dataclass
class PipelineResult:
    skill_name: str
    old_score: float = 0.0
    new_score: float = 0.0
    improvement: float = 0.0
    passed: bool = False
    version_created: Optional[str] = None
    failures_found: int = 0
    gaps_found: int = 0
    patches_generated: int = 0
    safety_passed: bool = False
    duration_seconds: float = 0.0
    steps: list = field(default_factory=list)
    error: Optional[str] = None
    # V3 fields
    cognitive_load_score: float = 0.0
    cognitive_load_severity: str = ""
    structural_completeness: float = 0.0
    structural_missing: list = field(default_factory=list)
    self_evolve_used: bool = False
    report_text: Optional[str] = None
    # Intermediate state passed between pipeline steps (not part of public API)
    _grazer_output: Optional[dict] = field(default=None, repr=False)
    _gaps: Optional[list] = field(default=None, repr=False)
    _patches: Optional[list] = field(default=None, repr=False)
    _best_patch: Optional[dict] = field(default=None, repr=False)
    _step_details: Optional[dict] = field(default=None, repr=False)
    _hybrid_test_cases: Optional[list] = field(default=None, repr=False)


class Pipeline:
    """Orchestrates the full self-evolution optimization pipeline."""

    def __init__(self, config: Optional[EvolutionConfig] = None):
        self.config = config or EvolutionConfig()
        self.grazer = SessionGrazer()
        self.gap_analyzer = SkillGapAnalyzer()
        self.patch_engine = PatchEngine(config=self.config)
        self.benchmark_runner = BenchmarkRunner(config=self.config)
        self.safety_net = SafetyNet(
            max_size=self.config.max_skill_size,
            max_growth_pct=self.config.max_prompt_growth,
        )
        self.version_manager = VersionManager()
        # V3 modules
        self.cognitive_analyzer = CognitiveLoadAnalyzer()
        self.structural_enforcer = StructuralEnforcer()
        self.hybrid_builder = HybridDatasetBuilder(config=self.config)
        self.self_evolver = SelfEvolver(config=self.config)
        # Lazy import to avoid circular dependency (pipeline→reporter→cron_runner→pipeline)
        from evolution.core.reporter import Reporter
        self.reporter = Reporter()

    def run(
        self,
        skill_name: str,
        mode: str = "session",
        self_evolve: bool = False,
        report: bool = False,
    ) -> PipelineResult:
        """Run the full optimization pipeline for a skill.

        mode="session": Use SessionGrazer data (real failures)
        mode="synthetic": Use synthetic dataset
        mode="hybrid": Use HybridDatasetBuilder (synthetic + session)
        self_evolve=True: Use SelfEvolver instead of PatchEngine+Benchmark
        report=True: Generate report via Reporter
        """
        start = time.time()
        result = PipelineResult(skill_name=skill_name)
        result.self_evolve_used = self_evolve

        # ── Step 1: SessionGrazer — find failures ────────────────────
        if not self._step(result, "session_grazer", lambda: self._run_grazer(skill_name, result)):
            result.duration_seconds = time.time() - start
            return result

        # ── Step 2: HybridDatasetBuilder (when mode="hybrid") ────────
        if mode == "hybrid":
            if not self._step(result, "hybrid_dataset", lambda: self._run_hybrid_dataset(skill_name, result)):
                result.duration_seconds = time.time() - start
                return result

        # ── Step 3: SkillGapAnalyzer — analyze gaps ──────────────────
        if not self._step(result, "gap_analyzer", lambda: self._run_gap_analyzer(result)):
            result.duration_seconds = time.time() - start
            return result

        if result.gaps_found == 0:
            result.error = "No gaps found — nothing to optimize"
            result.duration_seconds = time.time() - start
            return result

        # ── SelfEvolve path: replaces PatchEngine + Benchmark ────────
        if self_evolve:
            if not self._step(result, "self_evolve", lambda: self._run_self_evolve(skill_name, result)):
                result.duration_seconds = time.time() - start
                return result

            # Bail out if self_evolve did not improve
            if result.error:
                result.duration_seconds = time.time() - start
                return result

            # ── StructuralEnforcer after self_evolve ─────────────────
            if not self._step(result, "structural_enforce", lambda: self._run_structural_enforce(result)):
                result.duration_seconds = time.time() - start
                return result
        else:
            # ── Step 4: PatchEngine — generate patches ───────────────
            if not self._step(result, "patch_engine", lambda: self._run_patch_engine(skill_name, result)):
                result.duration_seconds = time.time() - start
                return result

            if result.patches_generated == 0:
                result.error = "No patches generated"
                result.duration_seconds = time.time() - start
                return result

            # ── Step 5: StructuralEnforcer after patch ───────────────
            if not self._step(result, "structural_enforce", lambda: self._run_structural_enforce(result)):
                result.duration_seconds = time.time() - start
                return result

            # ── Step 6: BenchmarkRunner — A/B test ───────────────────
            if not self._step(result, "benchmark", lambda: self._run_benchmark(skill_name, result)):
                result.duration_seconds = time.time() - start
                return result

        # ── Step 7: SafetyNet — validate patch ───────────────────────
        if not self._step(result, "safety_validate", lambda: self._run_safety_validate(skill_name, result)):
            result.duration_seconds = time.time() - start
            return result

        if not result.safety_passed:
            result.error = "SafetyNet validation failed"
            result.duration_seconds = time.time() - start
            return result

        # ── Step 8: VersionManager — save version ────────────────────
        if not self._step(result, "version_save", lambda: self._run_version_save(skill_name, result)):
            result.duration_seconds = time.time() - start
            return result

        # ── Step 9: SafetyNet.check_drift ────────────────────────────
        if not self._step(result, "drift_check", lambda: self._run_drift_check(skill_name, result)):
            result.duration_seconds = time.time() - start
            return result

        # ── Step 10: Reporter ────────────────────────────────────────
        if report:
            self._step(result, "report", lambda: self._run_report(result))

        result.duration_seconds = time.time() - start
        return result

    def _step(self, result: PipelineResult, name: str, fn) -> bool:
        """Execute a pipeline step, recording timing and errors.
        Returns True if the step succeeded, False if it failed (halting pipeline).
        """
        t0 = time.time()
        step_result = {"step": name, "status": "ok", "duration_seconds": 0.0, "details": {}}
        result._step_details = step_result["details"]
        try:
            fn()
        except Exception as e:
            step_result["status"] = "error"
            step_result["error"] = str(e)
            result.error = f"Step '{name}' failed: {e}"
        # Copy any details the step function wrote via result._step_details
        step_result["details"].update(getattr(result, "_step_details", {}))
        step_result["duration_seconds"] = round(time.time() - t0, 3)
        result.steps.append(step_result)
        return step_result["status"] == "ok"

    def _run_grazer(self, skill_name: str, result: PipelineResult) -> None:
        grazer_output = self.grazer.run(limit=50)
        # Filter to this skill
        skill_failures = [
            f for f in grazer_output.get("failures", [])
            if f.get("skill_name") == skill_name
        ]
        skill_usages = [
            u for u in grazer_output.get("skill_usages", [])
            if u.get("skill_name") == skill_name
        ]
        result.failures_found = len(skill_failures)
        # Store on result for downstream steps
        result._grazer_output = {
            "skill_usages": skill_usages,
            "failures": skill_failures,
            "skill_counts": {skill_name: len(skill_usages)},
            "failure_counts": {skill_name: len(skill_failures)},
        }

    def _run_hybrid_dataset(self, skill_name: str, result: PipelineResult) -> None:
        """Build a hybrid test dataset from synthetic + session failures."""
        grazer_output = getattr(result, "_grazer_output", None)
        test_cases = self.hybrid_builder.build(skill_name, grazer_result=grazer_output)
        result._hybrid_test_cases = test_cases
        result._step_details = {"hybrid_cases": len(test_cases)}

    def _run_gap_analyzer(self, result: PipelineResult) -> None:
        grazer_output = getattr(result, "_grazer_output", None)
        if grazer_output is None:
            grazer_output = {
                "skill_usages": [],
                "failures": [],
                "skill_counts": {},
                "failure_counts": {},
            }
        gaps = self.gap_analyzer.analyze(grazer_output)
        result.gaps_found = len(gaps)
        result._gaps = gaps

    def _run_patch_engine(self, skill_name: str, result: PipelineResult) -> None:
        gaps = getattr(result, "_gaps", [])
        if not gaps:
            return
        patches = self.patch_engine.generate_patches(gaps)
        result.patches_generated = len(patches)
        result._patches = patches
        # Track best patch for benchmarking
        if patches:
            # Pick patch with highest severity first, then first
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            best = min(
                patches,
                key=lambda p: severity_order.get(p.get("severity", "info"), 9),
            )
            result._best_patch = best
        else:
            result._best_patch = None

    def _run_structural_enforce(self, result: PipelineResult) -> None:
        """Run StructuralEnforcer on the best patch's new_text."""
        best_patch = getattr(result, "_best_patch", None)
        if best_patch is None:
            return
        new_text = best_patch.get("new_text", "")
        if not new_text:
            return
        report = self.structural_enforcer.analyze(new_text)
        result.structural_completeness = report.completeness_score
        result.structural_missing = report.missing_patterns
        result._step_details = {
            "completeness_score": report.completeness_score,
            "missing_patterns": report.missing_patterns,
        }
        # Auto-inject if score is low
        if report.completeness_score < 40:
            injections = self.structural_enforcer.suggest_injections(new_text, report)
            if injections:
                best_patch["new_text"] = self.structural_enforcer.auto_inject(new_text, injections)
                result._step_details["injections_applied"] = len(injections)

    def _run_self_evolve(self, skill_name: str, result: PipelineResult) -> None:
        """Use SelfEvolver to iteratively critique and improve the skill."""
        # Get current skill text
        skill_text = self._resolve_skill_text(skill_name)
        if not skill_text:
            result.error = f"Could not resolve skill text for '{skill_name}'"
            return

        # Build test cases: hybrid > gaps > default
        test_cases = getattr(result, "_hybrid_test_cases", None)
        if not test_cases:
            gaps = getattr(result, "_gaps", [])
            test_cases = []
            for gap in gaps[:3]:
                for sf in gap.get("sample_failures", [])[:2]:
                    test_cases.append({
                        "task_input": sf.get("task_input", "Describe this skill."),
                        "expected_behavior": gap.get("recommendation", "Skill works correctly."),
                    })
            if not test_cases:
                test_cases = [{"task_input": "Describe this skill.", "expected_behavior": "Skill works."}]

        evolve_result = self.self_evolver.evolve(
            skill_text=skill_text,
            test_cases=test_cases,
            max_iterations=self.config.iterations,
        )

        result.old_score = evolve_result.original_score
        result.new_score = evolve_result.final_score
        result.improvement = evolve_result.improvement
        result._step_details = {
            "iterations": evolve_result.iterations,
            "converged": evolve_result.converged,
            "original_score": evolve_result.original_score,
            "final_score": evolve_result.final_score,
        }

        # Set _best_patch for downstream safety + versioning
        if evolve_result.improvement > 0:
            result._best_patch = {
                "old_text": evolve_result.original_text,
                "new_text": evolve_result.final_text,
                "diff_summary": f"Self-evolved ({evolve_result.iterations} iterations)",
                "rationale": "LLM self-critique + improvement loop",
                "severity": "warning",
            }
            result.patches_generated = 1
        else:
            result.error = "SelfEvolver did not improve the skill"

        # Record cognitive load
        cl_result = self.cognitive_analyzer.analyze(evolve_result.final_text)
        result.cognitive_load_score = cl_result.total_score
        result.cognitive_load_severity = cl_result.severity

    def _resolve_skill_text(self, skill_name: str) -> Optional[str]:
        """Resolve the current SKILL.md text for a skill by name."""
        try:
            path = self.patch_engine._resolve_skill_path(skill_name)
            if path and Path(path).exists():
                return Path(path).read_text()
        except Exception:
            pass
        # Fallback: try hermes-agent skills dir
        hermes_path = getattr(self.config, "hermes_agent_path", None)
        if hermes_path:
            candidate = Path(hermes_path) / "skills" / skill_name / "SKILL.md"
            if candidate.exists():
                return candidate.read_text()
        return None

    def _run_benchmark(self, skill_name: str, result: PipelineResult) -> None:
        best_patch = getattr(result, "_best_patch", None)
        if best_patch is None:
            result.old_score = 0.0
            result.new_score = 0.0
            result.improvement = 0.0
            return

        old_text = best_patch.get("old_text", "")
        new_text = best_patch.get("new_text", "")

        # Use hybrid test cases if available, else build from gaps
        test_cases = getattr(result, "_hybrid_test_cases", None)
        if not test_cases:
            gaps = getattr(result, "_gaps", [])
            test_cases = []
            for gap in gaps[:3]:
                for sf in gap.get("sample_failures", [])[:2]:
                    test_cases.append({
                        "task_input": sf.get("task_input", "Describe this skill."),
                        "expected_behavior": gap.get("recommendation", "Skill works correctly."),
                    })
            if not test_cases:
                test_cases = [{"task_input": "Describe this skill.", "expected_behavior": "Skill works."}]

        bench_result = self.benchmark_runner.run_benchmark(old_text, new_text, test_cases)
        result.old_score = bench_result.old_score
        result.new_score = bench_result.new_score
        result.improvement = bench_result.improvement

        # Record cognitive load from benchmark adjustments (if available)
        try:
            if hasattr(bench_result, "old_adjustment") and bench_result.old_adjustment:
                result.cognitive_load_score = float(bench_result.old_adjustment.cognitive_load)
                penalty = float(bench_result.old_adjustment.penalty)
                result.cognitive_load_severity = (
                    "heavy" if penalty >= 0.30 else ("moderate" if penalty > 0 else "light")
                )
        except (AttributeError, TypeError):
            pass

    def _run_safety_validate(self, skill_name: str, result: PipelineResult) -> None:
        best_patch = getattr(result, "_best_patch", None)
        if best_patch is None:
            result.safety_passed = False
            return

        old_text = best_patch.get("old_text", "")
        new_text = best_patch.get("new_text", "")
        validation: ValidationResult = self.safety_net.validate_patch(old_text, new_text, skill_name)
        result.safety_passed = validation.passed
        result._step_details = {
            "passed": validation.passed,
            "issues": validation.issues,
            "warnings": validation.warnings,
        }

    def _run_version_save(self, skill_name: str, result: PipelineResult) -> None:
        best_patch = getattr(result, "_best_patch", None)
        if best_patch is None:
            return
        new_text = best_patch.get("new_text", "")
        version_str = self.version_manager.create_version(
            skill_name,
            new_text,
            {
                "source": "pipeline" if not result.self_evolve_used else "self_evolve",
                "benchmark_score": result.new_score,
                "diff_summary": best_patch.get("diff_summary", ""),
                "rationale": best_patch.get("rationale", ""),
                "old_score": result.old_score,
                "improvement": result.improvement,
                "cognitive_load": result.cognitive_load_score,
                "structural_completeness": result.structural_completeness,
            },
        )
        result.version_created = version_str
        # Also write to actual skill location if possible
        try:
            skill_path = self.patch_engine._resolve_skill_path(skill_name)
            if skill_path is not None:
                self.patch_engine.apply_patch(str(skill_path), best_patch)
        except Exception:
            pass

    def _run_drift_check(self, skill_name: str, result: PipelineResult) -> None:
        drift = self.safety_net.check_drift(skill_name, result.old_score, result.new_score)
        result._step_details = {
            "drift_detected": drift.drift_detected,
            "drift_pct": drift.drift_pct,
            "action": drift.action,
        }
        if drift.action == "rollback":
            rolled_back = self.safety_net.auto_rollback(skill_name, "drift detected")
            if rolled_back:
                result.version_created = None
                result.passed = False
                result._step_details["rolled_back"] = True
            return
        result.passed = True

    def _run_report(self, result: PipelineResult) -> None:
        """Generate a report via Reporter."""
        msg = self.reporter.format_pipeline_result(result)
        result.report_text = msg
        result._step_details = {"report_length": len(msg)}
