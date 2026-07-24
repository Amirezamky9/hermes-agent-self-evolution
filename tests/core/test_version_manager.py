"""Tests for VersionManager — file-based skill versioning."""
import json
import tempfile
from pathlib import Path

import pytest

from evolution.core.version_manager import VersionManager, MAX_VERSIONS_PER_SKILL


@pytest.fixture
def vm(tmp_path):
    return VersionManager(str(tmp_path / "versions"))


class TestCreateVersion:
    def test_creates_first_version(self, vm):
        v = vm.create_version("my-skill", "# Skill\nBody", {"source": "baseline"})
        assert v == "v1.0.0"
        skill_dir = vm.versions_dir / "my-skill" / "v1.0.0"
        assert (skill_dir / "SKILL.md").read_text() == "# Skill\nBody"
        meta = json.loads((skill_dir / "meta.json").read_text())
        assert meta["version"] == "v1.0.0"
        assert meta["source"] == "baseline"

    def test_increments_patch(self, vm):
        vm.create_version("s1", "v1", {"source": "manual"})
        v2 = vm.create_version("s1", "v2", {"source": "manual"})
        assert v2 == "v1.0.1"

    def test_versions_independent_across_skills(self, vm):
        vm.create_version("a", "a1", {})
        vm.create_version("b", "b1", {})
        v2 = vm.create_version("a", "a2", {})
        assert v2 == "v1.0.1"
        assert vm.get_current("b")["version"] == "v1.0.0"

    def test_max_versions_enforced(self, vm):
        for i in range(MAX_VERSIONS_PER_SKILL + 5):
            vm.create_version("overflow", f"v{i}", {})
        versions = vm.list_versions("overflow")
        assert len(versions) == MAX_VERSIONS_PER_SKILL
        # oldest (v1.0.0) should be gone
        assert versions[-1]["version"] != "v1.0.0"


class TestListVersions:
    def test_empty_skill(self, vm):
        assert vm.list_versions("nonexistent") == []

    def test_newest_first(self, vm):
        vm.create_version("s1", "first", {"source": "manual"})
        vm.create_version("s1", "second", {"source": "manual"})
        vm.create_version("s1", "third", {"source": "manual"})
        vs = vm.list_versions("s1")
        assert [v["version"] for v in vs] == ["v1.0.2", "v1.0.1", "v1.0.0"]


class TestRollbackTo:
    def test_rollback_success(self, vm):
        vm.create_version("s1", "v1-content", {"source": "manual"})
        vm.create_version("s1", "v2-content", {"source": "manual"})
        result = vm.rollback_to("s1", "v1.0.0")
        assert result is True
        current = vm.get_current("s1")
        assert current["source"] == "rollback"
        # New version was created with the rolled-back content
        skill_file = vm.versions_dir / "s1" / current["version"] / "SKILL.md"
        assert skill_file.read_text() == "v1-content"

    def test_rollback_nonexistent_version(self, vm):
        vm.create_version("s1", "content", {})
        assert vm.rollback_to("s1", "v9.9.9") is False

    def test_rollback_without_v_prefix(self, vm):
        vm.create_version("s1", "content", {})
        result = vm.rollback_to("s1", "1.0.0")
        assert result is True


class TestGetCurrent:
    def test_returns_none_for_empty(self, vm):
        assert vm.get_current("nope") is None

    def test_returns_latest(self, vm):
        vm.create_version("s1", "first", {})
        vm.create_version("s1", "second", {})
        assert vm.get_current("s1")["version"] == "v1.0.1"


class TestDiffVersions:
    def test_diff_two_versions(self, vm):
        vm.create_version("s1", "line1\nline2\n", {})
        vm.create_version("s1", "line1\nline3\n", {})
        diff = vm.diff_versions("s1", "v1.0.0", "v1.0.1")
        assert "line2" in diff
        assert "line3" in diff
        assert "-line2" in diff
        assert "+line3" in diff

    def test_diff_missing_version(self, vm):
        vm.create_version("s1", "content", {})
        assert vm.diff_versions("s1", "v1.0.0", "v9.9.9") == ""

    def test_diff_without_v_prefix(self, vm):
        vm.create_version("s1", "a", {})
        vm.create_version("s1", "b", {})
        diff = vm.diff_versions("s1", "1.0.0", "1.0.1")
        assert diff != ""
