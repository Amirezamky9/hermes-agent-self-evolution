# 🧬 Hermes Agent Self-Evolution

**Evolutionary self-improvement for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

Uses DSPy + GEPA (Genetic-Pareto Prompt Evolution) to automatically evolve and optimize Hermes Agent's skills, tool descriptions, system prompts, and code — producing measurably better versions through reflective evolutionary search.

**No GPU training required.** Everything operates via API calls — mutating text, evaluating results, and selecting the best variants. ~$2-10 per optimization run.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Supervisor Workflow                                │
│                                                     │
│  1. Load skill → record baseline (v1)               │
│  2. Build eval dataset (synthetic / golden / mined)  │
│  3. Run GEPA optimizer (N iterations)                │
│  4. Validate constraints (size, structure, growth)   │
│  5. Benchmark: baseline vs evolved (holdout set)     │
│  6. Deploy if improved / rollback if regressed       │
│                                                     │
│  Version Store (SQLite) ← tracks every version      │
│  Rollback Manager ← safe reversion to any version   │
└─────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Install
git clone https://github.com/NousResearch/hermes-agent-self-evolution.git
cd hermes-agent-self-evolution
pip install -e ".[dev]"

# Point at your hermes-agent repo
export HERMES_AGENT_REPO=~/.hermes/hermes-agent
```

## Usage

### Evolve a skill (basic)

```bash
python -m evolution.skills.evolve_skill \
    --skill github-code-review \
    --iterations 10 \
    --eval-source synthetic
```

### Full supervisor pipeline (versioning + benchmark + rollback)

```bash
# Run the supervisor — handles everything automatically
hse supervisor github-code-review \
    --skill-file ~/.hermes/skills/github-code-review/SKILL.md \
    --iterations 10 \
    --auto-rollback
```

### Version management

```bash
# List all versions of a skill
hse versions github-code-review

# Rollback to a specific version
hse rollback github-code-review --to 2

# Run benchmark on a skill
hse benchmark github-code-review \
    --skill-file ./my_skill.md \
    --dataset ./eval_tasks.jsonl
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `hse evolve` | Evolve a skill using DSPy + GEPA |
| `hse supervisor` | Full pipeline: optimize + benchmark + version + rollback |
| `hse versions <skill>` | List all versions |
| `hse rollback <skill> --to N` | Rollback to version N |
| `hse benchmark <skill>` | Run benchmark against test tasks |

## What Can Be Improved

| Tier | Target | Risk | Status |
|------|--------|------|--------|
| 1 | **Skill files** (SKILL.md) | Low | ✅ MVP |
| 2 | **Tool descriptions** | Low | 🔜 |
| 3 | **System prompt sections** | Medium | 🔜 |
| 4 | **Code evolution** | High | 🔜 |

## Components

### Version Store (`evolution/core/version_store.py`)
SQLite-backed version tracking. Every optimization run records:
- Skill text snapshot
- Parent version (lineage)
- Source (baseline / evolved / rollback)
- Metrics (score, improvement, iterations)
- Constraint validation status

### Rollback Manager (`evolution/core/rollback.py`)
Safe rollback to any previous version with:
- Constraint validation on target (won't rollback to broken version)
- Creates a new "rollback" version (non-destructive)
- Diff between any two versions

### Benchmark Evaluator (`evolution/core/benchmark.py`)
Evaluates skill quality against test tasks:
- LLM-as-judge scoring (correctness, procedure following, conciseness)
- Constraint compliance check
- Baseline vs evolved comparison with verdict (improved / no_change / regressed)

### Supervisor (`evolution/core/supervisor.py`)
Full pipeline orchestrator:
1. Record baseline version
2. Build eval dataset
3. Run optimization
4. Validate constraints
5. Benchmark comparison
6. Deploy if improved / rollback if regressed

### DSPy Integration
- `SkillModule` — wraps SKILL.md as a DSPy module for optimization
- `SyntheticDatasetBuilder` — generates eval tasks using LLM
- `GoldenDatasetLoader` — loads hand-curated test sets
- `LLMJudge` — multi-dimensional scoring with rubrics

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run specific test
pytest tests/core/test_versioning.py -v
```

## License

MIT — see [LICENSE](LICENSE)
