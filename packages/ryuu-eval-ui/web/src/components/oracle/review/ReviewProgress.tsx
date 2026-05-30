/**
 * ReviewProgress — overall progress bar + focus filter for the review matrix.
 *
 * Kept deliberately pure-in / pure-out (takes a `Progress`, emits a filter) so a
 * future progress-tracking layer (per-cell reviewed_at, a header stepper, cross
 * session persistence) can reuse the same seam without touching the table.
 */
import type { FC } from "react";
import type { Progress } from "./reviewModel";

export type ReviewFilter = "all" | "pending" | "reviewed";

const FILTERS: { id: ReviewFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "pending", label: "Needs review" },
  { id: "reviewed", label: "Reviewed" },
];

export const ReviewProgress: FC<{
  progress: Progress;
  filter: ReviewFilter;
  onFilter: (f: ReviewFilter) => void;
}> = ({ progress, filter, onFilter }) => {
  const { resolved, total, pending, pct } = progress;
  const done = pending === 0;

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 space-y-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">
          Review progress
        </span>
        <span className="text-[11px] font-semibold">
          {done
            ? <span className="text-green-600 dark:text-green-400">✓ all {total} reviewed</span>
            : <span className="text-yellow-600 dark:text-yellow-400">{resolved}/{total} reviewed · {pending} pending</span>}
        </span>
      </div>

      <div className="h-2 w-full rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${done ? "bg-green-500" : "bg-indigo-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="flex items-center gap-1">
        {FILTERS.map(f => (
          <button
            key={f.id}
            onClick={() => onFilter(f.id)}
            className={`text-[11px] px-2 py-1 rounded border font-medium transition-colors ${
              filter === f.id
                ? "bg-indigo-600 border-indigo-600 text-white"
                : "border-gray-200 dark:border-gray-600 text-gray-500 hover:border-indigo-300 hover:text-indigo-600"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
    </div>
  );
};
