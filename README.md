# UAAF — Universal Agentic AI Framework

> Pluggable Python foundation for AI agent products — cross-cutting (cost/trace/audit/retry)
> injected automatically so product teams focus on domain logic only.

[![CI](https://github.com/core-corp/uaaf-framework/actions/workflows/ci.yml/badge.svg)](https://github.com/core-corp/uaaf-framework/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

## Install

```bash
pip install uaaf                       # core
pip install "uaaf[openai]"             # + OpenAI adapter
pip install "uaaf[anthropic]"          # + Anthropic adapter
pip install "uaaf[openai,anthropic]"   # both
```

For development:

```bash
git clone <repo>
cd uaaf-framework
pip install -e ".[dev]"
```

## Quick start

```python
import anyio
from dataclasses import dataclass, field
from typing import Any

from uaaf.execution.agent import BaseAgent, Task, AgentResult
from uaaf.observability.cost import Cost, CostPolicy, CostTracker
from uaaf.observability.tracer import Tracer
from uaaf.observability.audit import AuditLogger
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.runtime.context import ContextScope, ExecutionContext
from uaaf._testing.fakes import FakeLLMProvider


@dataclass
class EchoAgent(BaseAgent):
    llm: FakeLLMProvider = field(default_factory=FakeLLMProvider)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        response = await self.llm.complete(None)  # type: ignore[arg-type]
        return AgentResult(
            task_id=task.task_id,
            output=response.content,
            cost=Cost(input_tokens=10, output_tokens=5, usd=0.001, provider="fake", model="fake"),
        )


async def main() -> None:
    scope = ContextScope(user_id="u1", session_id="s1", domain="demo")
    ctx = ExecutionContext(scope=scope, correlation_id="corr-001")
    agent = EchoAgent(
        agent_id="echo",
        cost_tracker=CostTracker(CostPolicy()),
        tracer=Tracer(),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy()),
    )
    result = await agent.execute(Task(task_id="t1", payload={"msg": "hello"}), ctx)
    print(result.output)


anyio.run(main)
```

## Verify

```bash
python -c "import uaaf; print(uaaf.__version__)"   # → 0.1.0a1
pytest --cov=uaaf --cov-report=term-missing
ruff check uaaf/
mypy uaaf/
```

## Documentation

### Guides

| Guide | Description |
|---|---|
| [Getting Started](docs/guides/getting-started.md) | Install → first agent in < 5 min |
| [Migration Guide](docs/guides/migration.md) | Strangler pattern, feature flag, rollback < 5 min |

### Cookbook — Use Case Recipes

| Recipe | Validates |
|---|---|
| [Todo App](docs/cookbook/01-todo-app.md) | `MemoryBackbone` + `DirectStrategy` |
| [Flashcard System](docs/cookbook/02-flashcard-system.md) | `EpisodicMemoryStore` + spaced repetition |
| [AI Coding Practice](docs/cookbook/03-coding-practice.md) | `SandboxManager` + tool isolation |
| [Stock Trading](docs/cookbook/04-stock-trading.md) | `AuditLogger` + `VerifierPipeline` + trust=HIGH |

## License

Apache 2.0 — see [LICENSE](LICENSE).
