#!/usr/bin/env bash
# Run test suite
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -e ".[dev]" -q
pytest tests/ -v --tb=short "$@"
