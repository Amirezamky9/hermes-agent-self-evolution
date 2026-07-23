"""Integration tests: end-to-end flows across multiple modules."""

import tempfile
from pathlib import Path

import pytest

from evolution.core.version_store import VersionStore, SkillVersion
from evolution.core.rollback import RollbackManager
from evolution.core.constraints import ConstraintValidator
from evolution.core.config import EvolutionConfig


# ── Integration: VersionStore + RollbackManager ──────────────────────

class TestVersionStoreRollbackIntegration:
    """Full lifecycle: baseline → evolve → benchmark → rollback."""

    @pytest.fixture
    def store(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        s = VersionStore(db_path)
        s.record_baseline("int-test-skill", "baseline content")
        # Version 2
        s.record_evolved("int-test-skill", "evolved v2", parent_version=1,
                         metrics={"score": 0.75}, constraints_passed=True)
        # Version 3 — worse score
        s.record_evolved("int-test-skill", "evolved v3", parent_version=2,
                         metrics={"score": 0.60}, constraints_passed=False)
        return s

    def test_baseline_to_evolved_via_version_numbers(self, store):
        v1 = store.get_latest("int-test-skill")
        assert v1.version_number == 3  # latest
        assert v1.skill_text == "evolved v3"

        v2 = store.get(2)
        assert v2.skill_text == "evolved v2"
        assert v2.metrics["score"] == 0.75

    def test_rollback_worse_version_then_rebaseline(self, store):
        mgr = RollbackManager(store)
        # Rollback version 3 → 2 (worse score, revert)
        result = mgr.rollback_to_version("int-test-skill", target_version_number=2)
        assert result.success is True

        # Now latest should be version 4 (rollback record) with v2's text
        latest = store.get_latest("int-test-skill")
        assert latest.version_number == 4
        assert latest.skill_text == "evolved v2"
        assert latest.source == "rollback"

        # Record new evolution on top
        store.record_evolved("int-test-skill", "fixed v5", parent_version=4,
                             metrics={"score": 0.95}, constraints_passed=True)
        latest = store.get_latest("int-test-skill")
        assert latest.version_number == 5
        assert latest.metrics["score"] == 0.95

    def test_list_versions_timeline(self, store):
        versions = store.list_versions("int-test-skill")
        numbers = [v.version_number for v in versions]
        assert numbers == [3, 2, 1]  # newest first
        assert versions[-1].source == "baseline"

    def test_rollback_nonexistent_skill(self, store):
        mgr = RollbackManager(store)
        result = mgr.rollback_to_baseline("no-such-skill")
        assert result.success is False

    def test_multiple_skills_independent(self, store):
        store.record_baseline("other-skill", "other content")
        mgr = RollbackManager(store)
        result = mgr.rollback_to_baseline("other-skill")
        assert result.success is False  # only 1 version
        assert len(store.list_versions("other-skill")) == 1
        # Default skill unaffected
        assert len(store.list_versions("int-test-skill")) == 3


# ── Integration: ConstraintValidator + VersionStore ──────────────────

class TestConstraintsVersionIntegration:
    """Constraints gate what gets stored as a valid version."""

    def test_constraints_block_and_rollback(self):
        db_path = Path(tempfile.mktemp(suffix=".db"))
        store = VersionStore(db_path)
        config = EvolutionConfig(max_skill_size=500, max_prompt_growth=0.2)
        validator = ConstraintValidator(config)

        # Baseline — push through
        baseline_text = "---\nname: test\ndescription: a test\n---\n\nBody text here."
        store.record_baseline("gate-test", baseline_text)

        # Attempt big evolved — should fail constraints
        big_text = "---\nname: test\ndescription: a test\n---\n\n" + "x" * 800
        results = validator.validate_all(big_text, "skill", baseline_text=baseline_text)
        size_result = [r for r in results if r.constraint_name == "size_limit"][0]
        growth_result = [r for r in results if r.constraint_name == "growth_limit"][0]
        assert not size_result.passed  # 800 > 500
        assert not growth_result.passed  # way over 20%

    def test_constraints_pass_and_record(self):
        db_path = Path(tempfile.mktemp(suffix=".db"))
        store = VersionStore(db_path)
        config = EvolutionConfig(max_skill_size=5000, max_prompt_growth=0.5)
        validator = ConstraintValidator(config)

        baseline_text = "---\nname: test\ndescription: a test\n---\n\n" + "x" * 200
        evolved_text = "---\nname: test\ndescription: a test\n---\n\n" + "x" * 250

        results = validator.validate_all(evolved_text, "skill", baseline_text=baseline_text)
        assert all(r.passed for r in results), [r.message for r in results if not r.passed]

        store.record_baseline("valid-skill", baseline_text)
        vid_baseline = store.get_latest("valid-skill").version_number
        store.record_evolved("valid-skill", evolved_text, parent_version=vid_baseline,
                             metrics={"score": 0.8}, constraints_passed=True)
        latest = store.get_latest("valid-skill")
        assert latest.skill_text == evolved_text


# ── Integration: Full pipeline simulation ────────────────────────────

class TestFullPipelineSimulation:
    """Simulate the full optimization pipeline without LLM calls."""

    def test_simulate_optimize_benchmark_rollback(self):
        db_path = Path(tempfile.mktemp(suffix=".db"))
        store = VersionStore(db_path)
        config = EvolutionConfig(max_skill_size=10000, max_prompt_growth=0.5)
        validator = ConstraintValidator(config)
        mgr = RollbackManager(store)

        # Step 1: Baseline — longer so evolved growth stays under 50%
        baseline = "---\nname: my-skill\ndescription: test\n---\n\n## Original\nDo X and Y.\nCheck Z. Verify output. Handle edge cases. Return result." + "x" * 100
        store.record_baseline("my-skill", baseline)
        v1 = store.get_latest("my-skill")
        assert v1 is not None
        assert v1.version_number == 1

        # Step 2: Constraint check for evolved version
        evolved = "---\nname: my-skill\ndescription: test\n---\n\n## Optimized\nAlways do X before Y. Then verify Z is correct. Cap at 10 iterations." + "x" * 100
        results = validator.validate_all(evolved, "skill", baseline_text=baseline)
        constraints_pass = all(r.passed for r in results)

        # Step 3: If constraints pass, record evolved
        if constraints_pass:
            store.record_evolved("my-skill", evolved, parent_version=1,
                                 metrics={"score": 0.92}, constraints_passed=True)
        else:
            store.record_evolved("my-skill", evolved, parent_version=1,
                                 metrics={"score": 0.92}, constraints_passed=False)

        assert store.get_latest("my-skill").version_number == 2
        assert constraints_pass  # small change should pass

        # Step 4: Benchmark comparison (simulated)
        baseline_v = store.get(1)
        evolved_v = store.get(2)
        assert baseline_v.skill_text != evolved_v.skill_text

        # Step 5: Simulate regression — rollback
        # Store a failed version, then rollback
        bad = "---\nname: my-skill\ndescription: test\n---\n\n" + "x" * 500
        store.record_evolved("my-skill", bad, parent_version=2,
                             metrics={"score": 0.3}, constraints_passed=False)
        assert store.get_latest("my-skill").version_number == 3

        result = mgr.rollback_to_version("my-skill", target_version_number=2)
        assert result.success is True
        latest = store.get_latest("my-skill")
        assert latest.version_number == 4
        assert latest.source == "rollback"
        assert latest.skill_text == evolved  # rolled back to v2 content

    def test_simulate_regression_auto_rollback(self):
        """What supervisor would do: detect regression → auto rollback."""
        db_path = Path(tempfile.mktemp(suffix=".db"))
        store = VersionStore(db_path)
        mgr = RollbackManager(store)

        store.record_baseline("auto-skill", "baseline good")
        store.record_evolved("auto-skill", "evolved great", parent_version=1,
                             metrics={"score": 0.9}, constraints_passed=True)
        store.record_evolved("auto-skill", "evolved bad", parent_version=2,
                             metrics={"score": 0.4}, constraints_passed=False)

        # Detect regression: latest score < previous score
        v2 = store.get(2)
        v3 = store.get(3)
        assert v3.metrics["score"] < v2.metrics["score"]  # 0.4 < 0.9

        # Auto-rollback
        result = mgr.rollback_to_version("auto-skill", target_version_number=2)
        assert result.success is True
        latest = store.get_latest("auto-skill")
        assert latest.skill_text == "evolved great"
        assert latest.source == "rollback"
