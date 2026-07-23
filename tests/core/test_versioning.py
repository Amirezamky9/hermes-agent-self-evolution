"""Tests for version_store, rollback, and benchmark."""

import json
import tempfile
from pathlib import Path

import pytest

from evolution.core.version_store import VersionStore, SkillVersion
from evolution.core.rollback import RollbackManager
from evolution.core.benchmark import BenchmarkEvaluator, BenchmarkResult
from evolution.core.config import EvolutionConfig


# ── VersionStore ────────────────────────────────────────────────────

@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    return VersionStore(db_path)


class TestVersionStore:
    def test_init_creates_db(self, store):
        assert store.db_path.exists()

    def test_save_and_get(self, store):
        v = SkillVersion(
            skill_name="test-skill",
            version_number=1,
            skill_text="# Test Skill\nHello",
            source="baseline",
        )
        vid = store.save(v)
        assert vid > 0

        loaded = store.get(vid)
        assert loaded is not None
        assert loaded.skill_name == "test-skill"
        assert loaded.skill_text == "# Test Skill\nHello"
        assert loaded.source == "baseline"

    def test_record_baseline(self, store):
        vid = store.record_baseline("my-skill", "raw content")
        assert vid > 0
        latest = store.get_latest("my-skill")
        assert latest is not None
        assert latest.version_number == 1
        assert latest.source == "baseline"

    def test_record_evolved(self, store):
        baseline_vid = store.record_baseline("my-skill", "original")
        evolved_vid = store.record_evolved(
            skill_name="my-skill",
            skill_text="evolved content",
            parent_version=baseline_vid,
            metrics={"score": 0.85},
        )
        assert evolved_vid > baseline_vid
        latest = store.get_latest("my-skill")
        assert latest.version_number == 2
        assert latest.metrics["score"] == 0.85

    def test_next_version_number(self, store):
        store.record_baseline("s1", "text")
        store.record_baseline("s1", "text2")
        # s1 has versions 1, 2
        assert store.next_version_number("s1") == 3
        # s2 has no versions
        assert store.next_version_number("s2") == 1

    def test_list_versions_newest_first(self, store):
        store.record_baseline("s1", "v1")
        store.record_evolved("s1", "v2", parent_version=1, metrics={})
        store.record_evolved("s1", "v3", parent_version=2, metrics={})

        versions = store.list_versions("s1")
        assert len(versions) == 3
        assert versions[0].version_number == 3
        assert versions[1].version_number == 2
        assert versions[2].version_number == 1

    def test_record_rollback(self, store):
        store.record_baseline("s1", "baseline")
        store.record_evolved("s1", "evolved", parent_version=1, metrics={})

        rollback_vid = store.record_rollback("s1", rollback_to_version_id=1)
        latest = store.get_latest("s1")
        assert latest.source == "rollback"
        assert latest.skill_text == "baseline"

    def test_get_nonexistent(self, store):
        assert store.get(999) is None

    def test_get_latest_nonexistent(self, store):
        assert store.get_latest("nonexistent") is None


# ── RollbackManager ─────────────────────────────────────────────────

@pytest.fixture
def rollback_store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    store = VersionStore(db_path)
    # Setup: baseline + evolved + another evolved
    store.record_baseline("test-skill", "baseline content")
    store.record_evolved("test-skill", "evolved v2", parent_version=1,
                         metrics={"score": 0.8}, constraints_passed=True)
    store.record_evolved("test-skill", "evolved v3", parent_version=2,
                         metrics={"score": 0.9}, constraints_passed=True)
    return store


class TestRollbackManager:
    def test_rollback_to_version(self, rollback_store):
        mgr = RollbackManager(rollback_store)
        result = mgr.rollback_to_version("test-skill", target_version_number=2)

        assert result.success is True
        assert result.from_version == 3
        assert result.to_version == 2
        assert result.new_version_id > 0

        # Latest should now be the rollback
        latest = rollback_store.get_latest("test-skill")
        assert latest.source == "rollback"
        assert latest.skill_text == "evolved v2"

    def test_rollback_to_baseline(self, rollback_store):
        mgr = RollbackManager(rollback_store)
        result = mgr.rollback_to_baseline("test-skill")

        assert result.success is True
        assert result.to_version == 1

        latest = rollback_store.get_latest("test-skill")
        assert latest.skill_text == "baseline content"

    def test_rollback_to_same_version_fails(self, rollback_store):
        mgr = RollbackManager(rollback_store)
        result = mgr.rollback_to_version("test-skill", target_version_number=3)

        assert result.success is False
        assert "Already at target" in result.message

    def test_rollback_nonexistent_version(self, rollback_store):
        mgr = RollbackManager(rollback_store)
        result = mgr.rollback_to_version("test-skill", target_version_number=99)

        assert result.success is False
        assert "not found" in result.message

    def test_rollback_no_versions(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            store = VersionStore(Path(f.name))
        mgr = RollbackManager(store)
        result = mgr.rollback_to_version("nope", target_version_number=1)
        assert result.success is False

    def test_diff_versions(self, rollback_store):
        mgr = RollbackManager(rollback_store)
        diff = mgr.diff_versions("test-skill", version_a=1, version_b=2)
        assert diff is not None
        assert "baseline content" in diff
        assert "evolved v2" in diff


# ── BenchmarkEvaluator ──────────────────────────────────────────────

class TestBenchmarkEvaluator:
    def test_evaluate_no_tasks(self):
        config = EvolutionConfig()
        evaluator = BenchmarkEvaluator(config)
        result = evaluator.evaluate("skill", "body", 1, [])
        assert result.num_examples == 0
        assert result.error == "No test tasks provided"
