#!/usr/bin/env bash
# Run skill optimization
# Usage: bash scripts/run_optimize.sh <skill-name> [--iterations N]
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -e ".[dev]" -q
python -m evolution.cli "$@"
