"""File-based version manager for SKILL.md files.

Stores versions as: <versions_dir>/<skill-name>/v1.0.0/SKILL.md + meta.json
Enforces max 20 versions per skill; older ones are archived.
"""
import difflib
import json
import re
import shutil
from pathlib import Path
from typing import Optional

MAX_VERSIONS_PER_SKILL = 20


class VersionManager:
    def __init__(self, versions_dir: str = "~/.hermes/skills/.versions"):
        self.versions_dir = Path(versions_dir).expanduser()

    def create_version(
        self, skill_name: str, skill_text: str, meta: dict
    ) -> str:
        """Create a new versioned snapshot. Returns the version string (e.g. 'v1.0.0')."""
        skill_dir = self.versions_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        next_version = self._next_version(skill_name)
        version_str = f"v{next_version}"
        version_path = skill_dir / version_str
        version_path.mkdir(parents=True, exist_ok=True)

        (version_path / "SKILL.md").write_text(skill_text)
        meta_with_version = {"version": version_str, **meta}
        (version_path / "meta.json").write_text(
            json.dumps(meta_with_version, indent=2)
        )

        self._enforce_max_versions(skill_name)
        return version_str

    def list_versions(self, skill_name: str) -> list[dict]:
        """Return list of meta dicts for all versions of a skill, newest first."""
        skill_dir = self.versions_dir / skill_name
        if not skill_dir.exists():
            return []

        versions = []
        for p in sorted(
            skill_dir.iterdir(),
            reverse=True,
            key=lambda p: self._parse_version_sort_key(p.name),
        ):
            meta_file = p / "meta.json"
            if meta_file.exists():
                versions.append(json.loads(meta_file.read_text()))
        return versions

    def rollback_to(self, skill_name: str, version: str) -> bool:
        """Rollback skill to a given version string. Returns True on success."""
        if not version.startswith("v"):
            version = f"v{version}"

        skill_dir = self.versions_dir / skill_name
        source_dir = skill_dir / version
        skill_file = source_dir / "SKILL.md"

        if not skill_file.exists():
            return False

        skill_text = skill_file.read_text()
        source_meta = json.loads((source_dir / "meta.json").read_text())
        new_meta = {
            "source": "rollback",
            "benchmark_score": source_meta.get("benchmark_score"),
            "diff_summary": f"Rolled back to {version}",
            "rationale": source_meta.get("rationale", ""),
        }
        self.create_version(skill_name, skill_text, new_meta)
        return True

    def get_current(self, skill_name: str) -> Optional[dict]:
        """Get the latest version info, or None if skill has no versions."""
        versions = self.list_versions(skill_name)
        return versions[0] if versions else None

    def diff_versions(self, skill_name: str, v1: str, v2: str) -> str:
        """Unified diff between two versions. Returns empty string if either missing."""
        if not v1.startswith("v"):
            v1 = f"v{v1}"
        if not v2.startswith("v"):
            v2 = f"v{v2}"

        skill_dir = self.versions_dir / skill_name
        f1 = skill_dir / v1 / "SKILL.md"
        f2 = skill_dir / v2 / "SKILL.md"

        if not f1.exists() or not f2.exists():
            return ""

        text1 = f1.read_text().splitlines(keepends=True)
        text2 = f2.read_text().splitlines(keepends=True)
        return "".join(difflib.unified_diff(text1, text2, fromfile=v1, tofile=v2))

    # ── internal ──────────────────────────────────────────────────────

    def _next_version(self, skill_name: str) -> str:
        """Determine the next version string (major.minor.patch)."""
        skill_dir = self.versions_dir / skill_name
        if not skill_dir.exists():
            return "1.0.0"

        # Find the numerically highest existing version
        best = (0, 0, 0)
        for p in skill_dir.iterdir():
            if p.is_dir() and (p / "meta.json").exists():
                key = self._parse_version_sort_key(p.name)
                if key > best:
                    best = key

        if best == (0, 0, 0):
            return "1.0.0"

        return f"{best[0]}.{best[1]}.{best[2] + 1}"

    def _enforce_max_versions(self, skill_name: str) -> None:
        """Archive (delete) oldest versions if count exceeds MAX."""
        skill_dir = self.versions_dir / skill_name
        dirs = sorted(
            (p for p in skill_dir.iterdir() if p.is_dir()),
            key=lambda p: self._parse_version_sort_key(p.name),
        )
        while len(dirs) > MAX_VERSIONS_PER_SKILL:
            oldest = dirs.pop(0)
            shutil.rmtree(oldest)

    @staticmethod
    def _parse_version_sort_key(name: str) -> tuple[int, int, int]:
        """Parse 'v1.0.2' into (1, 0, 2) for correct numeric sorting."""
        m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", name)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (0, 0, 0)
