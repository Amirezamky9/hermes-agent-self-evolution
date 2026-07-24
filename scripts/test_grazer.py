"""Quick smoke test of SessionGrazer against the real DB."""
import sys
sys.path.insert(0, "/workspace/hermes-agent-self-evolution")

from evolution.core.session_grazer import SessionGrazer

grazer = SessionGrazer()
result = grazer.run(limit=10)

print(f"Sessions scanned: {result['total_sessions']}")
print(f"Skill invocations: {result['total_skill_invocations']}")
print(f"Failures detected: {result['total_failures']}")

print("\nSkill counts:")
for name, count in sorted(result["skill_counts"].items(), key=lambda x: -x[1]):
    print(f"  {name}: {count}")

if result["failure_counts"]:
    print("\nFailure counts:")
    for name, count in sorted(result["failure_counts"].items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}")

print("\nSample usages:")
for u in result["skill_usages"][:5]:
    print(f"  [{u['error_type'] or 'OK'}] {u['skill_name']} @ {u['datetime']}")
    print(f"    task: {u['task_input'][:100]}...")
    if u['error_message']:
        print(f"    error: {u['error_message'][:150]}")

print("\nSample failures:")
for f in result["failures"][:5]:
    print(f"  [{f['error_type']}] {f['skill_name']}")
    print(f"    error: {f['error_message'][:200]}")
