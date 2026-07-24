#!/usr/bin/env python3
from evolution.core.safety_net import SafetyNet
print("import ok")

# Quick smoke test
sn = SafetyNet()
skill = "---\nname: test\ndescription: test skill\ntriggers:\n  - skill load\nversion: 0.1.0\n\n## Overview\n\nThis is a test.\n\n## When to Use\n\n- Use when testing\n\n## Error Handling\n\n```bash\nsome_command 2>/dev/null || true\n```\n\n## Verification\n\nVerify this works.\n\n## Pitfalls\n\n- Don't forget things\n"
result = sn.validate_patch("", skill, "test")
print(f"checks_run: {result.checks_run}")
print(f"passed: {result.passed}")
print(f"issues: {result.issues}")
print(f"warnings: {result.warnings}")
assert "structural_completeness" in result.checks_run, "missing structural_completeness check"
print("structural_completeness check is present")
