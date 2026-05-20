# uaaf-workflow

Standalone workflow engine and state machine library — extracted from [UAAF](https://github.com/core-corp/uaaf-framework).

## Install

```bash
pip install uaaf-workflow
```

No AI dependencies. Only requires `anyio`.

## Quickstart

```python
from uaaf_workflow import WorkflowEngine, Workflow, IState
from uaaf_workflow.context import ExecutionContext, ContextScope
from uaaf_workflow.stores.in_memory import InMemoryCheckpointStore

# Define states and workflow, then run:
engine = WorkflowEngine(checkpoint_store=InMemoryCheckpointStore())
```

See `packages/uaaf-workflow/` in the [UAAF monorepo](https://github.com/core-corp/uaaf-framework) for full docs.
