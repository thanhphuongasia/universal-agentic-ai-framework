# Phase 8.1 — Migration Guide: `ryuu` → `ryuu-workflow`

See `docs/architecture/ryuu-v2-architecture.md` §13 for the full roadmap.

---

# Phase 8.2 — Migration Guide: `ryuu` → `ryuu-core`

## What moved

| Symbol | Old location | New canonical location |
|--------|-------------|------------------------|
| `FrameworkError`, `RetryableError`, `DegradedError`, `FatalError`, `BudgetExceededError`, `RateLimitTimeout`, `RetryDecision`, `retry_policy`, `classify_external_error` | `ryuu_workflow.errors` | `ryuu_core.errors` |
| `ContextScope`, `ExecutionContext` | `ryuu_workflow.context` | `ryuu_core.context` |
| `Cost`, `Task`, `AgentResult` | `ryuu.observability.cost` / `ryuu.execution.agent` | `ryuu_core.models` |
| `StrategyId`, `DIRECT`, `REACT`, `EVALUATOR_OPTIMIZER`, `PARALLEL_FANOUT`, `ComplexityLevel`, `ModelTier`, `StructuredIntent`, `CognitiveResult`, `CostEstimate` | `ryuu.intent.models` | `ryuu_core.models` |
| `ICostTracker`, `ITracer`, `IAuditLogger`, `IRateLimiter` | (new) | `ryuu_core.protocols` |
| `NullCostTracker`, `NullTracer`, `NullAuditLogger`, `NullRateLimiter` | (new) | `ryuu_core.nulls` |

## No callsite changes needed

All old import paths continue to work via thin re-exports:

```python
# These still work without any changes:
from ryuu_workflow.errors import RetryableError
from ryuu_workflow.context import ContextScope
from ryuu.intent.models import StructuredIntent
from ryuu.execution.agent import Task, AgentResult
```

## New: zero-dep foundation package

```bash
pip install ryuu-core
```

`ryuu-core` has **zero runtime dependencies** — pure stdlib only. Use it to
share domain types across packages without pulling in the full RYUU stack.

## New: NullObject defaults in BaseAgent

`BaseAgent` no longer requires observability deps at construction time:

```python
# v0.1.x — all deps mandatory
agent = MyAgent(agent_id="x", cost_tracker=ct, tracer=tr, audit_logger=al, rate_limiter=rl)

# v0.2.x — all observability deps optional (NullObject defaults)
agent = MyAgent(agent_id="x")
```

## What moved

The following symbols are no longer part of `ryuu`. They now live in the
standalone `ryuu-workflow` package (namespace `ryuu_workflow`).

| Old import | New import |
|---|---|
| `from ryuu.observability.errors import ...` | `from ryuu_workflow.errors import ...` |
| `from ryuu.runtime.context import ...` | `from ryuu_workflow.context import ...` |
| `from ryuu.workflow.engine import ...` | `from ryuu_workflow.engine import ...` |
| `from ryuu.workflow.state_machine import ...` | `from ryuu_workflow.state_machine import ...` |
| `from ryuu.workflow.checkpoint import ...` | `from ryuu_workflow.checkpoint import ...` |
| `from ryuu.workflow.stores.file import ...` | `from ryuu_workflow.stores.file import ...` |
| `from ryuu.workflow.stores.in_memory import ...` | `from ryuu_workflow.stores.in_memory import ...` |
| `from ryuu.workflow import ...` | `from ryuu_workflow import ...` |
| `from ryuu import WorkflowEngine` (top-level) | `from ryuu_workflow import WorkflowEngine` |

## Symbols moved to `ryuu_workflow.errors`

`BudgetExceededError`, `DegradedError`, `FatalError`, `FrameworkError`,
`RateLimitTimeout`, `RetryableError`, `classify_external_error`, `retry_policy`

## Symbols moved to `ryuu_workflow.context`

`ExecutionContext`, `ContextScope`

## Symbols moved to `ryuu_workflow.*`

`WorkflowEngine`, `IWorkflowEngine`, `WorkflowResult`, `WorkflowStatus`,
`IState`, `StateMachine`, `StateTransition`, `Workflow`,
`Checkpoint`, `ICheckpointStore`,
`FileCheckpointStore`, `InMemoryCheckpointStore`

## Files deleted from `ryuu/` after Phase 8.1.C

| Deleted file | Replaced by |
|---|---|
| `ryuu/workflow/` (entire dir) | `packages/ryuu-workflow/src/ryuu_workflow/` |
| `ryuu/observability/errors.py` | `packages/ryuu-workflow/src/ryuu_workflow/errors.py` |
| `ryuu/runtime/context.py` | `packages/ryuu-workflow/src/ryuu_workflow/context.py` |

## Mechanical sed migration (Phase 8.1.D — T13)

Apply to all `.py` files in `tests/`, `examples/`, `conftest.py`, `ryuu/_testing/`:

```bash
find tests examples ryuu/_testing conftest.py -name "*.py" | xargs sed -i.bak \
  -e 's|from ryuu\.observability\.errors import|from ryuu_workflow.errors import|g' \
  -e 's|from ryuu\.runtime\.context import|from ryuu_workflow.context import|g' \
  -e 's|from ryuu\.workflow\.engine import|from ryuu_workflow.engine import|g' \
  -e 's|from ryuu\.workflow\.state_machine import|from ryuu_workflow.state_machine import|g' \
  -e 's|from ryuu\.workflow\.checkpoint import|from ryuu_workflow.checkpoint import|g' \
  -e 's|from ryuu\.workflow\.stores\.file import|from ryuu_workflow.stores.file import|g' \
  -e 's|from ryuu\.workflow\.stores\.in_memory import|from ryuu_workflow.stores.in_memory import|g' \
  -e 's|from ryuu\.workflow import|from ryuu_workflow import|g'
```

Top-level `from ryuu import {WorkflowEngine, ...}` must be migrated **manually**
because those lines may also import non-workflow AI symbols.

## `ryuu/__init__.py` — lines to delete (Phase 8.1.C — T10)

```python
# DELETE all of these:
from ryuu.workflow.checkpoint import Checkpoint, ICheckpointStore
from ryuu.workflow.engine import IWorkflowEngine, WorkflowEngine, WorkflowResult, WorkflowStatus
from ryuu.workflow.state_machine import IState, StateMachine, StateTransition, Workflow
from ryuu.workflow.stores.file import FileCheckpointStore
from ryuu.workflow.stores.in_memory import InMemoryCheckpointStore
from ryuu.observability.errors import (
    BudgetExceededError, DegradedError, FatalError, FrameworkError,
    RateLimitTimeout, RetryableError, classify_external_error, retry_policy,
)
from ryuu.runtime.context import ContextScope, ExecutionContext
```

And the corresponding entries from `__all__`.

## Install (after Phase 8.1 complete)

```bash
# Workflow only (no AI deps)
pip install ryuu-workflow

# Full AI framework (auto-pulls ryuu-workflow)
pip install ryuu

# Dev — editable both packages
bash scripts/install-dev.sh
```

---

# Phase 8.3 — Migration Guide: `ryuu.providers` → `ryuu-providers`

## What moved

| Symbol | Old location | New canonical location |
|--------|-------------|------------------------|
| `ILLMProvider`, `CompletionRequest`, `Message`, `Response`, `StreamChunk`, `TokenUsage`, `Embedding` | `ryuu.providers.llm` | `ryuu_providers.llm` |
| `CircuitBreaker`, `CircuitState` | `ryuu.providers.circuit_breaker` | `ryuu_providers.circuit_breaker` |
| `ProviderFallbackChain` | `ryuu.providers.fallback` | `ryuu_providers.fallback` |
| `ModelRouter` | `ryuu.providers.router` | `ryuu_providers.router` |
| `OpenAIProvider` | `ryuu.providers.adapters.openai` | `ryuu_providers.adapters.openai` |
| `AnthropicProvider` | `ryuu.providers.adapters.anthropic` | `ryuu_providers.adapters.anthropic` |
| `calculate_usd`, `reload_pricing`, `PRICING`, `CONTEXT_WINDOW` | `ryuu.observability._pricing` | `ryuu_providers._pricing` |

## No callsite changes needed (backward-compat shims in place)

All old import paths continue to work via thin re-exports:

```python
# These still work without any changes:
from ryuu.providers.llm import ILLMProvider, CompletionRequest
from ryuu.providers.router import ModelRouter
from ryuu.providers.adapters.openai import OpenAIProvider
from ryuu.observability._pricing import calculate_usd
```

## Canonical imports (recommended going forward)

```python
from ryuu_providers.llm import ILLMProvider, CompletionRequest, Message
from ryuu_providers.circuit_breaker import CircuitBreaker
from ryuu_providers.fallback import ProviderFallbackChain
from ryuu_providers.router import ModelRouter
from ryuu_providers.adapters.openai import OpenAIProvider
from ryuu_providers.adapters.anthropic import AnthropicProvider
from ryuu_providers._pricing import calculate_usd
```

## Patch path update (if you mock adapters in tests)

```python
# Old (still works via shim but object lives in canonical module):
patch("ryuu.providers.adapters.openai.AsyncOpenAI")       # ← broken (shim has no AsyncOpenAI)

# New (correct — patch where it's actually used):
patch("ryuu_providers.adapters.openai.AsyncOpenAI")       # ✓
patch("ryuu_providers.adapters.anthropic.AsyncAnthropic") # ✓
```

## Install

```bash
# Providers only (no full AI framework)
pip install ryuu-providers

# Full AI framework (auto-pulls ryuu-providers)
pip install ryuu
```

---

# Phase 8.4 — Migration Guide: `ryuu` → `ryuu-observability`

## What moved

| Symbol | Old location | New canonical location |
|--------|-------------|------------------------|
| `CostPolicy`, `UsageSnapshot`, `ICostStore`, `InMemoryCostStore`, `CostTracker` | `ryuu.observability.cost` | `ryuu_observability.cost` |
| `AuditEvent`, `AuditConfig`, `IAuditStore`, `ConsoleAuditStore`, `FileAuditStore`, `AuditLogger`, `verify_chain` | `ryuu.observability.audit` | `ryuu_observability.audit` |
| `Tracer`, `setup_tracing`, `get_current_correlation_id` | `ryuu.observability.tracer` | `ryuu_observability.tracer` |
| `RatePolicy`, `IRateStore`, `InMemoryRateStore`, `RateLimiter` | `ryuu.observability.rate_limit` | `ryuu_observability.rate_limit` |

## No callsite changes needed (backward-compat shims in place)

All old import paths continue to work via thin re-exports:

```python
# These still work without any changes:
from ryuu.observability.cost import CostTracker, CostPolicy
from ryuu.observability.audit import AuditLogger, verify_chain
from ryuu.observability.tracer import Tracer, setup_tracing
from ryuu.observability.rate_limit import RateLimiter, RatePolicy
```

## Canonical imports (recommended going forward)

```python
from ryuu_observability.cost import CostTracker, CostPolicy, InMemoryCostStore
from ryuu_observability.audit import AuditLogger, AuditConfig, verify_chain
from ryuu_observability.tracer import Tracer, setup_tracing, get_current_correlation_id
from ryuu_observability.rate_limit import RateLimiter, RatePolicy, InMemoryRateStore
```

## Install

```bash
# Observability only (no full AI framework)
pip install ryuu-observability

# Full AI framework (auto-pulls ryuu-observability)
pip install ryuu
```

---

# Phase 8.5 — Migration Guide: `ryuu` → `ryuu-cognitive`

## What moved

| Symbol | Old location | New canonical location |
|--------|-------------|------------------------|
| `VerificationResult`, `IVerifier` | `ryuu.cognitive.verifier` | `ryuu_cognitive.verifier` |
| `IAgentPool`, `ICognitiveStrategy` | `ryuu.cognitive.strategy` | `ryuu_cognitive.strategy` |
| `DirectStrategy`, `ReActStrategy`, `EvaluatorOptimizerStrategy` | `ryuu.cognitive.strategies` | `ryuu_cognitive.strategies` |
| `ParallelFanoutStrategy`, `ISubtaskBuilder`, `EntitySubtaskBuilder` | `ryuu.cognitive.strategies` | `ryuu_cognitive.strategies` |
| `GroundTruthVerifier`, `SchemaVerifier`, `LLMJudgeVerifier` | `ryuu.cognitive.verifiers` | `ryuu_cognitive.verifiers` |
| `VerifierPipeline`, `PipelineMode` | `ryuu.cognitive.verifiers` | `ryuu_cognitive.verifiers` |

## No callsite changes needed (backward-compat shims in place)

All old import paths continue to work via thin re-exports:

```python
# These still work without any changes:
from ryuu.cognitive.verifier import IVerifier, VerificationResult
from ryuu.cognitive.strategy import IAgentPool, ICognitiveStrategy
from ryuu.cognitive.strategies import DirectStrategy, ReActStrategy
from ryuu.cognitive.verifiers import GroundTruthVerifier, VerifierPipeline
```

## Canonical imports (recommended going forward)

```python
from ryuu_cognitive.verifier import IVerifier, VerificationResult
from ryuu_cognitive.strategy import IAgentPool, ICognitiveStrategy
from ryuu_cognitive.strategies import DirectStrategy, ReActStrategy, EvaluatorOptimizerStrategy
from ryuu_cognitive.strategies import ParallelFanoutStrategy, ISubtaskBuilder
from ryuu_cognitive.verifiers import GroundTruthVerifier, SchemaVerifier, LLMJudgeVerifier
from ryuu_cognitive.verifiers import VerifierPipeline, PipelineMode
```

## Install

```bash
# Cognitive only (no full AI framework)
pip install ryuu-cognitive

# Full AI framework (auto-pulls ryuu-cognitive)
pip install ryuu
```

---

# Phase 8.6 — Migration Guide: `ryuu` → `ryuu-execution`

## What moved

| Symbol | Old location | New canonical location |
|--------|-------------|------------------------|
| `BaseAgent`, `Task`, `AgentResult` | `ryuu.execution.agent` | `ryuu_execution.agent` |
| `LLMAgent`, `ReActCallbacks`, `SilentCallbacks`, `PrintCallbacks`, `BudgetSummary`, `ModelPolicy` | `ryuu.execution.llm_agent` | `ryuu_execution.llm_agent` |
| `AgentPool` | `ryuu.execution.pool` | `ryuu_execution.pool` |
| `ITool`, `ToolRegistry` | `ryuu.execution.tool_registry` | `ryuu_execution.tool_registry` |
| `SandboxResult`, `ISandbox`, `SubprocessSandbox`, `SandboxManager` | `ryuu.execution.sandbox` | `ryuu_execution.sandbox` |

## No callsite changes needed (backward-compat shims in place)

All old import paths continue to work via thin re-exports:

```python
# These still work without any changes:
from ryuu.execution.agent import BaseAgent, Task, AgentResult
from ryuu.execution.llm_agent import LLMAgent, ReActCallbacks, SilentCallbacks
from ryuu.execution.pool import AgentPool
from ryuu.execution.tool_registry import ITool, ToolRegistry
from ryuu.execution.sandbox import SandboxManager
```

## Canonical imports (recommended going forward)

```python
from ryuu_execution.agent import BaseAgent, Task, AgentResult
from ryuu_execution.llm_agent import LLMAgent, ReActCallbacks, SilentCallbacks, PrintCallbacks
from ryuu_execution.pool import AgentPool
from ryuu_execution.tool_registry import ITool, ToolRegistry
from ryuu_execution.sandbox import SandboxManager, SandboxResult
```

## Install

```bash
# Execution only (no full AI framework)
pip install ryuu-execution

# Full AI framework (auto-pulls ryuu-execution)
pip install ryuu
```

---

# Phase 8.7 — Migration Guide: `ryuu` → `ryuu-runtime`

## What moved

| Symbol | Old location | New canonical location |
|--------|-------------|------------------------|
| `IIntentAnalyzer` | `ryuu.intent.analyzer` | `ryuu_runtime.analyzer` |
| `LLMIntentAnalyzer`, `INTENT_SYSTEM_PROMPT` | `ryuu.intent.llm_analyzer` | `ryuu_runtime.llm_analyzer` |
| `StrategySelector` | `ryuu.intent.selector` | `ryuu_runtime.selector` |
| `RequestHandler` | `ryuu.runtime.request_handler` | `ryuu_runtime.request_handler` |

## No callsite changes needed (backward-compat shims in place)

All old import paths continue to work via thin re-exports:

```python
# These still work without any changes:
from ryuu.intent.analyzer import IIntentAnalyzer
from ryuu.intent.llm_analyzer import LLMIntentAnalyzer, INTENT_SYSTEM_PROMPT
from ryuu.intent.selector import StrategySelector
from ryuu.runtime.request_handler import RequestHandler
```

## Canonical imports (recommended going forward)

```python
from ryuu_runtime.analyzer import IIntentAnalyzer
from ryuu_runtime.llm_analyzer import LLMIntentAnalyzer, INTENT_SYSTEM_PROMPT
from ryuu_runtime.selector import StrategySelector
from ryuu_runtime.request_handler import RequestHandler
```

## Install

```bash
# Runtime only (intent analysis + request handling, no full AI framework)
pip install ryuu-runtime

# Full AI framework (auto-pulls ryuu-runtime)
pip install ryuu
```

---

# Phase 8.9 — New packages: `ryuu-guardrail` + `ryuu-eval`

## `ryuu-guardrail` — rule-based safety filters

These are **new** symbols — no old import paths to migrate.

### Canonical imports

```python
from ryuu_guardrail.protocol import IGuardrail, GuardrailResult, GuardrailAction, GuardrailBlockedError
from ryuu_guardrail.passthrough import PassthroughGuardrail
from ryuu_guardrail.filters.pii import PIIFilter
from ryuu_guardrail.filters.topic import TopicBlocker
from ryuu_guardrail.filters.injection import PromptInjectionDetector
from ryuu_guardrail.pipeline import GuardrailPipeline, TrustLevel
```

### Usage

```python
# Quick setup by trust level
pipeline = GuardrailPipeline.for_trust_level(TrustLevel.HIGH)

# or compose manually
pipeline = GuardrailPipeline([
    PromptInjectionDetector(),
    PIIFilter(entity_types=["email", "phone"]),
    TopicBlocker(denied_topics=["gambling", "meme coins"]),
])

try:
    result = await pipeline.check(user_message, ctx)
    if result.action == GuardrailAction.REDACT:
        user_message = result.redacted_content
except GuardrailBlockedError as e:
    return f"Request blocked: {e.reason}"
```

## `ryuu-eval` — evaluation framework (dev dependency)

These are **new** symbols — no old import paths to migrate.

### Canonical imports

```python
from ryuu_eval.models import EvalCase, CaseResult, SuiteResult, ScoreResult
from ryuu_eval.protocols import EvalTarget, Scorer
from ryuu_eval.scorers import ExactMatch, Constraint, Threshold, Composite, LLMJudge
from ryuu_eval.fixture_loader import FixtureLoader
from ryuu_eval.runner import EvalRunner
from ryuu_eval.renderers.terminal import TerminalRenderer
from ryuu_eval.renderers.github_actions import GitHubActionsRenderer
from ryuu_eval.renderers.api import ApiRenderer
```

### Install (dev only)

```bash
pip install ryuu-eval            # pulls in ryuu-core + ryuu-providers
# or as optional dep in your project:
pip install "my-product[eval]"
```

---

# Phase 8.8 — Migration Guide: `ryuu` → `ryuu-knowledge-*`

## What moved

| Symbol | Old location | New canonical location |
|--------|-------------|------------------------|
| `BackboneType`, `QueryResult`, `AssembledContext`, `IKnowledgeBackbone` | `ryuu.knowledge.backbone` | `ryuu_knowledge_base.backbone` |
| `ContextAssembler` | `ryuu.knowledge.context_assembler` | `ryuu_knowledge_base.context_assembler` |
| `MemoryLayer`, `MemoryEntry`, `IMemoryStore` | `ryuu.knowledge.memory.store` | `ryuu_knowledge_memory.store` |
| `WorkingMemoryStore` | `ryuu.knowledge.memory.working` | `ryuu_knowledge_memory.working` |
| `EpisodicMemoryStore` | `ryuu.knowledge.memory.episodic` | `ryuu_knowledge_memory.episodic` |
| `MemoryBackbone` | `ryuu.knowledge.memory.backbone` | `ryuu_knowledge_memory.backbone` |
| `Node`, `Edge`, `IGraphStore` | `ryuu.knowledge.graph.store` | `ryuu_knowledge_graph.store` |
| `InMemoryGraphStore` | `ryuu.knowledge.graph.in_memory` | `ryuu_knowledge_graph.in_memory` |
| `GraphBackbone` | `ryuu.knowledge.graph.backbone` | `ryuu_knowledge_graph.backbone` |
| `HybridBackbone` | `ryuu.knowledge.hybrid` | `ryuu_knowledge.hybrid` |

## No callsite changes needed (backward-compat shims in place)

All old import paths continue to work via thin re-exports:

```python
# These still work without any changes:
from ryuu.knowledge.backbone import IKnowledgeBackbone, BackboneType
from ryuu.knowledge.memory.backbone import MemoryBackbone
from ryuu.knowledge.graph.backbone import GraphBackbone
from ryuu.knowledge.hybrid import HybridBackbone
```

## Canonical imports (recommended going forward)

```python
# Base protocols (zero deps)
from ryuu_knowledge_base.backbone import IKnowledgeBackbone, BackboneType, QueryResult, AssembledContext
from ryuu_knowledge_base.context_assembler import ContextAssembler

# Memory implementations
from ryuu_knowledge_memory.backbone import MemoryBackbone
from ryuu_knowledge_memory.working import WorkingMemoryStore
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore

# Graph implementations
from ryuu_knowledge_graph.backbone import GraphBackbone
from ryuu_knowledge_graph.in_memory import InMemoryGraphStore
from ryuu_knowledge_graph.store import Node, Edge, IGraphStore

# Hybrid orchestrator
from ryuu_knowledge.hybrid import HybridBackbone
```

## Install

```bash
# Base protocols only (zero deps, good for type annotations)
pip install ryuu-knowledge-base

# Memory backbone only
pip install ryuu-knowledge-memory  # pulls in ryuu-knowledge-base

# Graph backbone only
pip install ryuu-knowledge-graph  # pulls in ryuu-knowledge-base

# Hybrid (all knowledge capabilities)
pip install ryuu-knowledge  # pulls in all knowledge packages

# Full AI framework
pip install ryuu
```
