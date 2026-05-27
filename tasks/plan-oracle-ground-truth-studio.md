# Implementation Plan — Oracle Ground Truth Studio

**Date:** 2026-05-27
**Source spec:** `2026-05-26_oracle_ground_truth_studio_ui_meta_prompt.md` (handoff)
**Goal:** Restructure existing OracleReviewPage from hardcoded `CrudMatrixOracleStrategy` to a **generic meta-prompt flow**: production prompt → meta-prompt generates oracle prompt → oracle prompt produces ground truth. Works for ANY LLM feature (CRUD matrix, Anki cards, todo classify…).

---

## 1. Gap Analysis — Current vs Target

| Step | Current State | Target State | Gap |
|------|--------------|--------------|-----|
| **1. Input** | Editable Route Context JSON · Production Prompt · Actual Output (local) | Same | ✅ Done |
| **2. Oracle Prompt** | Loads from `CrudMatrixOracleStrategy.render_prompt(input_data)` (hardcoded reasoning rules) · Manual override local only | Run **meta-prompt** on production prompt → return oracle prompt (system + user_template + schema) · Editable · Persisted | ❌ Backend missing meta-prompt endpoint; frontend wiring missing |
| **3. Run Oracle** | Calls hardcoded strategy via `/oracle-review/{id}/run` | Run **arbitrary oracle prompt** (from step 2) against `input_data` with Opus → cells + why + confidence | ❌ Need new endpoint that accepts oracle_prompt param |
| **4. Review** | Per-cell approve/fix/remove · Save | Side-by-side **actual vs oracle expected**; `high` cells auto-ticked, `low/medium` highlighted as mandatory | ⚠️ Partial — has Save & per-cell, missing confidence-based auto-tick + side-by-side diff |
| **5. Save to suite** | Save = update review actions (in-place fixture) | Export approved cells as **new fixture entry** appended to a target suite | ❌ No "export to suite" path; currently same fixture used |

Other gaps:
- Fixture format: needs `oracle_prompt_version` field (track which generated oracle prompt produced this ground truth)
- Project-agnostic: current strategy is hardcoded per project; meta-prompt approach removes this lock-in

---

## 2. Architecture Decisions

- **Meta-prompt = hardcoded server constant.** One source of truth in backend, not configurable per project (spec section 2: "GENERIC — 1 cái duy nhất cho mọi project"). Updates ship via code change.
- **Generated oracle prompt = persisted on fixture.** Stored as a string field on fixture JSON so we can re-run, audit, and rollback.
- **Run-with-prompt = stateless.** Endpoint takes `{oracle_prompt, input_data, model?}` and returns cells without persisting (preview). Persisting happens only on Save (step 5).
- **Save to suite = copy + append.** New endpoint `POST /oracle-review/{fixture_id}/promote-to-suite` writes a frozen fixture JSON into the target suite's case directory. Original review fixture stays for audit.
- **Tabs: 5 vs 4.** Spec lists 5 but step 5 is a single "Save" button — render as 4 tabs with a Save button in tab 4. Reduces clicks. (Confirm with user.)
- **Default model: Opus 4.7** for oracle (per spec section 1.3 — "giám khảo mạnh hơn thí sinh Sonnet").

---

## 3. Phased Delivery

### Phase 1 — Backend foundations (additive, no UI changes yet)

#### T01 — `POST /oracle-review/meta-generate`
- **Input:** `{production_prompt: string, domain_hint?: string, project_name?: string}`
- **Output:** `{oracle_prompt: string, generated_at: string, meta_prompt_version: string}`
- **Logic:** Build messages from hardcoded meta-prompt system (spec §2) + user template; call configured LLM (Opus); return raw oracle prompt text.
- **Files:** `packages/ryuu-eval/src/ryuu_eval/http/router.py` (new endpoint), new module `packages/ryuu-eval/src/ryuu_eval/oracle/meta_prompt.py` (constants + builder).
- **Scope:** S
- **Verify:** curl with sample production prompt → returns non-empty oracle prompt containing "JSON" and "confidence".

#### T02 — `POST /oracle-review/run-with-prompt`
- **Input:** `{input_data: object, oracle_prompt: string, model?: string}`
- **Output:** `{cells: {entity: {field: {op, confidence, oracle_why}}}, raw_response: string, latency_ms, cost_usd}`
- **Logic:** Use existing LLM adapter; render `oracle_prompt` as system; format `input_data` as user; parse JSON response into cells shape.
- **Files:** same router + reuse adapter from existing strategy.
- **Scope:** M (parsing + error paths)
- **Verify:** curl with sample oracle prompt + input → returns cells.

#### T03 — Extend fixture schema
- Add fields to fixture JSON: `oracle_prompt: string` (the generated oracle prompt), `oracle_prompt_version: string` (timestamp / hash), `meta_prompt_version: string` (server constant version).
- `_normalize_fixture_for_ui` reads these fields and surfaces them in the API response.
- **Files:** router.py (normalize + generate path)
- **Scope:** XS
- **Verify:** GET on existing fixture returns new fields (empty string for old ones).

#### T04 — `POST /oracle-review/{fixture_id}/promote-to-suite`
- **Input:** `{target_suite_id: string, case_id?: string}` (defaults to fixture_id)
- **Output:** `{written_path: string, case_id: string}`
- **Logic:** Read fixture JSON; write a YAML or JSON case file into the target suite's cases dir (e.g. `eval_fixtures/cases/<suite_id>/<case_id>.yml`); strip review-only fields, keep input + expected.
- **Files:** router.py
- **Scope:** S
- **Verify:** curl → file appears in target dir; subsequent suite run picks it up.

### Phase 2 — Frontend rewiring

#### T05 — Hook the meta-generate flow into Tab 2
- Replace `useOraclePrompt(fixtureId)` (which calls server-side render) with `useMetaGenerateOracle()` mutation.
- Tab 2 redesign:
  - Banner "Step 2: Generate oracle prompt from production prompt"
  - Button: "▶ Generate oracle prompt" → calls meta-generate with Tab 1's production prompt
  - Result rendered into a large editable textarea (`oracle_prompt`)
  - Save button persists to fixture (calls PATCH fixture, T03)
- **Files:** `hooks.ts` (new `useMetaGenerateOracle`), `OracleReviewPage.tsx` (Tab2_OraclePrompt rewrite).
- **Scope:** M
- **Verify:** click Generate → oracle prompt fills the textarea; edits persist on reload.

#### T06 — Wire Tab 3 to run-with-prompt
- Replace `useRunOracle` with `useRunWithPrompt`; pass the edited oracle_prompt from Tab 2.
- Tab 3: Run button now sends `{oracle_prompt, input_data}` → preview cells without writing to fixture (preview mode unchanged).
- Add "Save expectation" button that writes the preview to the fixture (separate from Save in Tab 4).
- **Files:** `hooks.ts`, Tab3_Expectation in `OracleReviewPage.tsx`.
- **Scope:** M

#### T07 — Tab 4 confidence-based auto-approve
- For each `review_item` with `confidence === "high"`, default `pendingAction: approve` (visual checkbox ticked).
- For `low|medium`, highlight border + require explicit click.
- Add side-by-side panel: oracle `expected` on left, parsed Actual Output (from Tab 1 sessionStorage) on right, diff cell colors when op differs.
- **Files:** Tab4_Review in `OracleReviewPage.tsx`.
- **Scope:** M

#### T08 — "Save to suite" button (step 5)
- Add prominent button at top of Tab 4: "Save & promote to suite…" → modal asks for `target_suite_id`, calls T04 endpoint.
- After success: toast + redirect to suite detail.
- **Files:** `OracleReviewPage.tsx`, `hooks.ts`.
- **Scope:** S

### Phase 3 — Cross-domain validation

#### T09 — Test with non-CRUD production prompt
- Provide a sample Anki flashcard generation prompt; run end-to-end (Tab 1 → 5).
- Verify oracle prompt makes sense (independent reasoning, no Anki rules copied).
- **Scope:** XS (manual test, no code)

#### T10 — Update spec doc with empirical findings
- Add a "Cross-domain test results" section to the source spec.
- **Scope:** XS

---

## 4. Task Summary

| ID | Title | Phase | Files | Deps | Size |
|----|-------|-------|-------|------|------|
| T01 | `meta-generate` endpoint | 1 | router.py, meta_prompt.py | None | S |
| T02 | `run-with-prompt` endpoint | 1 | router.py | T01 | M |
| T03 | Fixture schema fields | 1 | router.py | T01 | XS |
| T04 | `promote-to-suite` endpoint | 1 | router.py | T03 | S |
| T05 | Tab 2 meta-generate UI | 2 | hooks.ts, OracleReviewPage.tsx | T01, T03 | M |
| T06 | Tab 3 run-with-prompt UI | 2 | hooks.ts, OracleReviewPage.tsx | T02, T05 | M |
| T07 | Tab 4 confidence routing + diff | 2 | OracleReviewPage.tsx | T06 | M |
| T08 | "Save to suite" UI | 2 | hooks.ts, OracleReviewPage.tsx | T04, T07 | S |
| T09 | Cross-domain manual test | 3 | — | T08 | XS |
| T10 | Update spec doc | 3 | spec md | T09 | XS |

**Execution order:** T01 → T02 → T03 → T04 → T05 → T06 → T07 → T08 → T09 → T10
Frontend tasks (T05–T08) gated on their respective backend endpoints.

---

## 5. Open Questions

1. **4 tabs vs 5 tabs?** Spec says 5; merging step 5 into step 4's "Save & promote" button gives 4. Recommend 4. Confirm.
2. **Meta-prompt LLM model:** Opus 4.7 confirmed per spec, but expensive. Allow override per call? Default Opus, env-overridable.
3. **Where to write promoted fixtures?** Spec uses suite_id `eval_fixtures/cases/<suite_id>/`. Per-project? Currently uaaf-framework has no concept of project-level fixture dirs in the oracle path. Need to confirm target dir resolver.
4. **Should old `CrudMatrixOracleStrategy` stay?** It's still wired in `dev_server.py` (`oracle_strategy_factory=CrudMatrixOracleStrategy`). Plan: keep it as fallback when meta-prompt fails; deprecate later.
5. **Versioning meta-prompt:** semantic version string in `meta_prompt.py` (e.g. `META_PROMPT_VERSION = "1.0.0"`), bumped on edits.

---

## 6. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Meta-prompt output not parseable as oracle prompt format | High | Treat as raw text; let user edit before running |
| Run-with-prompt LLM cost spikes (Opus) | Med | Show cost preview; cap budget per call (e.g. $0.50) |
| Auto-generated oracle prompt copies forbidden HOW rules | Med | Surface a "lint" step that flags suspicious copy-paste; manual review in tab 2 |
| Suite promote overwrites existing case | Med | If file exists, require confirm + suffix `_v2` |
| Cross-domain failure modes hidden | Low | T09 explicit cross-domain test gate before declaring "done" |

---

## 7. Out of Scope (this plan)

- Multi-LLM A/B for oracle (run with Opus + GPT-4 + compare)
- Bulk meta-generate for N fixtures in one click
- Diff viewer for oracle_prompt versions over time
- UI for editing the meta-prompt itself (intentional — keeping it server-side per architecture decision)
