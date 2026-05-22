#!/usr/bin/env bash
# Verify ryuu-eval is independently installable without the full ryuu package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$(mktemp -d)/venv-eval-isolation"

echo "=== eval-isolation: creating fresh venv at $VENV_DIR ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== eval-isolation: installing ryuu-eval (editable) ==="
pip install -e "$REPO_ROOT/packages/ryuu-core" -q
pip install -e "$REPO_ROOT/packages/infrastructure/providers/ryuu-providers" -q
pip install -e "$REPO_ROOT/packages/ryuu-eval" -q

echo "=== eval-isolation: verifying ryuu is NOT installed ==="
python3 -c "
import sys
try:
    import ryuu
    print('FAIL: ryuu imported — it should not be present', file=sys.stderr)
    sys.exit(1)
except ModuleNotFoundError:
    print('OK: import ryuu → ModuleNotFoundError (expected)')
"

echo "=== eval-isolation: smoke test ryuu_eval ==="
python3 -c "
import asyncio
from ryuu_eval.models import CaseResult, EvalCase, ScoreResult, SuiteResult
from ryuu_eval.protocols import EvalTarget, Scorer
from ryuu_eval.scorers import Composite, Constraint, ExactMatch, Threshold
from ryuu_eval.fixture_loader import FixtureLoader
from ryuu_eval.runner import EvalRunner
from ryuu_eval.renderers.terminal import TerminalRenderer
from ryuu_eval.renderers.github_actions import GitHubActionsRenderer
from ryuu_eval.renderers.api import ApiRenderer

class FakeTarget:
    async def run(self, case):
        return CaseResult(case=case, output=str(case.expected))

async def test():
    cases = FixtureLoader.load_json([
        {'case_id': 'c1', 'input': 'q1', 'expected': 'Paris'},
        {'case_id': 'c2', 'input': 'q2', 'expected': 'Berlin'},
    ])
    runner = EvalRunner('iso-suite', FakeTarget(), [ExactMatch()])
    result = await runner.run(cases)
    assert result.total_count == 2
    assert result.passed_count == 2
    assert result.pass_rate == 1.0

    text = TerminalRenderer().render(result)
    assert 'iso-suite' in text

    gh = GitHubActionsRenderer().render(result)
    assert '::notice::' in gh

    data = ApiRenderer().render(result)
    assert data['suite_id'] == 'iso-suite'

    print('OK: ryuu_eval smoke test passed')

asyncio.run(test())
"

deactivate
rm -rf "$VENV_DIR"
echo "=== eval-isolation: PASSED ==="
