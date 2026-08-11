#!/bin/bash
# Prepare the Python environment for the freigang mail CLI (and its pytest suite).
#
# Creates/updates a project-local venv at .venv using uv, and installs the
# mail_cli package plus dev dependencies (pytest). Safe to re-run.
#
# Usage:
#   ./init_env.sh
#   source .venv/bin/activate   # to use the venv interactively
#   uv run pytest               # or run tests without activating

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but not found on PATH. Install it: https://docs.astral.sh/uv/" >&2
    exit 1
fi

uv sync --group dev

echo "Environment ready. Activate with: source .venv/bin/activate"
echo "Run tests with: uv run pytest"
