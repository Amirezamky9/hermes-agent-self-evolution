#!/usr/bin/env python3
from evolution.core.safety_net import SafetyNet

text = "---\nname: x\ndescription: y\n---\nplain text no formatting"
sn = SafetyNet()
result = sn.validate_patch("", text, "test")
print(f"passed={result.passed}")
print(f"issues={result.issues}")
print(f"warnings={result.warnings}")
print(f"checks_run={result.checks_run}")
print(f"has 'lack of structure' in any warning: {'lack of structure' in str(result.warnings)}")
