#!/usr/bin/env bash
# Install both packages in editable mode for local development.
# Run from repo root: bash scripts/install-dev.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing ryuu-workflow (editable)..."
pip install -e "$REPO_ROOT/packages/ryuu-workflow"

echo "Installing ryuu (editable, with dev extras)..."
pip install -e "$REPO_ROOT[dev]"

echo ""
echo "Verifying..."
python -c "import ryuu, ryuu_workflow; print('ryuu', ryuu.__version__, '+ ryuu_workflow', ryuu_workflow.__version__, '— OK')"
