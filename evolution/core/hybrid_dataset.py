"""Hybrid Dataset Builder — combines synthetic + session failure data.

Synthetic provides baseline coverage; session failures provide real-world edge cases.
Deduplicates overlapping cases, then balances so session data is at least 40% of the
final dataset when available.
"""
import json
from typing import Optional

from evolution.core.config import EvolutionConfig
from evolution.core.dataset_builder import EvalExample, EvalDataset, SyntheticDatasetBuilder
from evolution.core.session_grazer import SkillUsage


class HybridDatasetBuilder:
    """Combines synthetic test cases with real session failures into a unified dataset."""

    def __init__(
        self,
        config: Optional[EvolutionConfig] = None,
        synthetic_builder: Optional[SyntheticDatasetBuilder] = None,
    ):
        self.config = config or EvolutionConfig()
        self.synthetic_builder = synthetic_builder

    def build(
        self,
        skill_name: str,
        grazer_result: Optional[dict] = None,
    ) -> list[dict]:
        """Build a hybrid dataset.

        Args:
            skill_name: Target skill name.
            grazer_result: Output from SessionGrazer.run(), keyed 'failures'.
                           Each failure is a SkillUsage.to_dict() with task_input, error_type, etc.

        Returns:
            List of test case dicts with keys: task_input, expected_behavior, source.
        """
        synthetic_cases = self._get_synthetic(skill_name)
        session_cases = self._get_session_cases(grazer_result, skill_name)
        merged = self._merge(synthetic_cases, session_cases)
        deduped = self._deduplicate(merged)
        balanced = self._balance(deduped)
        return balanced

    def _get_synthetic(self, skill_name: str) -> list[dict]:
        """Generate or return empty list for synthetic cases."""
        if self.synthetic_builder is None:
            return []
        dataset: EvalDataset = self.synthetic_builder.generate(
            artifact_text=f"[hybrid] skill: {skill_name}",
            artifact_type="skill",
        )
        return [ex.to_dict() for ex in dataset.all_examples]

    @staticmethod
    def _get_session_cases(grazer_result: Optional[dict], skill_name: str) -> list[dict]:
        """Convert session failures into test case dicts."""
        if not grazer_result:
            return []
        failures = grazer_result.get("failures", [])
        cases = []
        for f in failures:
            if f.get("skill_name") and skill_name not in f["skill_name"]:
                continue
            if not f.get("task_input"):
                continue
            # Build expected behavior from the failure context
            error_ctx = f.get("error_message") or f.get("error_type") or "failure"
            expected = f"Handles the error gracefully. Context: {error_ctx}"
            cases.append({
                "task_input": f["task_input"],
                "expected_behavior": expected,
                "source": "session",
            })
        return cases

    @staticmethod
    def _merge(synthetic: list[dict], session: list[dict]) -> list[dict]:
        """Concatenate session (first) + synthetic (second).

        Session goes first so _balance can trim from the tail (synthetic) side.
        """
        return list(session) + list(synthetic)

    @staticmethod
    def _deduplicate(cases: list[dict]) -> list[dict]:
        """Remove duplicates by normalized task_input. Session cases win on conflict."""
        seen: set[str] = set()
        deduped = []

        # Session cases first — they're the ground truth
        session_cases = [c for c in cases if c.get("source") == "session"]
        synthetic_cases = [c for c in cases if c.get("source") != "session"]

        for case in session_cases + synthetic_cases:
            key = case.get("task_input", "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(case)

        return deduped

    @staticmethod
    def _balance(cases: list[dict], ratio: float = 0.4) -> list[dict]:
        """Ensure session failures make up at least `ratio` of the dataset.

        Strategy: if session ratio is below target, trim synthetic cases from the end.
        If session count exceeds the target, keep all (never drop real failures).
        """
        if not cases:
            return cases

        session_count = sum(1 for c in cases if c.get("source") == "session")
        total = len(cases)

        if total == 0:
            return cases

        current_ratio = session_count / total
        if current_ratio >= ratio or session_count == 0:
            return cases

        # Need at least `ratio` fraction to be session cases.
        # Keep all session cases + enough synthetic to fill the rest.
        # synthetic_target = session_count * (1 - ratio) / ratio
        synthetic_target = int(session_count * (1 - ratio) / ratio)
        # Keep all session cases + top synthetic_target synthetic cases
        session_cases = [c for c in cases if c.get("source") == "session"]
        synthetic_cases = [c for c in cases if c.get("source") != "session"]

        return session_cases + synthetic_cases[:synthetic_target]
