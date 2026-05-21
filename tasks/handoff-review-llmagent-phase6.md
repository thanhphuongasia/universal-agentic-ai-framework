# Handoff: Code Review — LLMAgent Plan + Phase 6 Multi-Agent Orchestration

**Ngày review**: 2026-05-08  
**Scope**: `plan.md` (LLMAgent tool-calling layer) + `phase6-multi-agent-orchestration-plan.md`  
**Thứ tự thực thi đã chốt**: `plan.md` trước → Phase 6 sau (tuần tự, 1 dev)  
**Baseline codebase**: Phase 5 done, 383 tests pass, 91.48% coverage, ruff ✓, mypy ✓

---

## Tóm tắt verdict

| | `plan.md` (LLMAgent) | Phase 6 (Multi-Agent) |
|---|---|---|
| Triết lý kiến trúc | Tốt | Tốt |
| Spec compliance | **Cần sửa** | **Cần sửa** |
| Risk awareness | Thiếu vài edge case | Tốt hơn, vẫn thiếu partial failure |
| Sẵn sàng start? | **Sau khi fix #1–#4** | **Sau khi fix #5–#8** |

**Không start coding cho đến khi 8 fixes ưu tiên cao được resolve.** Sửa sau khi có code tốn 3–5× effort.

---

## Phần 1 — `plan.md` (LLMAgent)

### Điểm tốt — giữ nguyên

- Phân biệt "orchestration layer" (`ReActStrategy`) vs "LLM interaction layer" (`LLMAgent.react_loop()`) là chuẩn xác. Tránh được class 1500 dòng làm tất cả như Code Analysis chat hiện tại.
- `select_model() → ModelTier` thay vì trả về model string — đúng separation of concerns, `ModelRouter` là single source of truth cho provider routing.
- `ReActCallbacks` Protocol thay vì print trực tiếp — tests không cần capture stdout, production dùng structlog/file.

---

### Fixes bắt buộc trước khi start

#### Fix #1 — [CRITICAL] Resolve mâu thuẫn `ModelPolicy` trong chính plan

Đầu plan và cuối plan nói **hai thứ đối nghịch nhau**:

> *Đầu plan*: `ModelPolicy` chỉ chứa complexity rules (keywords, word_count), **không chứa model name**. Per-provider config nằm ở `ModelRouter`.

> *Cuối plan (Architecture Decisions đã chốt)*: `ModelPolicy` có `provider_models: dict[str, tuple[str, str]]` mapping `provider_id → (default_model, complex_model)`.

**Quyết định cần chốt**: chọn một, bỏ cái kia.

Khuyến nghị giữ **option đầu** (complexity rules only) vì:
- Đúng tinh thần spec — không duplicate config giữa `ModelPolicy` và `ModelRouter`.
- Nếu `ModelPolicy` chứa model name → `LLMAgent` phải biết về provider specifics → leak abstraction.

Hành động: xóa block "Architecture Decisions (đã chốt)" về `ModelPolicy` cuối plan, thay bằng note rõ "per-provider config ở ModelRouter".

---

#### Fix #2 — [CRITICAL] `ToolRegistry` thiếu domain whitelist — vi phạm spec §9

Spec `ryuu-framework-spec.md` §9 "Always":
> Mọi tool register trong `ToolRegistry` với domain whitelist — không hardcode tool list trong agent.

Class diagram spec có `allowlist_per_domain: Dict` trên `ToolRegistry`.

Task L-01 hiện tại chỉ có `register(name, handler)` — không có concept domain. Với 5 product (Stock có `place_order`, AI coding có `run_code`), thiếu whitelist nghĩa là:
- Stock agent có thể accidentally invoke `run_code` nếu cùng pool.
- Không có cơ chế audit "tool nào được phép cho domain nào".
- Thêm sau là breaking change với tất cả downstream product đã register tool.

**Sửa Task L-01**: đổi signature thành:

```python
def register(
    self,
    name: str,
    handler: IToolHandler,
    allowed_domains: set[str] | None = None,  # None = all domains
) -> None: ...
```

Thêm acceptance criteria: `run(tool_call, domain)` raise `PermissionError` nếu domain không có trong `allowed_domains`.

---

#### Fix #3 — [HIGH] Define behavior cho empty `tool_calls` ở round N > 1 trong `react_loop`

Plan định nghĩa 3 cases:
1. No tool_calls ở round 1 → final answer.
2. Tool_calls → multi-round.
3. Max rounds exceeded → return.

**Case bị miss**: round N > 1 mà LLM trả về `tool_calls=[]` (LLM "đổi ý" giữa chừng). Hành xử thế nào?

Cần chốt explicit trong plan trước khi implement. Khuyến nghị: treat như final answer (terminate cleanly), add test case riêng.

---

#### Fix #4 — [MEDIUM] Align tên `IToolHandler` với `ITool` trong spec

Spec class diagram dùng `ITool` Protocol với `tool_id`, `schema: ToolSchema`, `execute(args, ctx) -> ToolResult`.

Plan dùng `IToolHandler` — tên khác, có thể schema cũng khác. Cần làm rõ:
- Nếu `IToolHandler` là rename → update spec để đồng bộ.
- Nếu `IToolHandler` là interface khác với `ITool` → justify tại sao cần 2 interface.

Không nên có 2 interface cho cùng concept trong 1 framework.

---

### Cảnh báo bổ sung (không block nhưng cần note)

**`BudgetSummary` auto-log — đặt tên cho rõ.**  
`BaseAgent.execute()` đã `cost_tracker.record()` rồi. `LLMAgent` thêm `audit_logger.log_budget()` là OK vì mục đích khác (cost record để enforce budget, audit log để compliance trail). Nhưng field tên `log_budget` mơ hồ — đổi thành `audit_token_usage: bool = True` để phân biệt với cost enforcement.

**Streaming không được mention.**  
`react_loop()` return `tuple[str, TokenUsage]` (full string). Nếu Code Analysis chat cần streaming, `LLMAgent` này không support. Nếu intentional defer, thêm comment: `# Streaming: out of scope, Phase X`.

**Keyword-based complexity classification là tech debt.**  
`ModelPolicy` dùng keyword matching không scale với multi-language. Thêm TODO: `# Phase X: replace với LLM-based hoặc embedding-based classifier`.

---

## Phần 2 — Phase 6 (Multi-Agent Orchestration)

### Điểm tốt — giữ nguyên

- Anyio task group thay `asyncio.gather` đúng spec — fix được vi phạm trong `examples/code_analysis` hiện tại.
- Index-stable result ordering trong `fan_out` (dùng `results[i] = ...`, không `results.append()`) — chi tiết thường bị miss.
- `ISubtaskBuilder` Protocol thay bare callable — đúng tinh thần "Protocol > callable" của spec.
- Tách rõ `dispatch()` / `dispatch_to()` / `fan_out()` — không overload.

---

### Fixes bắt buộc trước khi start

#### Fix #5 — [CRITICAL] Justify hoặc bỏ `OrchestratorAgent`

`OrchestratorAgent` và `ParallelFanoutStrategy` thực hiện cùng một flow:

```
Decompose → fan_out workers → aggregate
```

Spec gốc không có `OrchestratorAgent` trong class diagram — đây là invention mới của plan, không được justify.

Plan phải chọn một trong hai hướng:

**Option A — Bỏ `OrchestratorAgent`, giữ `ParallelFanoutStrategy`**  
`ParallelFanoutStrategy` đúng tier (cognitive tier, plugin contract), đúng spec. `OrchestratorAgent` là duplication. Nếu product cần supervisor pattern, viết ở examples/ như demo.

**Option B — Giữ cả hai, justify rõ vai trò khác nhau**  
Ví dụ: `ParallelFanoutStrategy` được `StrategySelector` chọn từ `StructuredIntent` (top-down từ Runtime). `OrchestratorAgent` là agent có thể đăng ký vào pool như worker (recursive orchestration). Nếu chọn option này, phải update spec class diagram và document rõ "khi nào dùng cái nào".

**Khuyến nghị**: Option A — less is more, không thêm vào framework core nếu chưa có use case cụ thể.

---

#### Fix #6 — [HIGH] Define `fan_out` partial failure semantics

Plan T02 nói:
> Exception trong 1 worker propagate ra `fan_out()` caller (không bị nuốt).

Nhưng `anyio.create_task_group()` mặc định **cancel tất cả task khác** khi 1 task raise. Nghĩa là 1 task fail → 9 task khác bị cancel → caller không có result của các task thành công.

Đây có thể không phải hành vi mong muốn cho `ParallelFanoutStrategy` (muốn aggregate partial result).

Cần chọn explicit và implement đúng:

```python
async def fan_out(
    self,
    tasks: list[Task],
    context: ExecutionContext,
    tag_filter: str | None = None,
    on_error: Literal["fail_fast", "collect"] = "fail_fast",
) -> list[AgentResult]: ...
```

- `fail_fast`: anyio default — 1 fail → cancel hết, raise. Dùng khi cần all-or-nothing.
- `collect`: dùng `anyio.CancelScope` per-task — collect tất cả result + exception, caller decide. Dùng khi `ParallelFanoutStrategy` muốn aggregate partial.

Thêm test case cho cả 2 modes trong T02.

---

#### Fix #7 — [HIGH] Redesign `dispatch()` no-target — "first registered" là silent bug magnet

Task T01 acceptance:
> `dispatch()` route đến agent đầu tiên trong registry.

10 agents trong pool, gọi `dispatch(task)` luôn chọn cùng 1 agent. Không round-robin, không capability-based, không load-aware. Dev local chạy đúng, production scale fail.

**Khuyến nghị**: bỏ `dispatch()` no-target khỏi public API. Force caller dùng `dispatch_to(agent_id, task)` (explicit) hoặc `fan_out(tasks, context, tag_filter=...)` (broadcast). Nếu thực sự cần default routing, phải có chiến lược rõ: `dispatch(task, strategy: Literal["round_robin", "random", "least_loaded"] = "round_robin")`.

---

#### Fix #8 — [MEDIUM] Test rate-limiter × max_concurrency interaction

`AgentPool.max_concurrency=8` (Semaphore) và `RateLimiter` trong `BaseAgent` có 2 mục đích khác nhau:
- Semaphore: limit số agent chạy song song trong pool.
- RateLimiter: limit request per scope/per provider xuyên suốt runtime.

Edge case nguy hiểm: `max_concurrency=8` nhưng `RateLimiter` cho 3 rps → 8 tasks acquire semaphore xong stack ở rate limiter, có thể dẫn đến timeout cascade.

Thêm vào T02: test case "fan_out với rate limiter saturation — không deadlock, timeout graceful".

---

### Cảnh báo bổ sung

**`OrchestratorAgent` cost aggregation — undercounted, không phải double-count.**  
Risk table trong plan nói "double-count" nhưng thực tế ngược lại: `BaseAgent.execute()` của Orchestrator chỉ track cost của chính nó (2 LLM call decompose + synthesize). Worker costs được track riêng bởi từng worker agent. Nếu muốn report tổng, phải explicit aggregate. Dùng `cost_tracker.get_usage(scope)` sau khi `fan_out()` xong — tránh manual sum `AgentResult.cost` vì dễ miss.

**`examples/code_analysis` workers nên extend `LLMAgent` sau khi `plan.md` xong.**  
Phase 6 T06 chỉ refactor `asyncio.gather → AgentPool.fan_out`. Nhưng nếu workers cần tool-calling (likely), nên cũng refactor sang `LLMAgent`. Thêm task này sau Phase 6 T06, hoặc ghi note follow-up.

**Verifier integration — cần document rõ trách nhiệm.**  
`plan.md` không nhắc verifier trong `react_loop`. Phase 6 `ParallelFanoutStrategy` có gọi verifier, nhưng `OrchestratorAgent` không. Nếu intentional (verifier là strategy tier's responsibility, không phải agent's), document explicit: "Agent layer không chạy verifier — đó là nhiệm vụ của Strategy tier."

---

## Phần 3 — Issues giao giữa 2 plan

### Thứ tự thực thi: `plan.md` trước → OK với caveat

Lý do hợp lý:
- `LLMAgent` không depend vào `AgentPool` — đứng riêng được.
- Phase 6 có sẵn `LLMAgent` thì viết worker agents trong `OrchestratorAgent` / `ParallelFanoutStrategy` dễ hơn.

Caveat: `examples/code_analysis` Phase 6 T06 chỉ refactor pool layer, chưa đụng vào individual workers. Cần track item: "workers extend `LLMAgent`" sau khi `plan.md` xong.

### Overlap ở `ryuu/execution/__init__.py`

Cả 2 plan đều update file này (exports). Nếu có merge conflict:
- `plan.md` thêm: `LLMAgent`, `ToolRegistry`, `PrintCallbacks`, `SilentCallbacks`
- Phase 6 thêm: `AgentPool`, `OrchestratorAgent`

Không phải conflict thực sự vì tuần tự — nhưng implementer nên kiểm tra file này khi bắt đầu Phase 6 để đảm bảo exports nhất quán.

### `plan.md` thiếu regression + coverage gate

Phase 6 có explicit: "383+ tests pass, coverage ≥ 88%". `plan.md` không có.

Thêm checkpoint cuối `plan.md`:
```
pytest tests/ -q                    → tất cả existing tests pass
pytest --cov=ryuu --cov-fail-under=85
ruff check ryuu/ examples/          → 0 violations  
mypy ryuu/ examples/                → 0 errors
```

---

## Phần 4 — Action items theo thứ tự ưu tiên

### Làm trước khi start `plan.md`

| # | Fix | File cần sửa | Effort |
|---|---|---|---|
| 1 | Resolve mâu thuẫn `ModelPolicy` — chọn complexity-only, xóa `provider_models` | `plan.md` | 15 phút |
| 2 | Thêm `allowed_domains` vào `ToolRegistry.register()` | `plan.md` Task L-01 | 30 phút |
| 3 | Define behavior `tool_calls=[]` ở round N>1 | `plan.md` Task L-02 | 15 phút |
| 4 | Chốt `IToolHandler` vs `ITool` — align tên với spec | `plan.md` + spec | 15 phút |

### Làm trước khi start Phase 6

| # | Fix | File cần sửa | Effort |
|---|---|---|---|
| 5 | Justify hoặc bỏ `OrchestratorAgent` — khuyến nghị bỏ | Phase 6 plan | 30 phút |
| 6 | Thêm `on_error: Literal["fail_fast", "collect"]` vào `fan_out` | Phase 6 T01 + T02 | 1 giờ |
| 7 | Bỏ `dispatch()` no-target hoặc thêm routing strategy | Phase 6 T01 | 30 phút |
| 8 | Thêm test "rate-limiter × max_concurrency — không deadlock" | Phase 6 T02 | 1 giờ |

### Nice-to-have (không block)

| # | Item | |
|---|---|---|
| 9 | `plan.md` thêm regression + coverage gate vào checkpoint cuối | |
| 10 | Note "Streaming → out of scope, Phase X" trong `react_loop` | |
| 11 | Note "keyword matching là tech debt → Phase X replace" trong `ModelPolicy` | |
| 12 | Note "workers extend `LLMAgent`" như follow-up task sau Phase 6 T06 | |
| 13 | Đổi `log_budget` → `audit_token_usage` trên `LLMAgent` | |
| 14 | Document explicit: "Verifier là responsibility của Strategy tier, không phải Agent tier" | |

---

## Quick reference — checklist cho implementer

### Trước khi code `plan.md`
- [ ] Fix #1: `ModelPolicy` chỉ complexity rules, xóa `provider_models`
- [ ] Fix #2: `ToolRegistry.register()` có `allowed_domains` param
- [ ] Fix #3: Document `tool_calls=[]` ở round N>1 trong `react_loop`
- [ ] Fix #4: Chốt tên `IToolHandler` hay `ITool`, update spec nếu cần

### Trước khi code Phase 6
- [ ] Fix #5: Quyết định `OrchestratorAgent` — bỏ hay giữ với justify
- [ ] Fix #6: `fan_out` có `on_error` parameter với 2 modes
- [ ] Fix #7: Bỏ `dispatch()` no-target hoặc có routing strategy
- [ ] Fix #8: Test rate-limiter saturation không deadlock

### CI gate sau `plan.md`
- [ ] `pytest tests/ -q` — all pass
- [ ] `pytest --cov=ryuu --cov-fail-under=85`
- [ ] `ruff check ryuu/ examples/` — 0 violations
- [ ] `mypy ryuu/ examples/` — 0 errors
- [ ] `python -m examples.todo_app.main` — output giống y chang trước refactor

### CI gate sau Phase 6
- [ ] `pytest tests/ --cov=ryuu --cov-fail-under=88` — ≥ 420 tests
- [ ] `ruff check ryuu/ tests/ examples/` — 0 violations
- [ ] `mypy ryuu/ examples/` — 0 errors
- [ ] `grep -r "asyncio.gather" ryuu/` — no results
- [ ] `python -c "from ryuu import AgentPool"` — no ImportError
