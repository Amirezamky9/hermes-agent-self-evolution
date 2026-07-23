"""Version store for skill evolution artifacts.

Tracks every version of a skill with metadata, metrics, and snapshots.
Storage: SQLite database at <project_root>/evolution_versions.db
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SkillVersion:
    """A versioned snapshot of a skill."""
    version_id: int = 0  # auto-increment
    skill_name: str = ""
    version_number: int = 0  # human-readable: 1, 2, 3...
    skill_text: str = ""  # full SKILL.md content
    parent_version: Optional[int] = None  # version_id of previous version
    source: str = "evolved"  # baseline | evolved | manual | rollback
    metrics: dict = field(default_factory=dict)  # score, improvement, etc.
    constraints_passed: bool = True
    commit_hash: Optional[str] = None  # git commit if deployed
    created_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "skill_name": self.skill_name,
            "version_number": self.version_number,
            "skill_text": self.skill_text,
            "parent_version": self.parent_version,
            "source": self.source,
            "metrics": self.metrics,
            "constraints_passed": self.constraints_passed,
            "commit_hash": self.commit_hash,
            "created_at": self.created_at,
            "notes": self.notes,
        }


class VersionStore:
    """SQLite-backed version store for skill evolution."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path("evolution_versions.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skill_versions (
                    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    skill_text TEXT NOT NULL,
                    parent_version INTEGER,
                    source TEXT DEFAULT 'evolved',
                    metrics TEXT DEFAULT '{}',
                    constraints_passed BOOLEAN DEFAULT 1,
                    commit_hash TEXT,
                    created_at TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    UNIQUE(skill_name, version_number)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_skill_name
                ON skill_versions(skill_name)
            """)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def save(self, version: SkillVersion) -> int:
        """Save a new version. Returns the version_id."""
        now = datetime.now(timezone.utc).isoformat()
        if not version.created_at:
            version.created_at = now

        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO skill_versions
                   (skill_name, version_number, skill_text, parent_version,
                    source, metrics, constraints_passed, commit_hash,
                    created_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version.skill_name,
                    version.version_number,
                    version.skill_text,
                    version.parent_version,
                    version.source,
                    json.dumps(version.metrics),
                    version.constraints_passed,
                    version.commit_hash,
                    version.created_at,
                    version.notes,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get(self, version_id: int) -> Optional[SkillVersion]:
        """Get a specific version by ID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM skill_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            return self._row_to_version(row) if row else None

    def get_latest(self, skill_name: str) -> Optional[SkillVersion]:
        """Get the latest version for a skill."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM skill_versions
                   WHERE skill_name = ?
                   ORDER BY version_number DESC LIMIT 1""",
                (skill_name,),
            ).fetchone()
            return self._row_to_version(row) if row else None

    def list_versions(self, skill_name: str) -> list[SkillVersion]:
        """List all versions for a skill, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM skill_versions
                   WHERE skill_name = ?
                   ORDER BY version_number DESC""",
                (skill_name,),
            ).fetchall()
            return [self._row_to_version(row) for row in rows]

    def next_version_number(self, skill_name: str) -> int:
        """Get the next version number for a skill."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT MAX(version_number) FROM skill_versions
                   WHERE skill_name = ?""",
                (skill_name,),
            ).fetchone()
            return (row[0] or 0) + 1 if row else 1

    def record_baseline(self, skill_name: str, skill_text: str) -> int:
        """Record the current skill as a baseline version."""
        # If no versions exist, start at 1; otherwise append
        vnum = self.next_version_number(skill_name)
        v = SkillVersion(
            skill_name=skill_name,
            version_number=vnum,
            skill_text=skill_text,
            source="baseline",
            notes="Initial baseline before optimization",
        )
        return self.save(v)

    def record_evolved(
        self,
        skill_name: str,
        skill_text: str,
        parent_version: int,
        metrics: dict,
        constraints_passed: bool = True,
        notes: str = "",
    ) -> int:
        """Record an evolved version."""
        vnum = self.next_version_number(skill_name)
        v = SkillVersion(
            skill_name=skill_name,
            version_number=vnum,
            skill_text=skill_text,
            parent_version=parent_version,
            source="evolved",
            metrics=metrics,
            constraints_passed=constraints_passed,
            notes=notes,
        )
        return self.save(v)

    def record_rollback(
        self,
        skill_name: str,
        rollback_to_version_id: int,
    ) -> int:
        """Record a rollback as a new version pointing to the old version."""
        target = self.get(rollback_to_version_id)
        if not target:
            raise ValueError(f"Version {rollback_to_version_id} not found")

        vnum = self.next_version_number(skill_name)
        v = SkillVersion(
            skill_name=skill_name,
            version_number=vnum,
            skill_text=target.skill_text,
            parent_version=target.version_id,
            source="rollback",
            metrics={"rolled_back_from_version": target.version_number},
            notes=f"Rolled back to version {target.version_number}",
        )
        return self.save(v)

    def _row_to_version(self, row) -> SkillVersion:
        return SkillVersion(
            version_id=row[0],
            skill_name=row[1],
            version_number=row[2],
            skill_text=row[3],
            parent_version=row[4],
            source=row[5],
            metrics=json.loads(row[6]) if row[6] else {},
            constraints_passed=bool(row[7]),
            commit_hash=row[8],
            created_at=row[9],
            notes=row[10] or "",
        )
