#!/usr/bin/env bash
# Verify ryuu-cognitive is independently installable without pulling in the full ryuu package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$(mktemp -d)/venv-cognitive-isolation"

echo "=== cognitive-isolation: creating fresh venv at $VENV_DIR ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== cognitive-isolation: installing ryuu-cognitive (editable) ==="
pip install -e "$REPO_ROOT/packages/ryuu-core" -q
pip install -e "$REPO_ROOT/packages/ryuu-providers" -q
pip install -e "$REPO_ROOT/packages/ryuu-cognitive" -q

echo "=== cognitive-isolation: verifying ryuu is NOT installed ==="
python3 -c "
import sys
try:
    import ryuu
    print('FAIL: ryuu imported — it should not be present', file=sys.stderr)
    sys.exit(1)
except ModuleNotFoundError:
    print('OK: import ryuu → ModuleNotFoundError (expected)')
"

echo "=== cognitive-isolation: smoke test ryuu_cognitive ==="
python3 -c "
from ryuu_cognitive.verifier import IVerifier, VerificationResult
from ryuu_cognitive.strategy import IAgentPool, ICognitiveStrategy
from ryuu_cognitive.strategies import (
    DirectStrategy,
    ReActStrategy,
    EvaluatorOptimizerStrategy,
    ParallelFanoutStrategy,
    ISubtaskBuilder,
    EntitySubtaskBuilder,
)
from ryuu_cognitive.verifiers import (
    GroundTruthVerifier,
    SchemaVerifier,
    VerifierPipeline,
    PipelineMode,
)

r = VerificationResult(passed=True, confidence=0.95)
assert r.passed and r.confidence == 0.95

d = DirectStrategy()
assert d.strategy_id == 'direct'

r_strat = ReActStrategy(max_steps=3)
assert r_strat.max_steps == 3

gt = GroundTruthVerifier(reference='hello', mode='substring')
assert gt is not None

sv = SchemaVerifier(required_keys=['name'])
assert sv is not None

p = VerifierPipeline(verifiers=[], mode=PipelineMode.ALL_PASS)
assert p is not None

print('OK: ryuu_cognitive smoke test passed')
"

deactivate
rm -rf "$VENV_DIR"
echo "=== cognitive-isolation: PASSED ==="
