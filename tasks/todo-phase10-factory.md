# Phase 10 — Factory `Agent()` MVP — Task Breakdown

> **Date**: 2026-05-21
> **Plan**: `tasks/plan-phase10-factory.md`
> **Strategy**: Option A — DX-first. MVP ship Tuần 2 (sau Audit 8.8).
> **Style**: Incremental — mỗi task verify pass trước khi sang task kế.

## Phase 8.8 Prerequisite (Tuần 1) — Audit Async Non-blocking

- [ ] **T0.1** Đọc `packages/ryuu-observability/src/ryuu_observability/{cost,audit,tracer,rate_limit}.py` — note sync vs async calls
- [ ] **T0.2** Viết stress test: `tests/perf/test_observability_concurrency.py` — 1000 concurrent `agent.execute()` với full cross-cutting
- [ ] **T0.3** Đo p50/p99 latency với + không có cross-cutting; threshold overhead < 5ms p99
- [ ] **T0.4** Nếu fail: fix với `aiofiles`, `anyio.Semaphore`, background queue
- [ ] **T0.5** Document async contract vào `packages/ryuu-observability/README.md` + interface docstring
- [ ] **T0.6** Update `docs/architecture/uaaf-v2-architecture.md` §7.6 với verified numbers

**Exit criteria**: Stress test pass, overhead < 5ms p99, doc updated.

---

## Phase 10 MVP (Tuần 2) — 7 Tasks

### T1 — Scaffold `packages/ryuu/`

- [ ] **T1.1** Tạo folder `packages/ryuu/` với `pyproject.toml`, `README.md`, `LICENSE`, `src/ryuu/__init__.py`
- [ ] **T1.2** `pyproject.toml` dependencies: `ryuu-core`, `ryuu-execution`, `ryuu-providers`, `ryuu-observability` (KHÔNG kéo guardrail/cognitive/knowledge — MVP không cần)
- [ ] **T1.3** `pip install -e packages/ryuu/` thành công, `python -c "import ryuu"` không lỗi
- [ ] **T1.4** Thêm `packages/ryuu/` vào root `pyproject.toml` workspace
- [ ] **T1.5** Update CI: `scripts/test-ryuu-isolation.sh` — chạy `pip install ryuu` trong venv mới + verify import

**Exit criteria**: `pip install ryuu` works in fresh venv. Empty `ryuu` package importable.

---

### T2 — Write Tests RED (TDD)

- [ ] **T2.1** Tạo `tests/unit/ryuu/__init__.py`
- [ ] **T2.2** `test_factory_basic.py` — 4 test cases (smoke, null defaults, validation errors)
- [ ] **T2.3** `test_factory_provider_detect.py` — 6 cases (auto-detect gpt-/claude-/o1-, explicit prefix, unknown raises)
- [ ] **T2.4** `test_factory_tools.py` — 6 cases (schema từ str/int/float/bool/list/dict, required vs optional, docstring extraction)
- [ ] **T2.5** `test_factory_cross_cutting.py` — 10 cases (5 toggles × 2: off=Null / on=Real — gồm `verbose`)
- [ ] **T2.6** `test_factory_limits.py` — 4 cases (max_tokens forwarded to request, temperature default 0.7, max_iterations=1 raises MaxIterationsExceededError, validation errors for negative)
- [ ] **T2.7** `test_factory_run.py` — 5 cases (FakeLLMProvider single call, tool call, error, scope wiring, multi-turn)
- [ ] **T2.8** Chạy `pytest tests/unit/ryuu/` — confirm ALL RED (37 fail vì chưa implement)

**Exit criteria**: 37 tests RED. Diff committed làm baseline.

---

### T3 — Implement `_provider_detect.py`

- [ ] **T3.1** Viết `packages/ryuu/src/ryuu/_provider_detect.py` với `build_provider(model, api_key) -> ILLMProvider`
- [ ] **T3.2** Cover formats: `"gpt-4o"`, `"openai:gpt-4o"`, `"anthropic:claude-sonnet-4"`, `"o1-preview"`, `"o3-mini"`
- [ ] **T3.3** Raise `ValueError` cho unknown model không có prefix
- [ ] **T3.4** Env var fallback: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
- [ ] **T3.5** Chạy `pytest tests/unit/ryuu/test_factory_provider_detect.py` → 6 GREEN

**Exit criteria**: 6/6 provider detect tests pass.

---

### T4 — Implement `_tool_introspect.py`

- [ ] **T4.1** Viết `build_tool_schema(fn: Callable) -> dict` — extract name, description từ docstring, parameters từ type hints
- [ ] **T4.2** Type mapping: `str/int/float/bool` → primitive JSON types
- [ ] **T4.3** Type mapping: `list/dict` → array/object
- [ ] **T4.4** Required detection: params không có default → required
- [ ] **T4.5** Edge case: callable không docstring → warn log, description=""
- [ ] **T4.6** Chạy `pytest tests/unit/ryuu/test_factory_tools.py` → 6 GREEN

**Exit criteria**: 6/6 tool schema tests pass. Edge case `Optional[T]`, `list[T]` deferred to Phase 10.x.

---

### T5 — Implement `factory.py` Core

- [ ] **T5.1** Viết `Agent` dataclass với fields: `model`, `instructions`, `tools`, `max_tokens`, `temperature`, `max_iterations`, `budget_usd`, `rate_limit_rps`, `audit`, `trace`, `api_key`
- [ ] **T5.2** `__post_init__()` validation: model required, budget/rate positive, `max_tokens > 0` if set, `max_iterations >= 1`, `0 <= temperature <= 2`
- [ ] **T5.3** `_build_provider()` delegate sang `_provider_detect.build_provider()`
- [ ] **T5.4** `_build_tool_registry()` loop callables → `ToolRegistry.register()` với schema từ introspect
- [ ] **T5.5** `_build_cross_cutting()` return tuple `(cost, rate, audit, tracer)` — Null defaults / Real khi set
- [ ] **T5.6** Build `_FactoryLLMAgent` internal class extends `LLMAgent` với `system_prompt` + `max_tokens` + `temperature` fields
- [ ] **T5.7** Wire cross-cutting + per-call limits (max_tokens/temperature) vào agent constructor → forward sang `CompletionRequest`
- [ ] **T5.8** Wire `max_iterations` vào `_react_loop(max_rounds=self.max_iterations)`
- [ ] **T5.9** Chạy `pytest tests/unit/ryuu/test_factory_basic.py test_factory_cross_cutting.py test_factory_limits.py` → 18 GREEN

**Exit criteria**: 18/18 (4 basic + 10 cross-cutting incl. verbose + 4 limits) pass.

---

### T6 — Implement `.run()` Method

- [ ] **T6.1** Viết `_scope_builder.build_scope(**kwargs) -> ContextScope` — defaults: user_id="anonymous", session_id=uuid, domain="default"
- [ ] **T6.2** Viết `Agent.run(message, **scope) -> AgentResult` — build Task + ExecutionContext + delegate sang `self._agent.execute()`
- [ ] **T6.3** Generate `correlation_id` mỗi call (uuid)
- [ ] **T6.4** Pack `message` vào `Task.payload["query"]`
- [ ] **T6.5** Chạy `pytest tests/unit/ryuu/test_factory_run.py` → 5 GREEN

**Exit criteria**: 5/5 run tests pass với FakeLLMProvider.

---

### T7 — Re-export + Integration Test

- [ ] **T7.1** `packages/ryuu/src/ryuu/__init__.py` re-export `Agent`
- [ ] **T7.2** `from ryuu import Agent` hoạt động
- [ ] **T7.3** Viết `tests/integration/ryuu/test_factory_openai.py` — 2 cases (single call, tool call) — SKIP nếu không có `OPENAI_API_KEY`
- [ ] **T7.4** Manual run với key: `OPENAI_API_KEY=sk-... pytest tests/integration/ryuu/`
- [ ] **T7.5** Verify cost reporting reasonable (`< $0.01`/call cho gpt-4o-mini)

**Exit criteria**: 31 unit + 2 integration GREEN (hoặc skipped nếu no key).

---

### T8 — Example + Docs

- [ ] **T8.1** Tạo `examples/factory_quickstart/__init__.py`
- [ ] **T8.2** Viết `examples/factory_quickstart/chatbot.py` — Mode 1 inline, ~20 dòng
- [ ] **T8.3** Viết `examples/factory_quickstart/tool_calling.py` — 2 tools inline, ~30 dòng
- [ ] **T8.4** Viết `examples/factory_quickstart/production.py` — full cross-cutting bật, ~40 dòng
- [ ] **T8.5** Verify cả 3 example chạy với key thật
- [ ] **T8.6** Update `docs/guides/quickstart.md` §1.1-1.5 — đổi status `🔲` → `✅` cho Mode 1
- [ ] **T8.7** Update `docs/guides/quickstart.md` §5.16 — Mode 1 + Mode A status `✅`, các mode còn lại vẫn `🔲 Phase 10.x`
- [ ] **T8.8** Update root `README.md` — thay quick start example sang Factory
- [ ] **T8.9** CHANGELOG entry: "Phase 10 MVP — Factory `Agent()` single-agent inline mode"

**Exit criteria**: 3 example chạy, docs reflect actual capability.

---

### T9 — Release Prep

- [ ] **T9.1** Bump version `packages/ryuu/pyproject.toml` → `0.3.0a1`
- [ ] **T9.2** `python -m build packages/ryuu/` produces wheel
- [ ] **T9.3** Test install wheel trong venv mới: `pip install dist/ryuu-0.3.0a1-*.whl` + chạy `chatbot.py`
- [ ] **T9.4** Git tag `v0.3.0a1` (KHÔNG push tới PyPI yet — chờ user confirm)
- [ ] **T9.5** Update `MEMORY.md` index với Phase 10 status

**Exit criteria**: Wheel install + example chạy. Tag local.

---

## Tổng Cộng

| Task block | Effort | Deliverable |
|---|---|---|
| T0 (Audit 8.8) | 1 tuần | Async guarantee verified |
| T1-T2 (scaffold + RED) | 1 ngày | 31 tests RED, empty package |
| T3 (provider detect) | 0.5 ngày | 6 tests GREEN |
| T4 (tool introspect) | 1 ngày | 6 tests GREEN |
| T5 (factory core) | 1.5 ngày | 12 tests GREEN |
| T6 (.run method) | 0.5 ngày | 5 tests GREEN |
| T7 (integration) | 0.5 ngày | 2 integration GREEN |
| T8 (docs + examples) | 1 ngày | 3 examples + quickstart update |
| T9 (release prep) | 0.5 ngày | Wheel + tag |

**Phase 10 MVP total: 1 tuần** (T1-T9, sau khi T0 audit xong)

---

## Sau Phase 10 MVP

Khi T1-T9 done, chuyển sang Phase 9 (Hooks). Sau đó Phase 10.x v2 thêm:

- Mode 2/3/4 prompt (system+user, file, YAML reference)
- `hooks=` param (sau Phase 9)
- `tool_registry=` direct pass (Mode C)
- `.stream()` AsyncIterator
- Multi-provider fallback chain

Xem `tasks/roadmap-phase8.8-to-14.md` cho thứ tự tổng thể.

---

## Notes

- KHÔNG over-engineer MVP — Mode 1 + Mode A đủ cho quick start examples
- Mỗi task verify pass trước khi sang task kế (incremental)
- Test RED first, sau đó implement → đảm bảo cover từ đầu
- Class-based examples (todo_app, code_analysis) KHÔNG migrate ở Phase 10 — chờ Phase 10.5 multi-agent facades
