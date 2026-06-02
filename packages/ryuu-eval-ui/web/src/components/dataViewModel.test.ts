/**
 * Pure-logic tests for dataViewModel. No test-runner dependency — run with:
 *   node --experimental-strip-types --test src/components/dataViewModel.test.ts
 * (see npm run test:model)
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { buildCrudOpDiffValues, coerce, detectCallSubgraph } from "./dataViewModel.ts";

const edge = (from: string, to: string, m: string) => ({
  from_class: from, to_class: to, to_method: m,
});

// ── coerce ───────────────────────────────────────────────────────────────────

test("coerce: parses a JSON string", () => {
  assert.deepEqual(coerce('{"a":1}'), { a: 1 });
});

test("coerce: leaves non-JSON strings untouched", () => {
  assert.equal(coerce("hello world"), "hello world");
});

test("coerce: passes through non-string values", () => {
  const obj = { a: 1 };
  assert.equal(coerce(obj), obj);
  assert.equal(coerce(42), 42);
  assert.equal(coerce(null), null);
});

// ── buildCrudOpDiffValues ────────────────────────────────────────────────────

test("buildCrudOpDiffValues: aligns actual object output to expected cells array and keeps only op", () => {
  const expected = {
    cells: [
      { entity: "Order", column: "id", op: "C" },
      { entity: "Order", column: "status", op: "U" },
    ],
  };
  const actual = {
    Order: {
      status: { op: "R", confidence: 0.95, reason: "noise" },
      id: { op: "C", confidence: 0.95, reason: "noise" },
    },
  };

  const diff = buildCrudOpDiffValues(expected, actual);

  assert.equal(diff.applied, true);
  assert.deepEqual(diff.expected, {
    Order: {
      id: { op: "C" },
      status: { op: "U" },
    },
  });
  assert.deepEqual(diff.actual, {
    Order: {
      id: { op: "C" },
      status: { op: "R" },
    },
  });
});

test("buildCrudOpDiffValues: represents missing fields with an explicit marker", () => {
  const diff = buildCrudOpDiffValues(
    { cells: [{ entity: "Order", field: "id", op: "C" }] },
    { Order: { status: { op: "C", reason: "ignored" } } },
  );

  assert.deepEqual(diff.expected, {
    Order: {
      id: { op: "C" },
      status: { op: "missing" },
    },
  });
  assert.deepEqual(diff.actual, {
    Order: {
      id: { op: "missing" },
      status: { op: "C" },
    },
  });
});

test("buildCrudOpDiffValues: uses input entity_fields aliases to match expected fields to actual db columns", () => {
  const expected = {
    cells: [
      { entity: "Order", column: "id", op: "R" },
      { entity: "Order", column: "customer", op: "R" },
      { entity: "Order", column: "createdAt", op: "R" },
      { entity: "Order", column: "totalPrice", op: "R" },
    ],
  };
  const actual = {
    Order: {
      created_at: { op: "R", confidence: 0.95, reason: "ignored" },
      customer_id: { op: "R", confidence: 0.95, reason: "ignored" },
      id: { op: "R", confidence: 0.95, reason: "ignored" },
      total_price: { op: "R", confidence: 0.95, reason: "ignored" },
    },
  };
  const inputData = {
    contexts: {
      "GET /orders/{orderId}": {
        entity_fields: {
          Order: [
            { name: "id", db_column: "id" },
            { name: "customer", db_column: "customer_id" },
            { name: "createdAt", db_column: "created_at" },
            { name: "totalPrice", db_column: "total_price" },
          ],
        },
      },
    },
  };

  const diff = buildCrudOpDiffValues(expected, actual, inputData);

  assert.equal(diff.applied, true);
  assert.deepEqual(diff.expected, {
    Order: {
      id: { op: "R" },
      customer: { op: "R" },
      createdAt: { op: "R" },
      totalPrice: { op: "R" },
    },
  });
  assert.deepEqual(diff.actual, {
    Order: {
      id: { op: "R" },
      customer: { op: "R" },
      createdAt: { op: "R" },
      totalPrice: { op: "R" },
    },
  });
});

test("buildCrudOpDiffValues: supports flat Entity::field expectation", () => {
  const diff = buildCrudOpDiffValues(
    { "MonthlyTimesheet::id": "R" },
    { MonthlyTimesheet: { id: { op: "R", confidence: "high" } } },
  );

  assert.equal(diff.applied, true);
  assert.deepEqual(diff.expected, { MonthlyTimesheet: { id: { op: "R" } } });
  assert.deepEqual(diff.actual, { MonthlyTimesheet: { id: { op: "R" } } });
});

// ── detectCallSubgraph ─────────────────────────────────────────────────────────

const SUBGRAPH = {
  "OrderController.create": [
    edge("OrderController", "OrderService", "save"),
    edge("OrderService", "OrderRepo", "insert"),
  ],
};

test("detectCallSubgraph: value nested under call_subgraph", () => {
  const result = detectCallSubgraph({ title: "x", call_subgraph: SUBGRAPH });
  assert.deepEqual(result, SUBGRAPH);
});

test("detectCallSubgraph: value that IS the subgraph", () => {
  assert.deepEqual(detectCallSubgraph(SUBGRAPH), SUBGRAPH);
});

test("detectCallSubgraph: null for plain object", () => {
  assert.equal(detectCallSubgraph({ a: 1, b: "two" }), null);
});

test("detectCallSubgraph: null for CRUD-shaped object", () => {
  assert.equal(detectCallSubgraph({ Order: { id: { op: "R" } } }), null);
});

test("detectCallSubgraph: null when arrays hold non-edge items", () => {
  assert.equal(detectCallSubgraph({ k: [1, 2, 3] }), null);
});

test("detectCallSubgraph: null for empty / array / primitive", () => {
  assert.equal(detectCallSubgraph({}), null);
  assert.equal(detectCallSubgraph([]), null);
  assert.equal(detectCallSubgraph("str"), null);
  assert.equal(detectCallSubgraph(null), null);
});

test("detectCallSubgraph: null when a group is empty (no edges)", () => {
  assert.equal(detectCallSubgraph({ flow: [] }), null);
});

test("detectCallSubgraph: route-context shape { contexts: { route: { call_edges } } }", () => {
  const input = {
    total: 1,
    contexts: {
      "GET /timesheets/monthly/{id}": {
        route: { http_method: "GET", endpoint: "/timesheets/monthly/{id}" },
        call_edges: [edge("MonthlyTimesheetController", "MonthlyTimesheetService", "getTimesheet")],
      },
    },
  };
  assert.deepEqual(detectCallSubgraph(input), {
    "GET /timesheets/monthly/{id}": [
      edge("MonthlyTimesheetController", "MonthlyTimesheetService", "getTimesheet"),
    ],
  });
});

test("detectCallSubgraph: flat call_edges array", () => {
  const e = edge("A", "B", "m");
  assert.deepEqual(detectCallSubgraph({ call_edges: [e] }), { calls: [e] });
});

test("detectCallSubgraph: contexts present but no valid edges → null", () => {
  assert.equal(detectCallSubgraph({ contexts: { r: { route: {}, call_edges: [] } } }), null);
});
