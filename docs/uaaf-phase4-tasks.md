# UAAF — Phase 4 (Provider Router + Circuit Breaker) — Task Breakdown

> Phase 4 goal: `ModelRouter` (routing matrix: intent_type × complexity → ILLMProvider) + `CircuitBreaker` (failure counting, half-open recovery) + `ProviderFallbackChain` (tries providers in order). Strategies can route through `ModelRouter` instead of receiving a hard-coded provider.

**Status**: In progress
**Last Updated**: 2026-05-07
**Predecessors**: Phase 3 complete (v0.1.0b3)

---

## Task graph

```
P4-T01 CircuitBreaker (uaaf/providers/circuit_breaker.py)
         │
P4-T02 RoutingKey + RoutingMatrix models (uaaf/providers/router.py)
         │
P4-T03 ModelRouter — wraps ILLMProvider + CircuitBreaker (uaaf/providers/router.py)
         │
P4-T04 ProviderFallbackChain (uaaf/providers/fallback.py)
         │
P4-T05 Tests (unit + contract + integration)
         │
P4-T06 CI gate
```

---

## P4-T01. CircuitBreaker (`uaaf/providers/circuit_breaker.py`)

**Acceptance**:
- `CircuitState(StrEnum)`: `CLOSED = "closed"`, `OPEN = "open"`, `HALF_OPEN = "half_open"`
- `CircuitBreaker(failure_threshold: int = 5, recovery_timeout: float = 60.0)`
  - `failure_threshold`: how many consecutive failures trigger OPEN
  - `recovery_timeout`: seconds to wait before trying HALF_OPEN
- Methods:
  - `record_success() -> None` — resets failure count; HALF_OPEN → CLOSED
  - `record_failure() -> None` — increments count; at threshold → OPEN
  - `is_available() -> bool` — False if OPEN and recovery_timeout not elapsed; True otherwise; OPEN→HALF_OPEN after timeout
  - `state: CircuitState` property
- Thread-safe via `threading.Lock`

**Files**: `uaaf/providers/circuit_breaker.py`

---

## P4-T02 + P4-T03. ModelRouter (`uaaf/providers/router.py`)

**Acceptance**:
- `RoutingKey` frozen dataclass: `model_tier: ModelTier`
- `ModelRouter(providers: dict[ModelTier, ILLMProvider], fallback: ILLMProvider | None = None)`
  - `provider_id = "router"`
  - Fully implements `ILLMProvider` Protocol (complete, stream, embed, estimate_cost)
  - `route(model_tier: ModelTier) -> ILLMProvider`:
    - Looks up `providers[model_tier]`; if circuit is OPEN or key missing → fallback (if configured) else raises `DegradedError`
  - Each provider gets its own `CircuitBreaker`
  - `complete(request)`: uses `request.model` to determine tier (via `_model_to_tier()`); falls back if circuit open
  - `record_failure(provider_id: str) -> None`
  - `_model_to_tier(model: str) -> ModelTier`:
    - contains "mini" or "haiku" → `CHEAP`
    - contains "opus" → `POWERFUL`
    - default → `STANDARD`

**Files**: `uaaf/providers/router.py`

---

## P4-T04. ProviderFallbackChain (`uaaf/providers/fallback.py`)

**Acceptance**:
- `ProviderFallbackChain(providers: list[ILLMProvider])`
  - `provider_id = "fallback_chain"`
  - Fully implements `ILLMProvider`
  - `complete(request)`: tries providers in order; on `DegradedError` or `RetryableError` from provider → try next; if all fail → raise `DegradedError("All providers failed")`
  - `estimate_cost`: returns estimate from first provider

**Files**: `uaaf/providers/fallback.py`

---

## P4-T05. Tests

**Unit tests**:
- `tests/unit/providers/test_circuit_breaker.py`
- `tests/unit/providers/test_model_router.py`
- `tests/unit/providers/test_fallback_chain.py`

**Contract test**:
- `tests/contract/test_provider_contract.py` — parametrized over ModelRouter + ProviderFallbackChain (both implement ILLMProvider)

**Integration**:
- `tests/integration/test_phase4_smoke.py` — ModelRouter + CircuitBreaker end-to-end (primary fails → fallback)

---

## P4-T06. CI gate

- [ ] `ruff check uaaf/ tests/` → 0 violations
- [ ] `mypy uaaf/ --ignore-missing-imports` → 0 errors
- [ ] `pytest --cov=uaaf` → coverage ≥85%
- [ ] User review + approve
- [ ] Tag v0.1.0b4

---

## Cross-task gates

- [ ] CI gate green
- [ ] ModelRouter + FallbackChain pass ILLMProvider contract test
- [ ] CHANGELOG v0.1.0b4 entry
- [ ] `_model_to_tier()` logic matches ModelTier enum values from Phase 1
