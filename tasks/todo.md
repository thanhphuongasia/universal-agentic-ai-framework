# Task List: LLMAgent Framework Layer

## Phase 1: Foundation

- [ ] **L-01** — ToolRegistry vào framework (`uaaf/execution/tool_registry.py`)
- [ ] **L-02** — LLMAgent core + react_loop (`uaaf/execution/llm_agent.py`)

### Checkpoint 1
- [ ] 383+ tests pass, mypy clean

## Phase 2: Model Selection + Token Budget

- [ ] **L-03** — ModelPolicy + select_model
- [ ] **L-04** — BudgetSummary + CONTEXT_WINDOW map

## Phase 3: Callbacks + Example Refactor

- [ ] **L-05** — ReActCallbacks (SilentCallbacks, PrintCallbacks)
- [ ] **L-06** — Refactor TodoAnalysisAgent → LLMAgent

### Checkpoint Final
- [ ] All tests pass, mypy + ruff clean
- [ ] `python -m examples.todo_app.main` runs end-to-end
