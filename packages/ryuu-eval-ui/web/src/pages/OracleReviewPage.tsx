import { useState } from "react";
import { useParams } from "react-router-dom";
import { useOracleSchema, useOracleFixtures, useOracleFixture, useUpdateOracleReview } from "@/api/hooks";
import type { OracleFixtureDetail, OracleReviewItem, ReviewActionPayload, ReviewSchema } from "@/api/types";
import { apiFetch } from "@/api/client";
import { CallSequenceDiagram } from "@/components/CallSequenceDiagram";

// ── Route context panel ───────────────────────────────────────────────────────

function RouteContextPanel({ inputData }: { inputData: Record<string, unknown> }) {
  const route = inputData.route as Record<string, unknown> | undefined;
  const entities = (inputData.entities as Array<Record<string, unknown>>) ?? [];
  const chain = inputData.call_subgraph as Record<string, unknown> | undefined;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4 text-sm">
      {route && (
        <section>
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Route</div>
          <div className="font-mono text-blue-400">
            {String(route.http_method ?? "")} {String(route.endpoint ?? "")}
          </div>
          {route.use_case ? (
            <div className="text-gray-400 text-xs mt-0.5">{String(route.use_case)}</div>
          ) : null}
        </section>
      )}

      {entities.length > 0 && (
        <section>
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Entities</div>
          {entities.map((ent) => {
            const fields = (ent.fields as Array<Record<string, unknown>>) ?? [];
            return (
              <div key={String(ent.short_name)} className="mb-2">
                <div className="font-medium text-gray-200">{String(ent.short_name)}</div>
                <div className="ml-2 space-y-0.5">
                  {fields.map((f) => (
                    <div key={String(f.name)} className="text-gray-400 text-xs">
                      <span className="text-gray-300">{String(f.db_column ?? f.name)}</span>
                      <span className="ml-1 text-gray-500">{String(f.type ?? "")}</span>
                      {(f.annotations as string[] | undefined)?.length ? (
                        <span className="ml-1 text-yellow-600 text-[10px]">
                          {(f.annotations as string[]).join(" ")}
                        </span>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </section>
      )}

      {chain && (
        <section>
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Call Chain</div>
          <CallSequenceDiagram subgraph={chain as Record<string, Array<{ from_class: string; to_class: string; to_method: string }>>} />
        </section>
      )}
    </div>
  );
}

// ── Cell badges ───────────────────────────────────────────────────────────────

function OpBadge({ op }: { op: string }) {
  const colors: Record<string, string> = {
    C: "bg-green-900 text-green-300",
    R: "bg-blue-900 text-blue-300",
    U: "bg-yellow-900 text-yellow-300",
    D: "bg-red-900 text-red-300",
  };
  return (
    <span className="font-mono text-xs font-bold flex gap-0.5">
      {op.split("").map((ch) => (
        <span key={ch} className={`px-1 py-0.5 rounded ${colors[ch] ?? "bg-gray-700 text-gray-300"}`}>
          {ch}
        </span>
      ))}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const cls =
    confidence === "high" ? "text-green-400" :
    confidence === "medium" ? "text-yellow-400" : "text-red-400";
  return <span className={`text-xs font-semibold ${cls}`}>{confidence}</span>;
}

// ── Cell review row ───────────────────────────────────────────────────────────

function CellRow({
  entity, field, cell, reviewItem, pendingAction, onAction, actions,
}: {
  entity: string;
  field: string;
  cell: { op: string; confidence: string; oracle_why: string };
  reviewItem: OracleReviewItem | undefined;
  pendingAction: ReviewActionPayload | undefined;
  onAction: (a: ReviewActionPayload) => void;
  actions: string[];
}) {
  const [showWhy, setShowWhy] = useState(false);
  const [fixOp, setFixOp] = useState(cell.op);
  const [showFix, setShowFix] = useState(false);

  const effectiveAction = pendingAction?.action ?? reviewItem?.action;
  const needsReview = cell.confidence !== "high" && effectiveAction == null;

  const rowCls = needsReview
    ? "border-l-2 border-yellow-500 bg-yellow-950/20"
    : effectiveAction === "remove" ? "opacity-40 line-through"
    : effectiveAction != null ? "border-l-2 border-green-600"
    : "";

  const canApprove = actions.includes("approve");
  const canFix = actions.includes("fix");
  const canRemove = actions.includes("remove");

  return (
    <div className={`px-3 py-2 rounded mb-1 ${rowCls}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-gray-300 font-medium text-sm w-28 truncate" title={entity}>{entity}</span>
        <span className="text-gray-400 text-sm w-32 truncate font-mono" title={field}>{field}</span>
        <OpBadge op={pendingAction?.action === "fix" ? (pendingAction.corrected_op ?? cell.op) : cell.op} />
        <ConfidenceBadge confidence={cell.confidence} />

        {effectiveAction === "approve" && <span className="text-green-400 text-xs">✓ approved</span>}
        {effectiveAction === "remove" && <span className="text-red-400 text-xs">✗ removed</span>}
        {effectiveAction === "fix" && (
          <span className="text-blue-400 text-xs">✏ fixed → {pendingAction?.corrected_op ?? reviewItem?.corrected_op}</span>
        )}

        <div className="ml-auto flex gap-1.5">
          {cell.oracle_why && (
            <button className="text-xs text-gray-500 hover:text-gray-300 underline" onClick={() => setShowWhy(v => !v)}>
              {showWhy ? "hide" : "why?"}
            </button>
          )}
          {effectiveAction == null && (
            <>
              {canApprove && (
                <button className="text-xs px-2 py-0.5 rounded bg-green-800 hover:bg-green-700 text-green-200"
                  onClick={() => onAction({ entity, field, action: "approve" })}>
                  ✓ Approve
                </button>
              )}
              {canFix && (
                <button className="text-xs px-2 py-0.5 rounded bg-blue-800 hover:bg-blue-700 text-blue-200"
                  onClick={() => setShowFix(v => !v)}>
                  ✏ Fix op
                </button>
              )}
              {canRemove && (
                <button className="text-xs px-2 py-0.5 rounded bg-red-900 hover:bg-red-800 text-red-300"
                  onClick={() => onAction({ entity, field, action: "remove" })}>
                  ✗ Remove
                </button>
              )}
            </>
          )}
          {effectiveAction != null && (
            <button className="text-xs text-gray-500 hover:text-gray-300"
              onClick={() => onAction({ entity, field, action: "approve" })}>
              undo
            </button>
          )}
        </div>
      </div>

      {showWhy && <div className="mt-1 ml-2 text-xs text-gray-400 italic">{cell.oracle_why}</div>}

      {showFix && effectiveAction == null && (
        <div className="mt-1 ml-2 flex gap-2 items-center">
          <input
            className="font-mono text-sm w-20 bg-gray-800 border border-gray-600 rounded px-2 py-0.5 text-gray-200"
            value={fixOp} maxLength={4}
            onChange={e => setFixOp(e.target.value.toUpperCase())}
            placeholder="CR"
          />
          <button className="text-xs px-2 py-0.5 rounded bg-blue-700 hover:bg-blue-600 text-white"
            onClick={() => { onAction({ entity, field, action: "fix", corrected_op: fixOp }); setShowFix(false); }}>
            Save
          </button>
          <button className="text-xs text-gray-500 hover:text-gray-300" onClick={() => setShowFix(false)}>
            cancel
          </button>
        </div>
      )}
    </div>
  );
}

// ── Table reviewer (kind="table") ─────────────────────────────────────────────

function TableReviewer({
  schema, fixture, pendingActions, onAction, onSave, isSaving,
}: {
  schema: ReviewSchema;
  fixture: OracleFixtureDetail;
  pendingActions: ReviewActionPayload[];
  onAction: (a: ReviewActionPayload) => void;
  onSave: () => void;
  isSaving: boolean;
}) {
  const reviewMap = new Map(fixture.review_items.map(r => [`${r.entity}::${r.field}`, r]));
  const pendingMap = new Map(pendingActions.map(a => [`${a.entity}::${a.field}`, a]));

  const totalCells = Object.values(fixture.expected).reduce(
    (sum, fmap) => sum + Object.keys(fmap as object).length, 0
  );
  const pendingCount = fixture.review_items.filter(r => r.action == null).length;
  const unsaved = pendingActions.length;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700 shrink-0">
        <div className="text-sm text-gray-400">
          <span className="text-gray-200 font-medium">{totalCells}</span> cells
          {pendingCount > 0 && <span className="ml-2 text-yellow-400">{pendingCount} need review</span>}
          {pendingCount === 0 && totalCells > 0 && <span className="ml-2 text-green-400">all reviewed</span>}
        </div>
        {unsaved > 0 && (
          <button
            className="text-xs px-3 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-50"
            disabled={isSaving} onClick={onSave}
          >
            {isSaving ? "Saving…" : `Save ${unsaved} change${unsaved > 1 ? "s" : ""}`}
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {/* Column headers from schema */}
        <div className="flex gap-2 px-3 mb-1 text-xs text-gray-500 font-semibold uppercase tracking-wide">
          {schema.columns.map(col => (
            <span key={col} className={col === "ENTITY" ? "w-28" : col === "FIELD" ? "w-32" : col === "OP" ? "w-16" : ""}>{col}</span>
          ))}
        </div>

        {Object.entries(fixture.expected).map(([entity, fmap]) =>
          Object.entries(fmap as Record<string, { op: string; confidence: string; oracle_why: string }>).map(([field, cell]) => (
            <CellRow
              key={`${entity}::${field}`}
              entity={entity} field={field} cell={cell}
              reviewItem={reviewMap.get(`${entity}::${field}`)}
              pendingAction={pendingMap.get(`${entity}::${field}`)}
              onAction={onAction}
              actions={schema.actions}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── Review dispatcher — routes by schema.kind ─────────────────────────────────

function ReviewDispatcher(props: {
  schema: ReviewSchema;
  fixture: OracleFixtureDetail;
  pendingActions: ReviewActionPayload[];
  onAction: (a: ReviewActionPayload) => void;
  onSave: () => void;
  isSaving: boolean;
}) {
  if (props.schema.kind === "table") {
    return <TableReviewer {...props} />;
  }
  return (
    <div className="flex-1 flex items-center justify-center text-gray-500 text-sm p-8">
      Reviewer for kind=<span className="font-mono ml-1 text-gray-400">{props.schema.kind}</span>
      <span className="ml-2 text-gray-600">— not yet implemented</span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function OracleReviewPage() {
  const { suiteId } = useParams<{ suiteId: string }>();
  const { data: schema } = useOracleSchema();
  const { data: summaries = [], isLoading: loadingList } = useOracleFixtures(suiteId);
  const [selectedId, setSelectedId] = useState<string>("");
  const activeId = selectedId || summaries[0]?.fixture_id || "";

  const { data: fixture, isLoading: loadingFixture } = useOracleFixture(activeId);
  const updateMutation = useUpdateOracleReview(activeId);

  const [pendingActions, setPendingActions] = useState<ReviewActionPayload[]>([]);
  const [reviewerName, setReviewerName] = useState<string>("");

  const prevId = useState(activeId)[0];
  if (prevId !== activeId && pendingActions.length > 0) setPendingActions([]);

  function handleAction(action: ReviewActionPayload) {
    setPendingActions(prev => {
      const filtered = prev.filter(a => !(a.entity === action.entity && a.field === action.field));
      if (
        action.action === "approve" &&
        prev.some(a => a.entity === action.entity && a.field === action.field && a.action === "approve")
      ) return filtered;
      return [...filtered, action];
    });
  }

  async function handleSave() {
    await updateMutation.mutateAsync({ actions: pendingActions, reviewed_by: reviewerName || undefined });
    setPendingActions([]);
  }

  async function handleExport() {
    const data = await apiFetch(`/oracle-review/${activeId}/export`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${activeId}.json`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="h-[calc(100vh-56px)] flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700 shrink-0 bg-gray-900">
        <span className="text-sm font-semibold text-gray-200">Oracle Review</span>
        {schema && (
          <span className="text-xs text-gray-500 font-mono border border-gray-700 rounded px-1.5 py-0.5">
            {schema.kind}
          </span>
        )}

        <select
          className="text-sm bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-200"
          value={activeId}
          onChange={e => { setSelectedId(e.target.value); setPendingActions([]); }}
        >
          {loadingList && <option>Loading…</option>}
          {summaries.map(s => (
            <option key={s.fixture_id} value={s.fixture_id}>
              {s.fixture_id}{s.pending_review > 0 ? ` (${s.pending_review} pending)` : " ✓"}
            </option>
          ))}
        </select>

        <input
          className="text-sm bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-200 w-32"
          placeholder="your name" value={reviewerName}
          onChange={e => setReviewerName(e.target.value)}
        />

        <div className="ml-auto flex gap-2">
          {fixture && (
            <>
              {fixture.reviewed_by && (
                <span className="text-xs text-gray-500">
                  reviewed by {fixture.reviewed_by} {fixture.reviewed_at}
                </span>
              )}
              <button
                className="text-xs px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200"
                onClick={handleExport}
              >
                Export JSON
              </button>
            </>
          )}
        </div>
      </div>

      {/* Body */}
      {loadingFixture || !fixture || !schema ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
          {loadingFixture ? "Loading fixture…" : !schema ? "Loading schema…" : "Select a fixture above"}
        </div>
      ) : (
        <div className="flex-1 min-h-0 grid grid-cols-2 divide-x divide-gray-700">
          {/* Left: route context */}
          <div className="overflow-hidden">
            <div className="px-4 py-2 border-b border-gray-700 text-xs font-semibold text-gray-400 uppercase tracking-wide">
              Route Context
            </div>
            <RouteContextPanel inputData={fixture.input_data} />
          </div>

          {/* Right: review panel — dispatched by schema.kind */}
          <div className="overflow-hidden flex flex-col">
            <ReviewDispatcher
              schema={schema}
              fixture={fixture}
              pendingActions={pendingActions}
              onAction={handleAction}
              onSave={handleSave}
              isSaving={updateMutation.isPending}
            />
          </div>
        </div>
      )}
    </div>
  );
}
