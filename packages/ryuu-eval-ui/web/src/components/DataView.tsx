/**
 * DataView — one shared renderer for any input/output value across the eval UI.
 *
 * Wherever the UI shows a JSON blob (case input, expected/actual, run output),
 * mount <DataView/> instead of a raw <pre>. It offers tabbed views and only
 * shows the tabs that make sense for the data:
 *
 *   • JSON       — always. Pretty-printed.
 *   • Table      — always. Delegates to CellsView's shape registry
 *                  (CRUD matrix → list → flat key/value → JSON fallback).
 *   • Call chain — only when the value carries a `call_subgraph`-shaped object.
 *                  Renders the existing CallSequenceDiagram.
 *   • Diff       — only when `expected` is supplied. Renders ReactDiffViewer.
 *
 * It does NOT reimplement any renderer — it composes CellsView,
 * CallSequenceDiagram, and ReactDiffViewer. Adding a new table shape still
 * means appending to CellsView's RENDERERS, nothing here.
 */

import { useMemo, useState } from "react";
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import { CellsView } from "@/components/oracle/CellsView";
import { CallSequenceDiagram } from "@/components/CallSequenceDiagram";
import { buildCrudOpDiffValues, coerce, detectCallSubgraph } from "@/components/dataViewModel";

// ── Types ──────────────────────────────────────────────────────────────────

export type DataViewMode = "json" | "table" | "callchain" | "diff";

interface DataViewProps {
  /** Primary value to display (the "actual"/output). */
  value: unknown;
  /** When present, enables a Diff tab and side-by-side JSON/Table columns. */
  expected?: unknown;
  /** Optional source context used to align expected field names with actual db columns. */
  inputData?: unknown;
  /** Force the initial tab. Falls back to the first available tab. */
  defaultMode?: DataViewMode;
  /** Max height of scrollable panels (Tailwind class, e.g. "max-h-72"). */
  maxHeight?: string;
  /** Column labels when `expected` is set (comparison mode). */
  valueLabel?: string;
  expectedLabel?: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Pretty-print, leaving plain strings untouched. Mirrors CaseDetail.stringify. */
function stringify(v: unknown): string {
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}

// ── Tab bar ────────────────────────────────────────────────────────────────

const TAB_LABEL: Record<DataViewMode, string> = {
  table: "⊞ Table",
  json: "{ } JSON",
  callchain: "↳ Call chain",
  diff: "~ Diff",
};

function Panel({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      {title && (
        <div className="px-3 py-2 bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 text-xs font-medium text-gray-500">
          {title}
        </div>
      )}
      <div className="px-3 py-3">{children}</div>
    </div>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function DataView({
  value,
  expected,
  inputData,
  defaultMode,
  maxHeight = "max-h-72",
  valueLabel = "Actual",
  expectedLabel = "Expected",
}: DataViewProps) {
  const hasExpected = expected !== undefined;

  const parsedValue = useMemo(() => coerce(value), [value]);
  const parsedExpected = useMemo(() => coerce(expected), [expected]);

  const subgraph = useMemo(() => detectCallSubgraph(parsedValue), [parsedValue]);

  // Available tabs in display order; only the relevant ones appear.
  const tabs = useMemo<DataViewMode[]>(() => {
    const t: DataViewMode[] = ["table", "json"];
    if (subgraph) t.push("callchain");
    if (hasExpected) t.push("diff");
    return t;
  }, [subgraph, hasExpected]);

  const [mode, setMode] = useState<DataViewMode>(
    defaultMode && (defaultMode === "table" || defaultMode === "json" || subgraph || hasExpected)
      ? defaultMode
      : tabs[0]
  );
  // Guard against a forced mode that isn't actually available.
  const activeMode = tabs.includes(mode) ? mode : tabs[0];

  const valueStr = stringify(parsedValue);
  const expectedStr = stringify(parsedExpected);
  const diffValues = useMemo(
    () => buildCrudOpDiffValues(parsedExpected, parsedValue, inputData),
    [parsedExpected, parsedValue, inputData],
  );
  const diffValueStr = stringify(diffValues.actual);
  const diffExpectedStr = stringify(diffValues.expected);
  const scroll = `overflow-auto ${maxHeight}`;

  return (
    <div className="space-y-3">
      {/* Tab bar */}
      <div className="flex rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden text-xs w-fit">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setMode(t)}
            className={`px-3 py-1 font-mono transition-colors ${
              activeMode === t
                ? "bg-purple-600 text-white"
                : "bg-white dark:bg-gray-900 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800"
            }`}
          >
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>

      {/* Table — delegate to CellsView's shape registry */}
      {activeMode === "table" && (
        hasExpected ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Panel title={expectedLabel}><CellsView cells={parsedExpected} /></Panel>
            <Panel title={valueLabel}><CellsView cells={parsedValue} /></Panel>
          </div>
        ) : (
          <CellsView cells={parsedValue} />
        )
      )}

      {/* JSON — pretty-printed */}
      {activeMode === "json" && (
        hasExpected ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Panel title={expectedLabel}>
              <pre className={`text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words ${scroll}`}>{expectedStr}</pre>
            </Panel>
            <Panel title={valueLabel}>
              <pre className={`text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words ${scroll}`}>{valueStr}</pre>
            </Panel>
          </div>
        ) : (
          <pre className={`rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 p-3 text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words ${scroll}`}>
            {valueStr}
          </pre>
        )
      )}

      {/* Call chain */}
      {activeMode === "callchain" && subgraph && (
        <CallSequenceDiagram subgraph={subgraph} />
      )}

      {/* Diff */}
      {activeMode === "diff" && hasExpected && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden text-xs">
          <ReactDiffViewer
            oldValue={diffExpectedStr}
            newValue={diffValueStr}
            leftTitle="Expectation"
            rightTitle="Actual"
            splitView
            compareMethod={DiffMethod.WORDS}
            useDarkTheme={typeof document !== "undefined" && document.documentElement.classList.contains("dark")}
            styles={{ variables: { dark: { diffViewerBackground: "#111" } } }}
          />
        </div>
      )}
    </div>
  );
}
