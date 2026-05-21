#!/usr/bin/env bash
# Prove ryuu-core is a truly standalone zero-dependency library.
# Run from repo root: bash scripts/test-core-isolation.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$(mktemp -d)/ryuu_core_isolation_venv"

echo "=== ryuu-core isolation test ==="
echo "Creating fresh venv at $VENV_DIR ..."
python3 -m venv "$VENV_DIR"

echo "Installing ryuu-core wheel only (no ryuu, no ryuu-workflow) ..."
"$VENV_DIR/bin/pip" install -q "$REPO_ROOT/packages/ryuu-core"

echo "Testing imports ..."
"$VENV_DIR/bin/python" - << 'PYEOF'
from ryuu_core.errors import (
    FrameworkError, RetryableError, DegradedError, FatalError,
    BudgetExceededError, RateLimitTimeout, RetryDecision,
    retry_policy, classify_external_error,
)
from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import (
    Cost, Task, AgentResult,
    StrategyId, DIRECT, REACT, EVALUATOR_OPTIMIZER, PARALLEL_FANOUT,
    ComplexityLevel, ModelTier, StructuredIntent, CognitiveResult, CostEstimate,
)
from ryuu_core.protocols import ICostTracker, ITracer, IAuditLogger, IRateLimiter
from ryuu_core.nulls import NullCostTracker, NullTracer, NullAuditLogger, NullRateLimiter
print("  All public symbols importable — OK")

# Prove ryuu AI framework and ryuu-workflow are NOT bundled
for mod in ("ryuu", "ryuu_workflow"):
    try:
        __import__(mod)
        raise SystemExit(f"FAIL: {mod} should not be importable in isolation venv")
    except ModuleNotFoundError:
        print(f"  {mod} not bundled — OK")

# Prove zero runtime deps (dev extras are optional, not runtime)
import importlib.metadata
dist = importlib.metadata.distribution("ryuu-core")
all_requires = dist.metadata.get_all("Requires-Dist") or []
runtime_requires = [r for r in all_requires if "extra ==" not in r]
assert not runtime_requires, f"FAIL: ryuu-core has runtime deps: {runtime_requires}"
print("  zero runtime dependencies confirmed — OK")
PYEOF

echo "Cleaning up venv ..."
rm -rf "$VENV_DIR"

echo ""
echo "=== CORE ISOLATION TEST PASSED ==="
