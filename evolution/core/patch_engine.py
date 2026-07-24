"""Patch Engine — generates targeted diffs for skill improvements.

Takes gaps from SkillGapAnalyzer, reads current SKILL.md content,
generates small patch proposals via LLM, validates YAML frontmatter preservation,
and applies approved patches.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import dspy
import yaml

from evolution.core.config import EvolutionConfig
from evolution.core.custom_provider import configure_dspy


# ponytail: Frontmatter parsing is duplicated with gap_analyzer. Extract to shared util when a third consumer appears.


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a SKILL.md string. Returns {} if absent."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def _strip_frontmatter(text: str) -> str:
    """Return the body after YAML frontmatter."""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2].lstrip("\n")


# ── LLM prompt module ──────────────────────────────────────────────

class _PatchGenerator(dspy.Module):
    """DSPy module that generates a patch for a skill given a gap."""

    def __init__(self):
        self.predict = dspy.Predict(
            "skill_name,skill_body,current_frontmatter,failures,recommendation,severity -> new_body,rationale"
        )

    def forward(self, skill_name, skill_body, current_frontmatter, failures, recommendation, severity):
        prompt = f"""You are patching a Hermes Agent skill file (SKILL.md).

Skill name: {skill_name}
Severity: {severity}
Recommendation: {recommendation}

Sample failures that triggered this patch:
{failures}

Current skill body (after frontmatter):
---
{skill_body[:3000]}
---

Generate an improved version of the skill body ONLY (not the frontmatter).
The patch should be a targeted fix — do NOT rewrite the entire file.
Focus on the specific issues described in the failures and recommendation.
Keep the same structure and style. Add specific instructions, examples, or
corrections that address the failure patterns.

Return the full new body text (everything after the YAML frontmatter)."""
        result = self.predict(
            skill_name=skill_name,
            skill_body=skill_body[:3000],
            current_frontmatter=current_frontmatter,
            failures=failures,
            recommendation=recommendation,
            severity=severity,
        )
        return result


# ── PatchEngine ─────────────────────────────────────────────────────

@dataclass
class PatchProposal:
    """A proposed patch for a skill."""
    skill_name: str
    old_text: str
    new_text: str
    diff_summary: str
    rationale: str
    severity: str

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "diff_summary": self.diff_summary,
            "rationale": self.rationale,
            "severity": self.severity,
        }


def _build_diff_summary(old_text: str, new_text: str) -> str:
    """Create a one-line summary of what changed."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    added = len(new_lines) - len(old_lines)
    if added > 0:
        return f"+{added} lines"
    if added < 0:
        return f"{added} lines"
    if old_text == new_text:
        return "no change"
    return "content changed, same line count"


class PatchEngine:
    """Generates and validates targeted patches for skill improvements."""

    def __init__(self, config: Optional[EvolutionConfig] = None, hermes_path: Optional[str] = None):
        self.config = config or EvolutionConfig()
        self.hermes_path = Path(hermes_path or "~/.hermes").expanduser()
        self._patch_gen = _PatchGenerator()

    def _resolve_skill_path(self, skill_name: str) -> Optional[Path]:
        """Find SKILL.md for a skill, checking hermes_path/skills/ first."""
        skill_dir = self.hermes_path / "skills" / skill_name
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_file():
            return skill_file
        return None

    def _read_skill(self, skill_name: str) -> Optional[str]:
        """Read SKILL.md content for a skill."""
        path = self._resolve_skill_path(skill_name)
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def validate_patch(self, old_text: str, new_text: str) -> dict:
        """Validate that a patch preserves YAML frontmatter structure.

        Returns dict with 'passed' (bool) and 'issues' (list[str]).
        """
        issues = []

        old_fm = _parse_frontmatter(old_text)
        new_fm = _parse_frontmatter(new_text)

        # Both must have frontmatter
        if not old_fm and not new_fm:
            issues.append("Neither old nor new text has YAML frontmatter")
        elif not old_fm:
            issues.append("New text is missing YAML frontmatter that existed in old text")
        elif not new_fm:
            issues.append("YAML frontmatter was removed from new text")

        # Critical frontmatter keys must be preserved
        for key in ("name", "description"):
            if old_fm.get(key) and not new_fm.get(key):
                issues.append(f"Frontmatter key '{key}' was removed")
            elif old_fm.get(key) and new_fm.get(key) and old_fm[key] != new_fm[key]:
                issues.append(f"Frontmatter key '{key}' changed from '{old_fm[key]}' to '{new_fm[key]}'")

        # new_text should not be empty
        if not new_text.strip():
            issues.append("New text is empty")

        return {"passed": len(issues) == 0, "issues": issues}

    def generate_patches(self, gaps: list[dict], llm_config=None) -> list[dict]:
        """Generate patch proposals for each gap.

        Args:
            gaps: List of gap dicts from SkillGapAnalyzer (with skill_name,
                  sample_failures, recommendation, severity).
            llm_config: Optional LLMConfig. If None, resolves from Hermes config.

        Returns:
            List of PatchProposal dicts.
        """
        if llm_config is not None:
            configure_dspy(llm_config)

        proposals = []
        for gap in gaps:
            skill_name = gap.get("skill_name", "")
            if not skill_name:
                continue

            skill_text = self._read_skill(skill_name)
            if skill_text is None:
                continue

            frontmatter = _parse_frontmatter(skill_text)
            body = _strip_frontmatter(skill_text)

            # Format failures for the prompt
            failures_text = "\n".join(
                f"- [{sf.get('error_type', '?')}] {sf.get('error_message', '?')[:150]}"
                for sf in gap.get("sample_failures", [])[:5]
            )

            try:
                result = self._patch_gen(
                    skill_name=skill_name,
                    skill_body=body,
                    current_frontmatter=str(frontmatter),
                    failures=failures_text or "No specific failures recorded",
                    recommendation=gap.get("recommendation", ""),
                    severity=gap.get("severity", "info"),
                )
                new_body = result.new_body.strip()
                if not new_body:
                    continue
                rationale = result.rationale.strip() if hasattr(result, "rationale") else ""
            except Exception:
                # LLM failed — skip this gap
                continue

            # Reconstruct full file: frontmatter + new body
            fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
            new_text = f"---\n{fm_yaml}\n---\n\n{new_body}"

            # Validate before proposing
            validation = self.validate_patch(skill_text, new_text)
            if not validation["passed"]:
                continue

            proposals.append(PatchProposal(
                skill_name=skill_name,
                old_text=skill_text,
                new_text=new_text,
                diff_summary=_build_diff_summary(body, new_body),
                rationale=rationale,
                severity=gap.get("severity", "info"),
            ).to_dict())

        return proposals

    def apply_patch(self, skill_path: str, patch: dict) -> bool:
        """Write a patch to disk.

        Args:
            skill_path: Path to the SKILL.md file to update.
            patch: PatchProposal dict (must contain 'new_text').

        Returns:
            True if applied successfully, False otherwise.
        """
        new_text = patch.get("new_text", "")
        if not new_text:
            return False

        path = Path(skill_path)
        if not path.is_file():
            return False

        try:
            path.write_text(new_text, encoding="utf-8")
            return True
        except OSError:
            return False
