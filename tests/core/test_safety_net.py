"""Tests for SafetyNet — patch validation, drift detection, auto-rollback."""
import json
import tempfile
from pathlib import Path

import pytest

from evolution.core.safety_net import SafetyNet, ValidationResult, DriftResult
from evolution.core.version_manager import VersionManager


# ── fixtures ────────────────────────────────────────────────────────

VALID_SKILL = """---
name: test-skill
description: A valid test skill.
---

# Test Skill

## Usage

- Step one
- Step two
"""

TOO_LARGE_SKILL = "---\nname: big\ndescription: big\n---\n" + "x" * 16000


# ── Validation: frontmatter ─────────────────────────────────────────

class TestFrontmatterCheck:
    def test_valid_frontmatter_passes(self):
        sn = SafetyNet()
        result = sn.validate_patch("", VALID_SKILL, "test")
        assert "frontmatter" in result.checks_run
        assert not any("frontmatter" in i for i in result.issues)

    def test_missing_delimiters(self):
        sn = SafetyNet()
        result = sn.validate_patch("", "no frontmatter at all", "test")
        assert result.passed is False
        assert any("---" in i for i in result.issues)

    def test_missing_name_field(self):
        sn = SafetyNet()
        text = "---\ndescription: only desc\n---\n# Body"
        result = sn.validate_patch("", text, "test")
        assert result.passed is False
        assert any("name:" in i for i in result.issues)

    def test_missing_description_field(self):
        sn = SafetyNet()
        text = "---\nname: skill\n---\n# Body"
        result = sn.validate_patch("", text, "test")
        assert result.passed is False
        assert any("description:" in i for i in result.issues)


# ── Validation: size ────────────────────────────────────────────────

class TestSizeCheck:
    def test_within_limit(self):
        sn = SafetyNet()
        result = sn.validate_patch("", VALID_SKILL, "test")
        assert not any("size" in i for i in result.issues)

    def test_exceeds_limit(self):
        sn = SafetyNet(max_size=100)
        result = sn.validate_patch("", VALID_SKILL, "test")
        assert result.passed is False
        assert any("exceeds max size" in i for i in result.issues)

    def test_approaching_limit_warns(self):
        sn = SafetyNet(max_size=200)
        # VALID_SKILL is ~100 chars, 80% of 200 is 160, so near threshold
        big = "---\nname: s\ndescription: d\n---\n" + "x" * 160
        result = sn.validate_patch("", big, "test")
        assert any("approaching max size" in w for w in result.warnings)

    def test_check_recorded(self):
        sn = SafetyNet()
        sn.validate_patch("", VALID_SKILL, "test")
        assert "size" in sn.validate_patch("", VALID_SKILL, "test").checks_run


# ── Validation: growth ──────────────────────────────────────────────

class TestGrowthCheck:
    def test_within_growth_limit(self):
        sn = SafetyNet()
        old = "a" * 1000
        new = "a" * 1100  # 10% growth
        result = sn.validate_patch(old, new, "test")
        assert "growth" in result.checks_run
        assert not any("growth" in w for w in result.warnings)

    def test_excessive_growth_warns(self):
        sn = SafetyNet(max_growth_pct=0.2)
        old = "a" * 1000
        new = "a" * 1300  # 30% growth
        result = sn.validate_patch(old, new, "test")
        assert any("Excessive growth" in w for w in result.warnings)

    def test_empty_old_text_no_crash(self):
        sn = SafetyNet()
        result = sn.validate_patch("", VALID_SKILL, "test")
        # Should not crash, no growth warning for empty old
        assert "growth" in result.checks_run


# ── Validation: content ─────────────────────────────────────────────

class TestContentCheck:
    def test_empty_text(self):
        sn = SafetyNet()
        result = sn.validate_patch("", "", "test")
        assert result.passed is False
        assert any("empty" in i for i in result.issues)

    def test_import_os_detected(self):
        sn = SafetyNet()
        text = "---\nname: x\ndescription: y\n---\nimport os\nos.system('rm -rf /')"
        result = sn.validate_patch("", text, "test")
        assert result.passed is False
        assert any("Dangerous" in i for i in result.issues)

    def test_eval_detected(self):
        sn = SafetyNet()
        text = "---\nname: x\ndescription: y\n---\neval(input())"
        result = sn.validate_patch("", text, "test")
        assert result.passed is False
        assert any("Dangerous" in i for i in result.issues)

    def test_api_key_detected(self):
        sn = SafetyNet()
        text = "---\nname: x\ndescription: y\n---\nsk-abcdefghijklmnopqrstuvwxyz123456"
        result = sn.validate_patch("", text, "test")
        assert result.passed is False
        assert any("API key" in i for i in result.issues)


# ── Validation: structure ───────────────────────────────────────────

class TestStructureCheck:
    def test_has_headings(self):
        sn = SafetyNet()
        result = sn.validate_patch("", VALID_SKILL, "test")
        assert "structure" in result.checks_run
        assert not any("structure" in w for w in result.warnings)

    def test_has_bullets(self):
        sn = SafetyNet()
        text = "---\nname: x\ndescription: y\n---\n- item 1\n- item 2"
        result = sn.validate_patch("", text, "test")
        assert not any("structure" in w for w in result.warnings)

    def test_no_structure_warns(self):
        sn = SafetyNet()
        text = "---\nname: x\ndescription: y\n---\nplain text no formatting"
        result = sn.validate_patch("", text, "test")
        assert any("lack structure" in w for w in result.warnings)


# ── Drift detection ─────────────────────────────────────────────────

class TestCheckDrift:
    def test_accept_when_improved(self):
        sn = SafetyNet()
        result = sn.check_drift("skill", 0.8, 0.9)
        assert result.action == "accept"
        assert result.drift_detected is False

    def test_accept_when_minor_drop(self):
        sn = SafetyNet()
        result = sn.check_drift("skill", 0.8, 0.78)  # 2.5% drop
        assert result.action == "accept"

    def test_warn_when_moderate_drop(self):
        sn = SafetyNet()
        result = sn.check_drift("skill", 0.8, 0.74)  # 7.5% drop
        assert result.action == "warn"
        assert result.drift_detected is True
        assert 0.05 < result.drift_pct <= 0.10

    def test_rollback_when_severe_drop(self):
        sn = SafetyNet()
        result = sn.check_drift("skill", 0.8, 0.70)  # 12.5% drop
        assert result.action == "rollback"
        assert result.drift_detected is True
        assert result.drift_pct > 0.10

    def test_zero_old_score(self):
        sn = SafetyNet()
        result = sn.check_drift("skill", 0.0, 0.5)
        assert result.action == "accept"
        assert result.drift_pct == 0.0


# ── Auto-rollback ───────────────────────────────────────────────────

class TestAutoRollback:
    def test_rollback_to_previous_version(self, tmp_path):
        vm = VersionManager(str(tmp_path / "versions"))
        sn = SafetyNet()
        sn._version_manager = vm

        vm.create_version("skill", "version 1", {"source": "baseline"})
        vm.create_version("skill", "version 2", {"source": "evolution"})

        result = sn.auto_rollback("skill", "drift detected")
        assert result is True

        current = vm.get_current("skill")
        assert current["source"] == "rollback"
        skill_file = vm.versions_dir / "skill" / current["version"] / "SKILL.md"
        assert skill_file.read_text() == "version 1"

    def test_rollback_skips_rollback_entries(self, tmp_path):
        vm = VersionManager(str(tmp_path / "versions"))
        sn = SafetyNet()
        sn._version_manager = vm

        vm.create_version("skill", "v1", {"source": "baseline"})
        vm.create_version("skill", "v2-rolled", {"source": "rollback"})
        vm.create_version("skill", "v3", {"source": "evolution"})

        result = sn.auto_rollback("skill", "bad evolution")
        assert result is True
        current = vm.get_current("skill")
        skill_file = vm.versions_dir / "skill" / current["version"] / "SKILL.md"
        assert skill_file.read_text() == "v1"

    def test_rollback_fails_with_single_version(self, tmp_path):
        vm = VersionManager(str(tmp_path / "versions"))
        sn = SafetyNet()
        sn._version_manager = vm

        vm.create_version("skill", "only", {"source": "baseline"})
        result = sn.auto_rollback("skill", "no prior version")
        assert result is False

    def test_rollback_fails_with_no_versions(self, tmp_path):
        vm = VersionManager(str(tmp_path / "versions"))
        sn = SafetyNet()
        sn._version_manager = vm

        result = sn.auto_rollback("skill", "nothing exists")
        assert result is False
