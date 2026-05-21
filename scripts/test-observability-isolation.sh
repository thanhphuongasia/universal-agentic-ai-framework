#!/usr/bin/env bash
# Verify ryuu-observability is independently installable without pulling in the full ryuu package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$(mktemp -d)/venv-observability-isolation"

echo "=== observability-isolation: creating fresh venv at $VENV_DIR ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== observability-isolation: installing ryuu-observability (editable) ==="
pip install -e "$REPO_ROOT/packages/ryuu-core" -q
pip install -e "$REPO_ROOT/packages/ryuu-observability" -q

echo "=== observability-isolation: verifying ryuu is NOT installed ==="
python3 -c "
import sys
try:
    import ryuu
    print('FAIL: ryuu imported — it should not be present', file=sys.stderr)
    sys.exit(1)
except ModuleNotFoundError:
    print('OK: import ryuu → ModuleNotFoundError (expected)')
"

echo "=== observability-isolation: smoke test ryuu_observability ==="
python3 -c "
from ryuu_observability.cost import CostPolicy, CostTracker, InMemoryCostStore
from ryuu_observability.audit import AuditConfig, AuditLogger, verify_chain
from ryuu_observability.tracer import setup_tracing, get_current_correlation_id
from ryuu_observability.rate_limit import RatePolicy, RateLimiter, InMemoryRateStore

store = InMemoryCostStore()
policy = CostPolicy(per_user_per_day_usd=5.0)
tracker = CostTracker(store=store, policy=policy)
assert tracker is not None

config = AuditConfig(backend='console')
logger = AuditLogger(config=config)
assert logger is not None

cid = get_current_correlation_id()
assert cid is None or isinstance(cid, str)

rate_store = InMemoryRateStore()
rate_policy = RatePolicy(rps=10.0)
limiter = RateLimiter(store=rate_store, policy=rate_policy)
assert limiter is not None

print('OK: ryuu_observability smoke test passed')
"

deactivate
rm -rf "$VENV_DIR"
echo "=== observability-isolation: PASSED ==="
