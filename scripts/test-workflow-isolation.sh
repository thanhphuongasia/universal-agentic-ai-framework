#!/usr/bin/env bash
# Prove uaaf-workflow is a truly standalone library with no uaaf dependency.
# Run from repo root: bash scripts/test-workflow-isolation.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$(mktemp -d)/uaaf_wf_isolation_venv"

echo "=== uaaf-workflow isolation test ==="
echo "Creating fresh venv at $VENV_DIR ..."
python3 -m venv "$VENV_DIR"

echo "Installing uaaf-workflow wheel only (no uaaf) ..."
"$VENV_DIR/bin/pip" install -q "$REPO_ROOT/packages/uaaf-workflow"

echo "Testing imports ..."
"$VENV_DIR/bin/python" - << 'PYEOF'
from uaaf_workflow import (
    WorkflowEngine, IWorkflowEngine,
    WorkflowResult, WorkflowStatus,
    IState, Workflow, StateMachine, StateTransition,
    Checkpoint, ICheckpointStore,
    FileCheckpointStore, InMemoryCheckpointStore,
    ExecutionContext, ContextScope,
    RetryableError, DegradedError, FatalError,
)
print("  All public symbols importable — OK")

# Prove uaaf AI framework is NOT bundled
try:
    import uaaf
    raise SystemExit("FAIL: uaaf should not be importable in isolation venv")
except ModuleNotFoundError:
    print("  uaaf not bundled — OK")
PYEOF

echo "Cleaning up venv ..."
rm -rf "$VENV_DIR"

echo ""
echo "=== ISOLATION TEST PASSED ==="
