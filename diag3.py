#!/usr/bin/env python3
from evolution.core.safety_net import SafetyNet

text = "---\nname: x\ndescription: y\n---\nplain text no formatting"
sn = SafetyNet()
result = sn.validate_patch("", text, "test")

for w in result.warnings:
    print(f"warning: {repr(w)}")
    print(f"  'lack' in w: {'lack' in w}")
    print(f"  'structure' in w: {'structure' in w}")
    print(f"  'lack of structure' in w: {'lack of structure' in w}")
    print(f"  'may lack' in w: {'may lack' in w}")
    print(f"  'found' in w: {'found' in w}")

# Also check the raw bytes around the em dash
for i, ch in enumerate(w):
    if ord(ch) > 127:
        print(f"  char at {i}: U+{ord(ch):04X} {repr(ch)}")
