# Phase 8.3 — ryuu-providers: Standalone LLM Provider Package — TODO

> **Approach**: TDD — RED tests trước, implement GREEN, backward-compat qua shims trong `ryuu/providers/`.  
> **Pattern**: Giống Phase 8.2 (ryuu-core).  
> See `plan-phase8-3-ryuu-providers.md` for full context.

---

## Phase 8.3.A — Skeleton + Tests RED

- [x] **T01** Create `packages/ryuu-providers/{src/ryuu_providers/adapters/, pyproject.toml, README.md, LICENSE}` skeleton
- [x] **T02** Write `tests/unit/providers_pkg/test_providers_llm.py` (RED — `from ryuu_providers.llm import ...`)
- [x] **T03** Write `tests/unit/providers_pkg/test_providers_fallback_router.py` (RED)
- [x] **T04** Write `tests/unit/providers_pkg/test_providers_pricing.py` (RED)

---

## Phase 8.3.B — Implement ryuu-providers (GREEN)

- [x] **T05** Copy + rewrite `circuit_breaker.py` + `llm.py` → `ryuu_providers/`
- [x] **T06** Copy + rewrite `fallback.py` + `router.py` → `ryuu_providers/`
- [x] **T07** Copy `_pricing.py` + `pricing.yaml` → `ryuu_providers/`; rewrite internal imports
- [x] **T08** Copy + rewrite `adapters/anthropic.py` + `adapters/openai.py` → `ryuu_providers/adapters/`
- [x] **T09** Write `ryuu_providers/__init__.py` with curated re-exports
- [x] **T10** Fill `pyproject.toml`: deps + optional extras; build wheel; verify contents

---

## Phase 8.3.C — Wire ryuu → ryuu-providers (shims)

- [x] **T11** Root `pyproject.toml`: add `ryuu-providers>=0.2.0a1` dep
- [x] **T12** Replace `ryuu/providers/*.py` + `ryuu/providers/adapters/*.py` with backward-compat shims
- [x] **T13** Replace `ryuu/observability/_pricing.py` with backward-compat shim (re-export from `ryuu_providers._pricing`)
- [x] **T14** Full pytest gate: all existing tests still GREEN (637+)

---

## Phase 8.3.D — Isolation + CI + Docs

- [x] **T15** Write `scripts/test-providers-isolation.sh` (fresh venv, install ryuu-providers only, run smoke test, assert `import ryuu` fails)
- [x] **T16** Update `.github/workflows/ci.yml`: add `providers-isolation` job
- [x] **T17** Update `packages/MIGRATION.md` Phase 8.3 section
- [x] **T18** Update `CHANGELOG.md` v0.2.0a1 with Phase 8.3 changes
- [x] **T19** Update memory + MEMORY.md index

---

## Quick reference — new import paths (canonical)

```
ryuu_providers.llm              →  ILLMProvider, CompletionRequest, Response, Message, ...
ryuu_providers.circuit_breaker  →  CircuitBreaker, CircuitState
ryuu_providers.fallback         →  ProviderFallbackChain
ryuu_providers.router           →  ModelRouter
ryuu_providers.adapters.openai  →  OpenAIProvider
ryuu_providers.adapters.anthropic → AnthropicProvider
ryuu_providers._pricing         →  calculate_usd, PRICING, CONTEXT_WINDOW, reload_pricing

# Backward-compat (still works via shims):
ryuu.providers.llm              →  shim → ryuu_providers.llm
ryuu.providers.router           →  shim → ryuu_providers.router
ryuu.providers.fallback         →  shim → ryuu_providers.fallback
ryuu.providers.circuit_breaker  →  shim → ryuu_providers.circuit_breaker
ryuu.providers.adapters.openai  →  shim → ryuu_providers.adapters.openai
ryuu.providers.adapters.anthropic → shim → ryuu_providers.adapters.anthropic
ryuu.observability._pricing     →  shim → ryuu_providers._pricing
```
