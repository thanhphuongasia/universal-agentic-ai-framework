#!/usr/bin/env bash
# Verify ryuu-providers is independently installable without pulling in the full ryuu package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$(mktemp -d)/venv-providers-isolation"

echo "=== providers-isolation: creating fresh venv at $VENV_DIR ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== providers-isolation: installing ryuu-providers (editable) ==="
pip install -e "$REPO_ROOT/packages/ryuu-core" -q
pip install -e "$REPO_ROOT/packages/infrastructure/providers/ryuu-providers" -q

echo "=== providers-isolation: verifying ryuu is NOT installed ==="
python3 -c "
import sys
try:
    import ryuu
    print('FAIL: ryuu imported — it should not be present', file=sys.stderr)
    sys.exit(1)
except ModuleNotFoundError:
    print('OK: import ryuu → ModuleNotFoundError (expected)')
"

echo "=== providers-isolation: smoke test ryuu_providers ==="
python3 -c "
from ryuu_providers.llm import ILLMProvider, CompletionRequest, Message, Response, TokenUsage
from ryuu_providers.circuit_breaker import CircuitBreaker, CircuitState
from ryuu_providers.fallback import ProviderFallbackChain
from ryuu_providers.router import ModelRouter
from ryuu_providers._pricing import calculate_usd, PRICING

cb = CircuitBreaker(failure_threshold=3)
assert cb.state == CircuitState.CLOSED

chain = ProviderFallbackChain(providers=[])
assert chain.provider_id == 'fallback_chain'

assert 'gpt-4o' in PRICING
usd = calculate_usd('gpt-4o', 1_000_000, 1_000_000)
assert usd > 0, f'Expected non-zero USD, got {usd}'

print('OK: ryuu_providers smoke test passed')
"

deactivate
rm -rf "$VENV_DIR"
echo "=== providers-isolation: PASSED ==="
