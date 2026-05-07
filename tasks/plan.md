# Implementation Plan: LLMAgent — Framework Tool-Calling Layer

## Overview

Hiện tại mỗi example (todo_app) phải tự viết `_tool_loop`, `_select_model`, và token budget display.
Mục tiêu: đưa những thứ này vào framework dưới dạng `LLMAgent(BaseAgent)` — một concrete-abstract class
mà các project chỉ cần extend và override `_execute()` với domain logic thuần túy.

Sau khi xong, `TodoAnalysisAgent` sẽ giảm từ ~170 dòng xuống còn ~50 dòng.

## Phân biệt với ReActStrategy đã có

`uaaf/cognitive/strategies/react.py` → **orchestration layer** (StructuredIntent → IAgentPool → multi-agent)
`LLMAgent.react_loop()` → **LLM interaction layer** (CompletionRequest → tool_calls → Observation → text)

Hai tầng này bổ sung cho nhau, không trùng lặp.

## Architecture Decisions

- **ToolRegistry vào framework**: generic enough để dùng lại, không gắn với todo domain.
- **ReAct callbacks thay vì print trực tiếp**: `LLMAgent` không tự print — truyền `ReActCallbacks`
  object vào `react_loop()`. Default: `SilentCallbacks` (no-op). `PrintCallbacks` cho CLI.
  Lý do: tests không cần capture stdout, prod code có thể dùng structlog/file thay vì print.
- **`select_model()` trả về `ModelTier`, KHÔNG phải model string**: tách biệt complexity
  classification (LLMAgent) khỏi provider routing (ModelRouter). Project tự config router:
  ```
  LLMAgent.select_model(query) → ModelTier.CHEAP / STANDARD / POWERFUL
       ↓
  CompletionRequest.model = tier.value  ("cheap" / "standard" / "powerful")
       ↓
  ModelRouter._model_to_tier() → ModelTier → routes to đúng provider (OpenAI / Anthropic / etc.)
  ```
  Cần update nhỏ `ModelRouter._model_to_tier()` để nhận diện tier string trực tiếp (backward compat).
- **`ModelPolicy`** chỉ chứa complexity rules (keywords, word_count), không chứa model name.
  Per-provider config nằm ở `ModelRouter` do project tự wire.
- **Context window map**: thêm vào `uaaf/observability/_pricing.py`.
- **`BudgetSummary` auto-log vào `AuditLogger`**: mặc định `log_budget=True` trên `LLMAgent`.

## Dependency Graph

```
uaaf/providers/llm.py          ← đã có (Message, CompletionRequest, TokenUsage)
uaaf/observability/_pricing.py ← đã có (calculate_usd) — sẽ thêm CONTEXT_WINDOW map
uaaf/execution/agent.py        ← đã có (BaseAgent)
        │
        ▼
uaaf/execution/tool_registry.py   [T-L01] — IToolHandler protocol + ToolRegistry
        │
        ▼
uaaf/execution/llm_agent.py       [T-L02] — LLMAgent core (react_loop)
        │
        ├── [T-L03] select_model + ModelPolicy
        ├── [T-L04] token budget (BudgetSummary)
        └── [T-L05] ReActCallbacks (SilentCallbacks, PrintCallbacks)
                │
                ▼
uaaf/execution/__init__.py        [T-L01, T-L02] — exports
tests/unit/execution/test_llm_agent.py  [T-L02..T-L05]
        │
        ▼
examples/todo_app/agent.py        [T-L06] — refactor to use LLMAgent
examples/todo_app/main.py         [T-L06] — wire PrintCallbacks
```

---

## Task List

### Phase 1: Foundation

#### Task L-01: Generic ToolRegistry vào framework

**Description:** Tách `ToolRegistry` khỏi `examples/todo_app/tools.py` và đưa vào
`uaaf/execution/tool_registry.py` dưới dạng framework primitive. Todo example sẽ import
từ framework thay vì tự define.

**Acceptance criteria:**
- [ ] `uaaf/execution/tool_registry.py` có `IToolHandler` Protocol và `ToolRegistry` class
- [ ] `ToolRegistry.register(name, handler)` và `.run(tool_call)` và `.run_all(tool_calls)` hoạt động
- [ ] `uaaf/execution/__init__.py` export `ToolRegistry`
- [ ] `examples/todo_app/tools.py` import `ToolRegistry` từ `uaaf.execution` thay vì tự define

**Verification:**
- [ ] `python -m pytest tests/unit/execution/ -q` — pass
- [ ] `python -m mypy uaaf/execution/tool_registry.py` — clean
- [ ] `python -m examples.todo_app.main` — vẫn chạy được (smoke test)

**Dependencies:** None

**Files touched:**
- `uaaf/execution/tool_registry.py` (new)
- `uaaf/execution/__init__.py` (update)
- `examples/todo_app/tools.py` (update import)
- `tests/unit/execution/test_tool_registry.py` (new)

**Estimated scope:** S (3 files new/updated)

---

#### Task L-02: LLMAgent core — react_loop

**Description:** Tạo `uaaf/execution/llm_agent.py` với `LLMAgent(BaseAgent)`.
Class này là abstract — subclass vẫn implement `_execute()`. Cung cấp `react_loop(request, max_rounds)`
trả về `tuple[str, TokenUsage]` với full Thought→Action→Observation loop.

**Acceptance criteria:**
- [ ] `LLMAgent` có fields: `llm: ILLMProvider`, `tool_registry: ToolRegistry | None`
- [ ] `react_loop()` xử lý đúng 3 cases: no tool_calls (round 1), tool_calls (multi-round), max_rounds exceeded
- [ ] `react_loop()` trả về `tuple[str, TokenUsage]` với accumulated token counts
- [ ] Messages được build đúng format OpenAI: assistant message có `tool_calls`, tool message có `tool_call_id`
- [ ] `LLMAgent` vẫn là abstract (có `@abstractmethod _execute`)

**Verification:**
- [ ] `python -m pytest tests/unit/execution/test_llm_agent.py -q` — pass
- [ ] `python -m mypy uaaf/execution/llm_agent.py` — clean

**Dependencies:** L-01

**Files touched:**
- `uaaf/execution/llm_agent.py` (new)
- `uaaf/execution/__init__.py` (update export)
- `tests/unit/execution/test_llm_agent.py` (new)

**Estimated scope:** M (3-4 files)

---

### Checkpoint: After L-01 + L-02
- [ ] 383+ tests pass (không có regression)
- [ ] mypy clean trên toàn bộ `uaaf/`
- [ ] `ToolRegistry` accessible từ `uaaf.execution`
- [ ] `LLMAgent` accessible từ `uaaf.execution`

---

### Phase 2: Model Selection + Token Budget

#### Task L-03: ModelPolicy + select_model → ModelTier

**Description:** Thêm `ModelPolicy` dataclass và `select_model(query) → ModelTier` vào `LLMAgent`.
Policy chỉ chứa complexity rules (keywords, word_count_threshold) — KHÔNG chứa model name.
Model name do `ModelRouter` quyết định dựa trên tier. Cũng update nhỏ `ModelRouter._model_to_tier()`
để nhận diện tier string trực tiếp ("cheap"/"standard"/"powerful").

**Acceptance criteria:**
- [ ] `ModelPolicy` dataclass có: `keywords: set[str]`, `word_count_threshold: int`, `cheap_threshold: int`
- [ ] `select_model(query) → ModelTier` — CHEAP nếu ngắn/đơn giản, STANDARD bình thường, POWERFUL nếu phức tạp
- [ ] `LLMAgent` có `model_policy: ModelPolicy` field với sensible default
- [ ] `ModelRouter._model_to_tier()` nhận diện `ModelTier.value` string trực tiếp (backward compat)
- [ ] `react_loop()` set `request.model = selected_tier.value` trước khi gửi LLM

**Verification:**
- [ ] Unit tests: short query → CHEAP, long query → STANDARD, keyword match → POWERFUL
- [ ] Unit tests: `ModelRouter._model_to_tier("cheap") == ModelTier.CHEAP`
- [ ] `python -m mypy uaaf/execution/llm_agent.py uaaf/providers/router.py` — clean

**Dependencies:** L-02

**Files touched:**
- `uaaf/execution/llm_agent.py` (update)
- `uaaf/providers/router.py` (update `_model_to_tier` — nhỏ)
- `tests/unit/execution/test_llm_agent.py` (update)
- `tests/unit/providers/test_model_router.py` (update — thêm tier-string cases)

**Estimated scope:** S (3 files, changes nhỏ)

---

#### Task L-04: Token budget — BudgetSummary

**Description:** Thêm context window map vào `_pricing.py` và `BudgetSummary` vào `llm_agent.py`.
`budget_summary(usage, model)` trả về dataclass với `input_tokens`, `output_tokens`,
`total_tokens`, `window_size`, `pct_used`.

**Acceptance criteria:**
- [ ] `CONTEXT_WINDOW: dict[str, int]` trong `_pricing.py` cover các OpenAI models thường dùng
- [ ] `BudgetSummary` dataclass có tất cả fields trên
- [ ] `budget_summary()` tính đúng `pct_used = total / window * 100`
- [ ] Unknown model fallback về 128_000

**Verification:**
- [ ] Unit tests cover: known model, unknown model fallback, pct_used calculation
- [ ] `python -m mypy uaaf/execution/llm_agent.py uaaf/observability/_pricing.py` — clean

**Dependencies:** L-02

**Files touched:**
- `uaaf/observability/_pricing.py` (update — thêm CONTEXT_WINDOW)
- `uaaf/execution/llm_agent.py` (update — thêm BudgetSummary + method)
- `tests/unit/execution/test_llm_agent.py` (update)

**Estimated scope:** S (2 files)

---

### Phase 3: ReAct Callbacks + Refactor Example

#### Task L-05: ReActCallbacks — tách display khỏi logic

**Description:** Định nghĩa `ReActCallbacks` Protocol với `on_thought`, `on_action`,
`on_observation`, `on_final` hooks. Provide `SilentCallbacks` (default, no-op) và
`PrintCallbacks` (CLI display). `react_loop()` nhận `callbacks` parameter.

**Acceptance criteria:**
- [ ] `ReActCallbacks` Protocol với 4 async methods
- [ ] `SilentCallbacks` — no-op implementation
- [ ] `PrintCallbacks` — print với icons (💭 🔧 📋 ✅) như hiện tại
- [ ] `react_loop(request, max_rounds, callbacks)` — callbacks default = SilentCallbacks
- [ ] Tests dùng `SilentCallbacks` (không capture stdout)

**Verification:**
- [ ] `python -m pytest tests/unit/execution/test_llm_agent.py -q` — pass (không cần capsys)
- [ ] `python -m mypy uaaf/execution/llm_agent.py` — clean

**Dependencies:** L-02

**Files touched:**
- `uaaf/execution/llm_agent.py` (update)
- `uaaf/execution/__init__.py` (export PrintCallbacks, SilentCallbacks)
- `tests/unit/execution/test_llm_agent.py` (update)

**Estimated scope:** S (2 files)

---

#### Task L-06: Refactor TodoAnalysisAgent → dùng LLMAgent

**Description:** `TodoAnalysisAgent` extend `LLMAgent` thay vì `BaseAgent`.
Xóa `_tool_loop`, `_select_model`, `_CONTEXT_WINDOW` khỏi agent.py.
`_execute()` chỉ còn domain logic: load prompt, assemble context, call `react_loop()`.
Wire `PrintCallbacks` trong `main.py` để output giữ nguyên.

**Acceptance criteria:**
- [ ] `TodoAnalysisAgent(LLMAgent)` — không còn `_tool_loop` hay `_select_model`
- [ ] `examples/todo_app/agent.py` giảm xuống ≤ 70 dòng
- [ ] Output của `python -m examples.todo_app.main` giống y chang (ReAct display, budget, model selection)
- [ ] `examples/todo_app/tools.py` import `ToolRegistry` từ `uaaf.execution`

**Verification:**
- [ ] `python -m pytest tests/ -q` — 383+ pass
- [ ] `python -m mypy examples/todo_app/` — clean
- [ ] `python -m examples.todo_app.main` (với FakeLLMProvider) — chạy đúng

**Dependencies:** L-01, L-02, L-03, L-04, L-05

**Files touched:**
- `examples/todo_app/agent.py` (major rewrite — ngắn hơn)
- `examples/todo_app/main.py` (wire PrintCallbacks)
- `examples/todo_app/tools.py` (update import)

**Estimated scope:** S (3 files, nhưng chủ yếu xóa code)

---

### Checkpoint: Final
- [ ] `python -m pytest tests/ -q` — tất cả tests pass (≥ 383)
- [ ] `python -m mypy uaaf/ examples/` — clean
- [ ] `python -m ruff check uaaf/ examples/` — clean
- [ ] `python -m examples.todo_app.main` — chạy end-to-end với FakeLLMProvider
- [ ] `uaaf/execution/__init__.py` export: `BaseAgent`, `LLMAgent`, `ToolRegistry`, `PrintCallbacks`, `SilentCallbacks`

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `LLMAgent` làm phức tạp `BaseAgent` hierarchy | Medium | `LLMAgent` là optional layer — ai không cần tool-calling vẫn dùng `BaseAgent` trực tiếp |
| `ToolRegistry` conflict với todo_app's existing class | Low | Xóa class cũ khỏi tools.py, import từ framework |
| mypy không happy với async callbacks Protocol | Low | Dùng `ABC` thay vì `Protocol` nếu cần |
| `react_loop` return type break existing test_agent.py | Low | `LLMAgent` tách file mới — `test_agent.py` không thay đổi |

## Architecture Decisions (đã chốt)

| Câu hỏi | Quyết định |
|---------|-----------|
| `PrintCallbacks` output | stdout (mặc định), nhưng project overwrite được bằng cách inject `ReActCallbacks` subclass riêng (ví dụ: log to file, structlog, etc.) |
| `ModelPolicy` per-provider | Có — `ModelPolicy` có `provider_models: dict[str, tuple[str, str]]` mapping `provider_id → (default_model, complex_model)`. Ví dụ: `{"openai": ("gpt-4o-mini", "gpt-4o"), "anthropic": ("claude-haiku-4-5", "claude-sonnet-4-6")}` |
| `BudgetSummary` auto-log | Mặc định `True` — tự log vào `AuditLogger` sau mỗi `react_loop()`. Config được qua `log_budget: bool = True` field trên `LLMAgent`, project override bằng `log_budget=False` hoặc subclass `budget_logged()` hook |
