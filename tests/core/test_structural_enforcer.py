"""Tests for Structural Pattern Enforcer (Phase D)."""

import pytest

from evolution.core.structural_enforcer import (
    Injection,
    StructuralEnforcer,
    StructuralReport,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def enforcer():
    return StructuralEnforcer()


EMPTY_SKILL = ""

MINIMAL_SKILL = """# My Skill

Run a simple command.
```bash
echo hello
```
"""

FULLY_FEATURED_SKILL = """---
triggers:
  - skill load
  - user asks for help
version: 1.2.3
---

# My Full Skill

## Overview

This skill does everything correctly.

## When to Use

- Use this when you need full coverage.

## Usage

```bash
export CONFIG_PATH="/tmp/config"
if [[ -n "$CONFIG_PATH" ]]; then
    run_tool 2>/dev/null || true
fi
```

## Verification

Check the output matches expected.

## Pitfalls

Don't forget to set CONFIG_PATH first.
"""


# ── analyze ───────────────────────────────────────────────────────────────

class TestAnalyze:
    def test_empty_skill(self, enforcer):
        r = enforcer.analyze(EMPTY_SKILL)
        assert isinstance(r, StructuralReport)
        assert r.completeness_score == 0.0
        assert len(r.missing_patterns) == 10  # every pattern missing

    def test_minimal_skill(self, enforcer):
        r = enforcer.analyze(MINIMAL_SKILL)
        assert r.completeness_score < 50.0
        assert r.has_bash_blocks is True
        assert r.has_triggers is False
        assert r.has_version is False
        assert r.has_error_handling is False

    def test_fully_featured_skill(self, enforcer):
        r = enforcer.analyze(FULLY_FEATURED_SKILL)
        assert r.has_triggers is True
        assert r.has_version is True
        assert r.has_preamble is True
        assert r.has_when_to_invoke is True
        assert r.has_error_handling is True
        assert r.has_env_vars is True
        assert r.has_conditionals is True
        assert r.has_bash_blocks is True
        assert r.has_verification is True
        assert r.has_pitfalls is True
        assert r.bash_block_count >= 1
        assert r.error_handling_count >= 1
        assert r.completeness_score == 100.0
        assert r.missing_patterns == []

    def test_partial_skill_catches_specific_missing(self, enforcer):
        skill = "---\nversion: 0.1.0\n---\n# Test\n\n## Overview\n\nHas preamble and version.\n"
        r = enforcer.analyze(skill)
        assert r.has_version is True
        assert r.has_preamble is True
        assert r.has_triggers is False
        assert r.has_env_vars is False
        assert "triggers (frontmatter)" in r.missing_patterns
        assert "env var exports (export KEY=)" in r.missing_patterns

    def test_error_handling_count(self, enforcer):
        skill = "```bash\ncmd 2>/dev/null || true\n```\n"
        r = enforcer.analyze(skill)
        assert r.has_error_handling is True
        assert r.error_handling_count >= 2  # both "2>/dev/null" and "|| true"

    def test_bash_block_count(self, enforcer):
        skill = "a\n```bash\nx\n```\nb\n```sh\ny\n```"
        r = enforcer.analyze(skill)
        assert r.bash_block_count == 2


# ── Score calculation ─────────────────────────────────────────────────────

class TestScore:
    def test_zero_score(self, enforcer):
        r = enforcer.analyze("")
        assert r.completeness_score == 0.0

    def test_partial_score(self, enforcer):
        skill = "---\ntriggers:\n  - x\nversion: 1\n---\n# H\n\n## Overview\n\n...\n"
        r = enforcer.analyze(skill)
        # 3 of 10 patterns: triggers (10), version (5), preamble (15) = 30 / 100
        assert 20 <= r.completeness_score <= 40

    def test_full_score(self, enforcer):
        r = enforcer.analyze(FULLY_FEATURED_SKILL)
        assert r.completeness_score == 100.0

    def test_score_rounding(self, enforcer):
        skill = "---\ntriggers:\n  - x\n---\n# H\n\n## When to Use\n\n...\n"
        r = enforcer.analyze(skill)
        assert isinstance(r.completeness_score, float)
        assert 0.0 < r.completeness_score < 50.0


# ── suggest_injections ────────────────────────────────────────────────────

class TestSuggestInjections:
    def test_injections_for_empty_skill(self, enforcer):
        r = enforcer.analyze("")
        injections = enforcer.suggest_injections("", r)
        assert len(injections) == 8
        assert all(isinstance(i, Injection) for i in injections)

    def test_no_injections_for_complete_skill(self, enforcer):
        r = enforcer.analyze(FULLY_FEATURED_SKILL)
        injections = enforcer.suggest_injections(FULLY_FEATURED_SKILL, r)
        assert injections == []

    def test_selective_injections(self, enforcer):
        skill = "---\ntriggers:\n  - x\nversion: 1\n---\n# H\n\n## Overview\n\n...\n"
        r = enforcer.analyze(skill)
        injections = enforcer.suggest_injections(skill, r)
        names = {i.pattern_name for i in injections}
        # Has triggers, version, preamble — missing: when_to_invoke, error_handling,
        # env_vars, pitfalls, verification
        assert names == {
            "when_to_invoke", "error_handling", "env_vars",
            "pitfalls", "verification",
        }

    def test_injection_location_frontmatter(self, enforcer):
        r = enforcer.analyze("no frontmatter")
        injections = enforcer.suggest_injections("", r)
        fm_injs = [i for i in injections if i.location == "frontmatter"]
        assert len(fm_injs) >= 2  # triggers + version

    def test_injection_location_after_heading(self, enforcer):
        r = enforcer.analyze("# just a heading")
        injections = enforcer.suggest_injections("# just a heading", r)
        heading_injs = [i for i in injections if i.location == "after_heading"]
        assert len(heading_injs) >= 1

    def test_injection_location_end(self, enforcer):
        r = enforcer.analyze("")
        injections = enforcer.suggest_injections("", r)
        end_injs = [i for i in injections if i.location == "end"]
        assert len(end_injs) >= 1


# ── auto_inject ───────────────────────────────────────────────────────────

class TestAutoInject:
    def test_inject_into_empty_skill(self, enforcer):
        r = enforcer.analyze("")
        injections = enforcer.suggest_injections("", r)
        result = enforcer.auto_inject("", injections)
        # Should have added frontmatter + body sections
        assert "triggers:" in result
        assert "version:" in result
        assert "Overview" in result
        assert "Error Handling" in result

    def test_inject_triggers_into_frontmatter(self, enforcer):
        skill = "---\nversion: 0.1.0\n---\n# Skill\n"
        r = enforcer.analyze(skill)
        injections = enforcer.suggest_injections(skill, r)
        result = enforcer.auto_inject(skill, injections)
        assert "triggers:" in result
        assert "version: 0.1.0" in result

    def test_inject_body_sections(self, enforcer):
        skill = "# My Skill\n\nSome text.\n"
        r = enforcer.analyze(skill)
        injections = enforcer.suggest_injections(skill, r)
        result = enforcer.auto_inject(skill, injections)
        assert "## Overview" in result
        assert "## When to Use" in result
        assert "## Error Handling" in result
        assert "## Pitfalls" in result
        assert "## Verification" in result

    def test_inject_no_duplication_on_full_skill(self, enforcer):
        r = enforcer.analyze(FULLY_FEATURED_SKILL)
        injections = enforcer.suggest_injections(FULLY_FEATURED_SKILL, r)
        result = enforcer.auto_inject(FULLY_FEATURED_SKILL, injections)
        # No injections, so text unchanged
        assert result == FULLY_FEATURED_SKILL

    def test_inject_preserves_existing_content(self, enforcer):
        skill = "# Original\n\nSome existing text.\n"
        r = enforcer.analyze(skill)
        injections = enforcer.suggest_injections(skill, r)
        result = enforcer.auto_inject(skill, injections)
        assert "Original" in result
        assert "Some existing text." in result
        assert "Overview" in result
        assert "When to Use" in result

    def test_inject_into_skill_without_frontmatter(self, enforcer):
        skill = "# Standalone Skill\n\n```bash\necho hi\n```\n"
        r = enforcer.analyze(skill)
        injections = enforcer.suggest_injections(skill, r)
        result = enforcer.auto_inject(skill, injections)
        # Frontmatter injections should be inserted (text becomes frontmatter)
        assert "triggers:" in result
        assert "---" in result

    def test_result_has_reasonable_newlines(self, enforcer):
        r = enforcer.analyze("")
        injections = enforcer.suggest_injections("", r)
        result = enforcer.auto_inject("", injections)
        # No excessive blank lines
        assert "\n\n\n" not in result


# ── Edge cases ────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_only_frontmatter(self, enforcer):
        skill = "---\ntriggers:\n  - x\n---\n"
        r = enforcer.analyze(skill)
        injections = enforcer.suggest_injections(skill, r)
        assert len(injections) > 0

    def test_large_bash_block_count(self, enforcer):
        blocks = "\n".join(f"```bash\necho {i}\n```" for i in range(10))
        r = enforcer.analyze(blocks)
        assert r.bash_block_count == 10

    def test_multiline_frontmatter_triggers(self, enforcer):
        skill = "---\ntriggers:\n  - one\n  - two\nversion: '2.0'\n---\n# Skill\n"
        r = enforcer.analyze(skill)
        assert r.has_triggers is True
        assert r.has_version is True
        assert r.completeness_score > 0

    def test_error_handling_variants(self, enforcer):
        variants = [
            "cmd 2>/dev/null",
            "cmd || true",
            "cmd || exit 1",
            "set -e",
            "trap 'cleanup' EXIT",
        ]
        for variant in variants:
            # Each report separately
            single = enforcer.analyze(variant)
            assert single.has_error_handling, f"variant failed: {variant}"

    def test_pitfall_variants(self, enforcer):
        variants = [
            "pitfall: don't do this",
            "Common mistake: using wrong flag",
            "Don't run this as root",
            "do not rely on environment",
            "Warning: this may fail",
            "Caution: check permissions first",
            "Gotcha: version mismatch",
        ]
        for variant in variants:
            r = enforcer.analyze(variant)
            assert r.has_pitfalls, f"missing pitfall: {variant}"
