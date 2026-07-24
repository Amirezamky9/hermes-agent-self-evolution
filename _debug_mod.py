#!/usr/bin/env python3
"""Debug scores for test fixtures."""
from evolution.core.structural_enforcer import StructuralEnforcer

se = StructuralEnforcer()

moderate = """\
---
name: mod-skill
description: Moderate skill.
version: 0.1.0
---

## Overview

A moderate skill.

## When to Use

- Use when needed.

## Steps

```bash
echo "hello"
```

## Verification

Verify the output.
"""
r = se.analyze(moderate)
print(f"Moderate score: {r.completeness_score}, missing: {r.missing_patterns}")
