#!/usr/bin/env bash
# Prove ryuu-workflow is a truly standalone library with no ryuu dependency.
# Run from repo root: bash scripts/test-workflow-isolation.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$(mktemp -d)/ryuu_wf_isolation_venv"

echo "=== ryuu-workflow isolation test ==="
echo "Creating fresh venv at $VENV_DIR ..."
python3 -m venv "$VENV_DIR"

echo "Installing ryuu-workflow wheel only (no ryuu) ..."
"$VENV_DIR/bin/pip" install -q "$REPO_ROOT/packages/ryuu-workflow"

echo "Testing imports ..."
"$VENV_DIR/bin/python" - << 'PYEOF'
from ryuu_workflow import (
    WorkflowEngine, IWorkflowEngine,
    WorkflowResult, WorkflowStatus,
    IState, Workflow, StateMachine, StateTransition,
    Checkpoint, ICheckpointStore,
    FileCheckpointStore, InMemoryCheckpointStore,
    ExecutionContext, ContextScope,
    RetryableError, DegradedError, FatalError,
)
print("  All public symbols importable — OK")

# Prove ryuu AI framework is NOT bundled
try:
    import ryuu
    raise SystemExit("FAIL: ryuu should not be importable in isolation venv")
except ModuleNotFoundError:
    print("  ryuu not bundled — OK")
PYEOF

echo "Cleaning up venv ..."
rm -rf "$VENV_DIR"

echo ""
echo "=== ISOLATION TEST PASSED ==="
