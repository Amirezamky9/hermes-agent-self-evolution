"""Cognitive Load Analyzer — scores a SKILL.md text on 9 dimensions of complexity.

Based on research from Reddit r/PromptEngineering. Each dimension is scored
0-100, then a weighted average produces a total cognitive load score.
"""

import re
from dataclasses import dataclass
from typing import Dict


@dataclass
class CognitiveLoadResult:
    """Result of a single cognitive-load analysis run."""

    # Raw counts
    task_count: int = 0
    reasoning_depth: int = 0
    tool_complexity: int = 0
    constraint_density: int = 0
    output_complexity: int = 0
    temporal_complexity: int = 0
    ambiguity: int = 0
    state_border_load: int = 0
    context_pressure: float = 0.0

    # Scaled scores 0-100
    task_score: float = 0.0
    reasoning_score: float = 0.0
    tool_score: float = 0.0
    constraint_score: float = 0.0
    output_score: float = 0.0
    temporal_score: float = 0.0
    ambiguity_score: float = 0.0
    state_score: float = 0.0
    context_score: float = 0.0

    total_score: float = 0.0
    severity: str = "light"  # "light", "moderate", "heavy"
    penalty: float = 0.0  # 0.0 / 0.15 / 0.30


# Weights for the 9 dimensions (must sum to 1.0)
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "task": 0.18,
    "reasoning": 0.15,
    "tool": 0.12,
    "constraint": 0.12,
    "output": 0.10,
    "temporal": 0.10,
    "ambiguity": 0.08,
    "state": 0.08,
    "context": 0.07,
}
# ponytail: hardcoded weights; move to config or auto-tune when more data exists.

# Ceilings for raw-count → 0-100 scaling. Derived from empirical SKILL.md corpus.
_CEILINGS = {
    "task": 40,
    "reasoning": 20,
    "tool": 15,
    "constraint": 25,
    "output": 15,
    "temporal": 15,
    "ambiguity": 10,
    "state": 15,
}

_ACTION_VERBS = re.compile(
    r"\b(implement|create|check|verify|run|build|write|update|delete|remove|"
    r"add|configure|setup|install|deploy|test|validate|parse|extract|"
    r"transform|generate|fetch|load|save|export|import|merge|split|"
    r"filter|sort|search|replace|modify|edit|patch|apply|execute)\b",
    re.IGNORECASE,
)

_CONDITIONAL_PATTERNS = re.compile(
    r"\b(if|elif|else|when\s+\w+\s+then|unless|otherwise|"
    r"depending\s+on|in\s+case|switch|case\s+\w+:)\b",
    re.IGNORECASE,
)

_TOOL_NAMES = re.compile(
    r"\b(read_file|write_file|patch|terminal|process|search_files|"
    r"web_search|web_fetch|vision_analyze|video_analyze|"
    r"session_search|skill_view|skill_manage|skills_list|"
    r"todo|browser|codebase|diagram|notebooklm)\b",
    re.IGNORECASE,
)

_CONSTRAINT_WORDS = re.compile(
    r"\b(must\b|should\b|never\b|always\b|required\b|shall\b|"
    r"mandatory\b|forbidden\b|prohibited\b|must\s+not|should\s+not)\b",
    re.IGNORECASE,
)

_OUTPUT_FORMATS = re.compile(
    r"\b(JSON|markdown|list|table|csv|xml|yaml|html|text|"
    r"dictionary|array|string|integer|boolean|float)\b",
    re.IGNORECASE,
)

_TEMPORAL_WORDS = re.compile(
    r"\b(before\b|after\b|then\b|finally\b|first\b|second\b|"
    r"next\b|meanwhile\b|during\b|once\b|until\b|"
    r"subsequently|afterwards|previously)\b",
    re.IGNORECASE,
)

_AMBIGUITY_WORDS = re.compile(
    r"\b(maybe\b|perhaps\b|might\b|could\b|possibly\b|roughly\b|"
    r"approximately|about\b|seems?\b|probably|likely\b|"
    r"potentially|suggest|occasionally)\b",
    re.IGNORECASE,
)

_STATE_REFERENCES = re.compile(
    r"\b(previous\b|current\b|next\b|context\b|state\b|"
    r"history\b|memory\b|cache\b|session\b|"
    r"beforehand|subsequent|antecedent|ongoing)\b",
    re.IGNORECASE,
)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _count_matches(pattern: re.Pattern, text: str) -> int:
    return len(pattern.findall(text))


class CognitiveLoadAnalyzer:
    """Scores a skill text's cognitive load across 9 dimensions.

    Usage::

        analyzer = CognitiveLoadAnalyzer()
        result = analyzer.analyze(skill_text)
        penalty = analyzer.get_penalty(result.total_score)
    """

    _weights: Dict[str, float]

    def __init__(self, weights: Dict[str, float] | None = None):
        self._weights = weights if weights is not None else dict(_DEFAULT_WEIGHTS)

    def analyze(self, skill_text: str) -> CognitiveLoadResult:
        """Analyze a skill's full text and return scored dimensions."""
        result = CognitiveLoadResult()
        n_words = len(skill_text.split()) or 1
        n_instruction_words = len(
            [w for w in skill_text.split() if w.lower() not in _NON_INSTRUCTION]
        )

        # --- Count raw metrics ---
        result.task_count = _count_matches(_ACTION_VERBS, skill_text)
        result.reasoning_depth = _count_matches(_CONDITIONAL_PATTERNS, skill_text)
        result.tool_complexity = _count_matches(_TOOL_NAMES, skill_text)
        result.constraint_density = _count_matches(_CONSTRAINT_WORDS, skill_text)
        result.output_complexity = _count_matches(_OUTPUT_FORMATS, skill_text)
        result.temporal_complexity = _count_matches(_TEMPORAL_WORDS, skill_text)
        result.ambiguity = _count_matches(_AMBIGUITY_WORDS, skill_text)
        result.state_border_load = _count_matches(_STATE_REFERENCES, skill_text)
        result.context_pressure = n_instruction_words / n_words

        # --- Scale to 0-100 ---
        result.task_score = _clamp(result.task_count / _CEILINGS["task"] * 100.0)
        result.reasoning_score = _clamp(
            result.reasoning_depth / _CEILINGS["reasoning"] * 100.0
        )
        result.tool_score = _clamp(
            result.tool_complexity / _CEILINGS["tool"] * 100.0
        )
        result.constraint_score = _clamp(
            result.constraint_density / _CEILINGS["constraint"] * 100.0
        )
        result.output_score = _clamp(
            result.output_complexity / _CEILINGS["output"] * 100.0
        )
        result.temporal_score = _clamp(
            result.temporal_complexity / _CEILINGS["temporal"] * 100.0
        )
        result.ambiguity_score = _clamp(
            result.ambiguity / _CEILINGS["ambiguity"] * 100.0
        )
        result.state_score = _clamp(
            result.state_border_load / _CEILINGS["state"] * 100.0
        )
        # Context pressure is already 0-1, multiply by 100
        result.context_score = _clamp(result.context_pressure * 100.0)

        # --- Weighted total ---
        result.total_score = (
            result.task_score * self._weights["task"]
            + result.reasoning_score * self._weights["reasoning"]
            + result.tool_score * self._weights["tool"]
            + result.constraint_score * self._weights["constraint"]
            + result.output_score * self._weights["output"]
            + result.temporal_score * self._weights["temporal"]
            + result.ambiguity_score * self._weights["ambiguity"]
            + result.state_score * self._weights["state"]
            + result.context_score * self._weights["context"]
        )

        # --- Severity & penalty ---
        if result.total_score < 30:
            result.severity = "light"
            result.penalty = 0.0
        elif result.total_score <= 60:
            result.severity = "moderate"
            result.penalty = 0.15
        else:
            result.severity = "heavy"
            result.penalty = 0.30

        return result

    @staticmethod
    def get_penalty(score: float) -> float:
        """Return the penalty multiplier (0.0 / 0.15 / 0.30) for a given score."""
        if score < 30:
            return 0.0
        if score <= 60:
            return 0.15
        return 0.30


# Function-word stoplist — words that carry negligible instructional weight.
# Used by context_pressure to approximate "instruction text" vs "filler text".
_NON_INSTRUCTION: set = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "need", "dare",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "because", "and", "but", "or", "if", "while", "that",
    "this", "which", "who", "whom", "what", "it", "its", "i", "you",
    "he", "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "mine", "yours", "his",
    "hers", "ours", "theirs", "not", "n't",
}
