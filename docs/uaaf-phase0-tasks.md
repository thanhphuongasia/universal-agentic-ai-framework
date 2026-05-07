# UAAF — Phase 0 (Foundation) — Task Breakdown

> Output của planning skill cho Phase 0. Mỗi task discrete, có acceptance + verification + files touched. Ordered by dependency.
>
> **Phase 0 goal**: bootstrapped `uaaf-framework` repo có thể `pip install -e .` và wrap 1 LLM call qua `BaseAgent` với full cross-cutting (cost + trace + audit + retry tier). Đây là smoke test cho Phase 1.

**Status**: Ready for review
**Last Updated**: 2026-05-07
**Estimated**: ~5-7 working days (1 dev focus, hoặc 2 dev parallel cho task song song)
**Predecessors**: Spec `uaaf-framework-spec.md`, ADR 005

---

## Task graph

```
T01 Repo bootstrap ─────┐
                        │
                        ├─→ T02 Errors tier ──┐
                        │                      │
                        ├─→ T03 Tracer ────────┤
                        │                      │
                        ├─→ T04 CostTracker ───┤
                        │                      ├──→ T08 BaseAgent ──→ T13 Smoke test
                        ├─→ T05 AuditLogger ───┤                          ▲
                        │                      │                          │
                        └─→ T06 RateLimiter ───┘                          │
                                                                          │
                        ┌─→ T07 ILLMProvider Protocol ─→ T09 OpenAIAdapter
                        │                              ─→ T10 AnthropicAdapter
                        │                                                  │
                        ├─→ T11 SandboxManager v0.1 ──────────────────────┤
                        │                                                  │
                        └─→ T12 Test utilities (FakeLLMProvider) ─────────┘

(T01 enables all; T08 needs T02-T06; T13 needs T08+T09+T12)
```

**Parallelization**: T02-T06 độc lập sau T01 → 2 dev có thể chia. T09 + T10 độc lập sau T07.

---

## T01. Repo bootstrap

**Description**: Tạo private GitHub repo `uaaf-framework`, config Python project + CI + license + contribution guide. Chuẩn bị OSS-ready từ đầu.

**Acceptance**:
- Repo public/private trên GitHub (private trong dev, public trước v1.0).
- `pip install -e ".[dev]"` thành công, import `uaaf` không error.
- `pytest` chạy được (kể cả 0 test).
- `ruff check uaaf/` và `mypy uaaf/` chạy được.
- CI workflow GitHub Actions: lint + type + test + build wheel — pass trên empty test suite.
- README có install instructions + 1-paragraph project description.
- LICENSE = Apache 2.0.
- CONTRIBUTING.md skeleton (có thể minimal).

**Verify**:
```bash
git clone <uaaf-framework>
cd uaaf-framework
pip install -e ".[dev]"
python -c "import uaaf; print(uaaf.__version__)"     # → 0.1.0a1
pytest
ruff check uaaf/
mypy uaaf/
```

**Files**:
- `uaaf-framework/pyproject.toml`
- `uaaf-framework/uaaf/__init__.py` (exports `__version__`)
- `uaaf-framework/uaaf/_internal/__init__.py`
- `uaaf-framework/tests/__init__.py`
- `uaaf-framework/README.md`
- `uaaf-framework/LICENSE`
- `uaaf-framework/CONTRIBUTING.md`
- `uaaf-framework/.github/workflows/ci.yml`
- `uaaf-framework/.gitignore`
- `uaaf-framework/CHANGELOG.md`

**Effort**: 0.5 day
**Depends on**: nothing
**Risk**: low

---

## T02. Errors tier (`uaaf.observability.errors`)

**Description**: Define exception tier — `RetryableError`, `DegradedError`, `FatalError` — với retry policy mặc định. Replace pattern `try/except: pass` của codebase Code Analysis hiện tại.

**Acceptance**:
- 3 exception class: `RetryableError`, `DegradedError`, `FatalError`. All extend `FrameworkError(Exception)`.
- `retry_policy(exc) -> RetryDecision` function: classify exception → decision (retry với backoff / degraded fallback / fatal raise).
- `RetryDecision` dataclass: `should_retry: bool`, `wait_seconds: float | None`, `tier: Literal['retryable','degraded','fatal']`.
- Default backoff: exponential với jitter (0.5s, 1s, 2s, 4s, max 30s).
- Helper `classify_external_error(exc)` adapt từ OpenAI/Anthropic SDK errors → đúng tier.

**Verify**:
```bash
pytest tests/unit/observability/test_errors.py -v
# > 8 test pass: tier classification, retry decision, backoff math, jitter bounds
```

**Files**:
- `uaaf/observability/errors.py`
- `tests/unit/observability/test_errors.py`

**Effort**: 0.5 day
**Depends on**: T01
**Risk**: low — straightforward implementation

---

## T03. Tracer (`uaaf.observability.tracer`)

**Description**: OpenTelemetry-backed tracer với correlation_id propagation. Replace ad-hoc `event_callback` pattern của Code Analysis chat.

**Acceptance**:
- `Tracer.span(name, **attrs)` returns async context manager (qua `anyio`).
- Mỗi span có correlation_id (auto-gen UUID nếu không pass).
- `get_current_correlation_id()` đọc từ context var.
- Default exporter: console (logs to stderr với JSON format).
- Configurable exporter: OTLP gRPC, OTLP HTTP, Jaeger (qua `setup_tracing(target='otlp://...')`).
- Spans nested: parent-child relationship đúng khi nested với nhau.

**Verify**:
```bash
pytest tests/unit/observability/test_tracer.py -v
# > 6 test: span enter/exit, correlation_id propagation, nesting, exporter switch
```

**Files**:
- `uaaf/observability/tracer.py`
- `tests/unit/observability/test_tracer.py`

**Effort**: 1 day
**Depends on**: T01
**Risk**: medium — OTel API có thể trickier với async context

---

## T04. CostTracker (`uaaf.observability.cost`)

**Description**: Track LLM token cost per scope (user_id / session_id / domain). Hard cap enforcement.

**Acceptance**:
- `Cost` dataclass: `input_tokens`, `output_tokens`, `usd`, `provider`, `model`.
- `CostPolicy` dataclass: budget per scope (per-user-per-day, per-domain-per-month, …).
- `CostTracker.record(scope, cost)` — accumulate.
- `CostTracker.enforce(scope, estimated_cost)` — raise `BudgetExceededError` (extends `DegradedError`) nếu vượt cap.
- `CostTracker.get_usage(scope)` returns `UsageSnapshot`.
- v0 storage: in-memory với optional persistent backend protocol (`ICostStore` để Phase 5 implement Postgres/Redis).
- Pricing table cho OpenAI / Anthropic models hardcoded (overridable qua config).

**Verify**:
```bash
pytest tests/unit/observability/test_cost.py -v
# > 10 test: record, enforce, snapshot, multi-scope isolation, cap edge cases
```

**Files**:
- `uaaf/observability/cost.py`
- `uaaf/observability/_pricing.py` (pricing table)
- `tests/unit/observability/test_cost.py`

**Effort**: 1 day
**Depends on**: T01, T02 (uses `DegradedError`)
**Risk**: medium — pricing table cần update khi providers đổi giá

---

## T05. AuditLogger (`uaaf.observability.audit`)

**Description**: Immutable structured log cho compliance (Stock trading 7y retention). Append-only.

**Acceptance**:
- `AuditLogger.log_start(task, ctx)`, `log_complete(task, result)`, `log_error(task, exc)`.
- Mỗi event có: timestamp UTC, correlation_id, scope, agent_id, event_type, payload, hash_of_payload.
- v0 backend: JSONL file append-only + console.
- `IAuditStore` Protocol cho Phase 5 implement S3/Postgres backend.
- Hash chain: mỗi event hash includes previous hash → immutability detection.
- Configurable retention period qua `AuditConfig`.

**Verify**:
```bash
pytest tests/unit/observability/test_audit.py -v
# > 8 test: event format, hash chain integrity, tamper detection, scope isolation
```

**Files**:
- `uaaf/observability/audit.py`
- `tests/unit/observability/test_audit.py`

**Effort**: 1 day
**Depends on**: T01
**Risk**: medium — hash chain logic phải đúng cho compliance

---

## T06. RateLimiter (`uaaf.observability.rate_limit`)

**Description**: Token-bucket rate limit per scope + per provider.

**Acceptance**:
- `RateLimiter.acquire(scope, agent_id)` — async, block tới khi có quota.
- `RatePolicy` dataclass: rps + burst per scope, per provider.
- v0 backend: in-memory token bucket.
- `IRateStore` Protocol cho Phase 5 distributed (Redis-based).
- Async-friendly: dùng `anyio.Event` thay vì busy-wait.
- Timeout configurable: `acquire(timeout=5.0)` raise `RateLimitTimeout` (extends `DegradedError`).

**Verify**:
```bash
pytest tests/unit/observability/test_rate_limit.py -v
# > 7 test: bucket refill, burst handling, multi-scope, timeout, fairness
```

**Files**:
- `uaaf/observability/rate_limit.py`
- `tests/unit/observability/test_rate_limit.py`

**Effort**: 1 day
**Depends on**: T01, T02
**Risk**: medium — async timing tests có thể flaky

---

## T07. ILLMProvider Protocol (`uaaf.providers.llm`)

**Description**: Protocol cho LLM provider. Define common interface trước khi viết adapters.

**Acceptance**:
- `ILLMProvider` Protocol: `provider_id`, `complete()`, `stream()`, `embed()`, `estimate_cost()`.
- `Response`, `StreamChunk`, `Embedding`, `CompletionRequest` dataclass.
- `CompletionRequest` có: messages, model, max_tokens, temperature, response_schema (cho structured output), tools.
- Async interface qua `anyio` (không asyncio trực tiếp).
- Contract test suite parametric — mọi adapter implement Protocol phải pass.

**Verify**:
```bash
pytest tests/contract/test_llm_provider_contract.py -v
# > 4 test sẽ chạy cho mỗi adapter ở T09, T10, T12 (FakeLLMProvider)
```

**Files**:
- `uaaf/providers/llm.py` (Protocol + dataclass)
- `uaaf/providers/__init__.py`
- `tests/contract/test_llm_provider_contract.py`

**Effort**: 0.5 day
**Depends on**: T01
**Risk**: low — chỉ design, không implement

---

## T08. BaseAgent template method (`uaaf.execution.agent`)

**Description**: Abstract class với template `execute()` ép cross-cutting (tracer, cost, audit, rate limit, error handling). Subclass chỉ implement `_execute()`.

**Acceptance**:
- `BaseAgent(ABC)` với abstract `_execute(task, ctx)` và concrete `execute(task, ctx)` template.
- `execute()` flow:
  1. `tracer.span(agent_id, task_id, ctx.correlation_id)`
  2. `rate_limiter.acquire(scope)`
  3. `cost_tracker.enforce(scope, estimated)` (raise DegradedError nếu over budget)
  4. `audit_logger.log_start`
  5. try → `_execute()` → `cost_tracker.record` + `audit_logger.log_complete`
  6. except RetryableError → re-raise (caller retry)
  7. except DegradedError → log + re-raise (caller fallback)
  8. except Exception → `audit_logger.log_error` + re-raise as FatalError
- Lint rule trong `pyproject.toml` cấm subclass override `execute()` (chỉ check tên — không phải runtime enforce).
- Documentation comment cảnh báo override.

**Verify**:
```bash
pytest tests/unit/execution/test_agent.py -v
# > 12 test: cross-cutting injection, error tier handling, span nesting, audit completeness
```

**Files**:
- `uaaf/execution/agent.py`
- `uaaf/execution/__init__.py`
- `tests/unit/execution/test_agent.py`

**Effort**: 1 day
**Depends on**: T02, T03, T04, T05, T06
**Risk**: high — đây là class foundation, bug ở đây propagate khắp framework

---

## T09. OpenAIProvider adapter (`uaaf.providers.adapters.openai`)

**Description**: Implement `ILLMProvider` qua OpenAI SDK. Adapt từ `src/llm/openai_adapter.py` hiện tại.

**Acceptance**:
- `OpenAIProvider(ILLMProvider)` implement đầy đủ.
- Async-only (qua `AsyncOpenAI` client wrap với `anyio`).
- Structured output qua `response_format` JSON schema.
- Token usage parse → `Cost` object qua pricing table.
- Error mapping: OpenAI `RateLimitError` → `RetryableError`, `BadRequestError` (transient 400 server bug) → `RetryableError`, `AuthenticationError` → `FatalError`, etc.
- Contract test ở T07 pass.

**Verify**:
```bash
pytest tests/unit/providers/test_openai.py -v
pytest tests/contract/test_llm_provider_contract.py::test_openai -v
```

**Files**:
- `uaaf/providers/adapters/openai.py`
- `tests/unit/providers/test_openai.py`

**Effort**: 0.5 day
**Depends on**: T07
**Risk**: low — đã có code reference từ Code Analysis

---

## T10. AnthropicProvider adapter (`uaaf.providers.adapters.anthropic`)

**Description**: Implement `ILLMProvider` qua Anthropic SDK. Adapt từ `src/llm/anthropic_adapter.py`.

**Acceptance**:
- `AnthropicProvider(ILLMProvider)` implement đầy đủ.
- Async (Anthropic SDK có async client).
- Structured output qua tool use pattern (Anthropic không có direct JSON mode).
- Error mapping → đúng tier.
- Contract test ở T07 pass.

**Verify**:
```bash
pytest tests/unit/providers/test_anthropic.py -v
pytest tests/contract/test_llm_provider_contract.py::test_anthropic -v
```

**Files**:
- `uaaf/providers/adapters/anthropic.py`
- `tests/unit/providers/test_anthropic.py`

**Effort**: 0.5 day
**Depends on**: T07
**Risk**: low — đã có code reference

---

## T11. SandboxManager v0.1 (`uaaf.execution.sandbox`)

**Description**: Subprocess-based sandbox với resource limits. Foundation cho AI coding practice + Stock paper trading. KHÔNG phải production-grade isolation (đó là Phase 3+ với container).

**Acceptance**:
- `SandboxManager.run(command, args, timeout, memory_limit_mb, cpu_seconds)` returns `SandboxResult`.
- Subprocess spawn với `resource.setrlimit` cho memory + CPU.
- Hard timeout enforce (kill nếu vượt).
- Stdin/stdout/stderr capture.
- `ISandbox` Protocol để Phase 3+ swap container backend.
- v0 KHÔNG promise full security isolation — doc rõ "subprocess-level only, not for untrusted code in v0.1".
- Default deny network (qua subprocess env scrub).

**Verify**:
```bash
pytest tests/unit/execution/test_sandbox.py -v
# > 8 test: timeout, memory limit, CPU limit, fork bomb resistance, output capture
```

**Files**:
- `uaaf/execution/sandbox.py`
- `tests/unit/execution/test_sandbox.py`

**Effort**: 1 day
**Depends on**: T01, T02
**Risk**: medium — resource limits POSIX-specific (Linux/macOS); Windows skip với explicit error

---

## T12. Test utilities (`uaaf._testing`)

**Description**: Public test fixtures + fakes cho product team test domain plugins KHÔNG cần real LLM/network.

**Acceptance**:
- `FakeLLMProvider(ILLMProvider)`: configurable response per call, count assertions.
- `fake_runtime(...)`: tạo UAAFRuntime minimal cho integration test.
- `pytest` fixtures: `tracer_fixture`, `cost_tracker_fixture`, `audit_fixture` — pre-configured cho test.
- Re-export public symbols ở `uaaf._testing.__init__`.

**Verify**:
```bash
pytest tests/unit/_testing/test_fakes.py -v
# > 6 test: FakeLLMProvider behavior, fixture composition
```

**Files**:
- `uaaf/_testing/__init__.py`
- `uaaf/_testing/fakes.py`
- `uaaf/_testing/fixtures.py`
- `tests/unit/_testing/test_fakes.py`

**Effort**: 0.5 day
**Depends on**: T07
**Risk**: low

---

## T13. Smoke test — minimal LLMAgent end-to-end

**Description**: Integration test chứng minh Phase 0 hoạt động: 1 LLMAgent qua BaseAgent với full cross-cutting, dùng FakeLLMProvider.

**Acceptance**:
- Test viết một `EchoLLMAgent(BaseAgent)` minimal: `_execute` gọi LLM, return result.
- Run test verify:
  1. Span được tạo với correlation_id.
  2. Audit log có start + complete event.
  3. Cost được record với đúng tokens.
  4. Rate limit được consume.
  5. Khi FakeLLMProvider raise RateLimitError → agent re-raise RetryableError đúng tier.
  6. Khi over budget → DegradedError raised trước khi gọi LLM.
- Test này serve làm canonical example trong README + docs.

**Verify**:
```bash
pytest tests/integration/test_phase0_smoke.py -v
# > 6 test cases pass
```

**Files**:
- `tests/integration/test_phase0_smoke.py`
- `examples/_phase0_smoke/main.py` (optional: standalone runnable)

**Effort**: 0.5 day
**Depends on**: T08, T09 (hoặc dùng FakeLLMProvider từ T12), T12
**Risk**: low — nếu fail → bug ở T08

---

## Cross-task gates

Cuối Phase 0, ALL phải pass trước khi proceed Phase 1:

- [x] CI gate: `ruff check && mypy uaaf && pytest --cov=uaaf` — coverage ≥85% (87.18%, 2026-05-07)
- [x] All 13 task acceptance criteria pass
- [x] T13 smoke test green
- [x] CHANGELOG.md có v0.1.0a1 entry
- [ ] User review code + approve merge to `main`
- [ ] Tag v0.1.0a1 (alpha — chưa publish PyPI)

---

## Estimated timeline

| Day | Tasks (1 dev) | Tasks (2 dev parallel) |
|---|---|---|
| 1 | T01 + T02 | Dev A: T01 + T02 / Dev B: chờ T01 |
| 2 | T03 + T04 | A: T03 + T04 / B: T05 + T06 |
| 3 | T05 + T06 | A: T07 + T11 / B: T09 + T10 |
| 4 | T07 + T11 | A: T08 / B: T12 |
| 5 | T08 + T12 | A+B: T13 + buffer |
| 6 | T09 + T10 | (done early) |
| 7 | T13 + buffer | — |

**Single dev focus**: ~7 days
**Two dev parallel**: ~5 days
**With ad-hoc interruption**: +2 days buffer realistic

---

## Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OTel async context propagation gotcha (T03) | Medium | High | Test sớm với nested spans across `anyio.create_task_group()`; có sample code reference từ OTel Python docs |
| Sandbox không isolate đủ trên macOS dev machine (T11) | Medium | Medium | Doc rõ "Linux production target"; CI test trên Ubuntu |
| BaseAgent template "leaky abstraction" — subclass cần custom flow (T08) | High | High | Doc rõ "DON'T override execute()". Nếu thật sự cần custom flow → tạo strategy plugin, không subclass agent |
| Cross-repo dev workflow chậm (Code Analysis test cần `pip install -e ../uaaf-framework` mỗi đổi) | Medium | Low | Doc workflow trong CONTRIBUTING.md; setup `pre-commit` để auto-reinstall |
| Pricing table outdated (T04) | Low | Medium | Comment rõ "as of YYYY-MM"; có CI job alert nếu provider release new model |
| User reject ADR/spec sau Phase 0 task #5 → rework | Low | High | Phase gate review TRƯỚC khi T01 — đây là điều đang chờ |

---

## Out of scope cho Phase 0

KHÔNG làm trong Phase 0 (move sang Phase 1+):

- IntentAnalyzer / StructuredIntent — Phase 1
- ICognitiveStrategy + strategies — Phase 1
- IVerifier + verifier pipeline — Phase 2
- IKnowledgeBackbone — Phase 3
- ModelRouter (chọn provider theo intent×complexity) — Phase 4
- Container-based sandbox — Phase 3+ (subprocess đủ cho v0.1)
- Multi-tenancy (`tenant_id` in scope) — chưa quyết định, Phase 1 review
- Streaming SSE/WebSocket — Phase 1 (cần khi build Code Analysis chat)
- Distributed cost/rate (Redis backend) — Phase 5 khi Stock production

---

## Approval

Phase 0 ready để start khi:

- [x] Spec approved
- [x] ADR 005 approved
- [ ] Phase 0 task breakdown (file này) approved by user
- [ ] Repo `uaaf-framework` private được tạo trên GitHub

→ Sau khi 4/4: bắt đầu T01.
