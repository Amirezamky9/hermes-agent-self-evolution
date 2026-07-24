"""V3 Integration Tests — Phase I wiring verification.

Tests pipeline with all new V3 modules (mocked), CLI new options,
and end-to-end flows.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from click.testing import CliRunner

from evolution.cli import cli
from evolution.core.pipeline import Pipeline, PipelineResult
from evolution.core.full_pipeline import FullPipeline
from evolution.core.config import EvolutionConfig


# ── Helpers ───────────────────────────────────────────────────────────

def _make_grazer_output(skill_name="test-skill"):
    return {
        "skill_usages": [{"skill_name": skill_name, "error_type": "tool_error", "task_input": "do thing", "error_message": "failed"}],
        "failures": [{"skill_name": skill_name, "error_type": "tool_error", "task_input": "do thing", "error_message": "failed"}],
        "skill_counts": {skill_name: 1},
        "failure_counts": {skill_name: 1},
    }

def _make_gap(skill_name="test-skill"):
    return {
        "skill_name": skill_name,
        "failure_count": 1,
        "severity": "warning",
        "recommendation": "Fix it",
        "sample_failures": [{"error_type": "tool_error", "error_message": "failed", "task_input": "do thing"}],
    }

def _make_patch(skill_name="test-skill"):
    return {
        "skill_name": skill_name,
        "old_text": "---\nname: test-skill\ndescription: A test\n---\n# Old Body",
        "new_text": "---\nname: test-skill\ndescription: A test\n---\n# New Body",
        "diff_summary": "+1 lines",
        "rationale": "Better instructions",
        "severity": "warning",
    }

def _setup_pipeline_mocks(pipeline, skill_name="test-skill", with_gaps=True, with_patches=True):
    """Configure all mocks on a Pipeline instance for a happy-path run."""
    pipeline.grazer = MagicMock()
    pipeline.grazer.run.return_value = _make_grazer_output(skill_name)

    pipeline.gap_analyzer = MagicMock()
    pipeline.gap_analyzer.analyze.return_value = [_make_gap(skill_name)] if with_gaps else []

    pipeline.patch_engine = MagicMock()
    pipeline.patch_engine.generate_patches.return_value = [_make_patch(skill_name)] if with_patches else []
    pipeline.patch_engine._resolve_skill_path.return_value = None

    pipeline.benchmark_runner = MagicMock()
    pipeline.benchmark_runner.run_benchmark.return_value = MagicMock(
        old_score=0.6, new_score=0.8, improvement=0.2, passed=True,
        old_adjustment=MagicMock(cognitive_load=25.0, penalty=0.0),
        new_adjustment=MagicMock(cognitive_load=20.0, penalty=0.0),
    )

    pipeline.safety_net = MagicMock()
    pipeline.safety_net.validate_patch.return_value = MagicMock(passed=True, issues=[], warnings=[])
    pipeline.safety_net.check_drift.return_value = MagicMock(drift_detected=False, drift_pct=0.0, action="accept")

    pipeline.version_manager = MagicMock()
    pipeline.version_manager.create_version.return_value = "v1.0.0"


# ── PipelineResult V3 fields ──────────────────────────────────────────

class TestPipelineResultV3:
    def test_v3_fields_default(self):
        r = PipelineResult(skill_name="test")
        assert r.cognitive_load_score == 0.0
        assert r.cognitive_load_severity == ""
        assert r.structural_completeness == 0.0
        assert r.structural_missing == []
        assert r.self_evolve_used is False
        assert r.report_text is None
        assert r._hybrid_test_cases is None


# ── Pipeline with hybrid mode ─────────────────────────────────────────

class TestPipelineHybrid:
    def test_hybrid_mode_runs_hybrid_dataset_step(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        # Mock hybrid builder
        pipeline.hybrid_builder = MagicMock()
        pipeline.hybrid_builder.build.return_value = [
            {"task_input": "test", "expected_behavior": "works", "source": "hybrid"},
        ]

        # Mock structural enforcer
        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 75.0
        report.missing_patterns = []
        pipeline.structural_enforcer.analyze.return_value = report

        result = pipeline.run("test-skill", mode="hybrid")

        assert "hybrid_dataset" in [s["step"] for s in result.steps]
        pipeline.hybrid_builder.build.assert_called_once()
        # Hybrid test cases should be passed to benchmark
        assert result._hybrid_test_cases is not None

    def test_hybrid_builder_called_with_grazer_output(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        pipeline.hybrid_builder = MagicMock()
        pipeline.hybrid_builder.build.return_value = []
        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 80.0
        report.missing_patterns = []
        pipeline.structural_enforcer.analyze.return_value = report

        pipeline.run("test-skill", mode="hybrid")

        call_args = pipeline.hybrid_builder.build.call_args
        assert call_args[0][0] == "test-skill"
        grazer_result = call_args[1].get("grazer_result") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["grazer_result"]
        assert grazer_result is not None
        assert "failures" in grazer_result


# ── Pipeline with self_evolve ─────────────────────────────────────────

class TestPipelineSelfEvolve:
    def test_self_evolve_skips_patch_engine(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        # Replace real self_evolver with a mock
        pipeline.self_evolver = MagicMock()
        evolve_result = MagicMock()
        evolve_result.original_text = "---\nname: test-skill\ndescription: A test\n---\n# Original"
        evolve_result.final_text = "---\nname: test-skill\ndescription: A test\n---\n# Improved"
        evolve_result.original_score = 0.5
        evolve_result.final_score = 0.7
        evolve_result.improvement = 0.2
        evolve_result.iterations = 3
        evolve_result.converged = False
        pipeline.self_evolver.evolve.return_value = evolve_result

        # Mock structural enforcer
        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 80.0
        report.missing_patterns = []
        pipeline.structural_enforcer.analyze.return_value = report

        # Mock _resolve_skill_text to return a skill
        pipeline._resolve_skill_text = MagicMock(return_value="# test skill")

        result = pipeline.run("test-skill", self_evolve=True)

        assert result.self_evolve_used is True
        step_names = [s["step"] for s in result.steps]
        assert "self_evolve" in step_names
        assert "patch_engine" not in step_names
        assert "benchmark" not in step_names
        assert result.old_score == 0.5
        assert result.new_score == 0.7
        assert result.improvement == 0.2

    def test_self_evolve_no_improvement_sets_error(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        # Replace real self_evolver with a mock
        pipeline.self_evolver = MagicMock()
        evolve_result = MagicMock()
        evolve_result.original_score = 0.5
        evolve_result.final_score = 0.5
        evolve_result.improvement = 0.0
        evolve_result.iterations = 3
        evolve_result.converged = True
        evolve_result.original_text = "old"
        evolve_result.final_text = "old"
        pipeline.self_evolver.evolve.return_value = evolve_result

        pipeline._resolve_skill_text = MagicMock(return_value="# test skill")

        result = pipeline.run("test-skill", self_evolve=True)

        assert result.error is not None
        assert "SelfEvolver did not improve" in result.error

    def test_self_evolve_cognitive_load_recorded(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        # Replace real self_evolver with a mock
        pipeline.self_evolver = MagicMock()
        evolve_result = MagicMock()
        evolve_result.original_score = 0.5
        evolve_result.final_score = 0.7
        evolve_result.improvement = 0.2
        evolve_result.iterations = 2
        evolve_result.converged = False
        evolve_result.original_text = "old text"
        evolve_result.final_text = "new text"
        pipeline.self_evolver.evolve.return_value = evolve_result
        pipeline._resolve_skill_text = MagicMock(return_value="# test skill")

        # Mock structural enforcer
        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 85.0
        report.missing_patterns = []
        pipeline.structural_enforcer.analyze.return_value = report

        result = pipeline.run("test-skill", self_evolve=True)

        # Cognitive load should be set by self_evolve step
        assert result.cognitive_load_severity in ("light", "moderate", "heavy")


# ── Pipeline StructuralEnforcer ───────────────────────────────────────

class TestPipelineStructuralEnforce:
    def test_structural_enforcer_called_after_patches(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 75.0
        report.missing_patterns = ["verification steps"]
        pipeline.structural_enforcer.analyze.return_value = report

        result = pipeline.run("test-skill", mode="session")

        assert "structural_enforce" in [s["step"] for s in result.steps]
        assert result.structural_completeness == 75.0
        assert "verification steps" in result.structural_missing

    def test_low_structural_score_triggers_auto_inject(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 30.0
        report.missing_patterns = ["triggers", "error handling"]
        pipeline.structural_enforcer.analyze.return_value = report
        injection = MagicMock()
        pipeline.structural_enforcer.suggest_injections.return_value = [injection]
        pipeline.structural_enforcer.auto_inject.return_value = "---\nname: test-skill\n---\n# Updated"

        result = pipeline.run("test-skill", mode="session")

        assert result.structural_completeness == 30.0
        pipeline.structural_enforcer.auto_inject.assert_called_once()
        # The best patch's new_text should be updated
        assert pipeline.structural_enforcer.auto_inject.called


# ── Pipeline Reporter ─────────────────────────────────────────────────

class TestPipelineReporter:
    def test_report_step_when_report_flag_true(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 80.0
        report.missing_patterns = []
        pipeline.structural_enforcer.analyze.return_value = report

        pipeline.reporter = MagicMock()
        pipeline.reporter.format_pipeline_result.return_value = "📊 Report text"

        result = pipeline.run("test-skill", mode="session", report=True)

        assert "report" in [s["step"] for s in result.steps]
        assert result.report_text == "📊 Report text"
        pipeline.reporter.format_pipeline_result.assert_called_once()

    def test_no_report_step_when_report_flag_false(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)
        _setup_pipeline_mocks(pipeline)

        pipeline.structural_enforcer = MagicMock()
        report = MagicMock()
        report.completeness_score = 80.0
        report.missing_patterns = []
        pipeline.structural_enforcer.analyze.return_value = report

        result = pipeline.run("test-skill", mode="session", report=False)

        assert "report" not in [s["step"] for s in result.steps]
        assert result.report_text is None


# ── CLI new options ───────────────────────────────────────────────────

class TestCLIV3Options:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_optimize_help_shows_hybrid(self, runner):
        result = runner.invoke(cli, ["optimize", "--help"])
        assert result.exit_code == 0
        assert "hybrid" in result.output

    def test_optimize_help_shows_self_evolve(self, runner):
        result = runner.invoke(cli, ["optimize", "--help"])
        assert result.exit_code == 0
        assert "--self-evolve" in result.output

    def test_optimize_help_shows_report_flag(self, runner):
        result = runner.invoke(cli, ["optimize", "--help"])
        assert result.exit_code == 0
        assert "--report" in result.output

    def test_optimize_rejects_invalid_mode(self, runner):
        result = runner.invoke(cli, ["optimize", "test", "--mode", "invalid"])
        assert result.exit_code != 0

    def test_optimize_hybrid_mode_accepted(self, runner):
        """hybrid is now a valid choice — should not fail at argument parsing."""
        result = runner.invoke(cli, ["optimize", "test", "--mode", "hybrid", "--help"])
        # --help makes it exit 0 without running the command
        assert result.exit_code == 0


# ── FullPipeline wiring ──────────────────────────────────────────────

class TestFullPipelineV3Wiring:
    @patch("evolution.core.full_pipeline.Pipeline")
    def test_full_pipeline_passes_self_evolve(self, MockPipeline):
        mock_pipeline = MagicMock()
        r = PipelineResult(skill_name="test")
        r.passed = True
        r.old_score = 0.5
        r.new_score = 0.7
        r.improvement = 0.2
        mock_pipeline.run.return_value = r
        MockPipeline.return_value = mock_pipeline

        fp = FullPipeline()
        result = fp.run("test", mode="hybrid", self_evolve=True, report=True)

        mock_pipeline.run.assert_called_once_with(
            "test", mode="hybrid", self_evolve=True, report=True,
        )
        assert result.passed is True

    @patch("evolution.core.full_pipeline.Pipeline")
    def test_full_pipeline_defaults_unchanged(self, MockPipeline):
        mock_pipeline = MagicMock()
        r = PipelineResult(skill_name="test")
        r.passed = True
        mock_pipeline.run.return_value = r
        MockPipeline.return_value = mock_pipeline

        fp = FullPipeline()
        fp.run("test", mode="session")

        mock_pipeline.run.assert_called_once_with(
            "test", mode="session", self_evolve=False, report=False,
        )


# ── End-to-end flow (all mocked, no LLM) ─────────────────────────────

class TestEndToEndFlow:
    """Full flow: session → hybrid dataset → self-evolve → structural → safety → version → report."""

    def test_full_v3_flow(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        # -- SessionGrazer --
        pipeline.grazer = MagicMock()
        pipeline.grazer.run.return_value = _make_grazer_output("my-skill")

        # -- HybridDatasetBuilder --
        pipeline.hybrid_builder = MagicMock()
        pipeline.hybrid_builder.build.return_value = [
            {"task_input": "hybrid test", "expected_behavior": "works", "source": "hybrid"},
        ]

        # -- GapAnalyzer (must find gaps for self_evolve path to proceed) --
        pipeline.gap_analyzer = MagicMock()
        pipeline.gap_analyzer.analyze.return_value = [_make_gap("my-skill")]

        # -- SelfEvolver --
        pipeline.self_evolver = MagicMock()
        evolve_result = MagicMock()
        evolve_result.original_text = "---\nname: my-skill\ndesc: d\n---\n# old"
        evolve_result.final_text = "---\nname: my-skill\ndesc: d\n---\n# new"
        evolve_result.original_score = 0.4
        evolve_result.final_score = 0.75
        evolve_result.improvement = 0.35
        evolve_result.iterations = 3
        evolve_result.converged = False
        pipeline.self_evolver.evolve.return_value = evolve_result

        # -- Resolve skill text --
        pipeline._resolve_skill_text = MagicMock(return_value="# my skill content")

        # -- StructuralEnforcer --
        pipeline.structural_enforcer = MagicMock()
        struct_report = MagicMock()
        struct_report.completeness_score = 82.0
        struct_report.missing_patterns = ["verification steps"]
        pipeline.structural_enforcer.analyze.return_value = struct_report

        # -- SafetyNet --
        pipeline.safety_net = MagicMock()
        pipeline.safety_net.validate_patch.return_value = MagicMock(passed=True, issues=[], warnings=[])
        pipeline.safety_net.check_drift.return_value = MagicMock(drift_detected=False, drift_pct=0.0, action="accept")

        # -- VersionManager --
        pipeline.version_manager = MagicMock()
        pipeline.version_manager.create_version.return_value = "v3.0.0"

        # -- Reporter --
        pipeline.reporter = MagicMock()
        pipeline.reporter.format_pipeline_result.return_value = "📊 Full V3 report"

        # Run
        result = pipeline.run(
            "my-skill",
            mode="hybrid",
            self_evolve=True,
            report=True,
        )

        # Verify all steps ran
        step_names = [s["step"] for s in result.steps]
        assert "session_grazer" in step_names
        assert "hybrid_dataset" in step_names
        assert "gap_analyzer" in step_names
        assert "self_evolve" in step_names
        assert "structural_enforce" in step_names
        assert "safety_validate" in step_names
        assert "version_save" in step_names
        assert "drift_check" in step_names
        assert "report" in step_names

        # Verify result fields
        assert result.skill_name == "my-skill"
        assert result.self_evolve_used is True
        assert result.old_score == 0.4
        assert result.new_score == 0.75
        assert result.improvement == 0.35
        assert result.safety_passed is True
        assert result.version_created == "v3.0.0"
        assert result.passed is True
        assert result.structural_completeness == 82.0
        assert result.report_text == "📊 Full V3 report"

        # Verify calls
        pipeline.hybrid_builder.build.assert_called_once()
        pipeline.self_evolver.evolve.assert_called_once()
        pipeline.structural_enforcer.analyze.assert_called()
        pipeline.safety_net.validate_patch.assert_called_once()
        pipeline.version_manager.create_version.assert_called_once()
        pipeline.reporter.format_pipeline_result.assert_called_once()

    def test_full_v3_flow_patch_path(self, tmp_path):
        """Non-self-evolve path with hybrid + structural + report."""
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        pipeline.grazer = MagicMock()
        pipeline.grazer.run.return_value = _make_grazer_output("skill-x")

        pipeline.hybrid_builder = MagicMock()
        pipeline.hybrid_builder.build.return_value = [
            {"task_input": "hybrid test", "expected_behavior": "works", "source": "hybrid"},
        ]

        pipeline.gap_analyzer = MagicMock()
        pipeline.gap_analyzer.analyze.return_value = [_make_gap("skill-x")]

        patch_dict = _make_patch("skill-x")
        pipeline.patch_engine = MagicMock()
        pipeline.patch_engine.generate_patches.return_value = [patch_dict]
        pipeline.patch_engine._resolve_skill_path.return_value = None

        pipeline.structural_enforcer = MagicMock()
        struct_report = MagicMock()
        struct_report.completeness_score = 70.0
        struct_report.missing_patterns = ["error handling"]
        pipeline.structural_enforcer.analyze.return_value = struct_report

        pipeline.benchmark_runner = MagicMock()
        pipeline.benchmark_runner.run_benchmark.return_value = MagicMock(
            old_score=0.5, new_score=0.7, improvement=0.2, passed=True,
            old_adjustment=MagicMock(cognitive_load=35.0, penalty=0.15),
            new_adjustment=MagicMock(cognitive_load=30.0, penalty=0.0),
        )

        pipeline.safety_net = MagicMock()
        pipeline.safety_net.validate_patch.return_value = MagicMock(passed=True, issues=[], warnings=[])
        pipeline.safety_net.check_drift.return_value = MagicMock(drift_detected=False, drift_pct=0.0, action="accept")

        pipeline.version_manager = MagicMock()
        pipeline.version_manager.create_version.return_value = "v2.0.0"

        pipeline.reporter = MagicMock()
        pipeline.reporter.format_pipeline_result.return_value = "📊 Patch path report"

        result = pipeline.run(
            "skill-x",
            mode="hybrid",
            self_evolve=False,
            report=True,
        )

        step_names = [s["step"] for s in result.steps]
        assert "hybrid_dataset" in step_names
        assert "patch_engine" in step_names
        assert "structural_enforce" in step_names
        assert "benchmark" in step_names
        assert "report" in step_names
        assert "self_evolve" not in step_names
        assert result.cognitive_load_severity == "moderate"  # penalty 0.15
        assert result.structural_completeness == 70.0


# ── Import smoke tests for V3 modules ─────────────────────────────────

class TestV3Imports:
    def test_all_v3_modules_importable(self):
        from evolution.core.cognitive_load import CognitiveLoadAnalyzer
        from evolution.core.structural_enforcer import StructuralEnforcer
        from evolution.core.hybrid_dataset import HybridDatasetBuilder
        from evolution.core.self_evolver import SelfEvolver
        from evolution.core.reporter import Reporter
        from evolution.core.pattern_extractor import PatternExtractor
        assert all([CognitiveLoadAnalyzer, StructuralEnforcer, HybridDatasetBuilder,
                    SelfEvolver, Reporter, PatternExtractor])

    def test_v3_modules_accessible_from_package(self):
        from evolution.core import (
            CognitiveLoadAnalyzer, StructuralEnforcer, HybridDatasetBuilder,
            SelfEvolver, Reporter, PatternExtractor,
        )
        assert all([CognitiveLoadAnalyzer, StructuralEnforcer, HybridDatasetBuilder,
                    SelfEvolver, Reporter, PatternExtractor])
