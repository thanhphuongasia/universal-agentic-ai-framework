# Phase 8.1 — Migration Guide: `uaaf` → `uaaf-workflow`

## What moved

The following symbols are no longer part of `uaaf`. They now live in the
standalone `uaaf-workflow` package (namespace `uaaf_workflow`).

| Old import | New import |
|---|---|
| `from uaaf.observability.errors import ...` | `from uaaf_workflow.errors import ...` |
| `from uaaf.runtime.context import ...` | `from uaaf_workflow.context import ...` |
| `from uaaf.workflow.engine import ...` | `from uaaf_workflow.engine import ...` |
| `from uaaf.workflow.state_machine import ...` | `from uaaf_workflow.state_machine import ...` |
| `from uaaf.workflow.checkpoint import ...` | `from uaaf_workflow.checkpoint import ...` |
| `from uaaf.workflow.stores.file import ...` | `from uaaf_workflow.stores.file import ...` |
| `from uaaf.workflow.stores.in_memory import ...` | `from uaaf_workflow.stores.in_memory import ...` |
| `from uaaf.workflow import ...` | `from uaaf_workflow import ...` |
| `from uaaf import WorkflowEngine` (top-level) | `from uaaf_workflow import WorkflowEngine` |

## Symbols moved to `uaaf_workflow.errors`

`BudgetExceededError`, `DegradedError`, `FatalError`, `FrameworkError`,
`RateLimitTimeout`, `RetryableError`, `classify_external_error`, `retry_policy`

## Symbols moved to `uaaf_workflow.context`

`ExecutionContext`, `ContextScope`

## Symbols moved to `uaaf_workflow.*`

`WorkflowEngine`, `IWorkflowEngine`, `WorkflowResult`, `WorkflowStatus`,
`IState`, `StateMachine`, `StateTransition`, `Workflow`,
`Checkpoint`, `ICheckpointStore`,
`FileCheckpointStore`, `InMemoryCheckpointStore`

## Files deleted from `uaaf/` after Phase 8.1.C

| Deleted file | Replaced by |
|---|---|
| `uaaf/workflow/` (entire dir) | `packages/uaaf-workflow/src/uaaf_workflow/` |
| `uaaf/observability/errors.py` | `packages/uaaf-workflow/src/uaaf_workflow/errors.py` |
| `uaaf/runtime/context.py` | `packages/uaaf-workflow/src/uaaf_workflow/context.py` |

## Mechanical sed migration (Phase 8.1.D — T13)

Apply to all `.py` files in `tests/`, `examples/`, `conftest.py`, `uaaf/_testing/`:

```bash
find tests examples uaaf/_testing conftest.py -name "*.py" | xargs sed -i.bak \
  -e 's|from uaaf\.observability\.errors import|from uaaf_workflow.errors import|g' \
  -e 's|from uaaf\.runtime\.context import|from uaaf_workflow.context import|g' \
  -e 's|from uaaf\.workflow\.engine import|from uaaf_workflow.engine import|g' \
  -e 's|from uaaf\.workflow\.state_machine import|from uaaf_workflow.state_machine import|g' \
  -e 's|from uaaf\.workflow\.checkpoint import|from uaaf_workflow.checkpoint import|g' \
  -e 's|from uaaf\.workflow\.stores\.file import|from uaaf_workflow.stores.file import|g' \
  -e 's|from uaaf\.workflow\.stores\.in_memory import|from uaaf_workflow.stores.in_memory import|g' \
  -e 's|from uaaf\.workflow import|from uaaf_workflow import|g'
```

Top-level `from uaaf import {WorkflowEngine, ...}` must be migrated **manually**
because those lines may also import non-workflow AI symbols.

## `uaaf/__init__.py` — lines to delete (Phase 8.1.C — T10)

```python
# DELETE all of these:
from uaaf.workflow.checkpoint import Checkpoint, ICheckpointStore
from uaaf.workflow.engine import IWorkflowEngine, WorkflowEngine, WorkflowResult, WorkflowStatus
from uaaf.workflow.state_machine import IState, StateMachine, StateTransition, Workflow
from uaaf.workflow.stores.file import FileCheckpointStore
from uaaf.workflow.stores.in_memory import InMemoryCheckpointStore
from uaaf.observability.errors import (
    BudgetExceededError, DegradedError, FatalError, FrameworkError,
    RateLimitTimeout, RetryableError, classify_external_error, retry_policy,
)
from uaaf.runtime.context import ContextScope, ExecutionContext
```

And the corresponding entries from `__all__`.

## Install (after Phase 8.1 complete)

```bash
# Workflow only (no AI deps)
pip install uaaf-workflow

# Full AI framework (auto-pulls uaaf-workflow)
pip install uaaf

# Dev — editable both packages
bash scripts/install-dev.sh
```
