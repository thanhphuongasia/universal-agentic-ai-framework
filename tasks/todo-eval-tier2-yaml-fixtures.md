# TODO: Eval Tier 2 + YAML Fixtures

## Phase 1: Backend Foundation

- [ ] T01 — Fix `_maybe_await` NameError in router.py
- [ ] T02 — YAML fixtures: `fixtures_dir` param + `GET /fixtures/{suite_id}` + `_load_all_cases`
- [ ] T03 — `POST /run/single` endpoint

### Checkpoint Phase 1
- [ ] `from ryuu_eval.http.router import build_eval_router` sạch
- [ ] Router có đủ endpoints: `/fixtures/{suite_id}`, `/run/single`, `/status`

## Phase 2: Frontend Fixtures UI

- [ ] T04 — Commit existing uncommitted changes (ui.py, mcp-client, ryuu-prompts, docs)
- [ ] T05 — `SmartCaseEditor` component (schema-driven form fields)
- [ ] T06 — `FixtureList` component + fixtures state trong EvalApp

### Checkpoint Phase 2
- [ ] Browser: sidebar hiện Templates + Cases + Fixtures
- [ ] Browser: schema-driven form hoạt động
- [ ] Browser: clone fixture vào editor được

## Phase 3: Run This Case

- [ ] T07 — "▶ Run this case" button + wire `POST /run/single` + swap CaseEditor → SmartCaseEditor

### Checkpoint Phase 3 (Done)
- [ ] Browser: pick template → fill form → run single case → see result
- [ ] Browser: pick fixture → clone → save → run suite
- [ ] git history clean
