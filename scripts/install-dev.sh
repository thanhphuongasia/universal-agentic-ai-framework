#!/usr/bin/env bash
# Install both packages in editable mode for local development.
# Run from repo root: bash scripts/install-dev.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing uaaf-workflow (editable)..."
pip install -e "$REPO_ROOT/packages/uaaf-workflow"

echo "Installing uaaf (editable, with dev extras)..."
pip install -e "$REPO_ROOT[dev]"

echo ""
echo "Verifying..."
python -c "import uaaf, uaaf_workflow; print('uaaf', uaaf.__version__, '+ uaaf_workflow', uaaf_workflow.__version__, '— OK')"
