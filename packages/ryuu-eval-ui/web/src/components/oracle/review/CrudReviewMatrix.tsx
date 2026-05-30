/**
 * CrudReviewMatrix — interactive review surface for Tab 4.
 *
 * Detects whether the fixture's expected output is a CRUD matrix. If so it
 * renders a per-entity, collapsible, action-able table driven by `expected`
 * (all cells) overlaid with review state. Otherwise it falls back to the
 * read-only CellsView so non-CRUD domains (Anki, classification…) still render.
 */
import { useMemo, useState, type FC } from "react";
import { CellsView } from "@/components/oracle/CellsView";
import type { OracleFixtureDetail, ReviewActionPayload } from "@/api/types";
import {
  buildRows,
  groupByEntity,
  computeProgress,
  isCrudReviewable,
  type RowVM,
} from "./reviewModel";
import { ReviewSection } from "./ReviewSection";
import { ReviewProgress, type ReviewFilter } from "./ReviewProgress";

function applyFilter(rows: RowVM[], filter: ReviewFilter): RowVM[] {
  if (filter === "pending") return rows.filter(r => r.status === "pending");
  if (filter === "reviewed") return rows.filter(r => r.status !== "pending");
  return rows;
}

export const CrudReviewMatrix: FC<{
  fixture: Pick<OracleFixtureDetail, "expected" | "review_items">;
  pendingActions: ReviewActionPayload[];
  onAction: (a: ReviewActionPayload) => void;
}> = ({ fixture, pendingActions, onAction }) => {
  const [filter, setFilter] = useState<ReviewFilter>("all");

  const rows = useMemo(() => buildRows(fixture, pendingActions), [fixture, pendingActions]);
  const progress = useMemo(() => computeProgress(rows), [rows]);

  if (!isCrudReviewable(fixture.expected)) {
    return <CellsView cells={fixture.expected} />;
  }

  const sections = groupByEntity(applyFilter(rows, filter));

  return (
    <div className="space-y-3">
      <ReviewProgress progress={progress} filter={filter} onFilter={setFilter} />

      {sections.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 dark:border-gray-700 p-4 text-center text-xs text-gray-400">
          No cells match this filter.
        </div>
      ) : (
        sections.map(section => (
          <ReviewSection
            key={section.entity}
            section={section}
            defaultOpen={filter === "pending" || section.pending > 0}
            onAction={onAction}
          />
        ))
      )}
    </div>
  );
};
