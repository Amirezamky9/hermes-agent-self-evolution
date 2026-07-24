"""Tests for patch_engine — uses mock LLM and tmp_path, no real DB needed."""
import pytest
from unittest.mock import MagicMock

from evolution.core.patch_engine import (
    PatchEngine,
    PatchProposal,
    _parse_frontmatter,
    _strip_frontmatter,
    _build_diff_summary,
)


# ── Fixtures ────────────────────────────────────────────────────────

SAMPLE_SKILL = """---
name: test-skill
description: A test skill for unit tests
---

# Test Skill

Do X, then Y.

## Steps

1. First step
2. Second step
"""

SAMPLE_SKILL_MINIMAL = """---
name: minimal
description: minimal
---

Body only."""


@pytest.fixture
def engine(tmp_path):
    """Create a PatchEngine with skills in tmp_path."""
    skills_dir = tmp_path / "skills" / "test-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(SAMPLE_SKILL)
    return PatchEngine(hermes_path=str(tmp_path))


@pytest.fixture
def sample_gap():
    return {
        "skill_name": "test-skill",
        "severity": "warning",
        "recommendation": "Fix the lint error in SKILL.md",
        "sample_failures": [
            {"error_type": "lint_error", "error_message": "Missing heading", "task_input": "load skill"},
        ],
    }


# ── Frontmatter helpers ─────────────────────────────────────────────

class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        fm = _parse_frontmatter("---\nname: x\ndescription: y\n---\nbody")
        assert fm["name"] == "x"
        assert fm["description"] == "y"

    def test_no_frontmatter(self):
        assert _parse_frontmatter("just body") == {}

    def test_empty_frontmatter(self):
        assert _parse_frontmatter("---\n---\nbody") == {}

    def test_broken_yaml(self):
        fm = _parse_frontmatter("---\n:invalid: yaml: [---\nbody")
        assert fm == {}


class TestStripFrontmatter:
    def test_strips_frontmatter(self):
        body = _strip_frontmatter("---\nname: x\n---\nbody")
        assert body == "body"

    def test_no_frontmatter_returns_same(self):
        assert _strip_frontmatter("just body") == "just body"

    def test_strips_leading_newline(self):
        body = _strip_frontmatter("---\nname: x\n---\n\nbody")
        assert body == "body"


class TestBuildDiffSummary:
    def test_no_change(self):
        assert _build_diff_summary("a\nb", "a\nb") == "no change"

    def test_lines_added(self):
        assert _build_diff_summary("a\nb", "a\nb\nc") == "+1 lines"

    def test_lines_removed(self):
        assert _build_diff_summary("a\nb\nc", "a\nb") == "-1 lines"

    def test_content_changed_same_lines(self):
        assert _build_diff_summary("a\nb", "x\ny") == "content changed, same line count"


# ── PatchProposal ──────────────────────────────────────────────────

class TestPatchProposal:
    def test_to_dict(self):
        p = PatchProposal(
            skill_name="s", old_text="old", new_text="new",
            diff_summary="+1", rationale="fix", severity="warning",
        )
        d = p.to_dict()
        assert d["skill_name"] == "s"
        assert d["old_text"] == "old"
        assert d["new_text"] == "new"
        assert d["severity"] == "warning"


# ── PatchEngine.validate_patch ──────────────────────────────────────

class TestValidatePatch:
    def test_valid_patch_passes(self, engine):
        old = "---\nname: x\ndescription: y\n---\nOld body."
        new = "---\nname: x\ndescription: y\n---\nNew body."
        result = engine.validate_patch(old, new)
        assert result["passed"] is True
        assert result["issues"] == []

    def test_missing_frontmatter_in_new_fails(self, engine):
        old = "---\nname: x\ndescription: y\n---\nBody."
        result = engine.validate_patch(old, "Just body, no frontmatter.")
        assert result["passed"] is False
        assert any("frontmatter" in i.lower() for i in result["issues"])

    def test_removed_name_key_fails(self, engine):
        old = "---\nname: x\ndescription: y\n---\nBody."
        new = "---\ndescription: y\n---\nBody."
        result = engine.validate_patch(old, new)
        assert result["passed"] is False
        assert any("name" in i for i in result["issues"])

    def test_changed_name_fails(self, engine):
        old = "---\nname: x\ndescription: y\n---\nBody."
        new = "---\nname: z\ndescription: y\n---\nBody."
        result = engine.validate_patch(old, new)
        assert result["passed"] is False
        assert any("name" in i for i in result["issues"])

    def test_empty_new_text_fails(self, engine):
        old = "---\nname: x\ndescription: y\n---\nBody."
        result = engine.validate_patch(old, "")
        assert result["passed"] is False
        assert any("empty" in i.lower() for i in result["issues"])


# ── PatchEngine.generate_patches (mocked LLM) ──────────────────────

class TestGeneratePatches:
    def test_skips_unknown_skill(self, engine):
        gaps = [{"skill_name": "nonexistent", "severity": "warning", "recommendation": "fix", "sample_failures": []}]
        patches = engine.generate_patches(gaps)
        assert patches == []

    def test_generates_validated_patch(self, engine, sample_gap):
        mock_result = MagicMock()
        mock_result.new_body = "New improved body.\n\nExtra instructions added."
        mock_result.rationale = "Added lint fix"
        engine._patch_gen.forward = MagicMock(return_value=mock_result)

        patches = engine.generate_patches([sample_gap])
        assert len(patches) == 1
        p = patches[0]
        assert p["skill_name"] == "test-skill"
        assert p["old_text"] == SAMPLE_SKILL
        assert "---" in p["new_text"]
        assert "name: test-skill" in p["new_text"]
        assert "New improved body" in p["new_text"]
        assert p["severity"] == "warning"

    def test_skips_invalid_patch(self, engine, sample_gap):
        """If LLM returns empty body, patch is skipped."""
        mock_result = MagicMock()
        mock_result.new_body = ""
        mock_result.rationale = "test"
        engine._patch_gen.forward = MagicMock(return_value=mock_result)
        patches = engine.generate_patches([sample_gap])
        assert patches == []

    def test_preserves_frontmatter(self, engine, sample_gap):
        mock_result = MagicMock()
        mock_result.new_body = "Updated body content here."
        mock_result.rationale = "Improved clarity"
        engine._patch_gen.forward = MagicMock(return_value=mock_result)

        patches = engine.generate_patches([sample_gap])
        assert len(patches) == 1
        new_text = patches[0]["new_text"]
        # Frontmatter keys preserved
        assert "name: test-skill" in new_text
        assert "description: A test skill for unit tests" in new_text

    def test_empty_gaps_returns_empty(self, engine):
        assert engine.generate_patches([]) == []


# ── PatchEngine.apply_patch ─────────────────────────────────────────

class TestApplyPatch:
    def test_apply_patch_writes_file(self, engine, tmp_path):
        skill_path = tmp_path / "skills" / "test-skill" / "SKILL.md"
        new_text = "---\nname: test-skill\ndescription: updated\n---\n\nNew content."
        patch = {"new_text": new_text}
        result = engine.apply_patch(str(skill_path), patch)
        assert result is True
        assert skill_path.read_text() == new_text

    def test_apply_patch_nonexistent_file(self, engine, tmp_path):
        result = engine.apply_patch(str(tmp_path / "nope" / "SKILL.md"), {"new_text": "x"})
        assert result is False

    def test_apply_patch_empty_new_text(self, engine, tmp_path):
        skill_path = tmp_path / "skills" / "test-skill" / "SKILL.md"
        result = engine.apply_patch(str(skill_path), {"new_text": ""})
        assert result is False
