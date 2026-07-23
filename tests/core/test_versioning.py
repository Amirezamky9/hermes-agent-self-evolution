"""Tests for version_store, rollback, constraints, and skill_module."""

import json
import tempfile
from pathlib import Path

import pytest

from evolution.core.version_store import VersionStore, SkillVersion
from evolution.core.rollback import RollbackManager
from evolution.core.constraints import ConstraintValidator, ConstraintResult
from evolution.core.config import EvolutionConfig
from evolution.skills.skill_module import load_skill, find_skill, reassemble_skill, SkillModule


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
        assert store.next_version_number("s1") == 3
        assert store.next_version_number("s2") == 1

    def test_list_versions_newest_first(self, store):
        store.record_baseline("s1", "v1")
        store.record_evolved("s1", "v2", parent_version=1, metrics={})
        store.record_evolved("s1", "v3", parent_version=2, metrics={})
        versions = store.list_versions("s1")
        assert len(versions) == 3
        assert versions[0].version_number == 3
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

    def test_multiple_skills_isolated(self, store):
        store.record_baseline("skill-a", "a-content")
        store.record_baseline("skill-b", "b-content")
        assert store.get_latest("skill-a").skill_text == "a-content"
        assert store.get_latest("skill-b").skill_text == "b-content"
        assert len(store.list_versions("skill-a")) == 1

    def test_metrics_roundtrip(self, store):
        metrics = {"score": 0.9, "improvement": 0.15, "tags": ["test"]}
        vid = store.record_baseline("s1", "text")
        store.record_evolved("s1", "text2", parent_version=vid, metrics=metrics)
        loaded = store.get_latest("s1")
        assert loaded.metrics == metrics


# ── RollbackManager ─────────────────────────────────────────────────

@pytest.fixture
def rollback_store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    store = VersionStore(db_path)
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

    def test_get_skill_text(self, rollback_store):
        mgr = RollbackManager(rollback_store)
        text = mgr.get_skill_text("test-skill", version_number=1)
        assert text == "baseline content"
        assert mgr.get_skill_text("test-skill", version_number=99) is None

    def test_rollback_last(self, rollback_store):
        mgr = RollbackManager(rollback_store)
        result = mgr.rollback_last("test-skill")
        assert result.success is True
        assert result.to_version == 2

    def test_rollback_last_no_parent(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            store = VersionStore(Path(f.name))
        store.record_baseline("s1", "only version")
        mgr = RollbackManager(store)
        result = mgr.rollback_last("s1")
        assert result.success is False


# ── Constraints ─────────────────────────────────────────────────────

class TestConstraints:
    def test_size_ok(self):
        config = EvolutionConfig(max_skill_size=10000)
        v = ConstraintValidator(config)
        result = v._check_size("x" * 500, "skill")
        assert result.passed is True

    def test_size_exceeded(self):
        config = EvolutionConfig(max_skill_size=100)
        v = ConstraintValidator(config)
        result = v._check_size("x" * 200, "skill")
        assert result.passed is False
        assert "200/100" in result.message

    def test_growth_ok(self):
        config = EvolutionConfig(max_prompt_growth=0.2)
        v = ConstraintValidator(config)
        result = v._check_growth("x" * 110, "x" * 100, "skill")
        assert result.passed is True

    def test_growth_exceeded(self):
        config = EvolutionConfig(max_prompt_growth=0.1)
        v = ConstraintValidator(config)
        result = v._check_growth("x" * 150, "x" * 100, "skill")
        assert result.passed is False

    def test_non_empty(self):
        config = EvolutionConfig()
        v = ConstraintValidator(config)
        assert v._check_non_empty("hello").passed is True
        assert v._check_non_empty("").passed is False
        assert v._check_non_empty("   ").passed is False

    def test_skill_structure_valid(self):
        config = EvolutionConfig()
        v = ConstraintValidator(config)
        text = "---\nname: test\ndescription: a test\n---\n\nBody"
        result = v._check_skill_structure(text)
        assert result.passed is True

    def test_skill_structure_no_frontmatter(self):
        config = EvolutionConfig()
        v = ConstraintValidator(config)
        result = v._check_skill_structure("# Just a heading")
        assert result.passed is False

    def test_validate_all(self):
        config = EvolutionConfig(max_skill_size=10000, max_prompt_growth=0.5)
        v = ConstraintValidator(config)
        baseline = "---\nname: old\ndescription: old\n---\n\n" + "x" * 200
        text = "---\nname: test\ndescription: a test\n---\n\n" + "x" * 250
        results = v.validate_all(text, "skill", baseline_text=baseline)
        assert all(r.passed for r in results), [r.message for r in results if not r.passed]

    def test_validate_all_bad_growth(self):
        config = EvolutionConfig(max_skill_size=10000, max_prompt_growth=0.1)
        v = ConstraintValidator(config)
        text = "---\nname: test\ndescription: a test\n---\n\n" + "x" * 5000
        results = v.validate_all(text, "skill", baseline_text="old")
        assert not all(r.passed for r in results)


# ── SkillModule ─────────────────────────────────────────────────────

class TestSkillModule:
    def test_load_skill_valid(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("---\nname: my-skill\ndescription: test skill\n---\n\n## Body\nDo stuff.")
        result = load_skill(skill_file)
        assert result["name"] == "my-skill"
        assert result["description"] == "test skill"
        assert "## Body" in result["body"]
        assert result["raw"].startswith("---")

    def test_load_skill_no_frontmatter(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("# Just body\nNo frontmatter here.")
        result = load_skill(skill_file)
        assert result["name"] == ""
        assert result["body"] == "# Just body\nNo frontmatter here."

    def test_reassemble_skill(self):
        frontmatter = "name: test\ndescription: test"
        body = "## Updated Body\nNew content."
        result = reassemble_skill(frontmatter, body)
        assert result.startswith("---\n")
        assert "name: test" in result
        assert "## Updated Body" in result

    def test_find_skill_direct_match(self, tmp_path):
        # find_skill searches hermes_agent_path / "skills" recursively
        skills_dir = tmp_path / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: test\n---\nBody")
        result = find_skill("my-skill", tmp_path)
        assert result is not None
        assert result.name == "SKILL.md"

    def test_find_skill_not_found(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(parents=True)
        result = find_skill("nonexistent", tmp_path)
        assert result is None

    def test_find_skill_fuzzy_match(self, tmp_path):
        skills_dir = tmp_path / "skills" / "some-dir"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\nname: my-awesome-skill\ndescription: test\n---\nBody")
        result = find_skill("my-awesome-skill", tmp_path)
        assert result is not None
