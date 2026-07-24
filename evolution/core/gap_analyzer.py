"""Skill Gap Analyzer — identifies skills with failures and produces actionable gaps.

Takes SessionGrazer output, groups failures by skill, enriches with skill descriptions,
and produces a prioritized gap report.
"""
import re
from collections import Counter
from pathlib import Path
from typing import Optional


# ponytail: Severity thresholds are hardcoded. Move to config if tuning becomes frequent.

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


class SkillGapAnalyzer:
    """Analyzes skill failures to identify gaps and recommend improvements."""

    def __init__(self, hermes_path: str = "~/.hermes"):
        self.hermes_path = Path(hermes_path).expanduser()
        self._skill_descriptions: dict[str, str] | None = None

    def _load_skill_descriptions(self) -> dict[str, str]:
        """Read SKILL.md frontmatter/body summary for each installed skill."""
        if self._skill_descriptions is not None:
            return self._skill_descriptions
        self._skill_descriptions = {}
        skills_dir = self.hermes_path / "skills"
        if not skills_dir.is_dir():
            return self._skill_descriptions
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                content = skill_file.read_text(encoding="utf-8")[:2000]
            except (OSError, UnicodeDecodeError):
                continue
            # Strip YAML frontmatter, grab first meaningful line as description
            desc = _extract_description(content)
            self._skill_descriptions[skill_dir.name] = desc
        return self._skill_descriptions

    def analyze(self, grazer_result: dict) -> list[dict]:
        """Produce a prioritized list of skill gaps from grazer output.

        Args:
            grazer_result: dict from SessionGrazer.run() with keys
                skill_usages, failures, skill_counts, failure_counts.

        Returns:
            List of SkillGap dicts sorted by severity (critical first).
        """
        skill_counts = grazer_result.get("skill_counts", {})
        failure_counts = grazer_result.get("failure_counts", {})
        failures = grazer_result.get("failures", [])
        skill_usages = grazer_result.get("skill_usages", [])

        # Group failures by skill
        failures_by_skill: dict[str, list[dict]] = {}
        for f in failures:
            name = f.get("skill_name", "")
            failures_by_skill.setdefault(name, []).append(f)

        # Group all usages by skill for error type distribution across all calls
        error_types_by_skill: dict[str, list[str]] = {}
        for u in skill_usages:
            name = u.get("skill_name", "")
            et = u.get("error_type", "")
            if et:
                error_types_by_skill.setdefault(name, []).append(et)

        descriptions = self._load_skill_descriptions()

        gaps = []
        # Analyze skills that have failures
        for skill_name, skill_failures in failures_by_skill.items():
            error_types = [f.get("error_type", "") for f in skill_failures]
            error_type_dist = dict(Counter(error_types))
            failure_count = len(skill_failures)

            # Sample failures (up to 5)
            sample_failures = [
                {
                    "task_input": f.get("task_input", "")[:200],
                    "error_type": f.get("error_type", ""),
                    "error_message": f.get("error_message", "")[:200],
                }
                for f in skill_failures[:5]
            ]

            severity = _classify_severity(failure_count)
            description = descriptions.get(skill_name, "")
            recommendation = _generate_recommendation(
                skill_name, failure_count, error_type_dist, description, skill_failures
            )

            gaps.append({
                "skill_name": skill_name,
                "failure_count": failure_count,
                "total_invocations": skill_counts.get(skill_name, failure_count),
                "error_types": error_type_dist,
                "sample_failures": sample_failures,
                "severity": severity,
                "skill_description": description[:300],
                "recommendation": recommendation,
            })

        # Sort: critical first, then by failure_count desc
        gaps.sort(key=lambda g: (_SEVERITY_ORDER.get(g["severity"], 9), -g["failure_count"]))
        return gaps

    def get_top_gaps(self, gaps: list[dict], n: int = 5) -> list[dict]:
        """Return top n gaps by severity priority and failure count."""
        return gaps[:n]

    def to_report(self, gaps: list[dict]) -> str:
        """Format gaps into a human-readable report."""
        if not gaps:
            return "No skill gaps detected."

        lines = ["# Skill Gap Report", ""]

        # Summary
        critical = sum(1 for g in gaps if g["severity"] == "critical")
        warning = sum(1 for g in gaps if g["severity"] == "warning")
        total_failures = sum(g["failure_count"] for g in gaps)
        lines.append(f"**{len(gaps)}** skills with issues, **{total_failures}** total failures")
        if critical:
            lines.append(f"- 🔴 Critical: {critical}")
        if warning:
            lines.append(f"- 🟡 Warning: {warning}")
        lines.append("")

        for i, gap in enumerate(gaps, 1):
            sev_icon = {"critical": "🔴", "warning": "🟡", "info": "⚪"}.get(gap["severity"], "⚪")
            total = gap.get("total_invocations", gap["failure_count"])
            lines.append(f"## {i}. {sev_icon} {gap['skill_name']}")
            lines.append(f"- Failures: {gap['failure_count']} / {total} invocations")
            lines.append(f"- Error types: {gap['error_types']}")
            if gap.get("skill_description"):
                lines.append(f"- Description: {gap['skill_description'][:150]}")
            lines.append(f"- Recommendation: {gap['recommendation']}")
            if gap.get("sample_failures"):
                lines.append("- Sample failures:")
                for sf in gap["sample_failures"][:3]:
                    lines.append(f"  - `{sf['error_type']}`: {sf['error_message'][:100]}")
                    if sf.get("task_input"):
                        lines.append(f"    Task: {sf['task_input'][:100]}")
            lines.append("")

        return "\n".join(lines)


def _extract_description(skill_md_content: str) -> str:
    """Pull the first meaningful description line from SKILL.md content."""
    # Skip YAML frontmatter
    in_frontmatter = False
    for line in skill_md_content.split("\n"):
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            # Grab 'description:' from frontmatter if present
            if stripped.lower().startswith("description:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
            continue
        # After frontmatter, first heading or paragraph
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped and not stripped.startswith("---"):
            return stripped[:200]
    return ""


def _classify_severity(failure_count: int) -> str:
    """Map failure count to severity level."""
    if failure_count >= 3:
        return "critical"
    if failure_count >= 1:
        return "warning"
    return "info"


# ponytail: Recommendations are template-based. Upgrade to LLM-generated
# recommendations when the feedback loop matures.


def _generate_recommendation(
    skill_name: str,
    failure_count: int,
    error_type_dist: dict,
    description: str,
    failures: list[dict],
) -> str:
    """Generate a human-readable recommendation based on failure patterns."""
    dominant_error = ""
    if error_type_dist:
        dominant_error = max(error_type_dist, key=lambda k: error_type_dist[k])

    if dominant_error == "skill_not_found" or dominant_error == "tool_error":
        if any("disabled" in f.get("error_message", "").lower() for f in failures):
            return f"Skill '{skill_name}' is disabled. Enable it or remove the reference if unused."

    if dominant_error == "lint_error":
        return f"Skill '{skill_name}' has lint/syntax errors in its SKILL.md. Fix formatting issues."

    if dominant_error == "timeout":
        return f"Skill '{skill_name}' times out during loading. Check for heavy linked files."

    if dominant_error == "exit_code_error":
        return f"Skill '{skill_name}' triggers commands that fail. Review script steps for errors."

    if dominant_error == "content_error":
        return f"Skill '{skill_name}' responses contain error signals. Review linked files and templates."

    if failure_count >= 5:
        return f"Skill '{skill_name}' fails frequently ({failure_count}x). Consider a full rewrite or deprecation."

    if failure_count >= 3:
        return f"Skill '{skill_name}' has recurring failures. Investigate root cause in the top error patterns."

    return f"Skill '{skill_name}' has {failure_count} failure(s). Monitor for patterns; may be transient."
