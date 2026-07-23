"""Rollback mechanism for evolved skills.

Provides rollback to any previous version, with validation and safety checks.
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from evolution.core.version_store import VersionStore, SkillVersion


@dataclass
class RollbackResult:
    """Result of a rollback operation."""
    success: bool
    from_version: int  # version_number we're rolling back from
    to_version: int  # version_number we're rolling back to
    new_version_id: int  # the new version created by rollback
    message: str


class RollbackManager:
    """Manages rollback of evolved skills to previous versions."""

    def __init__(self, store: VersionStore):
        self.store = store

    def rollback_to_version(
        self,
        skill_name: str,
        target_version_number: int,
        validate: bool = True,
    ) -> RollbackResult:
        """Rollback a skill to a specific version number.

        Args:
            skill_name: Name of the skill to rollback
            target_version_number: The version number to rollback to
            validate: If True, validate the target version exists and is safe

        Returns:
            RollbackResult with details of the operation
        """
        # Find current version
        current = self.store.get_latest(skill_name)
        if not current:
            return RollbackResult(
                success=False,
                from_version=0,
                to_version=target_version_number,
                new_version_id=0,
                message=f"No versions found for skill '{skill_name}'",
            )

        # Find target version
        versions = self.store.list_versions(skill_name)
        target = None
        for v in versions:
            if v.version_number == target_version_number:
                target = v
                break

        if not target:
            available = [str(v.version_number) for v in versions]
            return RollbackResult(
                success=False,
                from_version=current.version_number,
                to_version=target_version_number,
                new_version_id=0,
                message=f"Version {target_version_number} not found. Available: {', '.join(available)}",
            )

        # Safety: don't rollback to same version
        if current.version_id == target.version_id:
            return RollbackResult(
                success=False,
                from_version=current.version_number,
                to_version=target_version_number,
                new_version_id=0,
                message="Already at target version",
            )

        # Safety: validate target version passed constraints
        if validate and not target.constraints_passed:
            return RollbackResult(
                success=False,
                from_version=current.version_number,
                to_version=target_version_number,
                new_version_id=0,
                message=f"Target version {target_version_number} failed constraint validation — unsafe rollback",
            )

        # Perform rollback — creates a new version with the old content
        new_id = self.store.record_rollback(
            skill_name=skill_name,
            rollback_to_version_id=target.version_id,
        )

        return RollbackResult(
            success=True,
            from_version=current.version_number,
            to_version=target_version_number,
            new_version_id=new_id,
            message=f"Rolled back from v{current.version_number} to v{target_version_number}",
        )

    def rollback_to_baseline(self, skill_name: str) -> RollbackResult:
        """Rollback to the baseline (version 1)."""
        return self.rollback_to_version(skill_name, target_version_number=1)

    def rollback_last(self, skill_name: str) -> RollbackResult:
        """Rollback to the previous version (one step back)."""
        current = self.store.get_latest(skill_name)
        if not current or not current.parent_version:
            return RollbackResult(
                success=False,
                from_version=current.version_number if current else 0,
                to_version=0,
                new_version_id=0,
                message="No parent version to rollback to",
            )

        parent = self.store.get(current.parent_version)
        if not parent:
            return RollbackResult(
                success=False,
                from_version=current.version_number,
                to_version=0,
                new_version_id=0,
                message="Parent version not found in store",
            )

        return self.rollback_to_version(skill_name, parent.version_number)

    def diff_versions(
        self,
        skill_name: str,
        version_a: int,
        version_b: int,
    ) -> Optional[str]:
        """Generate a unified diff between two versions."""
        versions = self.store.list_versions(skill_name)
        a_text = None
        b_text = None
        for v in versions:
            if v.version_number == version_a:
                a_text = v.skill_text
            elif v.version_number == version_b:
                b_text = v.skill_text

        if a_text is None or b_text is None:
            return None

        import difflib
        diff = difflib.unified_diff(
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
            fromfile=f"v{version_a}",
            tofile=f"v{version_b}",
        )
        return "".join(diff)

    def get_skill_text(self, skill_name: str, version_number: int) -> Optional[str]:
        """Get the skill text at a specific version number."""
        versions = self.store.list_versions(skill_name)
        for v in versions:
            if v.version_number == version_number:
                return v.skill_text
        return None
