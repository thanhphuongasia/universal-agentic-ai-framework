/**
 * CrudReviewRow — one field of the CRUD matrix as an interactive table row.
 *
 * Columns: Field · OP (inline-editable) · Confidence · Reasoning · Status · Actions.
 * Edit only touches the OP (per product decision) → emits a "fix" action with
 * corrected_op. Approve/Delete map to the existing review actions. The parent
 * dedupes actions by (entity, field), so re-clicking simply overrides.
 */
import { useState, type FC } from "react";
import type { ReviewActionPayload } from "@/api/types";
import type { RowVM, RowStatus } from "./reviewModel";

const OP_COLORS: Record<string, string> = {
  C: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 border-green-200 dark:border-green-700",
  R: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-700",
  U: "bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300 border-yellow-200 dark:border-yellow-700",
  D: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300 border-red-200 dark:border-red-700",
};

const OpChips: FC<{ op: string }> = ({ op }) => {
  if (!op) return <span className="text-gray-400 font-mono text-xs">—</span>;
  return (
    <span className="flex gap-0.5">
      {op.split("").map((ch, i) => (
        <span
          key={`${ch}${i}`}
          className={`font-mono text-xs font-bold px-1.5 py-0.5 rounded border ${OP_COLORS[ch] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-600"}`}
        >
          {ch}
        </span>
      ))}
    </span>
  );
};

const CONF_CLS: Record<string, string> = {
  high: "text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800",
  medium: "text-yellow-700 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950 border-yellow-200 dark:border-yellow-800",
  low: "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800",
};

const STATUS_META: Record<RowStatus, { label: string; cls: string }> = {
  auto: { label: "auto ✓", cls: "text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 border-gray-200 dark:border-gray-700" },
  pending: { label: "needs review", cls: "text-yellow-700 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950 border-yellow-300 dark:border-yellow-800" },
  approved: { label: "approved", cls: "text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950 border-green-300 dark:border-green-800" },
  fixed: { label: "edited", cls: "text-indigo-700 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950 border-indigo-300 dark:border-indigo-800" },
  removed: { label: "removed", cls: "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950 border-red-300 dark:border-red-800" },
};

const ROW_TINT: Record<RowStatus, string> = {
  auto: "",
  pending: "bg-yellow-50/40 dark:bg-yellow-950/20",
  approved: "bg-green-50/40 dark:bg-green-950/15",
  fixed: "bg-indigo-50/40 dark:bg-indigo-950/15",
  removed: "bg-red-50/40 dark:bg-red-950/15 opacity-70",
};

export const CrudReviewRow: FC<{
  row: RowVM;
  onAction: (a: ReviewActionPayload) => void;
}> = ({ row, onAction }) => {
  const [editing, setEditing] = useState(false);
  const [draftOp, setDraftOp] = useState(row.op);

  const emit = (action: ReviewActionPayload["action"], corrected_op?: string) =>
    onAction({ entity: row.entity, field: row.field, action, corrected_op });

  const applyFix = () => {
    const v = draftOp.trim().toUpperCase();
    if (v) emit("fix", v);
    setEditing(false);
  };

  const status = STATUS_META[row.status];
  const removed = row.status === "removed";

  return (
    <tr className={`border-b border-gray-100 dark:border-gray-800 transition-colors ${ROW_TINT[row.status]}`}>
      <td className="px-3 py-2 font-mono text-gray-600 dark:text-gray-300 align-top">{row.field}</td>

      <td className="px-3 py-2 align-top">
        {editing ? (
          <div className="flex items-center gap-1">
            <input
              autoFocus
              className="w-20 text-xs border border-indigo-300 dark:border-indigo-700 rounded px-1.5 py-1 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 font-mono uppercase focus:outline-none focus:border-indigo-500"
              value={draftOp}
              placeholder="e.g. RU"
              onChange={e => setDraftOp(e.target.value.toUpperCase())}
              onKeyDown={e => {
                if (e.key === "Enter") applyFix();
                if (e.key === "Escape") { setEditing(false); setDraftOp(row.op); }
              }}
            />
            <button onClick={applyFix} className="text-[11px] px-1.5 py-1 rounded bg-indigo-600 text-white font-semibold">✓</button>
            <button onClick={() => { setEditing(false); setDraftOp(row.op); }} className="text-[11px] px-1.5 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-500">✕</button>
          </div>
        ) : (
          <span className={removed ? "line-through opacity-60" : ""}><OpChips op={row.op} /></span>
        )}
      </td>

      <td className="px-3 py-2 align-top">
        <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${CONF_CLS[row.confidence]}`}>
          {row.confidence}
        </span>
      </td>

      <td className="px-3 py-2 text-[11px] text-gray-500 dark:text-gray-400 max-w-[280px] align-top">
        <span className="line-clamp-2" title={row.why}>{row.why || "—"}</span>
      </td>

      <td className="px-3 py-2 align-top">
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border whitespace-nowrap ${status.cls}`}>
          {status.label}
        </span>
      </td>

      <td className="px-3 py-2 align-top">
        <div className="flex items-center gap-1 justify-end">
          <button
            onClick={() => emit("approve")}
            title="Approve as ground truth"
            className={`text-[11px] px-2 py-1 rounded border font-medium transition-colors ${row.effectiveAction === "approve" ? "bg-green-500 border-green-500 text-white" : "border-gray-200 dark:border-gray-600 text-gray-500 hover:border-green-300 hover:text-green-600"}`}
          >✓</button>
          <button
            onClick={() => { setEditing(e => !e); setDraftOp(row.op); }}
            title="Edit the CRUD op"
            className={`text-[11px] px-2 py-1 rounded border font-medium transition-colors ${row.effectiveAction === "fix" ? "bg-indigo-500 border-indigo-500 text-white" : "border-gray-200 dark:border-gray-600 text-gray-500 hover:border-indigo-300 hover:text-indigo-600"}`}
          >✏</button>
          <button
            onClick={() => emit("remove")}
            title="Remove this cell from the matrix"
            className={`text-[11px] px-2 py-1 rounded border font-medium transition-colors ${row.effectiveAction === "remove" ? "bg-red-500 border-red-500 text-white" : "border-gray-200 dark:border-gray-600 text-gray-500 hover:border-red-300 hover:text-red-600"}`}
          >🗑</button>
        </div>
      </td>
    </tr>
  );
};
