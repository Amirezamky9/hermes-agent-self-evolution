"""Full Pipeline — single entry point that wires all modules together.

Usage:
    from evolution.core.full_pipeline import FullPipeline
    result = FullPipeline().run("my-skill", mode="session")
    result = FullPipeline().run("my-skill", mode="mipro")
    report = FullPipeline().nightly(["skill-a", "skill-b"])
    status = FullPipeline().status()
"""
from dataclasses import dataclass, field
from typing import Optional

from evolution.core.config import EvolutionConfig
from evolution.core.pipeline import Pipeline, PipelineResult
from evolution.core.cron_runner import CronRunner, NightlyReport
from evolution.core.version_manager import VersionManager
from evolution.core.version_store import VersionStore


@dataclass
class SkillStatus:
    """Status of a single skill."""
    name: str
    latest_version: int = 0
    source: str = ""
    last_score: float = 0.0
    constraints_passed: bool = True
    created_at: str = ""


@dataclass
class SystemStatus:
    """Aggregate status of all tracked skills."""
    skills: list[SkillStatus] = field(default_factory=list)
    total_skills: int = 0


class FullPipeline:
    """Unified entry point for all self-evolution operations."""

    def __init__(self, config: Optional[EvolutionConfig] = None):
        self.config = config or EvolutionConfig()
        self.pipeline = Pipeline(config=self.config)

    def run(self, skill_name: str, mode: str = "session") -> PipelineResult:
        """Run the full optimization pipeline for a skill.

        Args:
            skill_name: Name of the skill to optimize.
            mode: "session" uses real session failures (Pipeline).
                  "synthetic" uses synthetic dataset (same pipeline, different data).
        """
        return self.pipeline.run(skill_name, mode=mode)

    def nightly(self, skills: list[str]) -> NightlyReport:
        """Run nightly optimization for multiple skills."""
        runner = CronRunner(config=self.config, skills=skills)
        return runner.run_nightly()

    def versions(self, skill_name: str) -> list[dict]:
        """List all versions of a skill (from VersionManager)."""
        vm = VersionManager()
        return vm.list_versions(skill_name)

    def rollback(self, skill_name: str, version: str) -> bool:
        """Rollback a skill to a previous version."""
        vm = VersionManager()
        return vm.rollback_to(skill_name, version)

    def status(self) -> SystemStatus:
        """Get the current status of all tracked skills."""
        store = VersionStore()
        vm = VersionManager()

        # Collect all unique skill names from both stores
        skill_names: set[str] = set()

        # From VersionStore (SQLite)
        try:
            with store._conn() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT skill_name FROM skill_versions"
                ).fetchall()
                for row in rows:
                    skill_names.add(row[0])
        except Exception:
            pass

        # From VersionManager (file-based)
        if vm.versions_dir.is_dir():
            for p in vm.versions_dir.iterdir():
                if p.is_dir():
                    skill_names.add(p.name)

        skills = []
        for name in sorted(skill_names):
            # Get latest from SQLite store
            latest = store.get_latest(name)
            # Get file-based latest
            fm_latest = vm.get_current(name)

            version_num = 0
            source = ""
            score = 0.0
            constraints_ok = True
            created = ""

            if latest:
                version_num = latest.version_number
                source = latest.source
                score = latest.metrics.get("evolved_score",
                       latest.metrics.get("benchmark_score",
                       latest.metrics.get("score", 0.0)))
                constraints_ok = latest.constraints_passed
                created = latest.created_at[:19] if latest.created_at else ""

            skills.append(SkillStatus(
                name=name,
                latest_version=version_num,
                source=source,
                last_score=score if isinstance(score, (int, float)) else 0.0,
                constraints_passed=constraints_ok,
                created_at=created,
            ))

        return SystemStatus(skills=skills, total_skills=len(skills))
