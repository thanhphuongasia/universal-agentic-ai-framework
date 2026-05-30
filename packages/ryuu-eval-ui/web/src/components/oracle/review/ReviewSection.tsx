/**
 * ReviewSection — one entity as a collapsible module.
 *
 * Splitting the matrix per entity keeps long reviews digestible (the user's
 * "review khỏi ngán" requirement). The header carries a mini progress count and
 * a confidence breakdown so the reviewer can triage which sections to open;
 * sections with no pending cells start collapsed.
 */
import { useState, type FC } from "react";
import type { ReviewActionPayload } from "@/api/types";
import type { SectionVM } from "./reviewModel";
import { CrudReviewRow } from "./CrudReviewRow";

const ConfCount: FC<{ n: number; tone: string; label: string }> = ({ n, tone, label }) =>
  n === 0 ? null : (
    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${tone}`} title={`${n} ${label}`}>
      {n} {label}
    </span>
  );

export const ReviewSection: FC<{
  section: SectionVM;
  defaultOpen: boolean;
  onAction: (a: ReviewActionPayload) => void;
}> = ({ section, defaultOpen, onAction }) => {
  const [open, setOpen] = useState(defaultOpen);

  const counts = section.rows.reduce(
    (acc, r) => { acc[r.confidence]++; return acc; },
    { high: 0, medium: 0, low: 0 } as Record<string, number>,
  );

  const approveAllPending = () => {
    for (const r of section.rows) {
      if (r.status === "pending") {
        onAction({ entity: r.entity, field: r.field, action: "approve" });
      }
    }
  };

  const allReviewed = section.pending === 0;

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2 bg-gray-50 dark:bg-gray-800/60 select-none">
        <button
          onClick={() => setOpen(o => !o)}
          className="flex items-center gap-2 flex-1 min-w-0 text-left"
        >
          <span className={`text-gray-400 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
          <span className="font-mono font-semibold text-sm text-gray-700 dark:text-gray-200 truncate">{section.entity}</span>
          <span className={`text-[11px] font-semibold ${allReviewed ? "text-green-600 dark:text-green-400" : "text-yellow-600 dark:text-yellow-400"}`}>
            {allReviewed ? "✓ all reviewed" : `${section.resolved}/${section.total} reviewed`}
          </span>
        </button>
        <div className="flex items-center gap-1 shrink-0">
          <ConfCount n={counts.high} label="high" tone="text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800" />
          <ConfCount n={counts.medium} label="med" tone="text-yellow-700 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950 border-yellow-200 dark:border-yellow-800" />
          <ConfCount n={counts.low} label="low" tone="text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800" />
          {!allReviewed && (
            <button
              onClick={approveAllPending}
              className="ml-1 text-[11px] px-2 py-1 rounded border border-green-300 dark:border-green-700 text-green-700 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-950/40 font-semibold transition-colors"
            >
              ✓ Approve {section.pending} pending
            </button>
          )}
        </div>
      </div>

      {open && (
        <div className="overflow-auto">
          <table className="w-full text-xs min-w-[640px]">
            <thead>
              <tr className="bg-white dark:bg-gray-900 text-left text-gray-500 dark:text-gray-400">
                {["Field", "OP", "Confidence", "Reasoning", "Status", ""].map((h, i) => (
                  <th key={h || `c${i}`} className="px-3 py-1.5 font-semibold border-b border-gray-200 dark:border-gray-700">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.rows.map(row => (
                <CrudReviewRow key={`${row.entity}::${row.field}`} row={row} onAction={onAction} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
