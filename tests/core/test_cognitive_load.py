"""Tests for CognitiveLoadAnalyzer — simple, heavy, and edge-case SKILL.md inputs."""

import pytest

from evolution.core.cognitive_load import (
    CognitiveLoadAnalyzer,
    CognitiveLoadResult,
    _count_matches,
    _ACTION_VERBS,
    _AMBIGUITY_WORDS,
)


# --- Fixtures ---


@pytest.fixture
def analyzer():
    return CognitiveLoadAnalyzer()


SIMPLE_SKILL = """# My Skill

This skill writes a greeting to the user.

Steps:
1. Read the user's name.
2. Create a greeting message.
3. Write the greeting.

No conditional logic is needed.
"""

COMPLEX_SKILL = """# Complex Integration Skill

This skill deploys a web service. It must verify prerequisites first.
If the service is running, stop it before deploying. When the port is
in use, then free it. Otherwise proceed with the fresh install.

Steps:
1. First, check if Docker is running — required before anything else.
2. If not running, start Docker. Then pull the latest image.
3. Always validate the image hash after pulling.
4. Never run containers as root — use a non-root user.
5. Finally, deploy the container and verify health.

After deployment, run integration tests. Before marking complete,
always check the logs for errors.

The output must be valid JSON containing:
- status: string
- version: string
- checks: list of check results

The previous deployment state is cached in /tmp/deploy-state.
Current context is the production environment.
Next step is to notify the team.

Maybe the Docker socket needs extra permissions. This could cause
permission errors. The health check might fail occasionally.
Potentially we should wrap in a retry loop.
"""

EMPTY_TEXT = ""
SHORT_TEXT = "Hello world."
VERY_LONG_TEXT = """# Long Skill

""" + " ".join(
    ["check"] * 100 + ["if"] * 50 + ["must"] * 30 + ["then"] * 20
)


# --- Test helper ---


class TestCountMatches:
    def test_action_verbs(self):
        assert _count_matches(_ACTION_VERBS, "Implement and create and verify") == 3

    def test_no_matches(self):
        assert _count_matches(_ACTION_VERBS, "just some words") == 0

    def test_ambiguity_words(self):
        assert _count_matches(_AMBIGUITY_WORDS, "maybe perhaps might could") == 4


# --- Test empty / short edge cases ---


class TestEdgeCases:
    def test_empty_skill(self, analyzer):
        r = analyzer.analyze(EMPTY_TEXT)
        assert r.total_score == 0.0
        assert r.severity == "light"
        assert r.penalty == 0.0

    def test_short_skill(self, analyzer):
        r = analyzer.analyze(SHORT_TEXT)
        assert r.task_count == 0
        assert r.severity == "light"

    def test_very_long_skill(self, analyzer):
        r = analyzer.analyze(VERY_LONG_TEXT)
        # Lots of action verbs, conditionals, constraints -> heavy
        assert r.task_count >= 90
        assert r.constraint_density >= 25
        assert r.reasoning_depth >= 45


# --- Test simple skill (low load) ---


class TestSimpleSkill:
    def test_low_scores(self, analyzer):
        r = analyzer.analyze(SIMPLE_SKILL)
        assert r.task_count >= 2  # "Read", "Create", "Write", "writes"...
        assert r.reasoning_depth == 0  # no conditionals
        assert r.tool_complexity == 0  # no tool references
        assert r.constraint_density == 0  # no must/should
        assert r.ambiguity == 0  # no vague words
        assert r.total_score < 50  # should be fairly low
        assert r.severity in ("light", "moderate")

    def test_dataclass_fields_populated(self, analyzer):
        r = analyzer.analyze(SIMPLE_SKILL)
        assert isinstance(r, CognitiveLoadResult)
        assert r.task_score > 0
        assert r.context_pressure > 0


# --- Test complex skill (high load) ---


class TestComplexSkill:
    def test_high_counts(self, analyzer):
        r = analyzer.analyze(COMPLEX_SKILL)
        assert r.task_count >= 10
        assert r.reasoning_depth >= 3  # if/when/otherwise
        assert r.constraint_density >= 4  # must/required/always/never
        assert r.temporal_complexity >= 3  # before/after/then/finally
        assert r.ambiguity >= 2  # maybe/could/might/potentially
        assert r.state_border_load >= 2  # previous/current/next

    def test_heavy_severity(self, analyzer):
        r = analyzer.analyze(COMPLEX_SKILL)
        assert r.total_score > 30  # at least moderate
        assert r.penalty > 0

    def test_output_complexity(self, analyzer):
        r = analyzer.analyze(COMPLEX_SKILL)
        assert r.output_complexity >= 3  # JSON, string, list


# --- Test get_penalty ---


class TestPenalty:
    def test_light_penalty(self):
        assert CognitiveLoadAnalyzer.get_penalty(0) == 0.0
        assert CognitiveLoadAnalyzer.get_penalty(29.9) == 0.0

    def test_moderate_penalty(self):
        assert CognitiveLoadAnalyzer.get_penalty(30) == 0.15
        assert CognitiveLoadAnalyzer.get_penalty(45) == 0.15
        assert CognitiveLoadAnalyzer.get_penalty(60) == 0.15

    def test_heavy_penalty(self):
        assert CognitiveLoadAnalyzer.get_penalty(60.1) == 0.30
        assert CognitiveLoadAnalyzer.get_penalty(100) == 0.30

    def test_custom_weights(self):
        weights = {"task": 1.0, "reasoning": 0, "tool": 0, "constraint": 0,
                   "output": 0, "temporal": 0, "ambiguity": 0, "state": 0, "context": 0}
        a = CognitiveLoadAnalyzer(weights=weights)
        r = a.analyze("implement, create, verify, run, build")
        assert r.total_score == r.task_score  # only task counts


# --- Test context_pressure on varied texts ---


class TestContextPressure:
    def test_filler_only(self, analyzer):
        # All filler words -> low context pressure
        r = analyzer.analyze("the a an is of in it")
        assert r.context_pressure < 0.3

    def test_full_instruction(self, analyzer):
        r = analyzer.analyze("implement the check and verify the must should")
        assert r.context_pressure > 0.3
