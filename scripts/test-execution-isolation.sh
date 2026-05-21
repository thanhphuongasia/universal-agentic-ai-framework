#!/usr/bin/env bash
# Verify ryuu-execution is independently installable without pulling in the full ryuu package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$(mktemp -d)/venv-execution-isolation"

echo "=== execution-isolation: creating fresh venv at $VENV_DIR ==="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== execution-isolation: installing ryuu-execution (editable) ==="
pip install -e "$REPO_ROOT/packages/ryuu-core" -q
pip install -e "$REPO_ROOT/packages/ryuu-providers" -q
pip install -e "$REPO_ROOT/packages/ryuu-execution" -q

echo "=== execution-isolation: verifying ryuu is NOT installed ==="
python3 -c "
import sys
try:
    import ryuu
    print('FAIL: ryuu imported — it should not be present', file=sys.stderr)
    sys.exit(1)
except ModuleNotFoundError:
    print('OK: import ryuu → ModuleNotFoundError (expected)')
"

echo "=== execution-isolation: smoke test ryuu_execution ==="
python3 -c "
import anyio
from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import AgentResult, Cost, Task
from ryuu_execution.agent import BaseAgent
from ryuu_execution.pool import AgentPool
from ryuu_execution.tool_registry import ITool, ToolRegistry
from ryuu_execution.sandbox import SandboxManager, SandboxResult
from ryuu_execution.llm_agent import (
    LLMAgent, ReActCallbacks, SilentCallbacks, PrintCallbacks,
    BudgetSummary, ModelPolicy,
)

class EchoAgent(BaseAgent):
    async def _execute(self, task, context):
        return AgentResult(task_id=task.task_id, output='echo', cost=Cost.zero(), success=True)

pool = AgentPool()
pool.register(EchoAgent(agent_id='echo'))
assert pool.agent_ids() == ['echo']

registry = ToolRegistry()
assert registry is not None

mgr = SandboxManager()
result = mgr.run(['python3', '-c', 'print(\"ok\")'])
assert result.success
assert 'ok' in result.stdout

print('OK: ryuu_execution smoke test passed')
"

deactivate
rm -rf "$VENV_DIR"
echo "=== execution-isolation: PASSED ==="
