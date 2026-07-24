import sqlite3, json

conn = sqlite3.connect('/home/hermeswebui/.hermes/state.db')

# Find skill_view/skill_manage tool calls
print("=== SKILL TOOL CALLS ===")
rows = conn.execute("""
    SELECT m.session_id, m.role, m.tool_calls, m.content, m.timestamp, m.tool_call_id
    FROM messages m
    WHERE m.tool_calls LIKE '%skill_view%' OR m.tool_calls LIKE '%skill_manage%'
    ORDER BY m.timestamp DESC LIMIT 10
""").fetchall()
for r in rows:
    print(f"\nsession={r[0][:30]} role={r[1]}")
    if r[2]:
        try:
            tc = json.loads(r[2])
            for call in tc:
                fname = call.get('function', {}).get('name', 'unknown')
                args = call.get('function', {}).get('arguments', '')[:200]
                print(f"  tool={fname} args={args}")
        except:
            print(f"  raw={r[2][:300]}")
    if r[3]:
        print(f"  content={str(r[3])[:200]}")

# Check tool response format
print("\n\n=== TOOL RESPONSES (next msg after skill call) ===")
rows = conn.execute("""
    SELECT m.session_id, m.role, m.content, m.tool_call_id, m.timestamp
    FROM messages m
    WHERE m.tool_call_id IS NOT NULL AND m.role = 'tool'
    ORDER BY m.timestamp DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"\nsession={r[0][:30]} role={r[1]} tool_call_id={r[3]}")
    print(f"  content={str(r[2])[:300]}")

# Check for patterns of skill failures
print("\n\n=== SKILL FAILURE PATTERNS ===")
rows = conn.execute("""
    SELECT m.session_id, substr(m.content, 1, 300), m.timestamp
    FROM messages m
    WHERE m.role = 'assistant'
    AND (
        m.content LIKE '%skill%failed%'
        OR m.content LIKE '%skill%error%'
        OR m.content LIKE '%skill%not found%'
        OR m.content LIKE '%skill%missing%'
        OR m.content LIKE '%SKILL.md%not found%'
    )
    ORDER BY m.timestamp DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  session={r[0][:30]} content={r[1][:300]}")

# Check how many sessions have skill mentions
print("\n\n=== SKILL USAGE STATS ===")
rows = conn.execute("""
    SELECT COUNT(DISTINCT m.session_id)
    FROM messages m
    WHERE m.tool_calls LIKE '%skill_view%' OR m.tool_calls LIKE '%skill_manage%'
""").fetchall()
print(f"Sessions with skill tool calls: {rows[0][0]}")

conn.close()
