"""Reference Manager — scans SKILL.md files for related_skills references.

Detects broken references, finds overlapping skills, and suggests merges.
"""
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional


# ponytail: Overlap threshold is hardcoded. Move to config if tuning becomes frequent.
_OVERLAP_THRESHOLD = 0.4
_NAME_SIMILARITY_THRESHOLD = 0.6
_KEYWORD_OVERLAP_THRESHOLD = 0.3


class ReferenceManager:
    """Scans skills for related_skills references and detects issues."""

    def __init__(self, hermes_path: str = "~/.hermes"):
        self.hermes_path = Path(hermes_path).expanduser()
        self._skills_cache: Optional[dict[str, dict]] = None

    def _parse_frontmatter(self, content: str) -> dict:
        """Extract YAML frontmatter values as a flat dict.

        Lightweight parser — handles simple key: value and key: [list] lines.
        No external dependency on yaml.
        """
        fm: dict = {}
        in_frontmatter = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                break  # end of frontmatter
            if not in_frontmatter:
                continue
            # key: value
            m = re.match(r"^(\w[\w_-]*):\s*(.*)", stripped)
            if m:
                key, val = m.group(1), m.group(2).strip()
                # Detect inline list: [a, b, c]
                list_match = re.match(r"^\[(.*)\]$", val)
                if list_match:
                    fm[key] = [
                        item.strip().strip("\"'") for item in list_match.group(1).split(",") if item.strip()
                    ]
                else:
                    fm[key] = val.strip("\"'")
        return fm

    def _extract_body(self, content: str) -> str:
        """Return text after frontmatter, used for description/keyword extraction."""
        lines = content.split("\n")
        in_fm = False
        body_lines: list[str] = []
        started = False
        for line in lines:
            stripped = line.strip()
            if stripped == "---":
                if not in_fm:
                    in_fm = True
                    continue
                started = True
                continue
            if started or (not in_fm and not started):
                if started:
                    body_lines.append(line)
        return "\n".join(body_lines)

    def _load_all_skills(self) -> dict[str, dict]:
        """Load metadata for all installed skills.

        Returns dict keyed by skill dir name with values:
            {related_skills: [...], description: str, body: str, name: str}
        """
        if self._skills_cache is not None:
            return self._skills_cache

        self._skills_cache = {}
        skills_dir = self.hermes_path / "skills"
        if not skills_dir.is_dir():
            return self._skills_cache

        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                content = skill_file.read_text(encoding="utf-8")[:4000]
            except (OSError, UnicodeDecodeError):
                continue
            fm = self._parse_frontmatter(content)
            body = self._extract_body(content)
            related = fm.get("related_skills", [])
            if isinstance(related, str):
                related = [related]
            self._skills_cache[skill_dir.name] = {
                "name": fm.get("name", skill_dir.name),
                "description": fm.get("description", ""),
                "related_skills": related,
                "body": body,
            }
        return self._skills_cache

    def scan_references(self) -> list[dict]:
        """Scan all skills and return reference info for each.

        Returns list of dicts:
            {skill_name, related_skills: [str], broken_refs: [str]}
        """
        skills = self._load_all_skills()
        result = []
        for skill_name, meta in sorted(skills.items()):
            refs = meta["related_skills"]
            broken = [r for r in refs if r not in skills]
            result.append({
                "skill_name": skill_name,
                "related_skills": refs,
                "broken_refs": broken,
            })
        return result

    def find_broken_references(self) -> list[dict]:
        """Find all skills referencing non-existent skills.

        Returns list of {skill_name, missing_ref}.
        """
        refs = self.scan_references()
        broken = []
        for info in refs:
            for missing in info["broken_refs"]:
                broken.append({
                    "skill_name": info["skill_name"],
                    "missing_ref": missing,
                })
        return broken

    def detect_overlap(self) -> list[dict]:
        """Detect overlapping skills by name similarity and keyword overlap.

        Returns list of {skill_a, skill_b, similarity_score, reason}.
        """
        skills = self._load_all_skills()
        names = list(skills.keys())
        overlaps: list[dict] = []

        # ponytail: O(n^2) pair scan. Fine for hundreds of skills, not thousands.
        for i, name_a in enumerate(names):
            for name_b in names[i + 1:]:
                meta_a = skills[name_a]
                meta_b = skills[name_b]

                name_sim = SequenceMatcher(None, name_a, name_b).ratio()
                desc_sim = self._keyword_overlap(
                    meta_a["description"], meta_b["description"]
                )
                # Also check body text overlap
                body_sim = self._keyword_overlap(meta_a["body"], meta_b["body"])

                # Use best signal
                best_score = max(name_sim, desc_sim, body_sim)
                reasons = []
                if name_sim >= _NAME_SIMILARITY_THRESHOLD:
                    reasons.append("similar names")
                if desc_sim >= _KEYWORD_OVERLAP_THRESHOLD:
                    reasons.append("similar descriptions")
                if body_sim >= _KEYWORD_OVERLAP_THRESHOLD:
                    reasons.append("similar body content")

                if best_score >= _OVERLAP_THRESHOLD and reasons:
                    overlaps.append({
                        "skill_a": name_a,
                        "skill_b": name_b,
                        "similarity_score": round(best_score, 3),
                        "reason": "; ".join(reasons),
                    })

        overlaps.sort(key=lambda o: -o["similarity_score"])
        return overlaps

    def suggest_merges(self) -> list[dict]:
        """Suggest merges for highly overlapping skills.

        Returns list of {keep, merge_into, similarity_score, reason}.
        """
        overlaps = self.detect_overlap()
        suggestions = []
        seen_pairs: set[tuple[str, str]] = set()

        for ov in overlaps:
            pair = (ov["skill_a"], ov["skill_b"])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            if ov["similarity_score"] >= _OVERLAP_THRESHOLD:
                # Keep the skill with the longer description as the primary
                skills = self._load_all_skills()
                desc_a = skills[ov["skill_a"]]["description"]
                desc_b = skills[ov["skill_b"]]["description"]
                if len(desc_a) >= len(desc_b):
                    keep, merge_into = ov["skill_a"], ov["skill_b"]
                else:
                    keep, merge_into = ov["skill_b"], ov["skill_a"]
                suggestions.append({
                    "keep": keep,
                    "merge_into": merge_into,
                    "similarity_score": ov["similarity_score"],
                    "reason": ov["reason"],
                })

        return suggestions

    def to_report(self) -> str:
        """Generate a human-readable reference report."""
        refs = self.scan_references()
        broken = self.find_broken_references()
        overlaps = self.detect_overlap()
        merges = self.suggest_merges()

        lines = ["# Skill Reference Report", ""]

        # Summary
        total_refs = sum(len(r["related_skills"]) for r in refs)
        broken_count = len(broken)
        lines.append(
            f"**{len(refs)}** skills scanned, **{total_refs}** references, "
            f"**{broken_count}** broken"
        )
        if overlaps:
            lines.append(f"- **{len(overlaps)}** overlapping skill pairs detected")
        if merges:
            lines.append(f"- **{len(merges)}** merge suggestions")
        lines.append("")

        # Broken references
        if broken:
            lines.append("## Broken References")
            for b in broken:
                lines.append(f"- `{b['skill_name']}` → missing `{b['missing_ref']}`")
            lines.append("")

        # Overlaps
        if overlaps:
            lines.append("## Overlapping Skills")
            for ov in overlaps:
                lines.append(
                    f"- `{ov['skill_a']}` ↔ `{ov['skill_b']}` "
                    f"(score={ov['similarity_score']}, {ov['reason']})"
                )
            lines.append("")

        # Merge suggestions
        if merges:
            lines.append("## Merge Suggestions")
            for mg in merges:
                lines.append(
                    f"- Keep `{mg['keep']}`, absorb `{mg['merge_into']}` "
                    f"(score={mg['similarity_score']})"
                )
            lines.append("")

        if not broken and not overlaps:
            lines.append("No issues detected.")

        return "\n".join(lines)

    @staticmethod
    def _keyword_overlap(text_a: str, text_b: str) -> float:
        """Compute keyword overlap between two texts using set intersection."""
        if not text_a or not text_b:
            return 0.0
        kw_a = _extract_keywords(text_a)
        kw_b = _extract_keywords(text_b)
        if not kw_a or not kw_b:
            return 0.0
        intersection = kw_a & kw_b
        union = kw_a | kw_b
        return len(intersection) / len(union) if union else 0.0


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase alpha keywords from text (3+ chars)."""
    return {w for w in re.findall(r"[a-z]{3,}", text.lower())}
