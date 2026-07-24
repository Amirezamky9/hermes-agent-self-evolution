import sqlite3, json

conn = sqlite3.connect('/home/hermeswebui/.hermes/state.db')

# Check message count and recent sessions
print("=== SESSIONS COUNT ===")
r = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
print(f"Total sessions: {r[0]}")

print("\n=== RECENT SESSIONS ===")
rows = conn.execute("""
    SELECT id, title, started_at, message_count, tool_call_count 
    FROM sessions ORDER BY started_at DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  session={r[0][:20]}... title={r[1]} msgs={r[3]} tools={r[4]}")

print("\n=== SAMPLE TOOL_CALLS MESSAGES (last 5) ===")
rows = conn.execute("""
    SELECT m.session_id, m.role, m.tool_calls, m.tool_name, m.content, m.timestamp
    FROM messages m
    WHERE m.tool_calls IS NOT NULL
    ORDER BY m.timestamp DESC LIMIT 5
""").fetchall()
for r in rows:
    tc = r[2][:200] if r[2] else None
    print(f"  session={r[0][:20]}... role={r[1]} tool_calls={tc} tool_name={r[3]} content_snippet={str(r[4])[:100]}")

print("\n=== SAMPLE skill_view/skill_manage MESSAGES ===")
rows = conn.execute("""
    SELECT m.session_id, m.role, m.tool_calls, m.content, m.timestamp
    FROM messages m
    WHERE (m.tool_calls LIKE '%skill_view%' OR m.tool_calls LIKE '%skill_manage%')
    ORDER BY m.timestamp DESC LIMIT 3
""").fetchall()
for r in rows:
    tc = r[2][:300] if r[2] else None
    print(f"  session={r[0][:20]}... role={r[1]}")
    print(f"    tool_calls={tc}")
    print(f"    content={str(r[3])[:150]}")
    print()

print("\n=== ERROR PATTERNS IN CONTENT ===")
rows = conn.execute("""
    SELECT m.session_id, m.role, substr(m.content, 1, 200), m.timestamp
    FROM messages m
    WHERE m.content LIKE '%error%' OR m.content LIKE '%Error%' OR m.content LIKE '%failed%' OR m.content LIKE '%traceback%'
    ORDER BY m.timestamp DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  session={r[0][:20]}... role={r[1]} content={r[2][:200]}")
    print()

conn.close()
