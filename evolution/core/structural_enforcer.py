"""Structural Pattern Enforcer — scores SKILL.md structural completeness and injects fixes.

Based on research: gstack skills have 89% preamble, 95% error handling, 97% env vars,
52% triggers. Hermes official skills often lack these. This enforcer detects patterns,
scores completeness, and can auto-inject missing elements.
"""
import re
from dataclasses import dataclass, field


@dataclass
class StructuralReport:
    has_triggers: bool = False
    has_when_to_invoke: bool = False
    has_preamble: bool = False
    has_error_handling: bool = False
    has_env_vars: bool = False
    has_conditionals: bool = False
    has_bash_blocks: bool = False
    has_verification: bool = False
    has_pitfalls: bool = False
    has_version: bool = False
    bash_block_count: int = 0
    error_handling_count: int = 0
    completeness_score: float = 0.0
    missing_patterns: list[str] = field(default_factory=list)


@dataclass
class Injection:
    pattern_name: str
    location: str  # "frontmatter", "after_heading", "end"
    content: str
    reason: str


# Weighted scoring: (pattern_attr, weight)
_WEIGHTS: list[tuple[str, float]] = [
    ("has_triggers", 10),
    ("has_when_to_invoke", 12),
    ("has_preamble", 15),
    ("has_error_handling", 15),
    ("has_env_vars", 12),
    ("has_conditionals", 8),
    ("has_bash_blocks", 8),
    ("has_verification", 10),
    ("has_pitfalls", 5),
    ("has_version", 5),
]

# Patterns to detect, mapping attr -> (compiled regex list for body, frontmatter_check)
_TRIGGER_RE = re.compile(
    r"(?:^|\n)triggers?:", re.IGNORECASE
)
_WHEN_RE = re.compile(
    r"(?:^|\n)\s*#+?\s*(?:when to (?:use|invoke|call|load)|trigger)", re.IGNORECASE
)
_PREAMBLE_RE = re.compile(
    r"(?:^|\n)#+?\s*(?:overview|summary|description|what this (?:skill|does)|preamble)",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(r"2>/dev/null|\|\|\s*true|\|\|\s*exit|set\s+\-e|trap\s+")
_ENV_RE = re.compile(r"export\s+[A-Z_][A-Z0-9_]*=")
_COND_RE = re.compile(r"if\s*\[|if\s*\[\[")
_BASH_OPEN = re.compile(r"```(?:bash|sh|shell|zsh)")
_BASH_CLOSE = re.compile(r"```")
_VERIFY_RE = re.compile(
    r"\b(?:verify|verif(?:y|ied|ication)|check(?:ed)?)\b", re.IGNORECASE
)
_PITFALL_RE = re.compile(
    r"(?:pitfall|common\s+mistake|don['']?t|do not|warning\s*:|caution\s*:|gotcha)",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(r"(?:^|\n)version\s*:", re.IGNORECASE)

FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _extract_frontmatter(text: str) -> str:
    m = FM_RE.match(text)
    return m.group(1) if m else ""


def _extract_body(text: str) -> str:
    m = FM_RE.match(text)
    return text[m.end():] if m else text


def _count_bash_blocks(body: str) -> int:
    opens = _BASH_OPEN.findall(body)
    return len(opens)


def _count_error_handling(body: str) -> int:
    return len(_ERROR_RE.findall(body))


class StructuralEnforcer:
    """Analyzes SKILL.md for structural patterns, scores completeness, injects fixes."""

    def analyze(self, skill_text: str) -> StructuralReport:
        fm = _extract_frontmatter(skill_text)
        body = _extract_body(skill_text)

        has_triggers = bool(_TRIGGER_RE.search(fm))
        has_when_to_invoke = bool(_WHEN_RE.search(body))
        has_preamble = bool(_PREAMBLE_RE.search(body))
        has_error_handling = _count_error_handling(body) > 0
        has_env_vars = bool(_ENV_RE.search(body))
        has_conditionals = bool(_COND_RE.search(body))
        bash_count = _count_bash_blocks(body)
        has_bash_blocks = bash_count > 0
        error_count = _count_error_handling(body)
        has_verification = bool(_VERIFY_RE.search(body))
        has_pitfalls = bool(_PITFALL_RE.search(body))
        has_version = bool(_VERSION_RE.search(fm))

        # Build report
        report = StructuralReport(
            has_triggers=has_triggers,
            has_when_to_invoke=has_when_to_invoke,
            has_preamble=has_preamble,
            has_error_handling=has_error_handling,
            has_env_vars=has_env_vars,
            has_conditionals=has_conditionals,
            has_bash_blocks=has_bash_blocks,
            has_verification=has_verification,
            has_pitfalls=has_pitfalls,
            has_version=has_version,
            bash_block_count=bash_count,
            error_handling_count=error_count,
        )

        # Score
        total_weight = sum(w for _, w in _WEIGHTS)
        earned = sum(
            w
            for attr, w in _WEIGHTS
            if getattr(report, attr)
        )
        report.completeness_score = round((earned / total_weight) * 100, 1) if total_weight else 0.0

        # Missing patterns
        missing = []
        _MISSING_LABELS = {
            "has_triggers": "triggers (frontmatter)",
            "has_when_to_invoke": "when-to-invoke section",
            "has_preamble": "preamble/overview section",
            "has_error_handling": "error handling (2>/dev/null, || true, || exit)",
            "has_env_vars": "env var exports (export KEY=)",
            "has_conditionals": "conditionals (if [/[[)",
            "has_bash_blocks": "bash code blocks",
            "has_verification": "verification steps",
            "has_pitfalls": "pitfalls section",
            "has_version": "version (frontmatter)",
        }
        for attr, label in _MISSING_LABELS.items():
            if not getattr(report, attr):
                missing.append(label)
        report.missing_patterns = missing
        return report

    def suggest_injections(
        self, skill_text: str, report: StructuralReport
    ) -> list[Injection]:
        fm = _extract_frontmatter(skill_text)
        injections: list[Injection] = []

        if not report.has_triggers:
            injections.append(Injection(
                pattern_name="triggers",
                location="frontmatter",
                content="triggers:\n  - skill load\n",
                reason="Missing triggers in frontmatter; gstack skills have 52% trigger coverage.",
            ))

        if not report.has_version:
            injections.append(Injection(
                pattern_name="version",
                location="frontmatter",
                content="version: 0.1.0\n",
                reason="Missing version in frontmatter.",
            ))

        if not report.has_preamble:
            injections.append(Injection(
                pattern_name="preamble",
                location="after_heading",
                content="\n## Overview\n\n<!-- Brief description of what this skill does and when to use it. -->\n",
                reason="Missing preamble/overview section; gstack skills have 89% preamble coverage.",
            ))

        if not report.has_when_to_invoke:
            injections.append(Injection(
                pattern_name="when_to_invoke",
                location="after_heading",
                content="\n## When to Use\n\n- Use this skill when: <describe trigger condition>\n",
                reason="Missing when-to-invoke section.",
            ))

        if not report.has_error_handling:
            injections.append(Injection(
                pattern_name="error_handling",
                location="end",
                content=(
                    "\n## Error Handling\n\n"
                    "```bash\n"
                    "# Always guard against failures in commands\n"
                    "some_command 2>/dev/null || echo \"command failed gracefully\"\n"
                    "```\n"
                ),
                reason="No error handling patterns found; gstack skills have 95% error handling coverage.",
            ))

        if not report.has_env_vars:
            injections.append(Injection(
                pattern_name="env_vars",
                location="end",
                content=(
                    "\n## Environment Variables\n\n"
                    "```bash\n"
                    "export SKILL_VAR=\"default_value\"\n"
                    "```\n"
                ),
                reason="No env var exports found; gstack skills have 97% env var coverage.",
            ))

        if not report.has_pitfalls:
            injections.append(Injection(
                pattern_name="pitfalls",
                location="end",
                content=(
                    "\n## Pitfalls\n\n"
                    "- Don't assume the environment has tools pre-installed.\n"
                    "- Common mistake: forgetting to check command exit codes.\n"
                ),
                reason="No pitfalls section found.",
            ))

        if not report.has_verification:
            injections.append(Injection(
                pattern_name="verification",
                location="end",
                content=(
                    "\n## Verification\n\n"
                    "After applying changes, verify:\n"
                    "1. Run the skill with a test input.\n"
                    "2. Check output matches expected result.\n"
                ),
                reason="No verification steps found.",
            ))

        return injections

    def auto_inject(self, skill_text: str, injections: list[Injection]) -> str:
        fm_match = FM_RE.match(skill_text)
        fm_text = fm_match.group(0) if fm_match else ""
        body = _extract_body(skill_text)

        # Separate frontmatter injections from body injections
        fm_injections = [i for i in injections if i.location == "frontmatter"]
        heading_injections = [i for i in injections if i.location == "after_heading"]
        end_injections = [i for i in injections if i.location == "end"]

        # Inject into frontmatter
        if fm_injections and fm_text:
            # Insert before closing ---
            closing_pos = fm_text.rfind("\n---")
            if closing_pos > 0:
                insert = "".join(f"  {i.content}" for i in fm_injections)
                fm_text = fm_text[:closing_pos] + "\n" + insert + fm_text[closing_pos:]
        elif fm_injections:
            # No existing frontmatter — create one
            fm_content = "".join(f"  {i.content}" for i in fm_injections)
            fm_text = f"---\n{fm_content}---"

        # Inject after first heading in body
        if heading_injections:
            heading_re = re.compile(r"^(#+\s+.+\n)", re.MULTILINE)
            m = heading_re.search(body)
            if m:
                insert = "".join(i.content for i in heading_injections)
                body = body[:m.end()] + insert + body[m.end():]
            else:
                # No heading, prepend
                insert = "".join(i.content for i in heading_injections)
                body = insert + body

        # Inject at end
        if end_injections:
            insert = "".join(i.content for i in end_injections)
            body = body.rstrip("\n") + "\n" + insert

        result = fm_text + "\n" + body if fm_text else body
        # Normalize newlines
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.lstrip("\n")
