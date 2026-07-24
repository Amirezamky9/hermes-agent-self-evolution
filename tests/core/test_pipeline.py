"""Tests for Pipeline — all mocked, no real LLM calls."""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from evolution.core.pipeline import Pipeline, PipelineResult
from evolution.core.config import EvolutionConfig


# ── PipelineResult ────────────────────────────────────────────────────
class TestPipelineResult:
    def test_defaults(self):
        r = PipelineResult(skill_name="test")
        assert r.skill_name == "test"
        assert r.old_score == 0.0
        assert r.new_score == 0.0
        assert r.improvement == 0.0
        assert r.passed is False
        assert r.version_created is None
        assert r.failures_found == 0
        assert r.gaps_found == 0
        assert r.patches_generated == 0
        assert r.safety_passed is False
        assert r.duration_seconds == 0.0
        assert r.steps == []
        assert r.error is None

    def test_intermediate_fields_default_none(self):
        r = PipelineResult(skill_name="test")
        assert r._grazer_output is None
        assert r._gaps is None
        assert r._patches is None
        assert r._best_patch is None


# ── Pipeline with no failures ─────────────────────────────────────────
class TestPipelineNoFailures:
    def test_returns_error_when_no_gaps(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        # Mock grazer to return empty
        pipeline.grazer = MagicMock()
        pipeline.grazer.run.return_value = {
            "skill_usages": [],
            "failures": [],
            "skill_counts": {},
            "failure_counts": {},
        }

        result = pipeline.run("test-skill", mode="session")
        assert result.gaps_found == 0
        assert result.error and "No gaps found" in result.error
        assert result.passed is False
        # Should have recorded grazer and gap_analyzer steps
        step_names = [s["step"] for s in result.steps]
        assert "session_grazer" in step_names
        assert "gap_analyzer" in step_names
        # Should NOT have run patch/benchmark/safety
        assert "patch_engine" not in step_names
        assert "benchmark" not in step_names


# ── Pipeline with gaps but no patches ─────────────────────────────────
class TestPipelineNoPatches:
    def test_returns_error_when_no_patches(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        # Mock grazer with failures for this skill
        pipeline.grazer = MagicMock()
        pipeline.grazer.run.return_value = {
            "skill_usages": [
                {"skill_name": "test-skill", "error_type": "tool_error", "task_input": "do thing", "error_message": "failed"},
            ],
            "failures": [
                {"skill_name": "test-skill", "error_type": "tool_error", "task_input": "do thing", "error_message": "failed"},
            ],
            "skill_counts": {"test-skill": 1},
            "failure_counts": {"test-skill": 1},
        }

        # Mock gap analyzer to return a gap
        pipeline.gap_analyzer = MagicMock()
        pipeline.gap_analyzer.analyze.return_value = [
            {
                "skill_name": "test-skill",
                "failure_count": 1,
                "severity": "warning",
                "recommendation": "Fix it",
                "sample_failures": [{"error_type": "tool_error", "error_message": "failed", "task_input": "do thing"}],
            }
        ]

        # Mock patch engine to return empty
        pipeline.patch_engine = MagicMock()
        pipeline.patch_engine.generate_patches.return_value = []

        result = pipeline.run("test-skill", mode="session")
        assert result.gaps_found == 1
        assert result.patches_generated == 0
        assert result.error and "No patches generated" in result.error


# ── Full pipeline happy path ──────────────────────────────────────────
class TestPipelineHappyPath:
    def test_full_run_success(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        old_skill = "---\nname: test-skill\ndescription: A test\n---\n# Old Body"
        new_skill = "---\nname: test-skill\ndescription: A test\n---\n# Improved Body"

        patch_dict = {
            "skill_name": "test-skill",
            "old_text": old_skill,
            "new_text": new_skill,
            "diff_summary": "+1 lines",
            "rationale": "Better instructions",
            "severity": "warning",
        }

        # Mock grazer
        pipeline.grazer = MagicMock()
        pipeline.grazer.run.return_value = {
            "skill_usages": [{"skill_name": "test-skill", "error_type": "tool_error", "task_input": "x", "error_message": "y"}],
            "failures": [{"skill_name": "test-skill", "error_type": "tool_error", "task_input": "x", "error_message": "y"}],
            "skill_counts": {"test-skill": 1},
            "failure_counts": {"test-skill": 1},
        }

        # Mock gap analyzer
        pipeline.gap_analyzer = MagicMock()
        pipeline.gap_analyzer.analyze.return_value = [
            {
                "skill_name": "test-skill",
                "failure_count": 1,
                "severity": "warning",
                "recommendation": "Fix it",
                "sample_failures": [{"error_type": "tool_error", "error_message": "y", "task_input": "x"}],
            }
        ]

        # Mock patch engine
        pipeline.patch_engine = MagicMock()
        pipeline.patch_engine.generate_patches.return_value = [patch_dict]
        pipeline.patch_engine._resolve_skill_path.return_value = None

        # Mock benchmark runner
        pipeline.benchmark_runner = MagicMock()
        pipeline.benchmark_runner.run_benchmark.return_value = MagicMock(
            old_score=0.6, new_score=0.8, improvement=0.2, passed=True
        )

        # Mock safety net
        pipeline.safety_net = MagicMock()
        pipeline.safety_net.validate_patch.return_value = MagicMock(passed=True, issues=[], warnings=[])
        pipeline.safety_net.check_drift.return_value = MagicMock(drift_detected=False, drift_pct=0.0, action="accept")

        # Mock version manager
        pipeline.version_manager = MagicMock()
        pipeline.version_manager.create_version.return_value = "v1.0.0"

        result = pipeline.run("test-skill", mode="session")

        assert result.skill_name == "test-skill"
        assert result.failures_found == 1
        assert result.gaps_found == 1
        assert result.patches_generated == 1
        assert result.old_score == 0.6
        assert result.new_score == 0.8
        assert result.improvement == 0.2
        assert result.safety_passed is True
        assert result.version_created == "v1.0.0"
        assert result.passed is True
        assert result.duration_seconds > 0
        assert len(result.steps) == 7

        # All steps should be OK
        for step in result.steps:
            assert step["status"] == "ok"


# ── Safety failure stops pipeline ─────────────────────────────────────
class TestPipelineSafetyFailure:
    def test_safety_failure_blocks_versioning(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        old_skill = "---\nname: test-skill\ndescription: A test\n---\n# Old Body"
        new_skill = "---\nname: test-skill\ndescription: A test\n---\n# New Body"

        patch_dict = {
            "skill_name": "test-skill",
            "old_text": old_skill,
            "new_text": new_skill,
            "diff_summary": "changed",
            "rationale": "fix",
            "severity": "warning",
        }

        pipeline.grazer = MagicMock()
        pipeline.grazer.run.return_value = {
            "skill_usages": [{"skill_name": "test-skill", "error_type": "x", "task_input": "", "error_message": ""}],
            "failures": [{"skill_name": "test-skill", "error_type": "x", "task_input": "", "error_message": ""}],
            "skill_counts": {"test-skill": 1},
            "failure_counts": {"test-skill": 1},
        }

        pipeline.gap_analyzer = MagicMock()
        pipeline.gap_analyzer.analyze.return_value = [
            {"skill_name": "test-skill", "failure_count": 1, "severity": "warning",
             "recommendation": "Fix", "sample_failures": []}
        ]

        pipeline.patch_engine = MagicMock()
        pipeline.patch_engine.generate_patches.return_value = [patch_dict]

        pipeline.benchmark_runner = MagicMock()
        pipeline.benchmark_runner.run_benchmark.return_value = MagicMock(
            old_score=0.5, new_score=0.7, improvement=0.2, passed=True
        )

        # Safety fails
        pipeline.safety_net = MagicMock()
        pipeline.safety_net.validate_patch.return_value = MagicMock(
            passed=False, issues=["Dangerous pattern"], warnings=[]
        )

        pipeline.version_manager = MagicMock()

        result = pipeline.run("test-skill", mode="session")

        assert result.safety_passed is False
        assert result.version_created is None
        assert result.passed is False
        assert result.error and "SafetyNet" in result.error
        # Should not have reached version_save or drift_check
        step_names = [s["step"] for s in result.steps]
        assert "version_save" not in step_names
        assert "drift_check" not in step_names


# ── Drift rollback ────────────────────────────────────────────────────
class TestPipelineDriftRollback:
    def test_drift_rollback_clears_version(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        old_skill = "---\nname: s\ndescription: d\n---\n# old"
        new_skill = "---\nname: s\ndescription: d\n---\n# new"

        pipeline.grazer = MagicMock()
        pipeline.grazer.run.return_value = {
            "skill_usages": [{"skill_name": "s", "error_type": "e", "task_input": "", "error_message": ""}],
            "failures": [{"skill_name": "s", "error_type": "e", "task_input": "", "error_message": ""}],
            "skill_counts": {"s": 1}, "failure_counts": {"s": 1},
        }

        pipeline.gap_analyzer = MagicMock()
        pipeline.gap_analyzer.analyze.return_value = [
            {"skill_name": "s", "failure_count": 1, "severity": "info",
             "recommendation": "Fix", "sample_failures": []}
        ]

        pipeline.patch_engine = MagicMock()
        pipeline.patch_engine.generate_patches.return_value = [
            {"skill_name": "s", "old_text": old_skill, "new_text": new_skill,
             "diff_summary": "x", "rationale": "y", "severity": "info"}
        ]

        pipeline.benchmark_runner = MagicMock()
        pipeline.benchmark_runner.run_benchmark.return_value = MagicMock(
            old_score=0.8, new_score=0.6, improvement=-0.2, passed=False
        )

        pipeline.safety_net = MagicMock()
        pipeline.safety_net.validate_patch.return_value = MagicMock(passed=True, issues=[], warnings=[])
        # Drift says rollback
        pipeline.safety_net.check_drift.return_value = MagicMock(
            drift_detected=True, drift_pct=0.25, action="rollback"
        )
        pipeline.safety_net.auto_rollback.return_value = True

        pipeline.version_manager = MagicMock()
        pipeline.version_manager.create_version.return_value = "v1.0.0"

        result = pipeline.run("s", mode="session")

        assert result.passed is False
        assert result.version_created is None
        pipeline.safety_net.auto_rollback.assert_called_once()
        # Drift step should record the rollback
        drift_step = [s for s in result.steps if s["step"] == "drift_check"][0]
        assert drift_step["details"]["rolled_back"] is True


# ── Exception handling in steps ────────────────────────────────────────
class TestPipelineExceptionHandling:
    def test_grazer_exception_recorded(self, tmp_path):
        config = EvolutionConfig(hermes_agent_path=tmp_path)
        pipeline = Pipeline(config)

        pipeline.grazer = MagicMock()
        pipeline.grazer.run.side_effect = RuntimeError("DB locked")

        result = pipeline.run("test-skill", mode="session")
        assert result.error is not None
        assert "DB locked" in result.error
        grazer_step = [s for s in result.steps if s["step"] == "session_grazer"][0]
        assert grazer_step["status"] == "error"
        assert "DB locked" in grazer_step["error"]


# ── Pipeline uses config correctly ────────────────────────────────────
class TestPipelineConfig:
    def test_config_passes_to_safety_net(self, tmp_path):
        config = EvolutionConfig(
            hermes_agent_path=tmp_path,
            max_skill_size=5000,
            max_prompt_growth=0.1,
        )
        pipeline = Pipeline(config)
        assert pipeline.safety_net.max_size == 5000
        assert pipeline.safety_net.max_growth_pct == 0.1

    def test_default_config(self):
        pipeline = Pipeline()
        assert pipeline.config is not None
        assert pipeline.config.max_skill_size == 15_000
