# Phase 8.3 — ryuu-providers: Standalone LLM Provider Package

> **Pattern**: Same clean-break + TDD approach as Phase 8.1 (workflow) and Phase 8.2 (core).  
> **Namespace**: `ryuu_providers` (top-level, underscore — consistent with `ryuu_workflow`, `ryuu_core`).  
> **Backward-compat**: `ryuu/providers/*.py` replaced with thin re-export shims (same as Phase 8.2 ryuu_workflow.errors shim).

## 1. Goal

Make LLM providers independently installable so products that only need API adapters (OpenAI, Anthropic) don't pull in the full AI framework:

```bash
pip install ryuu-providers            # standalone — only ryuu-core + pyyaml + optional openai/anthropic
pip install ryuu                      # AI framework — auto-pulls ryuu-providers
```

## 2. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Namespace | `ryuu_providers` (top-level, same pattern as ryuu_workflow, ryuu_core) |
| 2 | Backward-compat in `ryuu/providers/` | Thin re-export shims (NOT clean delete — too many callsites) |
| 3 | `_pricing.py` + `pricing.yaml` | Move to `ryuu_providers/`; `ryuu/observability/_pricing.py` becomes shim |
| 4 | Optional deps | `openai>=1.0` + `anthropic>=0.30` as optional extras in pyproject.toml |
| 5 | Version | `0.2.0a1` (same as ryuu-workflow + ryuu-core) |
| 6 | `ryuu-core` dep | `ryuu-core>=0.2.0a1` — provides Cost, ModelTier, errors (DegradedError, RetryableError, classify_external_error) |

## 3. Files Moving FROM `ryuu/` TO `packages/ryuu-providers/src/ryuu_providers/`

| Old path | New path |
|---|---|
| `ryuu/providers/llm.py` | `ryuu_providers/llm.py` |
| `ryuu/providers/circuit_breaker.py` | `ryuu_providers/circuit_breaker.py` |
| `ryuu/providers/fallback.py` | `ryuu_providers/fallback.py` |
| `ryuu/providers/router.py` | `ryuu_providers/router.py` |
| `ryuu/providers/adapters/anthropic.py` | `ryuu_providers/adapters/anthropic.py` |
| `ryuu/providers/adapters/openai.py` | `ryuu_providers/adapters/openai.py` |
| `ryuu/observability/_pricing.py` | `ryuu_providers/_pricing.py` |
| `ryuu/observability/pricing.yaml` | `ryuu_providers/pricing.yaml` |

## 4. Import Migration Map (inside copied files)

```bash
# Internal imports inside ryuu_providers files:
from ryuu.observability.cost import Cost             → from ryuu_core.models import Cost
from ryuu.observability._pricing import calculate_usd → from ryuu_providers._pricing import calculate_usd
from ryuu.intent.models import ModelTier             → from ryuu_core.models import ModelTier
from ryuu_workflow.errors import DegradedError       → from ryuu_core.errors import DegradedError
from ryuu_workflow.errors import RetryableError      → from ryuu_core.errors import RetryableError
from ryuu_workflow.errors import classify_external_error → from ryuu_core.errors import classify_external_error
from ryuu.providers.circuit_breaker import ...      → from ryuu_providers.circuit_breaker import ...
from ryuu.providers.llm import ...                  → from ryuu_providers.llm import ...
```

## 5. Shim Map (files staying in `ryuu/` as backward-compat re-exports)

```python
# ryuu/providers/llm.py → shim
from ryuu_providers.llm import *  # noqa: F401, F403

# ryuu/providers/circuit_breaker.py → shim
from ryuu_providers.circuit_breaker import *  # noqa: F401, F403

# ryuu/providers/fallback.py → shim
from ryuu_providers.fallback import *  # noqa: F401, F403

# ryuu/providers/router.py → shim
from ryuu_providers.router import *  # noqa: F401, F403

# ryuu/providers/adapters/anthropic.py → shim
from ryuu_providers.adapters.anthropic import *  # noqa: F401, F403

# ryuu/providers/adapters/openai.py → shim
from ryuu_providers.adapters.openai import *  # noqa: F401, F403

# ryuu/observability/_pricing.py → shim
from ryuu_providers._pricing import *  # noqa: F401, F403
```

## 6. pyproject.toml for ryuu-providers

```toml
[project]
name = "ryuu-providers"
version = "0.2.0a1"
dependencies = [
    "ryuu-core>=0.2.0a1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
openai = ["openai>=1.0"]
anthropic = ["anthropic>=0.30"]
all = ["openai>=1.0", "anthropic>=0.30"]
```

## 7. Phase Breakdown (tasks in todo-phase8-3-ryuu-providers.md)

### 8.3.A — Skeleton + RED Tests
T01: Package directory skeleton  
T02: RED tests for `ryuu_providers.llm` + `ryuu_providers.circuit_breaker`  
T03: RED tests for `ryuu_providers.fallback` + `ryuu_providers.router`  
T04: RED tests for `ryuu_providers._pricing`  

### 8.3.B — Build ryuu-providers (GREEN)
T05: Copy + rewrite `circuit_breaker.py` + `llm.py` (zero external deps)  
T06: Copy + rewrite `fallback.py` + `router.py` (dep on llm + circuit_breaker)  
T07: Copy + rewrite `_pricing.py` + copy `pricing.yaml`  
T08: Copy + rewrite `adapters/anthropic.py` + `adapters/openai.py`  
T09: Write `ryuu_providers/__init__.py` with curated re-exports  
T10: Fill `pyproject.toml`; build wheel; verify  

### 8.3.C — Wire ryuu → ryuu-providers (shims)
T11: Root `pyproject.toml`: add `ryuu-providers>=0.2.0a1` dep  
T12: Replace `ryuu/providers/*.py` with shims  
T13: Replace `ryuu/observability/_pricing.py` with shim  
T14: Full pytest gate (637+ GREEN)  

### 8.3.D — Isolation + CI + Docs
T15: Write `scripts/test-providers-isolation.sh`  
T16: Update `.github/workflows/ci.yml`: add `providers-isolation` job  
T17: Update `packages/MIGRATION.md` Phase 8.3 section  
T18: Update `CHANGELOG.md`  
T19: Update memory + MEMORY.md index  
