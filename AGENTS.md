# Project Context for Hermes Agent

## What This Project Is

Hermes Agent Self-Evolution — optimize Hermes Agent skills using DSPy + GEPA evolutionary search.

## Build & Test

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Key Commands

```bash
python -m evolution.cli evolve --skill <name>
python -m evolution.cli supervisor <name> --skill-file <path>
python -m evolution.cli versions <name>
python -m evolution.cli rollback <name> --to <version>
python -m evolution.cli benchmark <name> --skill-file <path> --dataset <path>
```

## Rules

- Never modify files outside `evolution/` and `tests/` without asking
- All new code must have tests
- Version store is SQLite, never modify the schema directly
- Rollback always creates a new version (non-destructive)
- Benchmark results use LLM-as-judge, not exact string matching
