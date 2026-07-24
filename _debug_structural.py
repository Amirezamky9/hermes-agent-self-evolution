#!/usr/bin/env python3
from evolution.core.safety_net import SafetyNet
from evolution.core.structural_enforcer import StructuralEnforcer

sn = SafetyNet()
se = StructuralEnforcer()

skill = "---\nname: test\ndescription: test skill\ntriggers:\n  - skill load\nversion: 0.1.0\n\n## Overview\n\nThis is a test.\n\n## When to Use\n\n- Use when testing\n\n## Error Handling\n\n```bash\nsome_command 2>/dev/null || true\n```\n\n## Verification\n\nVerify this works.\n\n## Pitfalls\n\n- Don't forget things\n"

# Debug the scores
report = se.analyze(skill)
print(f"Score: {report.completeness_score}")
print(f"Missing: {report.missing_patterns}")
print(f"Bash count: {report.bash_block_count}")
print(f"Has env_vars: {report.has_env_vars}")
print(f"Has conditionals: {report.has_conditionals}")
print(f"Has triggers: {report.has_triggers}")
print(f"Has when: {report.has_when_to_invoke}")
print(f"Has preamble: {report.has_preamble}")
print(f"Has error: {report.has_error_handling}")
print(f"Has bash: {report.has_bash_blocks}")
print(f"Has verification: {report.has_verification}")
print(f"Has pitfalls: {report.has_pitfalls}")
print(f"Has version: {report.has_version}")
