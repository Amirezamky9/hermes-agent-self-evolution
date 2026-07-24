"""Tests for SafetyNet structural completeness integration (Phase F)."""
import pytest
from evolution.core.safety_net import SafetyNet


# ── fixtures ────────────────────────────────────────────────────────

HIGH_COMPLETENESS_SKILL = """\
---
name: high-skill
description: A well-structured skill.
triggers:
  - skill load
version: 0.1.0
---

## Overview

This skill does things.

## When to Use

- Use when you need things done.

## Steps

Run the commands:

```bash
export MY_VAR="hello"
if [ "$MY_VAR" = "hello" ]; then
  echo "ok"
fi
some_command 2>/dev/null || true
```

## Verification

Verify the output is correct.

## Pitfalls

- Don't forget to set the env var.
"""

LOW_COMPLETENESS_SKILL = """\
---
name: low-skill
description: Bare minimum skill.
---

Just some plain text, no structure at all.
"""

MODERATE_COMPLETENESS_SKILL = """\
---
name: mod-skill
description: Moderate skill.
version: 0.1.0
---

## Overview

A moderate skill.

## When to Use

- Use when needed.

## Steps

```bash
echo "hello"
```

## Verification

Verify the output.
"""


# ── structural_completeness in checks_run ───────────────────────────

class TestStructuralCompletenessCheckRecorded:
    def test_check_recorded_in_checks_run(self):
        sn = SafetyNet()
        result = sn.validate_patch("", HIGH_COMPLETENESS_SKILL, "test")
        assert "structural_completeness" in result.checks_run


# ── high completeness passes ────────────────────────────────────────

class TestHighCompleteness:
    def test_no_structural_issue_or_warning(self):
        sn = SafetyNet()
        result = sn.validate_patch("", HIGH_COMPLETENESS_SKILL, "test")
        assert not any("structural completeness" in i for i in result.issues)
        assert "Moderate structural completeness" not in result.warnings


# ── low completeness → issue ────────────────────────────────────────

class TestLowCompleteness:
    def test_low_completeness_adds_issue(self):
        sn = SafetyNet()
        result = sn.validate_patch("", LOW_COMPLETENESS_SKILL, "test")
        assert result.passed is False
        assert any("Low structural completeness" in i for i in result.issues)

    def test_issue_mentions_missing_patterns(self):
        sn = SafetyNet()
        result = sn.validate_patch("", LOW_COMPLETENESS_SKILL, "test")
        low_issue = [i for i in result.issues if "Low structural completeness" in i]
        assert len(low_issue) == 1
        assert "missing" in low_issue[0]


# ── moderate completeness → warning ─────────────────────────────────

class TestModerateCompleteness:
    def test_moderate_completeness_adds_warning(self):
        sn = SafetyNet()
        result = sn.validate_patch("", MODERATE_COMPLETENESS_SKILL, "test")
        assert "Moderate structural completeness" in result.warnings


# ── bash block regression ───────────────────────────────────────────

class TestBashBlockRegression:
    def test_bash_block_decrease_adds_issue(self):
        sn = SafetyNet()
        old = """---
name: skill
description: d
---
```bash
echo a
```
```bash
echo b
```
"""
        new = """---
name: skill
description: d
---
```bash
echo a only
```
"""
        result = sn.validate_patch(old, new, "test")
        assert any("Bash block count regressed" in i for i in result.issues)

    def test_bash_block_no_decrease_no_issue(self):
        sn = SafetyNet()
        old = """---
name: skill
description: d
---
```bash
echo a
```
"""
        new = """---
name: skill
description: d
---
```bash
echo a
```
```bash
echo b
```
"""
        result = sn.validate_patch(old, new, "test")
        assert not any("Bash block count regressed" in i for i in result.issues)

    def test_bash_block_same_count_no_issue(self):
        sn = SafetyNet()
        text = """---
name: skill
description: d
---
```bash
echo a
```
"""
        result = sn.validate_patch(text, text, "test")
        assert not any("Bash block count regressed" in i for i in result.issues)


# ── check_structural_regression ─────────────────────────────────────

class TestCheckStructuralRegression:
    def test_returns_expected_keys(self):
        sn = SafetyNet()
        result = sn.check_structural_regression(LOW_COMPLETENESS_SKILL, HIGH_COMPLETENESS_SKILL)
        assert set(result.keys()) == {"regressed", "old_score", "new_score", "lost_patterns"}

    def test_improvement_not_regressed(self):
        sn = SafetyNet()
        result = sn.check_structural_regression(LOW_COMPLETENESS_SKILL, HIGH_COMPLETENESS_SKILL)
        assert result["regressed"] is False
        assert result["new_score"] > result["old_score"]

    def test_degradation_is_regressed(self):
        sn = SafetyNet()
        result = sn.check_structural_regression(HIGH_COMPLETENESS_SKILL, LOW_COMPLETENESS_SKILL)
        assert result["regressed"] is True
        assert result["new_score"] < result["old_score"]

    def test_lost_patterns_populated_on_regression(self):
        sn = SafetyNet()
        result = sn.check_structural_regression(HIGH_COMPLETENESS_SKILL, LOW_COMPLETENESS_SKILL)
        assert isinstance(result["lost_patterns"], list)
        assert len(result["lost_patterns"]) > 0

    def test_same_text_no_loss(self):
        sn = SafetyNet()
        result = sn.check_structural_regression(HIGH_COMPLETENESS_SKILL, HIGH_COMPLETENESS_SKILL)
        assert result["regressed"] is False
        assert result["old_score"] == result["new_score"]
        assert result["lost_patterns"] == []
