# ryuu-prompts

Versioned YAML prompt management for the Ryuu framework.

## Why

LLM prompts are **data, not code**. They change often (tuning, A/B testing, user customization), they need versioning, and they should be editable without redeploying code. This package gives you all three:

- **YAML-first** — prompts live in `prompts/<project>/<version>.yaml` files
- **Versioned** — `v1.yaml`, `v2.yaml`, … explicit upgrade path
- **Multi-root overlay** — user override directory shadows framework defaults
- **CompletionRequest-aware** — render directly to provider call shape

## Usage

```python
from pathlib import Path
from ryuu_prompts import PromptRegistry, make_framework_registry

# Simple: one root
registry = PromptRegistry(prompts_root=Path("./prompts"))
cfg = registry.load("my_project", "v1")
request = registry.build_request(cfg, "analyze", context="...", query="...")

# Layered: user overrides framework defaults
registry = PromptRegistry(prompts_roots=[
    Path("~/.ryuu/prompts").expanduser(),   # user shadow (highest)
    Path("./prompts"),                       # app-local
    # framework defaults appended automatically by package data
])

# Framework factory (auto-wires all installed ryuu-* package prompts)
registry = make_framework_registry(
    user_overrides_root=Path("~/.ryuu/prompts").expanduser(),
)
```

## YAML schema

```yaml
version: "1.0"
description: "Todo app — productivity analysis"
model: "gpt-4o-mini"
temperature: 0.1
max_tokens: 1024

prompts:
  analyze:
    system: |
      You are a productivity analyst.
      Data: {context}
    user: "{query}"

  next_sprint:
    system: |
      You are an engineering manager.
      Data: {context}
    user: "{query}"

tools:
  - name: get_task_stats
    description: Get task counts and completion rates
    parameters:
      type: object
      properties:
        goal_id: {type: string}
```

## Override patterns

| Layer | Path | Use case |
|-------|------|----------|
| 1. User shadow | `~/.ryuu/prompts/<project>/<version>.yaml` | Per-developer tweak, no deploy |
| 2. App-local | `./prompts/<project>/<version>.yaml` | Product-specific |
| 3. Package data | `<pkg>/prompts/<project>/<version>.yaml` | Framework default (shipped) |

First match wins. Add or remove roots to taste.
