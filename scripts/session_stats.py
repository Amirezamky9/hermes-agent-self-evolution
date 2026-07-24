#!/usr/bin/env python3
"""Session Stats — استخراج آمار روزانه سشن‌ها برای SessionGrazer.

Usage:
    python scripts/session_stats.py                  # آمار امروز
    python scripts/session_stats.py --date 2026-07-23 # آمار یک روز خاص
    python scripts/session_stats.py --days 7          # آمار ۷ روز اخیر
    python scripts/session_stats.py --output report.json  # خروجی JSON
"""

import sqlite3
import json
import sys
import argparse
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timedelta


def get_db_path():
    """Find the Hermes session database."""
    candidates = [
        Path.home() / ".hermes" / "state.db",
        Path("/home/hermeswebui/.hermes/state.db"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    raise FileNotFoundError("Session DB not found")


def analyze_day(db_path: str, date_str: str) -> dict:
    """Analyze all sessions for a specific day (YYYY-MM-DD)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get sessions from that day
    start_ts = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
    end_ts = start_ts + 86400

    sessions = conn.execute(
        "SELECT id, title, started_at FROM sessions WHERE started_at >= ? AND started_at < ?",
        (start_ts, end_ts)
    ).fetchall()

    if not sessions:
        conn.close()
        return {"date": date_str, "sessions": [], "summary": {"total_sessions": 0}}

    session_ids = [s["id"] for s in sessions]
    placeholders = ",".join(["?"] * len(session_ids))

    # Get all messages for these sessions
    messages = conn.execute(
        f"SELECT id, session_id, role, content, tool_calls, timestamp FROM messages WHERE session_id IN ({placeholders}) ORDER BY timestamp",
        session_ids
    ).fetchall()

    conn.close()

    # Analyze each session
    session_stats = []
    total_tool_calls = Counter()
    total_skill_usage = Counter()
    total_skill_errors = Counter()

    for sess in sessions:
        sid = sess["id"]
        sess_messages = [m for m in messages if m["session_id"] == sid]

        tool_calls = 0
        skill_usage = Counter()
        skill_errors = Counter()
        user_messages = 0
        assistant_messages = 0
        session_tools = Counter()

        for msg in sess_messages:
            role = msg["role"]
            content = msg["content"] or ""
            tool_calls_raw = msg["tool_calls"]

            if role == "user":
                user_messages += 1
            elif role == "assistant":
                assistant_messages += 1

            # Parse tool calls
            if tool_calls_raw:
                try:
                    tc = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
                    if isinstance(tc, list):
                        tool_calls += len(tc)
                        for call in tc:
                            func = call.get("function", {})
                            name = func.get("name", "")
                            if name in ("skill_view", "skill_manage"):
                                try:
                                    args = json.loads(func.get("arguments", "{}"))
                                    skill_name = args.get("name", args.get("skill", "unknown"))
                                    skill_usage[skill_name] += 1
                                except (json.JSONDecodeError, AttributeError):
                                    skill_usage["unknown"] += 1
                            elif name:
                                session_tools[name] += 1
                except (json.JSONDecodeError, TypeError):
                    pass

            # Check for errors in assistant content
            if role == "assistant" and content:
                error_patterns = ["error", "Error", "traceback", "Traceback", "failed", "FAILED"]
                has_error = any(p in content for p in error_patterns)
                if has_error and skill_usage:
                    for skill in skill_usage:
                        skill_errors[skill] += 1

        total_tool_calls.update(session_tools)
        total_skill_usage.update(skill_usage)
        total_skill_errors.update(skill_errors)

        session_stats.append({
            "session_id": sid,
            "title": sess["title"] or "untitled",
            "tool_calls": tool_calls,
            "skill_usage": dict(skill_usage),
            "skill_errors": dict(skill_errors),
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "total_messages": user_messages + assistant_messages,
        })

    # Summary
    summary = {
        "date": date_str,
        "total_sessions": len(sessions),
        "total_tool_calls": sum(session_stats[s]["tool_calls"] for s in range(len(session_stats))),
        "total_user_messages": sum(session_stats[s]["user_messages"] for s in range(len(session_stats))),
        "total_assistant_messages": sum(session_stats[s]["assistant_messages"] for s in range(len(session_stats))),
        "skills_used": dict(total_skill_usage),
        "skill_errors": dict(total_skill_errors),
        "top_tools": dict(total_tool_calls.most_common(20)),
    }

    # Rank sessions by value for optimization
    for stat in session_stats:
        # Value = skill usage count + error count (more data = more useful)
        stat["optimization_value"] = (
            sum(stat["skill_usage"].values()) * 2 +
            sum(stat["skill_errors"].values()) * 3 +
            stat["tool_calls"]
        )

    # Sort by optimization value (highest first)
    session_stats.sort(key=lambda x: x["optimization_value"], reverse=True)

    return {
        "date": date_str,
        "sessions": session_stats,
        "summary": summary,
    }


def analyze_date_range(db_path: str, days: int) -> list:
    """Analyze multiple days."""
    results = []
    today = datetime.now()
    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        result = analyze_day(db_path, date_str)
        if result["summary"]["total_sessions"] > 0:
            results.append(result)
    return results


def generate_report(results: list) -> str:
    """Generate a human-readable report."""
    if not results:
        return "آماری برای نمایش وجود ندارد."

    lines = ["📊 گزارش آمار سشن‌ها", "━━━━━━━━━━━━━━━━━━━━"]

    for result in results:
        date = result["date"]
        summary = result["summary"]
        lines.append(f"\n📅 {date}")
        lines.append(f"  سشن‌ها: {summary['total_sessions']}")
        lines.append(f"  تماس ابزار: {summary['total_tool_calls']}")
        lines.append(f"  پیام کاربر: {summary['total_user_messages']}")

        if summary["skills_used"]:
            lines.append("  مهارت‌ها:")
            for skill, count in sorted(summary["skills_used"].items(), key=lambda x: -x[1]):
                err = summary["skill_errors"].get(skill, 0)
                err_str = f" (❌{err})" if err else ""
                lines.append(f"    {skill}: {count}x{err_str}")

        if summary["top_tools"]:
            lines.append("  ابزارها:")
            for tool, count in list(summary["top_tools"].items())[:5]:
                lines.append(f"    {tool}: {count}x")

        # Show top sessions for optimization
        top_sessions = [s for s in result["sessions"] if s["optimization_value"] > 0][:3]
        if top_sessions:
            lines.append("  سشن‌های ارزشمند برای بهینه‌سازی:")
            for s in top_sessions:
                skills = ", ".join(s["skill_usage"].keys())
                lines.append(f"    [{s['optimization_value']}pts] {s['title'][:40]} ({skills})")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Session Stats Analyzer")
    parser.add_argument("--date", help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=1, help="Number of days to analyze")
    parser.add_argument("--output", help="Output JSON file path")
    args = parser.parse_args()

    db_path = get_db_path()

    if args.date:
        result = analyze_day(db_path, args.date)
        results = [result]
    else:
        results = analyze_date_range(db_path, args.days)

    # Print report
    print(generate_report(results))

    # Save JSON if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 ذخیره شد: {args.output}")


if __name__ == "__main__":
    main()
