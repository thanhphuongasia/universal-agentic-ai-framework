# Plan — Generic `DataView` (JSON / Table / Call chain) across eval UI

> Status: PLANNED (next session). Goal: wherever the UI shows input/output JSON,
> offer JSON + Table + Call-chain views from one shared component, with
> CRUD-specific rendering when the data is a CRUD matrix.

## Why

Today raw JSON is shown in several places; only `CaseDetail` has a view-switcher
(and only for Expected-vs-Actual). The pieces to do this well already exist but
are scattered — this plan consolidates them into one reusable component and
applies it everywhere.

## Reusable pieces that already exist (do NOT rebuild)

| Piece | File | Notes |
|---|---|---|
| Call-chain view | `packages/ryuu-eval-ui/web/src/components/CallSequenceDiagram.tsx` (`CallSequenceDiagram`) | currently used in `SuiteDetail.tsx` |
| View-switcher Table/JSON/Diff | inline in `src/pages/CaseDetail.tsx` — state `viewMode` (~line 243), tab bar (~line 394), branches (411/433/447) | extract into the shared component |
| CRUD cells table | `src/components/oracle/CellsView.tsx` | used in `OracleReviewPage` |
| Recursive stringify helper | `CaseDetail.tsx` `stringify()` / `toDisplayString()` | reuse for JSON view |

## Design — `<DataView>`

New component: `src/components/DataView.tsx`

```tsx
type DataViewKind = "auto" | "crud" | "callchain" | "plain";
interface DataViewProps {
  value: unknown;            // the input or output object/string
  expected?: unknown;        // when present, enables a Diff tab (expected vs value)
  kind?: DataViewKind;       // default "auto" — detect from shape
  defaultMode?: "json" | "table" | "callchain" | "diff";
  maxHeight?: string;
}
```

Tabs shown (only the relevant ones):
- **JSON** — always. Pretty-printed (reuse `stringify`).
- **Table** — always. Recursive key/value table for generic objects; for CRUD
  (`kind="crud"` or detected `{entity: {field: op}}` / `{cells: [...]}`) render
  via `CellsView`.
- **Call chain** — when the value has a route/sequence shape (`route`, `contexts`,
  `participants`/`messages`, or `CallSequenceDiagram`'s expected input) → render
  `CallSequenceDiagram`.
- **Diff** — only when `expected` is provided (move CaseDetail's diff here).

Detection (`kind="auto"`): CRUD if two-level `{str: {str: str}}` with C/R/U/D-ish
values or a `cells` array; call-chain if `route`/`contexts`/`participants` keys;
else plain.

## Where to apply

1. **CaseDetail** (`src/pages/CaseDetail.tsx`) — replace the inline Table/JSON/Diff
   block with `<DataView value={actual} expected={expected} kind={...} />`; add the
   Call-chain tab. Also wrap the INPUT section.
2. **SuiteDetail** (`src/pages/SuiteDetail.tsx`) — case input/expected preview.
3. **RunResults / run history** (`src/pages/RunResults.tsx`, run monitor) — per-case
   output.
4. (Optional) **OracleReviewPage** Tab 1 input + preview — route context as call chain.

## Steps

1. Extract `DataView.tsx` consolidating the three existing renderers + detection.
2. Unit-test detection (node strip-types `*.test.ts`, the repo's web test style).
3. Swap CaseDetail's inline switcher → `DataView` (verify diff/table parity).
4. Apply to SuiteDetail, RunResults.
5. tsc --noEmit clean; manual smoke on crud_matrix_llm (CRUD table) +
   class_diagram/sequence_diagram (call chain).

## Acceptance

- One `<DataView>` used by CaseDetail, SuiteDetail, RunResults.
- CRUD suite → cells table; diagram suites → call chain; generic → key/value table.
- JSON always available; Diff only when expected present. No regression in CaseDetail.
