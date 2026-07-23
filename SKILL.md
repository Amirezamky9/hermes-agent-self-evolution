---
name: hermes-self-evolution
description: "Evolutionary self-improvement for Hermes Agent skills — optimize, benchmark, version, and rollback using DSPy + GEPA."
version: 0.1.0
author: Nous Research
license: MIT
tags: [hermes, optimization, evolution, dspy, gepa, skills]
---

# Hermes Agent Self-Evolution

## When to Use

Optimize a Hermes Agent skill's quality by running it through an evolutionary loop:

1. **Baseline** — Record current skill as version 1
2. **Optimize** — Run GEPA (Genetic-Pareto Prompt Evolution) to mutate the skill text
3. **Benchmark** — Compare baseline vs evolved on holdout test set
4. **Deploy** — If improved, save as new version
5. **Rollback** — If regressed, auto-revert to last good version

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Evolve a skill
python -m evolution.skills.evolve_skill \
    --skill github-code-review \
    --iterations 10

# Run full supervisor pipeline
python -m evolution.cli supervisor \
    github-code-review \
    --skill-file ~/.hermes/skills/github-code-review/SKILL.md

# List versions
python -m evolution.cli versions github-code-review

# Rollback
python -m evolution.cli rollback github-code-review --to 1

# Benchmark
python -m evolution.cli benchmark github-code-review \
    --skill-file ./my_skill.md \
    --dataset ./eval_tasks.jsonl
```

## Components

| Module | Purpose |
|--------|---------|
| `evolution/core/version_store.py` | SQLite version tracking |
| `evolution/core/rollback.py` | Safe rollback to any previous version |
| `evolution/core/benchmark.py` | LLM-as-judge quality evaluation |
| `evolution/core/supervisor.py` | Full optimization pipeline orchestrator |
| `evolution/skills/evolve_skill.py` | GEPA skill evolution entry point |
| `evolution/skills/skill_module.py` | SKILL.md → DSPy module wrapper |
| `evolution/core/config.py` | Configuration and hermes-agent repo discovery |
| `evolution/core/constraints.py` | Hard constraint validators |
| `evolution/core/fitness.py` | LLM-as-judge fitness scoring |
| `evolution/core/dataset_builder.py` | Synthetic/golden eval dataset generation |

## Configuration

Point at your hermes-agent repo:

```bash
export HERMES_AGENT_REPO=~/.hermes/hermes-agent
```

Or the tool auto-discovers from:
1. `HERMES_AGENT_REPO` env var
2. `~/.hermes/hermes-agent` (standard install)
3. `../hermes-agent` (sibling directory)

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
