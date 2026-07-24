"""Session Grazer — reads Hermes Agent session database for skill failures and usage patterns.

Reads ~/.hermes/state.db directly via SQLite. Extracts skill_view/skill_manage
calls, their responses, and detects failures from error patterns in content.
"""
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class SkillUsage:
    """A single skill invocation extracted from session data."""
    session_id: str
    timestamp: float
    skill_name: str
    task_input: str  # the user message that triggered this skill load
    response: str  # tool response content (truncated)
    error_type: str  # "", "tool_error", "exit_code_error", "skill_not_found", "timeout"
    error_message: str  # detail of failure, empty on success
    message_id: int = 0  # the assistant message containing the tool call

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat() if self.timestamp else "",
            "skill_name": self.skill_name,
            "task_input": self.task_input,
            "response": self.response[:500],
            "error_type": self.error_type,
            "error_message": self.error_message[:500],
            "message_id": self.message_id,
        }


# Patterns that indicate genuine failure in tool response content
# More conservative: avoid matching doc/code that happens to contain "error"
_ERROR_PATTERNS = [
    re.compile(r'"exit_code"\s*:\s*-1'),
    re.compile(r'"exit_code"\s*:\s*[1-9]\d*'),
    re.compile(r'"error"\s*:\s*"[^"]{3,}"'),   # non-empty error field in JSON
    re.compile(r'^Traceback \(most recent call last\)', re.MULTILINE),
    re.compile(r'^.*Error:\s+.+', re.MULTILINE),  # Python Exception: lines
    re.compile(r'command not found'),
    re.compile(r'No such file or directory'),
    re.compile(r'Permission denied'),
    re.compile(r'rate limit', re.IGNORECASE),
]

_VALID_SKILL_SIGNALS = re.compile(
    r'(SKILL\.md|# Skill\b|---\nname:|## Overview|## Steps|## Usage)',
    re.IGNORECASE,
)

# Patterns for failure signals in assistant text after a skill call
_ASSISTANT_FAILURE_PATTERNS = [
    re.compile(r'skill.*(?:fail|error|not found|missing|broken)', re.IGNORECASE),
    re.compile(r'couldn.t.*(?:load|find|read).*skill', re.IGNORECASE),
    re.compile(r'(?:load|view|manage).*skill.*(?:fail|error)', re.IGNORECASE),
]


class SessionGrazer:
    """Reads Hermes session DB to find skill usage patterns and failures."""

    def __init__(self, db_path: str = "~/.hermes/state.db"):
        self.db_path = Path(db_path).expanduser()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def find_recent_sessions(self, limit: int = 20) -> list[dict]:
        """Return recent session summaries, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, title, started_at, ended_at, message_count,
                          tool_call_count, source, model
                   FROM sessions
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "session_id": r[0],
                "title": r[1],
                "started_at": r[2],
                "ended_at": r[3],
                "message_count": r[4],
                "tool_call_count": r[5],
                "source": r[6],
                "model": r[7],
            }
            for r in rows
        ]

    def _get_skill_calls_in_session(self, conn: sqlite3.Connection, session_id: str) -> list[dict]:
        """Extract skill_view/skill_manage tool calls and their responses from a session.

        Returns list of dicts with keys: assistant_msg_id, skill_name, arguments,
        tool_call_id, response_content, timestamp.
        """
        # Find assistant messages with skill tool calls
        rows = conn.execute(
            """SELECT id, tool_calls, content, timestamp
               FROM messages
               WHERE session_id = ?
                 AND role = 'assistant'
                 AND tool_calls IS NOT NULL
                 AND (tool_calls LIKE '%skill_view%' OR tool_calls LIKE '%skill_manage%')
               ORDER BY timestamp""",
            (session_id,),
        ).fetchall()

        results = []
        for assistant_msg_id, tool_calls_json, content, ts in rows:
            try:
                tool_calls = json.loads(tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                continue

            for tc in tool_calls:
                fname = tc.get("function", {}).get("name", "")
                if fname not in ("skill_view", "skill_manage"):
                    continue
                call_id = tc.get("id") or tc.get("call_id", "")
                try:
                    args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}

                skill_name = args.get("name", "")
                # Find corresponding tool response
                resp_row = conn.execute(
                    """SELECT content FROM messages
                       WHERE session_id = ? AND role = 'tool' AND tool_call_id = ?""",
                    (session_id, call_id),
                ).fetchone()

                response_content = resp_row[0] if resp_row else ""

                results.append({
                    "assistant_msg_id": assistant_msg_id,
                    "skill_name": skill_name,
                    "arguments": args,
                    "tool_call_id": call_id,
                    "response_content": response_content,
                    "timestamp": ts,
                    "assistant_content": content or "",
                })

        return results

    def _get_context_user_message(self, conn: sqlite3.Connection, session_id: str, msg_id: int) -> str:
        """Get the most recent user message before a given assistant message ID."""
        row = conn.execute(
            """SELECT content FROM messages
               WHERE session_id = ? AND role = 'user' AND id < ?
               ORDER BY id DESC LIMIT 1""",
            (session_id, msg_id),
        ).fetchone()
        return row[0] if row and row[0] else ""

    def _detect_error(self, response_content: str, assistant_content_after: str) -> tuple[str, str]:
        """Detect errors in tool response and following assistant message.

        Returns (error_type, error_message).
        """
        if not response_content:
            return "", ""

        # Try to parse as JSON for structured error detection
        try:
            resp_data = json.loads(response_content)
        except (json.JSONDecodeError, TypeError):
            resp_data = None

        # Check structured errors first
        if resp_data and isinstance(resp_data, dict):
            # Successful response — skip error detection
            if resp_data.get("success") is True:
                return "", ""
            # Terminal exit code
            if "exit_code" in resp_data and resp_data["exit_code"] not in (0, None):
                return "exit_code_error", f"exit_code={resp_data['exit_code']}: {resp_data.get('error', '') or resp_data.get('output', '')[:200]}"
            # Explicit error field
            if resp_data.get("error"):
                return "tool_error", str(resp_data["error"])[:500]
            # Write_file lint failures
            if resp_data.get("lint", {}).get("status") == "error":
                return "lint_error", str(resp_data["lint"].get("output", ""))[:500]

        # Regex-based error detection on raw content
        # First check: if response looks like valid skill content, skip error detection
        if _VALID_SKILL_SIGNALS.search(response_content):
            return "", ""

        for pattern in _ERROR_PATTERNS:
            match = pattern.search(response_content)
            if match:
                # Try to extract meaningful error from match context
                start = max(0, match.start() - 50)
                end = min(len(response_content), match.end() + 100)
                snippet = response_content[start:end]
                return "content_error", snippet

        # Check assistant content for skill failure mentions
        if assistant_content_after:
            for pattern in _ASSISTANT_FAILURE_PATTERNS:
                match = pattern.search(assistant_content_after)
                if match:
                    start = max(0, match.start() - 30)
                    end = min(len(assistant_content_after), match.end() + 100)
                    return "skill_failure_signal", assistant_content_after[start:end]

        return "", ""

    def extract_failures(self, sessions: Optional[list[dict]] = None) -> list[SkillUsage]:
        """Find skill invocations with detected failures.

        Args:
            sessions: list of session dicts (from find_recent_sessions). If None,
                      scans all sessions with skill tool calls.
        """
        return [u for u in self.get_skill_usage_stats(sessions) if u.error_type]

    def get_skill_usage_stats(self, sessions: Optional[list[dict]] = None) -> list[SkillUsage]:
        """Extract all skill_view/skill_manage usages across sessions.

        Returns list of SkillUsage dataclass instances.
        """
        if sessions is None:
            sessions = self.find_recent_sessions(limit=100)

        usages = []
        with self._conn() as conn:
            for session in sessions:
                sid = session["session_id"] if isinstance(session, dict) else session
                skill_calls = self._get_skill_calls_in_session(conn, sid)
                for sc in skill_calls:
                    task_input = self._get_context_user_message(
                        conn, sid, sc["assistant_msg_id"]
                    )
                    error_type, error_msg = self._detect_error(
                        sc["response_content"],
                        sc.get("assistant_content", ""),
                    )
                    usages.append(
                        SkillUsage(
                            session_id=sid,
                            timestamp=sc["timestamp"],
                            skill_name=sc["skill_name"],
                            task_input=task_input[:500],
                            response=sc["response_content"][:500] if sc["response_content"] else "",
                            error_type=error_type,
                            error_message=error_msg,
                            message_id=sc["assistant_msg_id"],
                        )
                    )
        return usages

    def run(self, limit: int = 20) -> dict:
        """Complete analysis: recent sessions, skill usages, failure summary.

        Returns dict with keys:
          - sessions: list of session dicts
          - skill_usages: list of SkillUsage.to_dict()
          - failures: list of SkillUsage.to_dict() where error_type is non-empty
          - skill_counts: dict of skill_name -> invocation count
          - failure_counts: dict of skill_name -> failure count
          - total_sessions: int
          - total_skill_invocations: int
          - total_failures: int
        """
        sessions = self.find_recent_sessions(limit=limit)
        usages = self.get_skill_usage_stats(sessions)
        failures = [u for u in usages if u.error_type]

        skill_counts = Counter(u.skill_name for u in usages)
        failure_counts = Counter(u.skill_name for u in failures)

        return {
            "sessions": sessions,
            "skill_usages": [u.to_dict() for u in usages],
            "failures": [u.to_dict() for u in failures],
            "skill_counts": dict(skill_counts),
            "failure_counts": dict(failure_counts),
            "total_sessions": len(sessions),
            "total_skill_invocations": len(usages),
            "total_failures": len(failures),
        }
