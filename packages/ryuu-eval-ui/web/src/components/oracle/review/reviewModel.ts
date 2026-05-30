/**
 * reviewModel — pure logic for the CRUD review matrix (no React).
 *
 * Tab 4 renders ALL cells of a fixture (high + medium + low), grouped into
 * collapsible per-entity sections, with per-cell approve/edit(op)/delete.
 * `fixture.review_items` only carries the low/medium cells that need a human;
 * high-confidence cells live only in `fixture.expected`. So the matrix is
 * driven by `expected` and overlays review state from `review_items` (persisted)
 * and `pendingActions` (unsaved, local).
 *
 * Everything here is pure and unit-tested (reviewModel.test.ts) so the UI
 * components stay thin and a future progress-tracking layer has a stable seam.
 */

import type {
  OracleConfidence,
  ReviewAction,
  ReviewActionPayload,
  OracleFixtureDetail,
} from "@/api/types";

// ── Shape detection / unwrap (mirrors backend router._unwrap_extra_nesting) ──

function looksLikeCell(o: unknown): boolean {
  if (!o || typeof o !== "object" || Array.isArray(o)) return false;
  const c = o as Record<string, unknown>;
  return (
    c.op != null ||
    c.confidence != null ||
    c.verdict != null ||
    c.score != null ||
    c.value != null
  );
}

/** True iff cells == {entity: {field: cell}} with cell leaves. */
export function isCrud2Level(cells: unknown): boolean {
  if (!cells || typeof cells !== "object" || Array.isArray(cells)) return false;
  const entries = Object.values(cells as Record<string, unknown>);
  if (entries.length === 0) return false;
  for (const fields of entries) {
    if (!fields || typeof fields !== "object" || Array.isArray(fields)) return false;
    const leaves = Object.values(fields as Record<string, unknown>);
    if (leaves.length === 0) return false;
    if (!leaves.every(looksLikeCell)) return false;
  }
  return true;
}

/**
 * Strip a single placeholder wrapper key the oracle LLM sometimes leaks
 * (e.g. {"$FUNCTION_NAME": {entity: {field: cell}}}). A genuine single-entity
 * matrix is detected as 2-level first and left untouched.
 */
export function unwrapCells(cells: unknown): Record<string, Record<string, CellLike>> {
  if (!cells || typeof cells !== "object" || Array.isArray(cells)) return {};
  if (isCrud2Level(cells)) return cells as Record<string, Record<string, CellLike>>;
  const keys = Object.keys(cells as Record<string, unknown>);
  if (keys.length === 1) {
    const inner = (cells as Record<string, unknown>)[keys[0]];
    if (isCrud2Level(inner)) return inner as Record<string, Record<string, CellLike>>;
  }
  return cells as Record<string, Record<string, CellLike>>;
}

/** Can this fixture's expected matrix be shown as an interactive CRUD table? */
export function isCrudReviewable(expected: unknown): boolean {
  return isCrud2Level(unwrapCells(expected));
}

// ── View models ──────────────────────────────────────────────────────────────

export interface CellLike {
  op?: unknown;
  confidence?: unknown;
  why?: unknown;
  oracle_why?: unknown;
  [k: string]: unknown;
}

export type RowStatus = "auto" | "pending" | "approved" | "fixed" | "removed";

export interface RowVM {
  entity: string;
  field: string;
  op: string;
  confidence: OracleConfidence;
  why: string;
  /** confidence ∈ {low, medium} → a human must look at it. */
  needsReview: boolean;
  /** pending (unsaved) overrides persisted; null = no action yet. */
  effectiveAction: ReviewAction | null;
  status: RowStatus;
}

export interface SectionVM {
  entity: string;
  rows: RowVM[];
  total: number;
  /** rows that no longer need a human (status !== "pending"). */
  resolved: number;
  /** low/medium rows still awaiting an action. */
  pending: number;
}

export interface Progress {
  /** all non-removed cells. */
  total: number;
  /** auto (high) + approved + fixed. */
  resolved: number;
  /** low/medium not yet acted on. */
  pending: number;
  /** resolved / total, 0–100. Empty matrix → 100. */
  pct: number;
}

// ── Builders ──────────────────────────────────────────────────────────────────

/**
 * Mirror backend semantics: a missing/unknown confidence is treated as "high"
 * (the backend's needs_review only flags explicit low/medium), so a malformed
 * leaf does not silently become a blocking review item.
 */
export function normalizeConfidence(v: unknown): OracleConfidence {
  return v === "low" || v === "medium" || v === "high" ? v : "high";
}

function statusFor(action: ReviewAction | null, needsReview: boolean): RowStatus {
  if (action === "remove") return "removed";
  if (action === "fix") return "fixed";
  if (action === "approve") return "approved";
  return needsReview ? "pending" : "auto";
}

const key = (entity: string, field: string) => `${entity}::${field}`;

/** Flatten expected + overlay review state → one RowVM per cell. */
export function buildRows(
  fixture: Pick<OracleFixtureDetail, "expected" | "review_items">,
  pendingActions: ReviewActionPayload[],
): RowVM[] {
  const cells = unwrapCells(fixture.expected);
  const pendingMap = new Map(pendingActions.map(a => [key(a.entity, a.field), a]));
  const persistedMap = new Map(
    (fixture.review_items ?? [])
      .filter(it => it.action != null)
      .map(it => [key(it.entity, it.field), it.action as ReviewAction]),
  );

  const rows: RowVM[] = [];
  for (const [entity, fields] of Object.entries(cells)) {
    if (!fields || typeof fields !== "object") continue;
    for (const [field, cellRaw] of Object.entries(fields as Record<string, CellLike>)) {
      const cell = (cellRaw ?? {}) as CellLike;
      const confidence = normalizeConfidence(cell.confidence);
      const needsReview = confidence !== "high";
      const k = key(entity, field);
      const effectiveAction: ReviewAction | null =
        pendingMap.get(k)?.action ?? persistedMap.get(k) ?? null;
      rows.push({
        entity,
        field,
        op: cell.op == null ? "" : String(cell.op),
        confidence,
        why: String(cell.oracle_why ?? cell.why ?? ""),
        needsReview,
        effectiveAction,
        status: statusFor(effectiveAction, needsReview),
      });
    }
  }
  return rows;
}

/** Group rows by entity, preserving first-seen order. */
export function groupByEntity(rows: RowVM[]): SectionVM[] {
  const order: string[] = [];
  const byEntity = new Map<string, RowVM[]>();
  for (const r of rows) {
    if (!byEntity.has(r.entity)) {
      byEntity.set(r.entity, []);
      order.push(r.entity);
    }
    byEntity.get(r.entity)!.push(r);
  }
  return order.map(entity => {
    const list = byEntity.get(entity)!;
    const pending = list.filter(r => r.status === "pending").length;
    return {
      entity,
      rows: list,
      total: list.length,
      resolved: list.length - pending,
      pending,
    };
  });
}

/** Overall progress across the matrix; removed cells drop out of the total. */
export function computeProgress(rows: RowVM[]): Progress {
  const live = rows.filter(r => r.status !== "removed");
  const pending = live.filter(r => r.status === "pending").length;
  const total = live.length;
  const resolved = total - pending;
  const pct = total === 0 ? 100 : Math.round((resolved / total) * 100);
  return { total, resolved, pending, pct };
}

/** Cells still blocking promotion (low/medium not yet acted on). */
export function countPendingReview(rows: RowVM[]): number {
  return rows.filter(r => r.status === "pending").length;
}
