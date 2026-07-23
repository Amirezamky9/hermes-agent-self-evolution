#!/usr/bin/env bash
# Run benchmark on a skill
# Usage: bash scripts/run_benchmark.sh <skill-name> --skill-file <path> --dataset <path>
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -e ".[dev]" -q
python -m evolution.cli benchmark "$@"
