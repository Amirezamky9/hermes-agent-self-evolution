"""Extended test of SessionGrazer with all sessions."""
import sys
sys.path.insert(0, "/workspace/hermes-agent-self-evolution")

from evolution.core.session_grazer import SessionGrazer

grazer = SessionGrazer()

# Test individual methods
print("=== find_recent_sessions ===")
sessions = grazer.find_recent_sessions(limit=5)
print(f"Got {len(sessions)} sessions")
for s in sessions[:2]:
    print(f"  {s['session_id'][:30]} title={s['title']} msgs={s['message_count']}")

print("\n=== get_skill_usage_stats (all sessions) ===")
usages = grazer.get_skill_usage_stats()  # defaults to limit=100
print(f"Total skill usages: {len(usages)}")
from collections import Counter
skill_counts = Counter(u.skill_name for u in usages)
for name, count in skill_counts.most_common(10):
    print(f"  {name}: {count}")

print("\n=== extract_failures ===")
failures = grazer.extract_failures()
print(f"Failures: {len(failures)}")
for f in failures[:5]:
    print(f"  [{f.error_type}] {f.skill_name}")
    print(f"    error: {f.error_message[:200]}")

print("\n=== run (limit=30) ===")
result = grazer.run(limit=30)
print(f"Sessions: {result['total_sessions']}")
print(f"Invocations: {result['total_skill_invocations']}")
print(f"Failures: {result['total_failures']}")
if result["failure_counts"]:
    print("Failure counts:", result["failure_counts"])
