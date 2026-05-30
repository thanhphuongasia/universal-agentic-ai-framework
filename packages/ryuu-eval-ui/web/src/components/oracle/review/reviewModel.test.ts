/**
 * Pure-logic tests for reviewModel. No test-runner dependency — run with:
 *   node --experimental-strip-types --test src/components/oracle/review/reviewModel.test.ts
 * (see npm run test:model)
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  isCrud2Level,
  unwrapCells,
  isCrudReviewable,
  normalizeConfidence,
  buildRows,
  groupByEntity,
  computeProgress,
  countPendingReview,
} from "./reviewModel.ts";

const cell = (op: string, confidence: string, why = "because") => ({ op, confidence, why });

const TWO_LEVEL = {
  Order: { id: cell("R", "high"), total: cell("RU", "medium") },
  User: { email: cell("R", "low") },
};

const WRAPPED = { $FUNCTION_NAME: TWO_LEVEL };

test("isCrud2Level: true for {entity:{field:cell}}", () => {
  assert.equal(isCrud2Level(TWO_LEVEL), true);
});

test("isCrud2Level: false for wrapped 3-level", () => {
  assert.equal(isCrud2Level(WRAPPED), false);
});

test("isCrud2Level: false for flat / list / empty", () => {
  assert.equal(isCrud2Level({ a: 1 }), false);
  assert.equal(isCrud2Level({ k: [1, 2] }), false);
  assert.equal(isCrud2Level({}), false);
  assert.equal(isCrud2Level(null), false);
});

test("unwrapCells: strips single placeholder wrapper", () => {
  assert.deepEqual(Object.keys(unwrapCells(WRAPPED)), ["Order", "User"]);
});

test("unwrapCells: leaves a genuine single-entity matrix untouched", () => {
  const single = { Order: { id: cell("R", "high") } };
  assert.deepEqual(Object.keys(unwrapCells(single)), ["Order"]);
});

test("unwrapCells: non-object → {}", () => {
  assert.deepEqual(unwrapCells(null), {});
  assert.deepEqual(unwrapCells([1, 2]), {});
});

test("isCrudReviewable: true for wrapped (after unwrap) and 2-level, false for non-crud", () => {
  assert.equal(isCrudReviewable(WRAPPED), true);
  assert.equal(isCrudReviewable(TWO_LEVEL), true);
  assert.equal(isCrudReviewable({ cards: [{ q: "a" }] }), false);
});

test("normalizeConfidence: passthrough valid, default unknown → high", () => {
  assert.equal(normalizeConfidence("low"), "low");
  assert.equal(normalizeConfidence("medium"), "medium");
  assert.equal(normalizeConfidence("high"), "high");
  assert.equal(normalizeConfidence(undefined), "high");
  assert.equal(normalizeConfidence("bogus"), "high");
});

test("buildRows: high→auto, low/medium→pending when no action", () => {
  const rows = buildRows({ expected: TWO_LEVEL, review_items: [] }, []);
  assert.equal(rows.length, 3);
  const byField = Object.fromEntries(rows.map(r => [`${r.entity}.${r.field}`, r]));
  assert.equal(byField["Order.id"].status, "auto");
  assert.equal(byField["Order.id"].needsReview, false);
  assert.equal(byField["Order.total"].status, "pending");
  assert.equal(byField["User.email"].status, "pending");
});

test("buildRows: defensively unwraps a leaked $FUNCTION_NAME wrapper", () => {
  const rows = buildRows({ expected: WRAPPED, review_items: [] }, []);
  assert.equal(rows.length, 3);
  assert.ok(rows.every(r => r.entity === "Order" || r.entity === "User"));
});

test("buildRows: pendingActions overlay overrides", () => {
  const rows = buildRows(
    { expected: TWO_LEVEL, review_items: [] },
    [
      { entity: "Order", field: "total", action: "fix", corrected_op: "CU" },
      { entity: "User", field: "email", action: "remove" },
    ],
  );
  const byField = Object.fromEntries(rows.map(r => [`${r.entity}.${r.field}`, r]));
  assert.equal(byField["Order.total"].status, "fixed");
  assert.equal(byField["Order.total"].effectiveAction, "fix");
  assert.equal(byField["User.email"].status, "removed");
});

test("buildRows: persisted review_items action shows when no pending", () => {
  const rows = buildRows(
    {
      expected: TWO_LEVEL,
      review_items: [
        { entity: "Order", field: "total", op: "RU", confidence: "medium", oracle_why: "", action: "approve", corrected_op: null },
      ],
    } as never,
    [],
  );
  const total = rows.find(r => r.field === "total")!;
  assert.equal(total.status, "approved");
});

test("groupByEntity: groups in first-seen order with counts", () => {
  const rows = buildRows({ expected: TWO_LEVEL, review_items: [] }, []);
  const secs = groupByEntity(rows);
  assert.deepEqual(secs.map(s => s.entity), ["Order", "User"]);
  const order = secs[0];
  assert.equal(order.total, 2);
  assert.equal(order.pending, 1); // total is medium
  assert.equal(order.resolved, 1); // id is high → auto
});

test("computeProgress: removed cells drop out of the total", () => {
  const rows = buildRows(
    { expected: TWO_LEVEL, review_items: [] },
    [{ entity: "User", field: "email", action: "remove" }],
  );
  const p = computeProgress(rows);
  assert.equal(p.total, 2); // Order.id + Order.total ; User.email removed
  assert.equal(p.pending, 1); // Order.total
  assert.equal(p.resolved, 1);
  assert.equal(p.pct, 50);
});

test("computeProgress: all high → 100%", () => {
  const allHigh = { A: { x: cell("R", "high"), y: cell("C", "high") } };
  const p = computeProgress(buildRows({ expected: allHigh, review_items: [] }, []));
  assert.equal(p.pct, 100);
  assert.equal(p.pending, 0);
});

test("countPendingReview: counts only pending rows", () => {
  const rows = buildRows({ expected: TWO_LEVEL, review_items: [] }, []);
  assert.equal(countPendingReview(rows), 2); // total + email
});
