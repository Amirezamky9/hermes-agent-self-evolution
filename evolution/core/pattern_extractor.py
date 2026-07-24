"""Pattern Extractor — groups skill failures and extracts recurring patterns.

Takes failure dicts from SessionGrazer, groups by skill_name / error_type,
and produces a PatternReport with actionable insights.
"""
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could am at by for in of on "
    "to and or but if then so than that this it its i me my we our you "
    "your he him his she her they them their what which who whom how when "
    "where why not no nor just also very too much many".split()
)

_WORD_RE = re.compile(r"[a-zA-Z]{3,}")


@dataclass
class PatternReport:
    total_patterns: int = 0
    error_distribution: dict[str, int] = field(default_factory=dict)
    common_keywords: list[tuple[str, int]] = field(default_factory=list)
    avg_input_length: float = 0.0
    input_length_correlation: float = 0.0
    per_skill_patterns: dict[str, list[dict]] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


class PatternExtractor:
    """Extracts recurring failure patterns from SessionGrazer output."""

    def extract_patterns(self, failures: list[dict]) -> PatternReport:
        if not failures:
            return PatternReport()

        error_dist = self.get_error_distribution(failures)
        keywords = self.get_common_keywords(failures)
        corr = self.get_correlation(failures)
        per_skill = self._get_per_skill(failures)
        recs = self._build_recommendations(failures, error_dist, keywords, corr)

        total = len(error_dist) + len(keywords) + len(per_skill)
        return PatternReport(
            total_patterns=total,
            error_distribution=error_dist,
            common_keywords=keywords,
            avg_input_length=corr["avg_input_length"],
            input_length_correlation=corr["correlation"],
            per_skill_patterns=per_skill,
            recommendations=recs,
        )

    def get_common_keywords(self, failures: list[dict]) -> list[tuple[str, int]]:
        """Top keywords in task_inputs across all failures."""
        counter: Counter[str] = Counter()
        for f in failures:
            text = f.get("task_input", "")
            for word in _WORD_RE.findall(text):
                lw = word.lower()
                if lw not in _STOP_WORDS:
                    counter[lw] += 1
        return counter.most_common(20)

    def get_error_distribution(self, failures: list[dict]) -> dict[str, int]:
        """Count failures per error_type, plus 'success' for non-failures."""
        return dict(Counter(f.get("error_type", "unknown") for f in failures))

    def get_correlation(self, failures: list[dict]) -> dict:
        """Pearson correlation between input length and failure occurrence.

        Since every item in the list is a failure, we correlate input length
        against *position* in the list (a proxy for time) to detect whether
        longer inputs fail more as time progresses — i.e. an increasing-failure
        trend that suggests input length matters.

        Also returns avg_input_length and per-type stats.
        """
        lengths = [len(f.get("task_input", "")) for f in failures]
        avg = sum(lengths) / len(lengths) if lengths else 0.0

        # Per error-type average input length
        type_lengths: dict[str, list[int]] = defaultdict(list)
        for f in failures:
            type_lengths[f.get("error_type", "unknown")].append(len(f.get("task_input", "")))
        avg_per_type = {k: sum(v) / len(v) for k, v in type_lengths.items()}

        # Pearson correlation: input_length vs index
        n = len(lengths)
        if n < 2:
            corr = 0.0
        else:
            indices = list(range(n))
            mean_idx = (n - 1) / 2.0
            mean_len = avg
            cov = sum((i - mean_idx) * (l - mean_len) for i, l in zip(indices, lengths))
            var_idx = sum((i - mean_idx) ** 2 for i in indices)
            var_len = sum((l - mean_len) ** 2 for l in lengths)
            denom = math.sqrt(var_idx * var_len)
            corr = cov / denom if denom > 0 else 0.0

        return {
            "correlation": round(corr, 4),
            "avg_input_length": round(avg, 2),
            "avg_per_type": avg_per_type,
        }

    def _get_per_skill(self, failures: list[dict]) -> dict[str, list[dict]]:
        """Group failures by skill_name, with error counts."""
        grouped: dict[str, Counter] = defaultdict(Counter)
        grouped_msgs: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for f in failures:
            skill = f.get("skill_name", "unknown")
            err = f.get("error_type", "unknown")
            grouped[skill][err] += 1
            msgs = grouped_msgs[skill][err]
            if len(msgs) < 3:
                msgs.append(f.get("error_message", "")[:200])

        result: dict[str, list[dict]] = {}
        for skill, counter in grouped.items():
            patterns = []
            for err_type, count in counter.most_common():
                patterns.append({
                    "error_type": err_type,
                    "count": count,
                    "sample_messages": grouped_msgs[skill][err_type],
                })
            result[skill] = patterns
        return result

    def _build_recommendations(
        self,
        failures: list[dict],
        error_dist: dict[str, int],
        keywords: list[tuple[str, int]],
        corr: dict,
    ) -> list[str]:
        recs: list[str] = []
        total = len(failures)

        # Dominant error type
        if error_dist:
            dominant = max(error_dist, key=lambda k: error_dist[k])
            pct = error_dist[dominant] / total * 100
            if pct > 50:
                recs.append(
                    f"Focus on '{dominant}' errors: {pct:.0f}% of all failures"
                )

        # High-failure skills
        skill_counts: Counter = Counter(f.get("skill_name", "unknown") for f in failures)
        for skill, count in skill_counts.most_common(3):
            pct = count / total * 100
            recs.append(f"Skill '{skill}' has {count} failures ({pct:.0f}%) — prioritize fixes")

        # Correlation insight
        if abs(corr["correlation"]) > 0.3:
            direction = "longer" if corr["correlation"] > 0 else "shorter"
            recs.append(
                f"Input length correlation {corr['correlation']:.2f}: {direction} inputs fail more over time"
            )

        # Frequent keywords
        if keywords:
            top3 = ", ".join(kw for kw, _ in keywords[:3])
            recs.append(f"Failure-triggering keywords: {top3}")

        return recs
