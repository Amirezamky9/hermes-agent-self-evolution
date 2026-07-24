import sqlite3, json

conn = sqlite3.connect('/home/hermeswebui/.hermes/state.db')

# Check tool call/response matching pattern
print("=== TOOL CALL ID MATCHING ===")
rows = conn.execute("""
    SELECT m.id, m.session_id, m.role, m.tool_calls, m.tool_call_id, m.content, m.timestamp
    FROM messages m
    WHERE m.session_id = '20260723_060210_fb6aab68'
    ORDER BY m.timestamp
    LIMIT 30
""").fetchall()
for r in rows:
    msg_id, sess, role, tc, tcid, content, ts = r
    print(f"  id={msg_id} role={role}", end="")
    if tc:
        try:
            calls = json.loads(tc)
            for c in calls:
                fname = c.get('function', {}).get('name', '?')
                call_id = c.get('id', c.get('call_id', '?'))
                args = c.get('function', {}).get('arguments', '')[:80]
                print(f"  tool_call: {fname}({args}...) id={call_id}", end="")
        except:
            pass
    if tcid:
        print(f"  response_to: {tcid}", end="")
    if content and len(str(content)) < 120:
        print(f"  content={str(content)[:120]}", end="")
    elif content:
        print(f"  content_len={len(str(content))}", end="")
    print()

# Check if tool_call_id matches the id field in the tool_calls array
print("\n\n=== VERIFY ID MATCHING ===")
rows = conn.execute("""
    SELECT m.id, m.role, m.tool_calls, m.tool_call_id
    FROM messages m
    WHERE m.session_id = '20260723_172911_d40f81'
    AND m.tool_calls IS NOT NULL
    ORDER BY m.timestamp
    LIMIT 5
""").fetchall()
for r in rows:
    msg_id, role, tc, tcid = r
    if tc:
        calls = json.loads(tc)
        for c in calls:
            print(f"  assistant_msg_id={msg_id} tool_call_id={c.get('id', '?')} call_id={c.get('call_id', '?')}")

rows = conn.execute("""
    SELECT m.id, m.role, m.tool_call_id
    FROM messages m
    WHERE m.session_id = '20260723_172911_d40f81'
    AND m.role = 'tool'
    ORDER BY m.timestamp
    LIMIT 10
""").fetchall()
for r in rows:
    print(f"  tool_msg_id={r[0]} tool_call_id={r[2]}")

conn.close()
