#!/usr/bin/env python3
import re

text = "---\nname: x\ndescription: y\n---\nplain text no formatting"

has_headings = bool(re.search(r"^#{1,6}\s+", text, re.MULTILINE))
has_bullets = bool(re.search(r"^[\-\*]\s+", text, re.MULTILINE))

print(f"has_headings={has_headings}, has_bullets={has_bullets}")

# Check each line for bullet match
for i, line in enumerate(text.split("\n")):
    m_h = re.search(r"^#{1,6}\s+", line)
    m_b = re.search(r"^[\-\*]\s+", line)
    if m_h or m_b:
        print(f"  line {i}: {repr(line)} heading={bool(m_h)} bullet={bool(m_b)}")

if not has_headings and not has_bullets:
    print("WOULD ADD WARNING")
else:
    print("NO WARNING ADDED")
