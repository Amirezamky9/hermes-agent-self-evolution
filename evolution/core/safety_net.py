"""Safety net for skill evolution — validates patches, detects drift, auto-rollbacks."""
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .version_manager import VersionManager


DANGEROUS_PATTERNS = [
    re.compile(r"import\s+os", re.MULTILINE),
    re.compile(r"subprocess", re.MULTILINE),
    re.compile(r"eval\s*\(", re.MULTILINE),
    re.compile(r"exec\s*\(", re.MULTILINE),
    re.compile(r"__import__", re.MULTILINE),
    re.compile(r"open\s*\(.*['\"]w", re.MULTILINE),
    re.compile(r"os\.system", re.MULTILINE),
]

API_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"(?:api[_-]?key|token|secret)\s*[:=]\s*['\"][A-Za-z0-9\-_]{16,}['\"]", re.IGNORECASE),
]


@dataclass
class ValidationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)


@dataclass
class DriftResult:
    drift_detected: bool
    drift_pct: float
    action: str  # "accept" | "warn" | "rollback"


class SafetyNet:
    def __init__(self, max_size: int = 15000, max_growth_pct: float = 0.2):
        self.max_size = max_size
        self.max_growth_pct = max_growth_pct
        self._version_manager: Optional[VersionManager] = None

    @property
    def version_manager(self) -> VersionManager:
        if self._version_manager is None:
            self._version_manager = VersionManager()
        return self._version_manager

    def validate_patch(self, old_text: str, new_text: str, skill_name: str) -> ValidationResult:
        issues = []
        warnings = []
        checks_run = []

        self._check_frontmatter(new_text, issues, checks_run)
        self._check_size(new_text, issues, warnings, checks_run)
        self._check_growth(old_text, new_text, warnings, checks_run)
        self._check_content(new_text, issues, warnings, checks_run)
        self._check_structure(new_text, warnings, checks_run)

        return ValidationResult(
            passed=len(issues) == 0,
            issues=issues,
            warnings=warnings,
            checks_run=checks_run,
        )

    def check_drift(self, skill_name: str, old_score: float, new_score: float) -> DriftResult:
        if old_score == 0:
            return DriftResult(drift_detected=False, drift_pct=0.0, action="accept")

        drift_pct = (old_score - new_score) / old_score

        if drift_pct > 0.10:
            return DriftResult(drift_detected=True, drift_pct=drift_pct, action="rollback")
        elif drift_pct > 0.05:
            return DriftResult(drift_detected=True, drift_pct=drift_pct, action="warn")
        else:
            return DriftResult(drift_detected=False, drift_pct=drift_pct, action="accept")

    def auto_rollback(self, skill_name: str, reason: str) -> bool:
        versions = self.version_manager.list_versions(skill_name)
        if len(versions) < 2:
            return False

        # Find the most recent non-rollback version (skip rollback entries)
        current_version = versions[0]
        target_version = None

        for v in versions[1:]:
            if v.get("source") != "rollback":
                target_version = v
                break

        if target_version is None:
            target_version = versions[-1]

        return self.version_manager.rollback_to(skill_name, target_version["version"])

    # ── internal checks ──────────────────────────────────────────────

    def _check_frontmatter(self, text: str, issues: list[str], checks_run: list[str]) -> None:
        checks_run.append("frontmatter")
        if "---" not in text:
            issues.append("Missing YAML frontmatter delimiters (---)")
            return
        if re.search(r"^name:\s*\S", text, re.MULTILINE) is None:
            issues.append("Missing 'name:' field in frontmatter")
        if re.search(r"^description:\s*\S", text, re.MULTILINE) is None:
            issues.append("Missing 'description:' field in frontmatter")

    def _check_size(self, text: str, issues: list[str], warnings: list[str], checks_run: list[str]) -> None:
        checks_run.append("size")
        if len(text) > self.max_size:
            issues.append(f"Skill exceeds max size: {len(text)} > {self.max_size} chars")
        elif len(text) > self.max_size * 0.8:
            warnings.append(f"Skill approaching max size: {len(text)}/{self.max_size} chars")

    def _check_growth(self, old_text: str, new_text: str, warnings: list[str], checks_run: list[str]) -> None:
        checks_run.append("growth")
        if len(old_text) == 0:
            return
        growth = (len(new_text) - len(old_text)) / len(old_text)
        if growth > self.max_growth_pct:
            warnings.append(f"Excessive growth: {growth:.0%} (limit {self.max_growth_pct:.0%})")

    def _check_content(self, text: str, issues: list[str], warnings: list[str], checks_run: list[str]) -> None:
        checks_run.append("content")
        if not text.strip():
            issues.append("Skill text is empty")
            return

        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(text):
                issues.append(f"Dangerous code pattern detected: {pattern.pattern}")
                break  # one is enough

        for pattern in API_KEY_PATTERNS:
            if pattern.search(text):
                issues.append("Potential API key or secret detected")
                break

    def _check_structure(self, text: str, warnings: list[str], checks_run: list[str]) -> None:
        checks_run.append("structure")
        has_headings = bool(re.search(r"^#{1,6}\s+", text, re.MULTILINE))
        has_bullets = bool(re.search(r"^[\-\*]\s+", text, re.MULTILINE))
        if not has_headings and not has_bullets:
            warnings.append("No headings or bullet points found — skill may lack structure")
