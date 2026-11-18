#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for MoonKVSim.
# Installs the uv package manager (if missing) and syncs the locked
# dependency set, including the dev and trace extras used by CI.
set -euo pipefail

# uv installs to ~/.local/bin, which is already on the login PATH.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="${HOME}/.local/bin:${PATH}"

# Pin CPython 3.11 to match the CI toolchain (pyproject targets py311).
# uv downloads and caches the interpreter on first run and reuses it after.
uv sync --python 3.11 --extra dev --extra trace
