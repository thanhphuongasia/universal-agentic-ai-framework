# ryuu-workflow

Standalone workflow engine and state machine — extracted from [RYUU](https://github.com/core-corp/ryuu-framework).

Use when you need a durable, checkpoint-safe state machine without pulling in the full AI framework.

## Install

```bash
pip install ryuu-workflow
```

Only dependency: `anyio>=4.0`.

## Quickstart

```python
import asyncio
from dataclasses import dataclass
from ryuu_workflow import (
    WorkflowEngine, Workflow, IState,
    StateTransition, ExecutionContext, ContextScope,
    InMemoryCheckpointStore,
)

@dataclass
class FetchState:
    name: str = "fetch"
    next_state: str | None = "process"

    async def run(self, ctx: ExecutionContext) -> str:
        print("fetching...")
        return "done"

@dataclass
class ProcessState:
    name: str = "process"
    next_state: str | None = None

    async def run(self, ctx: ExecutionContext) -> str:
        print("processing...")
        return "done"

workflow = Workflow(
    workflow_id="demo",
    states=[FetchState(), ProcessState()],
    initial_state="fetch",
)

async def main():
    engine = WorkflowEngine(checkpoint_store=InMemoryCheckpointStore())
    ctx = ExecutionContext(scope=ContextScope(user_id="u1", session_id="s1"))
    result = await engine.run(workflow, ctx)
    print(result.status)  # WorkflowStatus.COMPLETED

asyncio.run(main())
```

## What's included

| Module | Contents |
|---|---|
| `ryuu_workflow.engine` | `WorkflowEngine`, `IWorkflowEngine`, `WorkflowResult`, `WorkflowStatus` |
| `ryuu_workflow.state_machine` | `IState`, `Workflow`, `StateMachine`, `StateTransition` |
| `ryuu_workflow.checkpoint` | `ICheckpointStore`, `Checkpoint` |
| `ryuu_workflow.stores.in_memory` | `InMemoryCheckpointStore` |
| `ryuu_workflow.stores.file` | `FileCheckpointStore` (SIGKILL-safe persistence) |
| `ryuu_workflow.context` | `ExecutionContext`, `ContextScope` |
| `ryuu_workflow.errors` | `RetryableError`, `DegradedError`, `FatalError`, `BudgetExceededError`, ... |

## Part of RYUU

This package is the workflow tier of the [RYUU monorepo](https://github.com/core-corp/ryuu-framework).
Install `ryuu` for the full AI framework (LLM providers, cognitive strategies, observability).
