/**
 * CellsView — pluggable renderer for oracle output cells.
 *
 * Each domain emits a different shape (CRUD matrix nests entity→field→cell,
 * Anki produces an array of cards, classification produces flat label→score,
 * summary is a single object…). Hardcoding any one shape into the page is
 * fragile. CellsView dispatches to a registered renderer based on shape
 * detection, falling back to a pretty-printed JSON tree.
 *
 * Adding a new shape = append a `CellsRenderer` to RENDERERS. No edit
 * required anywhere else.
 */

import { useState } from "react";
import type { FC } from "react";

// ── Plugin contract ──────────────────────────────────────────────────────────

export interface CellsRenderer {
  /** Stable identifier for debug/telemetry. */
  shape: string;
  /** Return true if this renderer can display the given cells. Order matters
   *  — the first matching renderer in RENDERERS wins. */
  detect: (cells: unknown) => boolean;
  /** React component rendering the cells. */
  Component: FC<{ cells: unknown }>;
}

// ── Built-in renderers ───────────────────────────────────────────────────────

/** CRUD shape: { entity: { field: { op|score|verdict|value, ...} } } */
function isCrudShape(cells: unknown): boolean {
  if (!cells || typeof cells !== "object" || Array.isArray(cells)) return false;
  const entries = Object.entries(cells as Record<string, unknown>);
  if (entries.length === 0) return false;
  for (const [, fields] of entries) {
    if (!fields || typeof fields !== "object" || Array.isArray(fields)) return false;
    for (const cell of Object.values(fields as Record<string, unknown>)) {
      if (!cell || typeof cell !== "object" || Array.isArray(cell)) return false;
      const c = cell as Record<string, unknown>;
      if (c.op == null && c.score == null && c.verdict == null && c.value == null) {
        return false;
      }
    }
  }
  return true;
}

const CrudView: FC<{ cells: unknown }> = ({ cells }) => {
  const entities = Object.entries(cells as Record<string, Record<string, Record<string, unknown>>>);
  return (
    <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
      <table className="w-full text-xs min-w-[560px]">
        <thead>
          <tr className="bg-gray-50 dark:bg-gray-800 text-left">
            {["Entity", "Field", "OP", "Confidence", "Reasoning"].map(h => (
              <th key={h} className="px-3 py-2 font-semibold text-gray-600 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entities.flatMap(([entity, fields]) =>
            Object.entries(fields).map(([field, cell]) => {
              const op = String(cell.op ?? cell.score ?? cell.verdict ?? cell.value ?? "");
              const conf = String(cell.confidence ?? "");
              const why = String(cell.oracle_why ?? cell.why ?? cell.reason ?? "");
              return (
                <tr key={`${entity}::${field}`} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                  <td className="px-3 py-2 font-mono font-medium text-gray-700 dark:text-gray-300">{entity}</td>
                  <td className="px-3 py-2 font-mono text-gray-500 dark:text-gray-400">{field}</td>
                  <td className="px-3 py-2 font-mono font-semibold">{op || "—"}</td>
                  <td className="px-3 py-2">{conf && <span className="text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">{conf}</span>}</td>
                  <td className="px-3 py-2 text-gray-500 dark:text-gray-400 max-w-[240px] truncate" title={why}>{why}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
};

/** List shape: { collection_key: [ {item}, {item}, ... ] } */
function isListShape(cells: unknown): boolean {
  if (!cells || typeof cells !== "object" || Array.isArray(cells)) return false;
  const values = Object.values(cells as Record<string, unknown>);
  return values.length > 0 && values.every(v => Array.isArray(v));
}

const ListView: FC<{ cells: unknown }> = ({ cells }) => {
  const groups = Object.entries(cells as Record<string, unknown[]>);
  // Collect union of keys across all items for stable columns.
  const itemKeys = (items: unknown[]): string[] => {
    const seen = new Set<string>();
    for (const it of items) {
      if (it && typeof it === "object" && !Array.isArray(it)) {
        for (const k of Object.keys(it as object)) seen.add(k);
      }
    }
    return Array.from(seen);
  };

  return (
    <div className="space-y-3">
      {groups.map(([key, items]) => {
        const cols = itemKeys(items);
        return (
          <div key={key}>
            <div className="text-[10px] uppercase font-semibold tracking-wider text-gray-500 dark:text-gray-400 mb-1">
              {key} <span className="font-normal text-gray-400">· {items.length} items</span>
            </div>
            <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
              <table className="w-full text-xs min-w-[400px]">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-800 text-left">
                    <th className="px-3 py-2 font-semibold text-gray-600 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">#</th>
                    {cols.map(c => (
                      <th key={c} className="px-3 py-2 font-semibold text-gray-600 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((it, i) => (
                    <tr key={i} className="border-b border-gray-100 dark:border-gray-800">
                      <td className="px-3 py-2 font-mono text-gray-400">{i}</td>
                      {cols.map(c => {
                        const v = (it as Record<string, unknown>)?.[c];
                        const text = v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
                        return (
                          <td key={c} className="px-3 py-2 text-gray-600 dark:text-gray-300 max-w-[280px] truncate" title={text}>{text}</td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
};

/** Flat key/value shape: { key: primitive, ... } */
function isFlatShape(cells: unknown): boolean {
  if (!cells || typeof cells !== "object" || Array.isArray(cells)) return false;
  const values = Object.values(cells as Record<string, unknown>);
  if (values.length === 0) return false;
  return values.every(v => v === null || typeof v !== "object");
}

const FlatView: FC<{ cells: unknown }> = ({ cells }) => {
  const rows = Object.entries(cells as Record<string, unknown>);
  return (
    <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
      <table className="w-full text-xs min-w-[300px]">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-b border-gray-100 dark:border-gray-800">
              <td className="px-3 py-2 font-mono font-semibold text-gray-700 dark:text-gray-300 align-top">{k}</td>
              <td className="px-3 py-2 text-gray-600 dark:text-gray-300 break-all">{String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

/** Generic object/array shape: anything structured that isn't crud/list/flat.
 *  Renders a recursive key/value table — nested objects become nested tables,
 *  arrays of objects become columnar sub-tables — so a mixed payload like
 *  `{total, contexts:{…}}` reads as a table instead of raw JSON. */
function isObjectShape(cells: unknown): boolean {
  return cells !== null && typeof cells === "object";
}

function _isPrimitive(v: unknown): boolean {
  return v === null || typeof v !== "object";
}

function _primText(v: unknown): string {
  if (v === null) return "null";
  if (v === "") return '""';
  return String(v);
}

/** One-line summary of a nested object/array, shown when collapsed. */
function _summary(v: object): string {
  if (Array.isArray(v)) return `[${v.length} item${v.length === 1 ? "" : "s"}]`;
  const n = Object.keys(v).length;
  return `{${n} field${n === 1 ? "" : "s"}}`;
}

/** Collapsible wrapper for a nested object/array — default CLOSED, click to
 *  expand into a sub-table. Keeps deep payloads compact (no horizontal sprawl). */
const Collapsible: FC<{ v: object }> = ({ v }) => {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 font-mono text-xs text-gray-400 hover:text-purple-600 dark:hover:text-purple-400 select-none"
      >
        <span className="w-3 text-center">{open ? "▾" : "▸"}</span>
        <span>{_summary(v)}</span>
      </button>
      {open && <div className="mt-1.5"><Inner v={v} /></div>}
    </div>
  );
};

/** Recursive value renderer used by the object/array tables.
 *  Primitives + primitive arrays render inline; nested objects/arrays render
 *  as a collapsible (closed by default). */
const Value: FC<{ v: unknown }> = ({ v }) => {
  if (_isPrimitive(v)) {
    return <span className="font-mono text-gray-700 dark:text-gray-300 break-all">{_primText(v)}</span>;
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="text-gray-400">[]</span>;
    if (v.every(_isPrimitive)) {
      return <span className="font-mono text-gray-600 dark:text-gray-400 break-all">{v.map(_primText).join(", ")}</span>;
    }
    return <Collapsible v={v} />;
  }
  if (Object.keys(v as object).length === 0) return <span className="text-gray-400">{"{}"}</span>;
  return <Collapsible v={v as object} />;
};

const KVTable: FC<{ obj: Record<string, unknown> }> = ({ obj }) => {
  const rows = Object.entries(obj);
  if (rows.length === 0) return <span className="text-gray-400">{"{}"}</span>;
  return (
    <table className="w-full text-xs border border-gray-200 dark:border-gray-700 rounded overflow-hidden">
      <tbody>
        {rows.map(([k, val]) => (
          <tr key={k} className="border-b border-gray-100 dark:border-gray-800 last:border-0 align-top">
            <td className="px-2 py-1.5 font-mono font-semibold text-gray-600 dark:text-gray-400 whitespace-nowrap align-top">{k}</td>
            <td className="px-2 py-1.5"><Value v={val} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

/** Array of objects → columnar table (union of keys across items). */
const ArrayTable: FC<{ items: unknown[] }> = ({ items }) => {
  const cols: string[] = (() => {
    const seen = new Set<string>();
    for (const it of items) {
      if (it && typeof it === "object" && !Array.isArray(it)) {
        for (const k of Object.keys(it as object)) seen.add(k);
      }
    }
    return Array.from(seen);
  })();
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs border border-gray-200 dark:border-gray-700 rounded min-w-[320px]">
        <thead>
          <tr className="bg-gray-50 dark:bg-gray-800 text-left">
            <th className="px-2 py-1.5 font-semibold text-gray-500 border-b border-gray-200 dark:border-gray-700">#</th>
            {cols.map((c) => (
              <th key={c} className="px-2 py-1.5 font-semibold text-gray-600 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700 whitespace-nowrap">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i} className="border-b border-gray-100 dark:border-gray-800 last:border-0 align-top">
              <td className="px-2 py-1.5 font-mono text-gray-400">{i}</td>
              {cols.map((c) => (
                <td key={c} className="px-2 py-1.5 align-top"><Value v={(it as Record<string, unknown>)?.[c]} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

/** Render an expanded object/array, dispatching to the specialized renderer
 *  when the value matches a known shape (crud → CrudView so op/confidence/why
 *  show as columns; list → ListView; flat → FlatView), else generic tables. */
const Inner: FC<{ v: object }> = ({ v }) => {
  if (Array.isArray(v)) return <ArrayTable items={v} />;
  if (isCrudShape(v)) return <CrudView cells={v} />;
  if (isListShape(v)) return <ListView cells={v} />;
  if (isFlatShape(v)) return <FlatView cells={v} />;
  return <KVTable obj={v as Record<string, unknown>} />;
};

/** Top level renders EXPANDED (nested objects/arrays inside collapse on demand). */
const ObjectView: FC<{ cells: unknown }> = ({ cells }) => <Inner v={cells as object} />;

/** Final fallback: pretty-printed JSON. Always matches. */
const JsonView: FC<{ cells: unknown }> = ({ cells }) => (
  <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3">
    <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-all">
      {JSON.stringify(cells, null, 2)}
    </pre>
  </div>
);

// ── Registry — order matters; first match wins ──────────────────────────────

export const RENDERERS: CellsRenderer[] = [
  { shape: "crud", detect: isCrudShape, Component: CrudView },
  { shape: "list", detect: isListShape, Component: ListView },
  { shape: "flat", detect: isFlatShape, Component: FlatView },
  { shape: "object", detect: isObjectShape, Component: ObjectView }, // recursive tables for mixed objects/arrays
  { shape: "json", detect: () => true, Component: JsonView }, // fallback — always last (primitives)
];

export function pickRenderer(cells: unknown): CellsRenderer {
  return RENDERERS.find(r => r.detect(cells)) ?? RENDERERS[RENDERERS.length - 1];
}

// ── Public component ─────────────────────────────────────────────────────────

export function CellsView({ cells }: { cells: unknown }) {
  const renderer = pickRenderer(cells);
  const Comp = renderer.Component;
  return (
    <div className="space-y-2">
      <div className="text-[10px] text-gray-400">
        view: <span className="font-mono">{renderer.shape}</span>
      </div>
      <Comp cells={cells} />
    </div>
  );
}
