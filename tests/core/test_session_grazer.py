"""Tests for session_grazer — uses a temporary SQLite DB with sample data."""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from evolution.core.session_grazer import SessionGrazer, SkillUsage


# ponytail: This creates the exact schema from ~/.hermes/state.db.
# Add new columns when Hermes adds them; this covers the subset SessionGrazer reads.


def _create_test_db(db_path: Path):
    """Create a minimal Hermes state.db schema and populate with test data."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            session_key TEXT,
            chat_id TEXT,
            chat_type TEXT,
            thread_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            end_reason TEXT,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            reasoning_tokens INTEGER DEFAULT 0,
            cwd TEXT,
            git_branch TEXT,
            git_repo_root TEXT,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            title TEXT,
            api_call_count INTEGER DEFAULT 0,
            handoff_state TEXT,
            handoff_platform TEXT,
            handoff_error TEXT,
            compression_failure_cooldown_until REAL,
            compression_failure_error TEXT,
            rewind_count INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL NOT NULL,
            token_count INTEGER,
            finish_reason TEXT,
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            codex_reasoning_items TEXT,
            codex_message_items TEXT,
            platform_message_id TEXT,
            observed INTEGER DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            compacted INTEGER NOT NULL DEFAULT 0
        );
    """)

    # Session 1: successful skill_view
    conn.execute(
        "INSERT INTO sessions (id, source, started_at, message_count, tool_call_count) VALUES (?, ?, ?, ?, ?)",
        ("sess_success", "cli", 1700000000.0, 4, 2),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_success", "user", "Load the gstack-spec skill please", 1700000000.0),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_calls, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_success",
            "assistant",
            json.dumps(
                [
                    {
                        "id": "call_abc123",
                        "call_id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "skill_view",
                            "arguments": json.dumps({"name": "gstack/spec"}),
                        },
                    }
                ]
            ),
            "Loading gstack/spec skill.",
            1700000001.0,
        ),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_call_id, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_success",
            "tool",
            "call_abc123",
            json.dumps(
                {
                    "name": "gstack/spec",
                    "content": "# Skill: gstack-spec\n## Overview\nThis skill turns intent into spec.",
                    "file_path": "SKILL.md",
                    "success": True,
                }
            ),
            1700000002.0,
        ),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_success", "assistant", "The skill has been loaded successfully.", 1700000003.0),
    )

    # Session 2: skill not found error
    conn.execute(
        "INSERT INTO sessions (id, source, started_at, message_count, tool_call_count) VALUES (?, ?, ?, ?, ?)",
        ("sess_error", "cli", 1700000100.0, 4, 2),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_error", "user", "Show me the n8n-workflow-pipeline skill", 1700000100.0),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_calls, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_error",
            "assistant",
            json.dumps(
                [
                    {
                        "id": "call_err1",
                        "call_id": "call_err1",
                        "type": "function",
                        "function": {
                            "name": "skill_view",
                            "arguments": json.dumps({"name": "n8n-workflow-pipeline"}),
                        },
                    }
                ]
            ),
            "Trying to load the skill.",
            1700000101.0,
        ),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_call_id, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_error",
            "tool",
            "call_err1",
            json.dumps(
                {
                    "error": "Skill 'n8n-workflow-pipeline' is disabled. Enable it with `hermes skills`.",
                    "success": False,
                }
            ),
            1700000102.0,
        ),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_error", "assistant", "The skill is disabled. This failed.", 1700000103.0),
    )

    # Session 3: terminal exit code error (not skill-related but tests error detection)
    conn.execute(
        "INSERT INTO sessions (id, source, started_at, message_count, tool_call_count) VALUES (?, ?, ?, ?, ?)",
        ("sess_terminal_err", "cli", 1700000200.0, 3, 1),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_terminal_err", "user", "Run a failing command", 1700000200.0),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_calls, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_terminal_err",
            "assistant",
            json.dumps(
                [
                    {
                        "id": "call_term1",
                        "call_id": "call_term1",
                        "type": "function",
                        "function": {
                            "name": "terminal",
                            "arguments": json.dumps({"command": "exit 1"}),
                        },
                    }
                ]
            ),
            "Running the command.",
            1700000201.0,
        ),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_call_id, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_terminal_err",
            "tool",
            "call_term1",
            json.dumps({"output": "", "exit_code": 1, "error": None}),
            1700000202.0,
        ),
    )

    # Session 4: skill_manage with lint error
    conn.execute(
        "INSERT INTO sessions (id, source, started_at, message_count, tool_call_count) VALUES (?, ?, ?, ?, ?)",
        ("sess_lint", "cli", 1700000300.0, 3, 1),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_lint", "user", "Update the skill", 1700000300.0),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_calls, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_lint",
            "assistant",
            json.dumps(
                [
                    {
                        "id": "call_lint1",
                        "call_id": "call_lint1",
                        "type": "function",
                        "function": {
                            "name": "skill_manage",
                            "arguments": json.dumps(
                                {"action": "patch", "name": "my-skill"}
                            ),
                        },
                    }
                ]
            ),
            "Updating the skill now.",
            1700000301.0,
        ),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, tool_call_id, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            "sess_lint",
            "tool",
            "call_lint1",
            json.dumps(
                {"bytes_written": 100, "lint": {"status": "error", "output": "SyntaxError at line 5"}}
            ),
            1700000302.0,
        ),
    )

    # Session 5: no skill calls at all (should be skipped)
    conn.execute(
        "INSERT INTO sessions (id, source, started_at, message_count, tool_call_count) VALUES (?, ?, ?, ?, ?)",
        ("sess_noskill", "cli", 1700000400.0, 2, 0),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_noskill", "user", "Hello", 1700000400.0),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        ("sess_noskill", "assistant", "Hi there!", 1700000401.0),
    )

    conn.commit()
    conn.close()


@pytest.fixture
def grazer(tmp_path):
    """Create a SessionGrazer pointed at a temporary test database."""
    db_path = tmp_path / "test_state.db"
    _create_test_db(db_path)
    return SessionGrazer(db_path=str(db_path))


class TestFindRecentSessions:
    def test_returns_sessions(self, grazer):
        sessions = grazer.find_recent_sessions(limit=10)
        assert len(sessions) == 5

    def test_ordering_is_desc(self, grazer):
        sessions = grazer.find_recent_sessions(limit=10)
        timestamps = [s["started_at"] for s in sessions]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_limit_works(self, grazer):
        sessions = grazer.find_recent_sessions(limit=2)
        assert len(sessions) == 2

    def test_session_fields(self, grazer):
        sessions = grazer.find_recent_sessions(limit=1)
        s = sessions[0]
        assert "session_id" in s
        assert "started_at" in s
        assert "message_count" in s


class TestGetSkillUsageStats:
    def test_finds_skill_view_calls(self, grazer):
        usages = grazer.get_skill_usage_stats()
        assert len(usages) == 3  # sess_success + sess_error + sess_lint (terminal session has no skill calls, sess_noskill has none)
        skill_names = [u.skill_name for u in usages]
        assert "gstack/spec" in skill_names
        assert "n8n-workflow-pipeline" in skill_names
        assert "my-skill" in skill_names

    def test_extracts_task_input(self, grazer):
        usages = grazer.get_skill_usage_stats()
        gstack_usage = [u for u in usages if u.skill_name == "gstack/spec"][0]
        assert "Load the gstack-spec skill" in gstack_usage.task_input

    def test_no_error_on_success(self, grazer):
        usages = grazer.get_skill_usage_stats()
        gstack_usage = [u for u in usages if u.skill_name == "gstack/spec"][0]
        assert gstack_usage.error_type == ""
        assert gstack_usage.error_message == ""

    def test_skips_sessions_without_skills(self, grazer):
        usages = grazer.get_skill_usage_stats()
        session_ids = {u.session_id for u in usages}
        assert "sess_noskill" not in session_ids


class TestExtractFailures:
    def test_finds_disabled_skill_error(self, grazer):
        failures = grazer.extract_failures()
        disabled = [f for f in failures if "n8n-workflow-pipeline" in f.skill_name]
        assert len(disabled) >= 1
        assert disabled[0].error_type == "tool_error"
        assert "disabled" in disabled[0].error_message.lower()

    def test_finds_lint_error(self, grazer):
        failures = grazer.extract_failures()
        lint_failures = [f for f in failures if f.error_type == "lint_error"]
        assert len(lint_failures) >= 1
        assert lint_failures[0].skill_name == "my-skill"

    def test_success_not_in_failures(self, grazer):
        failures = grazer.extract_failures()
        gstack_failures = [f for f in failures if f.skill_name == "gstack/spec"]
        assert len(gstack_failures) == 0

    def test_error_has_session_id(self, grazer):
        failures = grazer.extract_failures()
        for f in failures:
            assert f.session_id
            assert f.error_type
            assert f.error_message


class TestRun:
    def test_returns_all_keys(self, grazer):
        result = grazer.run(limit=10)
        assert "sessions" in result
        assert "skill_usages" in result
        assert "failures" in result
        assert "skill_counts" in result
        assert "failure_counts" in result
        assert "total_sessions" in result
        assert "total_skill_invocations" in result
        assert "total_failures" in result

    def test_totals_consistent(self, grazer):
        result = grazer.run(limit=10)
        assert result["total_sessions"] == 5
        assert result["total_skill_invocations"] == len(result["skill_usages"])
        assert result["total_failures"] == len(result["failures"])

    def test_skill_counts_match(self, grazer):
        result = grazer.run(limit=10)
        from collections import Counter
        expected = Counter(u["skill_name"] for u in result["skill_usages"])
        assert result["skill_counts"] == dict(expected)

    def test_to_dict_output(self, grazer):
        result = grazer.run(limit=10)
        for u in result["skill_usages"]:
            assert "session_id" in u
            assert "datetime" in u
            assert "skill_name" in u
            assert "error_type" in u

    def test_limit_controls_session_count(self, grazer):
        r2 = grazer.run(limit=2)
        assert r2["total_sessions"] == 2


class TestSkillUsageDataclass:
    def test_to_dict(self):
        u = SkillUsage(
            session_id="test",
            timestamp=1700000000.0,
            skill_name="test-skill",
            task_input="do something",
            response="ok",
            error_type="",
            error_message="",
        )
        d = u.to_dict()
        assert d["skill_name"] == "test-skill"
        assert d["datetime"]  # non-empty
        assert d["error_type"] == ""
