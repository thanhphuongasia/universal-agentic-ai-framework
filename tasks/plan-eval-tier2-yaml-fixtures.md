# Implementation Plan: Eval Tier 2 Interactive Frontend + YAML-driven Fixtures

## Overview

Nâng cấp ryuu-eval theo 2 hướng:

1. **YAML-driven fixtures** — router nhận `fixtures_dir` param, scan YAML files từ đó,
   expose qua `GET /fixtures/{suite_id}`. Run endpoints tự động gộp fixture cases + UI cases.
   Frontend hiển thị Fixtures section trong sidebar (read-only, có "Clone to editor").

2. **Tier 2 interactive frontend** — `SmartCaseEditor` render form fields từ
   `template.input_schema.properties` thay vì raw JSON textarea. Thêm `POST /run/single`
   endpoint + "▶ Run this case" button cho single-case run trực tiếp từ editor.

Cũng fix bug `_maybe_await` chưa được định nghĩa trong router.py.

## Architecture Decisions

- `fixtures_dir` là `Path | None = None` — feature opt-in, không break existing projects
- `GET /fixtures/` trả read-only (không có PUT/DELETE) — fixture files là source-of-truth, không editable qua UI
- Run endpoints gộp fixture + UI cases nhưng deduplicate theo `case_id` (UI case thắng)
- `SmartCaseEditor` fallback về raw JSON textarea khi `input_schema.properties` rỗng/absent
- `POST /run/single` blocking (không SSE) — đủ đơn giản, result hiện ngay vào `runResult` slot
- CSS `.field-row` đã có sẵn — chỉ cần thêm `.fixture-badge` và `.schema-form`

## Dependency Graph

```
EvalCaseTemplate.input_schema (already in ryuu-eval-core/models.py)
    └── SmartCaseEditor [T05] — renders form from schema
            └── EvalApp: replaces CaseEditor [T07]

fixtures_dir param [T02]
    ├── _load_all_cases() helper [T02] — used by run endpoints
    ├── GET /fixtures/{suite_id} [T02]
    │       └── FixtureList + EvalApp fixtures state [T06]
    └── run endpoints: stream_suite + run_suite_blocking [T02]

POST /run/single [T03]
    └── "▶ Run this case" button [T07]

_maybe_await bug [T01] — standalone fix
```

## Task List

### Phase 1: Backend Foundation

#### T01 — Fix `_maybe_await` NameError in router.py

**Description:** `trigger_optimize` gọi `await _maybe_await(...)` nhưng hàm này chưa được
định nghĩa. Sẽ raise `NameError` khi user bấm "Optimize". Fix bằng cách thêm helper ở cuối file.

**Files:** `packages/ryuu-eval/src/ryuu_eval/http/router.py`

**Acceptance criteria:**
- [ ] `_maybe_await(sync_fn, ...)` trả kết quả của sync fn
- [ ] `_maybe_await(async_fn, ...)` await và trả kết quả
- [ ] `import inspect` được thêm vào top-level imports

**Verification:**
- [ ] `python -c "from ryuu_eval.http.router import build_eval_router"` không raise

**Dependencies:** None  
**Estimated scope:** XS (1 file, 10 lines)

---

#### T02 — YAML fixtures backend: `fixtures_dir` + `GET /fixtures/{suite_id}`

**Description:** Thêm `fixtures_dir: Path | None = None` vào `build_eval_router`. Thêm
`GET /fixtures/{suite_id}` endpoint scan YAML từ `fixtures_dir/<suite_id>/`. Thêm
`_load_all_cases(suite_id)` helper gộp UI cases + fixture cases (dedup by case_id).
Update `run_suite_blocking` và `stream_suite` dùng `_load_all_cases`.

**Files:** `packages/ryuu-eval/src/ryuu_eval/http/router.py`

**Acceptance criteria:**
- [ ] `build_eval_router(..., fixtures_dir=Path("fixtures"))` không lỗi
- [ ] `GET /fixtures/{suite_id}` trả `[]` khi `fixtures_dir=None`
- [ ] `GET /fixtures/{suite_id}` trả list cases với `_source: "fixture"` khi có YAML files
- [ ] Run endpoints load cả fixture cases lẫn UI cases (fixture cases với case_id trùng bị bỏ)
- [ ] `status` endpoint trả `fixtures_dir` field

**Verification:**
- [ ] `python -c "from ryuu_eval.http.router import build_eval_router; print('ok')"` không lỗi
- [ ] Manual: tạo `test_fixtures/suite1/case1.yml`, gọi `GET /fixtures/suite1` → trả case

**Dependencies:** T01  
**Estimated scope:** S (1 file, ~60 lines thêm)

---

#### T03 — `POST /run/single` endpoint

**Description:** Thêm endpoint nhận `{suite_id, case_id, input, expected}` và chạy một
ad-hoc case. Trả `CaseResult` dict (không phải `SuiteResult`). Dùng cùng `runner_factory`
như suite run.

**Files:** `packages/ryuu-eval/src/ryuu_eval/http/router.py`

**Acceptance criteria:**
- [ ] `POST /run/single` với valid payload → trả `{case_id, passed, scores, cost_usd, latency_ms}`
- [ ] `suite_id` missing → 400
- [ ] Kết quả là CaseResult của case đầu tiên (và duy nhất) trong SuiteResult

**Verification:**
- [ ] Route list của router chứa `POST /run/single`

**Dependencies:** T02  
**Estimated scope:** XS (1 file, ~20 lines)

---

### Checkpoint: Phase 1 Backend

- [ ] `python -c "from ryuu_eval.http.router import build_eval_router"` sạch
- [ ] Router có đủ các endpoints: `/fixtures/{suite_id}`, `/run/single`, `/status`

---

### Phase 2: Frontend — Fixtures UI

#### T04 — Commit existing uncommitted changes

**Description:** Commit `ui.py` redirect fix + cache-control change + các modified files khác
(ryuu-prompts, mcp-client, quickstart docs) trước khi bắt đầu thêm feature mới.

**Files:** Tất cả files trong `git diff --stat HEAD`

**Acceptance criteria:**
- [ ] `git status` chỉ còn untracked `examples/ryuu_sensei/skills/`, `packages/ryuu-prompts/src/ryuu_prompts/skills/`, `packages/infrastructure/mcp/ryuu-mcp-client/src/ryuu_mcp_client/data/`, `registry.py`, `skill_manager.py`
- [ ] Commit message mô tả đúng nội dung

**Verification:**
- [ ] `git log --oneline -1` hiện commit mới

**Dependencies:** None (independent)  
**Estimated scope:** XS

---

#### T05 — `SmartCaseEditor` component (schema-driven form)

**Description:** Thêm component `SmartCaseEditor({ caseData, template, onChange })` vào
`ryuu-eval.js`. Khi `template.input_schema.properties` có entries, render từng property
thành `<input>`, `<select>`, hoặc `<textarea>` tương ứng. Expected side luôn là JSON
textarea. Thêm CSS `.schema-form` container.

**Files:**
- `packages/ryuu-eval-frontend/src/ryuu_eval_frontend/dist/ryuu-eval.js`
- `packages/ryuu-eval-frontend/src/ryuu_eval_frontend/dist/ryuu-eval.css`

**Acceptance criteria:**
- [ ] Schema `{type: "string"}` → `<input type="text">`
- [ ] Schema `{type: "integer"}` / `{type: "number"}` → `<input type="number">`
- [ ] Schema `{type: "boolean"}` → `<input type="checkbox">`
- [ ] Schema `{enum: [...]}` → `<select>`
- [ ] Schema `{type: "array"}` / `{type: "object"}` → `<textarea>` với JSON
- [ ] Khi `properties` rỗng/không có → fallback về CaseEditor (raw JSON textarea)
- [ ] onChange cập nhật `caseData.input` đúng type (number không bị string)

**Verification:**
- [ ] Browser: chọn template có `input_schema` → form fields hiện ra
- [ ] Browser: chọi template không có schema → JSON textarea hiện ra

**Dependencies:** T04  
**Estimated scope:** M (2 files, ~80 lines JS + ~15 lines CSS)

---

#### T06 — `FixtureList` component + fixtures state trong `EvalApp`

**Description:** Thêm `FixtureList({ fixtures, onClone })` component hiển thị fixture cases
với `📌 fixture` badge (không có delete). Trong `EvalApp`: thêm `fixtures` state, fetch
`GET /fixtures/{suiteId}` khi suite thay đổi, thêm section "Fixtures" trong sidebar, thêm
`onCloneFixture(fixture)` handler (load vào editor như new case). Thêm CSS `.fixture-badge`.

**Files:**
- `packages/ryuu-eval-frontend/src/ryuu_eval_frontend/dist/ryuu-eval.js`
- `packages/ryuu-eval-frontend/src/ryuu_eval_frontend/dist/ryuu-eval.css`

**Acceptance criteria:**
- [ ] Sidebar có section "Fixtures (N)" khi có fixture cases
- [ ] Mỗi fixture item có `📌` badge + tên file gốc
- [ ] Click fixture → load vào editor với `_source: "fixture"` để biết là clone
- [ ] `GET /fixtures/` trả 404 hoặc `[]` → section ẩn (không hiện "Fixtures (0)")
- [ ] Fixture cases không có delete button

**Verification:**
- [ ] Browser: tạo YAML fixture file, reload → hiện trong sidebar

**Dependencies:** T02, T05  
**Estimated scope:** M (2 files, ~70 lines JS + ~10 lines CSS)

---

### Checkpoint: Phase 2 Frontend

- [ ] Browser: sidebar hiện Templates + Cases + Fixtures sections
- [ ] Browser: form editor hoạt động với schema-driven template
- [ ] Browser: clone fixture vào editor → có thể edit và save

---

### Phase 3: Run This Case

#### T07 — "▶ Run this case" button + wire `POST /run/single`

**Description:** Trong `EvalApp`:
- Thêm `runningCase` state (loading indicator)
- Thêm `onRunSingle()` handler: POST `/run/single` với `{suite_id, case_id, input, expected}`
- Thêm "▶ Run this case" button trong toolbar (chỉ hiện khi có case loaded trong editor)
- Kết quả ghi vào `runResult` state (cùng slot với suite run result)
- Thay `<CaseEditor>` bằng `<SmartCaseEditor template=${selectedTemplate}>` trong EvalApp render

**Files:**
- `packages/ryuu-eval-frontend/src/ryuu_eval_frontend/dist/ryuu-eval.js`

**Acceptance criteria:**
- [ ] "▶ Run this case" chỉ hiện khi `caseData.case_id || caseData._template_id` có giá trị
- [ ] Bấm button → gọi `POST /run/single`, button disabled trong lúc chờ
- [ ] Kết quả hiện trong result summary (passed/failed, latency, cost)
- [ ] `SmartCaseEditor` được dùng thay `CaseEditor` trong EvalApp
- [ ] `selectedTemplate` được derive từ `templates.find(t => t.template_id === caseData._template_id)`

**Verification:**
- [ ] Browser: chọn template, điền form, bấm "▶ Run this case" → kết quả hiện
- [ ] Browser: suite run vẫn hoạt động bình thường

**Dependencies:** T03, T05, T06  
**Estimated scope:** S (1 file, ~40 lines thêm/sửa)

---

### Checkpoint: Phase 3 Complete

- [ ] Browser: full flow — pick template → fill form → run single case → see result
- [ ] Browser: full flow — pick fixture → clone → edit → save → run suite
- [ ] `git log --oneline -5` thể hiện clean commit history

---

## Summary Task Table

| ID | Title | Size | Files | Deps |
|----|-------|------|-------|------|
| T01 | Fix `_maybe_await` bug | XS | router.py | None |
| T02 | YAML fixtures backend | S | router.py | T01 |
| T03 | `POST /run/single` endpoint | XS | router.py | T02 |
| T04 | Commit existing changes | XS | multiple | None |
| T05 | `SmartCaseEditor` component | M | js + css | T04 |
| T06 | `FixtureList` + fixtures state | M | js + css | T02, T05 |
| T07 | "Run this case" button | S | js | T03, T05, T06 |

**Execution order:** T01 → T02 → T03 → T04 (parallel với T01-T03) → T05 → T06 → T07

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| EvalRunner.run() signature không accept single case | Med | Wrap trong list[EvalCase] — đã làm trong suite run |
| `input_schema` format không chuẩn JSON Schema | Low | Fallback về raw textarea khi properties rỗng |
| fixtures_dir path resolver (relative vs absolute) | Low | Ghi rõ trong docstring: caller cung cấp absolute path |
| SSE race condition khi run single + run suite cùng lúc | Low | UI disable suite run khi runningCase=true |

## Open Questions

- `POST /run/single` có nên dùng SSE stream (cho live progress) hay blocking đủ không? → Plan này dùng blocking (đơn giản hơn, đủ cho single case).
- Fixture YAML files có nên hỗ trợ `!py` tag không? → Có, vì dùng `FixtureLoader.load()` vốn đã support `!py`.
