/**
 * Pure detection/coercion logic for <DataView> — no React, no JSX, no `@/`
 * imports, so it runs under `node --experimental-strip-types --test`.
 */

export type CallEdge = { from_class: string; to_class: string; to_method: string };
type CrudOpRow = { entity: string; field: string; op: string };
type CrudOpMatrix = Record<string, Record<string, { op: string }>>;

const MISSING_OP = "missing";

/** LLM output often arrives as a JSON string — parse it so views can inspect
 *  the shape, but fall back to the raw string when it isn't JSON. */
export function coerce(v: unknown): unknown {
  if (typeof v !== "string") return v;
  try { return JSON.parse(v); } catch { return v; }
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function opOf(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
    return String(v);
  }
  const obj = asRecord(v);
  if (!obj) return null;
  const op = obj.op ?? obj.value ?? obj.expected_op ?? obj.actual_op;
  return op == null ? null : String(op);
}

function isCrudCell(v: unknown): boolean {
  return opOf(v) != null;
}

function isCrudEntityMap(v: unknown): boolean {
  const obj = asRecord(v);
  if (!obj || Object.keys(obj).length === 0) return false;
  return Object.values(obj).every((fields) => {
    const fieldObj = asRecord(fields);
    return !!fieldObj && Object.keys(fieldObj).length > 0 && Object.values(fieldObj).every(isCrudCell);
  });
}

function unwrapCrudCandidate(v: unknown): unknown {
  const obj = asRecord(v);
  if (!obj) return v;
  if (obj.cells != null) return obj.cells;
  if (isCrudEntityMap(obj)) return obj;
  const keys = Object.keys(obj);
  if (keys.length === 1) {
    const inner = obj[keys[0]];
    if (isCrudEntityMap(inner) || Array.isArray(inner)) return inner;
  }
  return obj;
}

function crudRowFromRecord(row: Record<string, unknown>): CrudOpRow | null {
  const entity = row.entity ?? row.entity_name ?? row.short_name ?? row.table;
  const field = row.field ?? row.column ?? row.db_column ?? row.name;
  const op = opOf(row);
  if (entity == null || field == null || op == null) return null;
  return { entity: String(entity), field: String(field), op };
}

function collectCrudOpRows(v: unknown): CrudOpRow[] {
  const candidate = unwrapCrudCandidate(coerce(v));

  if (Array.isArray(candidate)) {
    return candidate
      .map((row) => {
        const obj = asRecord(row);
        return obj ? crudRowFromRecord(obj) : null;
      })
      .filter((row): row is CrudOpRow => row != null);
  }

  const obj = asRecord(candidate);
  if (!obj) return [];

  const flatRows: CrudOpRow[] = [];
  for (const [k, raw] of Object.entries(obj)) {
    if (!k.includes("::")) continue;
    const [entity, field] = k.split("::", 2);
    const op = opOf(raw);
    if (entity && field && op != null) flatRows.push({ entity, field, op });
  }
  if (flatRows.length > 0) return flatRows;

  if (!isCrudEntityMap(obj)) return [];
  const rows: CrudOpRow[] = [];
  for (const [entity, fields] of Object.entries(obj)) {
    const fieldObj = asRecord(fields);
    if (!fieldObj) continue;
    for (const [field, raw] of Object.entries(fieldObj)) {
      const op = opOf(raw);
      if (op != null) rows.push({ entity, field, op });
    }
  }
  return rows;
}

function toSnakeCase(s: string): string {
  return s
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s-]+/g, "_")
    .toLowerCase();
}

function addAlias(aliases: Map<string, Set<string>>, entity: string, field: string, alias: string) {
  if (!field || !alias) return;
  const k = `${entity}::${field}`;
  if (!aliases.has(k)) aliases.set(k, new Set());
  aliases.get(k)!.add(alias);
}

function addFieldAliases(aliases: Map<string, Set<string>>, entity: string, field: Record<string, unknown>) {
  const name = String(field.name ?? "");
  const dbColumn = String(field.db_column ?? field.column ?? "");
  if (!name && !dbColumn) return;

  const values = [name, dbColumn, name ? toSnakeCase(name) : ""].filter(Boolean);
  for (const source of values) {
    for (const alias of values) addAlias(aliases, entity, source, alias);
  }
}

function buildCrudFieldAliases(inputData: unknown): Map<string, Set<string>> {
  const aliases = new Map<string, Set<string>>();
  const input = asRecord(coerce(inputData));
  if (!input) return aliases;

  function addEntityFields(entity: string, fields: unknown) {
    if (!Array.isArray(fields)) return;
    for (const raw of fields) {
      const field = asRecord(raw);
      if (field) addFieldAliases(aliases, entity, field);
    }
  }

  const contexts = asRecord(input.contexts);
  if (contexts) {
    for (const ctx of Object.values(contexts)) {
      const entityFields = asRecord(asRecord(ctx)?.entity_fields);
      if (!entityFields) continue;
      for (const [entity, fields] of Object.entries(entityFields)) {
        addEntityFields(entity, fields);
      }
    }
  }

  const entities = Array.isArray(input.entities) ? input.entities : [];
  for (const raw of entities) {
    const entity = asRecord(raw);
    if (!entity) continue;
    const name = String(entity.short_name ?? entity.name ?? "");
    if (name) addEntityFields(name, entity.fields);
  }

  return aliases;
}

function setMatrixOp(matrix: CrudOpMatrix, row: CrudOpRow, op: string) {
  matrix[row.entity] ??= {};
  matrix[row.entity][row.field] = { op };
}

/**
 * Build a focused CRUD diff model: expected order drives the output, actual is
 * looked up by entity+field, and only the `op` value is compared.
 */
export function buildCrudOpDiffValues(
  expected: unknown,
  actual: unknown,
  inputData?: unknown,
): { applied: boolean; expected: unknown; actual: unknown } {
  const expectedRows = collectCrudOpRows(expected);
  const actualRows = collectCrudOpRows(actual);
  if (expectedRows.length === 0 || actualRows.length === 0) {
    return { applied: false, expected, actual };
  }

  const actualByKey = new Map(actualRows.map((row) => [`${row.entity}::${row.field}`, row]));
  const aliases = buildCrudFieldAliases(inputData);
  const consumedActual = new Set<string>();
  const expectedMatrix: CrudOpMatrix = {};
  const actualMatrix: CrudOpMatrix = {};

  for (const expectedRow of expectedRows) {
    const candidates = new Set([
      expectedRow.field,
      toSnakeCase(expectedRow.field),
      ...(aliases.get(`${expectedRow.entity}::${expectedRow.field}`) ?? []),
    ]);
    let actualRow: CrudOpRow | undefined;
    let actualKey = "";
    for (const field of candidates) {
      const k = `${expectedRow.entity}::${field}`;
      const row = actualByKey.get(k);
      if (row) {
        actualRow = row;
        actualKey = k;
        break;
      }
    }
    if (actualKey) consumedActual.add(actualKey);
    setMatrixOp(expectedMatrix, expectedRow, expectedRow.op);
    setMatrixOp(actualMatrix, expectedRow, actualRow?.op ?? MISSING_OP);
  }

  for (const actualRow of actualRows) {
    const k = `${actualRow.entity}::${actualRow.field}`;
    if (consumedActual.has(k)) continue;
    setMatrixOp(expectedMatrix, actualRow, MISSING_OP);
    setMatrixOp(actualMatrix, actualRow, actualRow.op);
  }

  return { applied: true, expected: expectedMatrix, actual: actualMatrix };
}

/** True if `e` looks like a call edge ({from_class,to_class,to_method}). */
function isEdge(e: unknown): e is CallEdge {
  return (
    !!e && typeof e === "object" &&
    "from_class" in (e as object) &&
    "to_class" in (e as object) &&
    "to_method" in (e as object)
  );
}

/** A non-empty array all of whose items are call edges. */
function edgeArray(v: unknown): CallEdge[] | null {
  return Array.isArray(v) && v.length > 0 && v.every(isEdge) ? (v as CallEdge[]) : null;
}

/** Detect a call-sequence subgraph (→ `{ label: CallEdge[] }` for
 *  CallSequenceDiagram) from any of the shapes the eval inputs use:
 *    A. `value.call_subgraph` = { key: CallEdge[] }
 *    B. `value` is itself { key: CallEdge[] }
 *    C. `value.contexts` = { route: { call_edges: CallEdge[] } }   ← route context
 *    D. `value.call_edges` = CallEdge[]
 *  Returns the subgraph or null. */
export function detectCallSubgraph(v: unknown): Record<string, CallEdge[]> | null {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const obj = v as Record<string, unknown>;

  // C. route-context: { contexts: { "<route>": { call_edges: [...] } } }
  const contexts = obj.contexts;
  if (contexts && typeof contexts === "object" && !Array.isArray(contexts)) {
    const sub: Record<string, CallEdge[]> = {};
    for (const [route, ctx] of Object.entries(contexts as Record<string, unknown>)) {
      const edges = ctx && typeof ctx === "object" ? edgeArray((ctx as Record<string, unknown>).call_edges) : null;
      if (edges) sub[route] = edges;
    }
    if (Object.keys(sub).length) return sub;
  }

  // D. flat list of edges under `call_edges`
  const direct = edgeArray(obj.call_edges);
  if (direct) return { calls: direct };

  // A + B. `call_subgraph` map, or the value is itself a { key: CallEdge[] } map
  const candidate = (obj.call_subgraph ?? obj) as unknown;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  const groups = Object.values(candidate as Record<string, unknown>);
  if (groups.length === 0 || !groups.every((g) => Array.isArray(g))) return null;
  const edges = (groups as unknown[][]).flat();
  return edges.length > 0 && edges.every(isEdge)
    ? (candidate as Record<string, CallEdge[]>)
    : null;
}
