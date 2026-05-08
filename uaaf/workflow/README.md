# `uaaf.workflow` — Workflow Engine

Batch pipeline module for UAAF. Runs a directed graph of states, checkpoints after every step, and resumes from the last checkpoint after a SIGKILL.

## Core concepts

| Class | Role |
|---|---|
| `IState` | Protocol — implement `state_id: str` + `async execute(input, context) → StateTransition` |
| `StateTransition` | Return value from a state — `next_state` (or `None` to end) + `output` passed to next state |
| `Workflow` | Frozen config — `states` dict + `initial_state` + `terminal_states` |
| `StateMachine` | Validates the graph and steps through it |
| `WorkflowEngine` | Runs/resumes a workflow; checkpoints after every state |
| `ICheckpointStore` | Protocol — `save / load_latest / load_history / delete` |
| `InMemoryCheckpointStore` | Default store — tests, dev, single-process |
| `FileCheckpointStore` | JSON-backed, atomic writes (`tmpfile → os.replace`) — prod, SIGKILL-safe |

## Quick start

```python
from dataclasses import dataclass
from uaaf.workflow.engine import WorkflowEngine
from uaaf.workflow.state_machine import Workflow, StateTransition
from uaaf.workflow.stores.in_memory import InMemoryCheckpointStore
from uaaf.runtime.context import ContextScope, ExecutionContext

# 1. Define states — plain dataclasses, no inheritance
@dataclass
class FetchState:
    state_id: str = "fetch"

    async def execute(self, input, context) -> StateTransition:
        data = await fetch_data(input)
        return StateTransition(next_state="process", output=data)

@dataclass
class ProcessState:
    state_id: str = "process"

    async def execute(self, input, context) -> StateTransition:
        result = transform(input)
        return StateTransition(next_state=None, output=result)  # None = done

# 2. Wire workflow
workflow = Workflow(
    workflow_id="my-pipeline",
    states={"fetch": FetchState(), "process": ProcessState()},
    initial_state="fetch",
    terminal_states=frozenset(),  # states that exit before executing (optional)
)

# 3. Run
store = InMemoryCheckpointStore()
engine = WorkflowEngine(checkpoint_store=store)

ctx = ExecutionContext(
    scope=ContextScope(user_id="u1", session_id="s1", domain="demo"),
    correlation_id="run-001",
)
result = await engine.run(workflow, initial_input="https://...", context=ctx)
print(result.status, result.output)
```

## SIGKILL-safe resume

```python
from uaaf.workflow.stores.file import FileCheckpointStore
from pathlib import Path

store = FileCheckpointStore(base_dir=Path("/tmp/checkpoints"))
engine = WorkflowEngine(checkpoint_store=store)

# First run — interrupted after state "fetch"
await engine.run(workflow, initial_input=url, context=ctx)  # process never ran

# Resume — engine reads latest checkpoint, skips "fetch", runs from "process"
result = await engine.resume(workflow, context=ctx)
print(result.status)  # completed
```

## Error handling

States raise typed errors; the engine classifies and handles each tier:

| Exception | Engine behaviour |
|---|---|
| `RetryableError` | Retry up to `max_state_retries` (default 3) with exponential backoff |
| `DegradedError` | Log warning, mark workflow `FAILED` — no retry, no exception raised |
| `FatalError` | Mark workflow `FAILED` immediately — no retry, no exception raised |
| Any other `Exception` | Wrapped in `FatalError`, same behaviour |

```python
from uaaf.observability.errors import RetryableError

@dataclass
class FlakeyState:
    state_id: str = "flakey"
    _attempts: int = 0

    async def execute(self, input, context) -> StateTransition:
        self._attempts += 1
        if self._attempts < 3:
            raise RetryableError("rate limited")
        return StateTransition(next_state=None, output="ok")
```

## WorkflowResult

```python
@dataclass
class WorkflowResult:
    status: WorkflowStatus        # COMPLETED | FAILED | PAUSED
    final_state: str | None       # last state that executed
    output: Any                   # output of the last state
    checkpoints_saved: int
    error: str | None             # set on FAILED
```

## `terminal_states`

States listed in `terminal_states` are **exit markers** — the engine stops *before* executing them (use for explicit named end-points like `"DONE"` or `"CANCELLED"`).

States that return `StateTransition(next_state=None, ...)` **are executed and checkpointed** — they are the natural last step of a pipeline. Do not add them to `terminal_states`.

## Reading intermediate outputs

```python
history = await store.load_history("my-pipeline")
# history is sorted by sequence ascending
# history[i].state_id, history[i].output, history[i].sequence
```

## Checkpoint stores

```python
# In-memory (tests, dev)
from uaaf.workflow.stores.in_memory import InMemoryCheckpointStore
store = InMemoryCheckpointStore()

# File-backed (prod, SIGKILL-safe)
from uaaf.workflow.stores.file import FileCheckpointStore
store = FileCheckpointStore(base_dir=Path("/var/lib/myapp/checkpoints"))
# Layout: <base_dir>/<workflow_id>/<sequence>.json
```

## Real-world example

See `examples/code_analysis/` — a 3-state pipeline:
- `IngestState` → parse Python source files → `list[ClassInfo]`
- `AnalyseState` → parallel multi-agent analysis → `CodebaseReport`
- `SummarizeState` → LLM codebase summary → `str`
