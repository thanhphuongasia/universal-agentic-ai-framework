# RYUU — Universal Agentic AI Framework

> Modular Python foundation for AI agent products. Core interfaces without AI dependencies. Pick the packages you need, skip the rest.

[![CI](https://github.com/core-corp/ryuu-framework/actions/workflows/ci.yml/badge.svg)](https://github.com/core-corp/ryuu-framework/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

## Why RYUU?

**Before**: Monolithic frameworks force you to pull torch, faiss, opentelemetry, kubernetes-client just to write a simple agent.

**After**: RYUU is 13 independent packages. Install `ryuu-core` (stdlib + anyio only). Add observability, knowledge, guardrails, evaluation as needed.

| Concern | Traditional | RYUU |
|---|---|---|
| Simple agent + OpenAI | `pip install langchain[openai,guardrails,eval]` (50+ deps) | `pip install ryuu-core ryuu-providers` (7 deps) |
| RAG + vector DB | Monolith scales poor | `ryuu-knowledge-rag` + your vector DB |
| Content filtering | Bolted on after | `ryuu-guardrail` from day 1 |
| Workflow state | Job queue required | `ryuu-workflow` (no DB, local or Redis) |
| Evaluation | Custom code | `ryuu-eval` (cost-aware scoring framework) |

---

## Packages

**Core (Zero Dependencies)**

| Package | Purpose | Version |
|---------|---------|---------|
| [`ryuu-core`](packages/ryuu-core/) | Protocols + models + errors + NullObject defaults | 0.2.0a1 |

**Providers & Observability**

| Package | Purpose |
|---------|---------|
| [`ryuu-providers`](packages/ryuu-providers/) | ILLMProvider + adapters (OpenAI, Anthropic) + IEmbedder + pricing |
| [`ryuu-observability`](packages/ryuu-observability/) | CostTracker, Tracer, AuditLogger (OpenTelemetry-backed), RateLimiter |
| [`ryuu-guardrail`](packages/ryuu-guardrail/) | IGuardrail + PIIFilter + TopicBlocker + PromptInjectionDetector |

**Execution & Reasoning**

| Package | Purpose |
|---------|---------|
| [`ryuu-cognitive`](packages/ryuu-cognitive/) | Strategies + Verifier pipeline (schema, LLM judge, ground truth) |
| [`ryuu-execution`](packages/ryuu-execution/) | BaseAgent + AgentPool + ToolRegistry + SandboxManager |
| [`ryuu-workflow`](packages/ryuu-workflow/) | WorkflowEngine + StateMachine + CheckpointStore |
| [`ryuu-runtime`](packages/ryuu-runtime/) | RYUURuntime facade + RequestHandler + StreamManager (SSE/QueueCallbacks) |

**Knowledge & Retrieval**

| Package | Purpose |
|---------|---------|
| [`ryuu-knowledge-base`](packages/ryuu-knowledge-base/) | IKnowledgeBackbone protocol + ContextAssembler |
| [`ryuu-knowledge-memory`](packages/ryuu-knowledge-memory/) | WorkingMemoryStore + EpisodicMemoryStore |
| [`ryuu-knowledge-graph`](packages/ryuu-knowledge-graph/) | InMemoryGraphStore + text search |
| [`ryuu-knowledge`](packages/ryuu-knowledge/) | HybridBackbone combining memory + graph (60/40 budget split) |

**Evaluation (Dev-Only)**

| Package | Purpose |
|---------|---------|
| [`ryuu-eval`](packages/ryuu-eval/) | EvalCase + Scorers (exact match, constraint, LLM judge) + EvalRunner + renderers |

---

## Install

### Minimal (workflow only)

```bash
pip install ryuu-workflow        # 1 dep: anyio
```

### Agent with OpenAI

```bash
pip install ryuu-core ryuu-providers ryuu-execution
# Now: from ryuu_providers.openai import OpenAIProvider
```

### Full (all packages)

```bash
pip install ryuu-core ryuu-providers ryuu-observability ryuu-guardrail \
  ryuu-cognitive ryuu-execution ryuu-workflow ryuu-runtime \
  ryuu-knowledge-base ryuu-knowledge-memory ryuu-knowledge-graph ryuu-knowledge \
  ryuu-eval
```

### Development (editable, monorepo)

```bash
git clone <repo>
cd ryuu-framework
bash scripts/install-dev.sh
```

See [packages/MIGRATION.md](packages/MIGRATION.md) if upgrading from v0.1.x.

---

## Quick Start

**Lean class-based agent with full observability:**

```python
import anyio
from dataclasses import dataclass, field
from ryuu_execution.agent import BaseAgent, Task, AgentResult
from ryuu_core.models import Cost
from ryuu_providers.openai import OpenAIProvider
from ryuu_observability.cost import CostTracker, CostPolicy
from ryuu_workflow.context import ContextScope, ExecutionContext


@dataclass
class MyAgent(BaseAgent):
    llm: OpenAIProvider = field(default_factory=lambda: OpenAIProvider(api_key="sk-..."))

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        response = await self.llm.complete(...)  # your logic
        return AgentResult(
            task_id=task.task_id,
            output=response.content,
            cost=Cost(input_tokens=10, output_tokens=5, usd=0.001, provider="openai", model="gpt-4o"),
        )


async def main():
    scope = ContextScope(user_id="user-1", session_id="s1", domain="demo")
    ctx = ExecutionContext(scope=scope, correlation_id="req-001")
    agent = MyAgent(
        agent_id="my-agent",
        cost_tracker=CostTracker(CostPolicy(max_usd_per_session=1.0)),
    )
    result = await agent.execute(Task(task_id="t1", payload={}), ctx)
    print(result.output)

anyio.run(main)
```

See [Quickstart](docs/guides/quickstart.md) for comparison with Claude Agent SDK and factory-based styles.

---

## Verify

```bash
# Check version
python -c "from ryuu_core import __version__; print(__version__)"

# Full test suite (all packages)
pytest

# Lint + type check
ruff check .
mypy ryuu/ packages/

# Coverage
pytest --cov=ryuu --cov=packages --cov-report=term-missing
```

---

## Documentation

### Guides

| Guide | Description |
|---|---|
| [Quickstart](docs/guides/quickstart.md) | Factory vs Class-based — when to use which |
| [Hooks Guide](docs/guides/hooks.md) | Dynamic lifecycle injection (Claude SDK style) |
| [Getting Started](docs/guides/getting-started.md) | Install + core concepts |
| [Migration Guide](docs/guides/migration.md) | Upgrade from v0.1 → v0.2 |
| [Adapter Guide](docs/guides/adapter-guide.md) | Implement ILLMProvider for a new SDK |
| [Runbook](docs/guides/runbook.md) | Common operational tasks |

### Cookbook — Use Case Recipes

| Recipe | Validates |
|---|---|
| [Todo App](docs/cookbook/01-todo-app.md) | `MemoryBackbone` + `DirectStrategy` |
| [Flashcard System](docs/cookbook/02-flashcard-system.md) | `EpisodicMemoryStore` + spaced repetition |
| [AI Coding Practice](docs/cookbook/03-coding-practice.md) | `SandboxManager` + tool isolation |
| [Stock Trading](docs/cookbook/04-stock-trading.md) | `AuditLogger` + `VerifierPipeline` + trust=HIGH |

---

## Architecture

See [docs/architecture/uaaf-v2-architecture.md](docs/architecture/uaaf-v2-architecture.md) for the design rationale, dependency graph, and phase rollout.

**Key principles:**
- `ryuu-core` has zero external dependencies (stdlib + anyio only)
- Packages communicate via Protocols — no forced coupling
- Cross-cutting concerns (cost, audit, trace, rate limit) injectable as NullObjects
- Each package is independently installable and upgradeable

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
