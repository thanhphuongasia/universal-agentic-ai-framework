#!/usr/bin/env bash
# Verify ryuu-runtime is independently installable without pulling in the full ryuu package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$(mktemp -d)/venv-runtime-isolation"

echo "=== runtime-isolation: creating fresh venv at $VENV_DIR ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== runtime-isolation: installing ryuu-runtime (editable) ==="
pip install -e "$REPO_ROOT/packages/ryuu-core" -q
pip install -e "$REPO_ROOT/packages/infrastructure/providers/ryuu-providers" -q
pip install -e "$REPO_ROOT/packages/ryuu-cognitive" -q
pip install -e "$REPO_ROOT/packages/ryuu-execution" -q
pip install -e "$REPO_ROOT/packages/ryuu-runtime" -q

echo "=== runtime-isolation: verifying ryuu is NOT installed ==="
python3 -c "
import sys
try:
    import ryuu
    print('FAIL: ryuu imported — it should not be present', file=sys.stderr)
    sys.exit(1)
except ModuleNotFoundError:
    print('OK: import ryuu → ModuleNotFoundError (expected)')
"

echo "=== runtime-isolation: smoke test ryuu_runtime ==="
python3 -c "
from ryuu_runtime.analyzer import IIntentAnalyzer
from ryuu_runtime.llm_analyzer import LLMIntentAnalyzer, INTENT_SYSTEM_PROMPT
from ryuu_runtime.selector import StrategySelector
from ryuu_runtime.request_handler import RequestHandler
from ryuu_cognitive.strategies import DirectStrategy
from ryuu_core.models import DIRECT, ComplexityLevel, ModelTier, StructuredIntent

assert INTENT_SYSTEM_PROMPT  # non-empty

selector = StrategySelector([DirectStrategy()])
assert selector is not None

intent = StructuredIntent(
    intent_type='query', action='search', entities={},
    complexity=ComplexityLevel.LOW, confidence=0.9,
    ambiguous=False, clarification_questions=[],
    suggested_strategy=DIRECT, suggested_model_tier=ModelTier.STANDARD,
)
from ryuu_core.context import ContextScope, ExecutionContext
ctx = ExecutionContext(
    scope=ContextScope(user_id='u', session_id='s', domain='d'),
    correlation_id='cid',
)
strategy = selector.select(intent, ctx)
assert strategy.strategy_id == DIRECT

print('OK: ryuu_runtime smoke test passed')
"

deactivate
rm -rf "$VENV_DIR"
echo "=== runtime-isolation: PASSED ==="
