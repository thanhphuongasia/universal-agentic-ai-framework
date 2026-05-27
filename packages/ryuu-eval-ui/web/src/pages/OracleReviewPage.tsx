import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  useOracleSchema, useOracleFixtures, useOracleFixture,
  useUpdateOracleReview, useOraclePrompt, useRunOracle,
  useGenerateOracle, useDeleteOracleFixture,
} from "@/api/hooks";
import type {
  OracleFixtureDetail, OracleFixtureSummary, OracleReviewItem,
  ReviewActionPayload, ReviewSchema, OracleRunPreview,
} from "@/api/types";
import { apiFetch } from "@/api/client";
import { CallSequenceDiagram } from "@/components/CallSequenceDiagram";

// ─── Pipeline ─────────────────────────────────────────────────────────────────

type PipeStatus = "done" | "active" | "pending" | "na";

const PIPE_STEPS = [
  { label: "Input",         desc: "Route Context JSON" },
  { label: "Oracle Gen",    desc: "Generate expectation" },
  { label: "Actual Output", desc: "Model output (opt.)" },
  { label: "Evaluation",    desc: "Score & evidence" },
  { label: "Human Review",  desc: "Approve / Adjust" },
  { label: "Finalized",     desc: "Locked for regression" },
];

function pipeStatuses(fixture: OracleFixtureDetail | null): PipeStatus[] {
  if (!fixture) return ["pending", "pending", "na", "na", "pending", "pending"];
  const hasCells = Object.keys(fixture.expected).length > 0;
  const pendingCount = fixture.review_items.filter(r => r.action == null).length;
  const allReviewed = hasCells && pendingCount === 0;
  const finalized = allReviewed && !!fixture.reviewed_by;
  return [
    "done",
    hasCells ? "done" : "active",
    "na",
    "na",
    allReviewed ? "done" : (hasCells ? "active" : "pending"),
    finalized ? "done" : "pending",
  ];
}

function PipelineHeader({ fixture }: { fixture: OracleFixtureDetail | null }) {
  const statuses = pipeStatuses(fixture);
  const statusLabel: Record<PipeStatus, string> = {
    done: "Completed", active: "In Progress", pending: "Pending", na: "N/A",
  };
  return (
    <div className="flex items-start gap-0 px-6 py-4 border-b border-gray-700 bg-gray-900 shrink-0 overflow-x-auto">
      {PIPE_STEPS.map((step, i) => {
        const s = statuses[i];
        const ringCls =
          s === "done"   ? "bg-green-600 border-green-500 text-white" :
          s === "active" ? "bg-yellow-500 border-yellow-400 text-black" :
          s === "na"     ? "bg-gray-800 border-gray-600 text-gray-500" :
                           "bg-gray-800 border-gray-600 text-gray-400";
        const labelCls =
          s === "done" ? "text-green-400" : s === "active" ? "text-yellow-400" : "text-gray-500";
        return (
          <div key={i} className="flex items-start shrink-0">
            <div className="flex flex-col items-center min-w-[100px]">
              <div className={`w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold ${ringCls}`}>
                {s === "done" ? "✓" : i + 1}
              </div>
              <div className="mt-1.5 text-center px-1">
                <div className="text-xs font-semibold text-gray-200 leading-tight">{step.label}</div>
                <div className="text-[10px] text-gray-500 mt-0.5 leading-tight">{step.desc}</div>
                <div className={`text-[10px] mt-1 font-medium ${labelCls}`}>{statusLabel[s]}</div>
              </div>
            </div>
            {i < PIPE_STEPS.length - 1 && (
              <div className={`h-px w-8 mt-4 shrink-0 ${s === "done" ? "bg-green-600" : "bg-gray-700"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function OpBadge({ op }: { op: string }) {
  const colors: Record<string, string> = {
    C: "bg-green-900 text-green-300 border-green-700",
    R: "bg-blue-900 text-blue-300 border-blue-700",
    U: "bg-yellow-900 text-yellow-300 border-yellow-700",
    D: "bg-red-900 text-red-300 border-red-700",
  };
  if (!op) return <span className="text-gray-500 font-mono text-xs border border-gray-700 px-1.5 py-0.5 rounded">—</span>;
  return (
    <span className="flex gap-0.5">
      {op.split("").map(ch => (
        <span key={ch} className={`font-mono text-xs font-bold px-1.5 py-0.5 rounded border ${colors[ch] ?? "bg-gray-800 text-gray-300 border-gray-600"}`}>{ch}</span>
      ))}
    </span>
  );
}

function ConfBadge({ confidence }: { confidence: string }) {
  const cls = confidence === "high" ? "text-green-400 bg-green-950 border-green-800"
    : confidence === "medium" ? "text-yellow-400 bg-yellow-950 border-yellow-800"
    : "text-red-400 bg-red-950 border-red-800";
  return <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${cls}`}>{confidence}</span>;
}

function StatusDot({ pending }: { pending: number }) {
  return <span className={`w-2 h-2 rounded-full shrink-0 ${pending > 0 ? "bg-yellow-400" : "bg-green-500"}`} />;
}

// ─── CodePane ─────────────────────────────────────────────────────────────────

function CodePane({ title, content, maxHeight = "260px", badge }: {
  title: string; content: string; maxHeight?: string; badge?: string;
}) {
  const [copied, setCopied] = useState(false);
  const lines = content.split("\n");

  function copy() {
    navigator.clipboard.writeText(content).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div className="flex flex-col border border-gray-700 rounded-lg overflow-hidden h-full">
      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-200 uppercase tracking-wider">{title}</span>
          {badge && <span className="text-[10px] text-gray-500 font-mono bg-gray-900 px-1.5 py-0.5 rounded border border-gray-700">{badge}</span>}
        </div>
        <button className="text-[10px] text-gray-500 hover:text-gray-300 font-mono transition-colors" onClick={copy}>
          {copied ? "✓ copied" : "copy"}
        </button>
      </div>
      <div className="flex min-h-0 overflow-y-auto" style={{ maxHeight }}>
        <div className="shrink-0 bg-gray-900 text-gray-600 text-right px-2.5 py-3 select-none border-r border-gray-700 text-[10px] leading-5 font-mono min-w-[36px]">
          {lines.map((_, i) => <div key={i}>{i + 1}</div>)}
        </div>
        <pre className="flex-1 bg-gray-950 text-gray-300 px-4 py-3 overflow-x-auto text-xs leading-5 font-mono whitespace-pre">
          {content}
        </pre>
      </div>
    </div>
  );
}

// ─── Left sidebar ─────────────────────────────────────────────────────────────

function FixtureListItem({
  summary, isActive, onSelect, onEdit, onDelete,
}: {
  summary: OracleFixtureSummary;
  isActive: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={`px-3 py-2.5 cursor-pointer border-l-2 transition-colors ${
        isActive
          ? "border-indigo-500 bg-gray-800"
          : "border-transparent hover:bg-gray-800/50"
      }`}
      onClick={onSelect}
    >
      <div className="flex items-center gap-2 mb-0.5">
        <StatusDot pending={summary.pending_review} />
        <span className="text-xs font-semibold text-gray-200 truncate flex-1" title={summary.fixture_id}>
          {summary.fixture_id}
        </span>
      </div>
      <div className="ml-4 space-y-0.5">
        <div className="text-[10px] text-gray-500 font-mono truncate">{summary.oracle_model}</div>
        <div className="flex items-center gap-2">
          {summary.pending_review > 0
            ? <span className="text-[10px] text-yellow-400">{summary.pending_review} pending</span>
            : <span className="text-[10px] text-green-400">✓ reviewed</span>
          }
          {summary.reviewed_at && (
            <span className="text-[10px] text-gray-600">{summary.reviewed_at}</span>
          )}
        </div>
      </div>
      {isActive && (
        <div className="ml-4 mt-1.5 flex gap-1" onClick={e => e.stopPropagation()}>
          <button
            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors"
            onClick={onEdit}
          >✏ Edit</button>
          <button
            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 hover:bg-red-900 text-gray-400 hover:text-red-300 transition-colors"
            onClick={onDelete}
          >🗑</button>
        </div>
      )}
    </div>
  );
}

function FixtureSidebar({
  summaries, activeId, onSelect, onAdd, onEdit, onDelete, isLoading,
}: {
  summaries: OracleFixtureSummary[];
  activeId: string;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  isLoading: boolean;
}) {
  return (
    <div className="w-56 shrink-0 border-r border-gray-700 flex flex-col bg-gray-900">
      <div className="px-3 py-3 border-b border-gray-700 shrink-0">
        <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Oracle Fixtures</div>
        <button
          className="w-full text-xs px-3 py-1.5 rounded bg-indigo-700 hover:bg-indigo-600 text-white font-semibold transition-colors flex items-center justify-center gap-1.5"
          onClick={onAdd}
        >
          + New Fixture
        </button>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-gray-800">
        {isLoading && (
          <div className="px-3 py-4 text-xs text-gray-500 text-center">Loading…</div>
        )}
        {!isLoading && summaries.length === 0 && (
          <div className="px-3 py-4 text-xs text-gray-500 text-center">No fixtures yet</div>
        )}
        {summaries.map(s => (
          <FixtureListItem
            key={s.fixture_id}
            summary={s}
            isActive={s.fixture_id === activeId}
            onSelect={() => onSelect(s.fixture_id)}
            onEdit={() => onEdit(s.fixture_id)}
            onDelete={() => onDelete(s.fixture_id)}
          />
        ))}
      </div>
    </div>
  );
}

// ─── Center: Input tab ────────────────────────────────────────────────────────

function InputTab({ fixture }: { fixture: OracleFixtureDetail }) {
  const [view, setView] = useState<"split" | "structured">("split");
  const inputJson = JSON.stringify(fixture.input_data, null, 2);
  const entities = (fixture.input_data.entities as Array<Record<string, unknown>>) ?? [];
  const route = fixture.input_data.route as Record<string, unknown> | undefined;
  const chain = fixture.input_data.call_subgraph as Record<string, unknown> | undefined;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-700 shrink-0">
        <span className="text-xs text-gray-400">View:</span>
        {(["split", "structured"] as const).map(v => (
          <button key={v} onClick={() => setView(v)}
            className={`text-xs px-2 py-0.5 rounded transition-colors ${view === v ? "bg-gray-700 text-gray-200" : "text-gray-500 hover:text-gray-300"}`}>
            {v === "split" ? "JSON + Info" : "Structured"}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {view === "split" ? (
          <div className="h-full grid grid-cols-2 gap-4 p-4">
            <CodePane title="Route Context JSON" content={inputJson} maxHeight="100%" badge={`${fixture.oracle_model}`} />
            <div className="flex flex-col gap-3 overflow-y-auto">
              {/* Fixture meta */}
              <div className="border border-gray-700 rounded-lg p-3 bg-gray-900 text-xs space-y-1.5">
                <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Fixture Info</div>
                <div className="flex gap-2"><span className="text-gray-500 w-24">ID</span><span className="text-gray-200 font-mono">{fixture.fixture_id}</span></div>
                <div className="flex gap-2"><span className="text-gray-500 w-24">Model</span><span className="text-gray-200 font-mono">{fixture.oracle_model}</span></div>
                <div className="flex gap-2"><span className="text-gray-500 w-24">Prompt ver.</span><span className="text-gray-200 font-mono">{fixture.prompt_version}</span></div>
                {fixture.reviewed_by && <div className="flex gap-2"><span className="text-gray-500 w-24">Reviewed by</span><span className="text-gray-200">{fixture.reviewed_by}</span></div>}
                {fixture.reviewed_at && <div className="flex gap-2"><span className="text-gray-500 w-24">Reviewed at</span><span className="text-gray-200">{fixture.reviewed_at}</span></div>}
                <div className="flex gap-2">
                  <span className="text-gray-500 w-24">Review items</span>
                  <span className={fixture.review_items.filter(r => r.action == null).length > 0 ? "text-yellow-400" : "text-green-400"}>
                    {fixture.review_items.filter(r => r.action == null).length} pending / {fixture.review_items.length} total
                  </span>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="h-full overflow-y-auto p-4 space-y-4 text-sm">
            {route && (
              <section>
                <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Route</div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold px-2 py-1 rounded bg-blue-900 text-blue-300 border border-blue-700">{String(route.http_method ?? "")}</span>
                  <span className="font-mono text-sm text-gray-200">{String(route.endpoint ?? "")}</span>
                </div>
                {route.use_case ? <div className="text-xs text-gray-500 mt-1">{String(route.use_case)}</div> : null}
              </section>
            )}
            {entities.length > 0 && (
              <section>
                <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Entities</div>
                {entities.map(ent => {
                  const fields = (ent.fields as Array<Record<string, unknown>>) ?? [];
                  return (
                    <div key={String(ent.short_name)} className="border border-gray-700 rounded-lg overflow-hidden mb-2">
                      <div className="px-3 py-1.5 bg-gray-800 text-xs font-semibold text-gray-200">{String(ent.short_name)}</div>
                      <div className="divide-y divide-gray-800">
                        {fields.map(f => (
                          <div key={String(f.name)} className="px-3 py-1.5 flex items-center gap-3">
                            <span className="font-mono text-xs text-gray-300 w-24">{String(f.db_column ?? f.name)}</span>
                            <span className="text-xs text-gray-500 w-20">{String(f.type ?? "")}</span>
                            {(f.annotations as string[] | undefined)?.length ? (
                              <span className="text-[10px] text-yellow-600">{(f.annotations as string[]).join(" ")}</span>
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
                <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Call Chain</div>
                <CallSequenceDiagram subgraph={chain as Record<string, Array<{ from_class: string; to_class: string; to_method: string }>>} />
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Center: Oracle Generation tab ───────────────────────────────────────────

function OracleGenTab({ fixtureId }: { fixtureId: string }) {
  const { data, isLoading, isError } = useOraclePrompt(fixtureId, true);

  if (isLoading) return <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">Loading prompt…</div>;
  if (isError || !data) return (
    <div className="flex-1 flex items-center justify-center p-6 text-center">
      <div>
        <div className="text-yellow-500 text-sm mb-1">No oracle strategy configured</div>
        <div className="text-xs text-gray-500">Add <code className="bg-gray-800 px-1 rounded">oracle_strategy_factory=CrudMatrixOracleStrategy</code> to dev_server.py</div>
      </div>
    </div>
  );

  return (
    <div className="h-full grid grid-cols-2 gap-4 p-4">
      <CodePane title="System Prompt" content={data.system} maxHeight="100%" />
      <CodePane title="User Prompt" content={data.user} maxHeight="100%" badge="rendered" />
    </div>
  );
}

// ─── Center: Expectation tab ──────────────────────────────────────────────────

function ExpectationTab({ fixture }: { fixture: OracleFixtureDetail }) {
  const cells: Array<{ entity: string; field: string; op: string; confidence: string; why: string }> = [];
  for (const [entity, fmap] of Object.entries(fixture.expected)) {
    for (const [field, cell] of Object.entries(fmap as Record<string, { op: string; confidence: string; oracle_why: string }>)) {
      cells.push({ entity, field, op: cell.op, confidence: cell.confidence, why: cell.oracle_why });
    }
  }

  if (cells.length === 0) return (
    <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">No expectation cells generated yet</div>
  );

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 border-b border-gray-700 shrink-0">
        <span className="text-xs text-gray-400">{cells.length} cells · oracle ground truth</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-900 border-b border-gray-700">
            <tr>
              {["ENTITY", "FIELD", "OP", "CONFIDENCE", "ORACLE REASONING"].map(h => (
                <th key={h} className="px-4 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {cells.map((c, i) => (
              <tr key={i} className="hover:bg-gray-800/40 transition-colors">
                <td className="px-4 py-2.5 font-medium text-gray-300">{c.entity}</td>
                <td className="px-4 py-2.5 font-mono text-gray-400">{c.field}</td>
                <td className="px-4 py-2.5"><OpBadge op={c.op} /></td>
                <td className="px-4 py-2.5"><ConfBadge confidence={c.confidence} /></td>
                <td className="px-4 py-2.5 text-gray-500 italic">{c.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Center: Preview tab ──────────────────────────────────────────────────────

function PreviewTab({ preview, isRunning }: { preview: OracleRunPreview | null; isRunning: boolean }) {
  if (isRunning) return (
    <div className="flex-1 flex items-center justify-center gap-2 text-gray-400 text-sm">
      <span className="animate-spin text-lg">⟳</span> Running oracle…
    </div>
  );
  if (!preview) return (
    <div className="flex-1 flex items-center justify-center text-center p-8">
      <div>
        <div className="text-gray-500 text-sm mb-1">No preview yet</div>
        <div className="text-xs text-gray-600">Click <span className="text-indigo-400 font-semibold">▶ Run Oracle</span> to generate a fresh result</div>
      </div>
    </div>
  );

  const cells: Array<{ entity: string; field: string; op: string; confidence: string; why: string }> = [];
  for (const [entity, fmap] of Object.entries(preview.cells)) {
    for (const [field, cell] of Object.entries(fmap)) {
      cells.push({ entity, field, op: cell.op, confidence: cell.confidence, why: cell.oracle_why });
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 border-b border-gray-700 shrink-0 flex items-center gap-2">
        <span className="text-xs text-gray-400">{cells.length} cells ·</span>
        <span className="text-xs text-yellow-500">preview — not saved</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-900 border-b border-gray-700">
            <tr>
              {["ENTITY", "FIELD", "OP", "CONFIDENCE", "ORACLE REASONING"].map(h => (
                <th key={h} className="px-4 py-2 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {cells.map((c, i) => (
              <tr key={i} className="hover:bg-gray-800/40 transition-colors">
                <td className="px-4 py-2.5 font-medium text-gray-300">{c.entity}</td>
                <td className="px-4 py-2.5 font-mono text-gray-400">{c.field}</td>
                <td className="px-4 py-2.5"><OpBadge op={c.op} /></td>
                <td className="px-4 py-2.5"><ConfBadge confidence={c.confidence} /></td>
                <td className="px-4 py-2.5 text-gray-500 italic">{c.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Right: Review side panel ─────────────────────────────────────────────────

function CellReviewItem({
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
  const [fixOp, setFixOp] = useState(cell.op);
  const [showAdjust, setShowAdjust] = useState(false);

  const effectiveAction = pendingAction?.action ?? reviewItem?.action;
  const displayOp = pendingAction?.action === "fix" ? (pendingAction.corrected_op ?? cell.op) : cell.op;

  const statusEl = effectiveAction === "approve"
    ? <span className="text-green-400 text-[10px] font-semibold">✓ Approved & Locked</span>
    : effectiveAction === "remove"
    ? <span className="text-red-400 text-[10px] font-semibold">✗ Rejected</span>
    : effectiveAction === "fix"
    ? <span className="text-blue-400 text-[10px] font-semibold">✏ Adjusted → {pendingAction?.corrected_op ?? reviewItem?.corrected_op}</span>
    : null;

  return (
    <div className={`px-3 py-2.5 border-b border-gray-800 ${effectiveAction === "remove" ? "opacity-40" : ""}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-[10px] text-gray-500 font-mono">{entity}</span>
        <span className="text-gray-600">·</span>
        <span className="text-xs text-gray-200 font-mono font-medium">{field}</span>
        <div className="ml-auto flex items-center gap-1.5">
          <OpBadge op={displayOp} />
          <ConfBadge confidence={cell.confidence} />
        </div>
      </div>

      {cell.oracle_why && (
        <p className="text-[10px] text-gray-500 italic leading-relaxed mb-1.5">{cell.oracle_why}</p>
      )}

      {statusEl
        ? (
          <div className="flex items-center justify-between mt-1">
            {statusEl}
            <button className="text-[10px] text-gray-600 hover:text-gray-400" onClick={() => onAction({ entity, field, action: "approve" })}>undo</button>
          </div>
        )
        : (
          <div className="flex gap-1 mt-1.5 flex-wrap">
            {actions.includes("approve") && (
              <button className="text-[10px] px-2 py-1 rounded bg-green-900 hover:bg-green-800 text-green-300 border border-green-800 font-semibold transition-colors"
                onClick={() => onAction({ entity, field, action: "approve" })}>
                ✓ Approve & Lock
              </button>
            )}
            {actions.includes("remove") && (
              <button className="text-[10px] px-2 py-1 rounded bg-red-950 hover:bg-red-900 text-red-400 border border-red-900 transition-colors"
                onClick={() => onAction({ entity, field, action: "remove" })}>
                ✗ Reject
              </button>
            )}
            {actions.includes("fix") && (
              <button className="text-[10px] px-2 py-1 rounded bg-blue-950 hover:bg-blue-900 text-blue-400 border border-blue-900 transition-colors"
                onClick={() => setShowAdjust(v => !v)}>
                ✏ Adjust
              </button>
            )}
          </div>
        )
      }

      {showAdjust && effectiveAction == null && (
        <div className="mt-2 flex items-center gap-2">
          <input
            className="font-mono text-xs w-14 bg-gray-800 border border-gray-600 rounded px-2 py-0.5 text-gray-200"
            value={fixOp} maxLength={4} placeholder="CRU"
            onChange={e => setFixOp(e.target.value.toUpperCase())}
          />
          <button className="text-[10px] px-2 py-0.5 rounded bg-blue-700 hover:bg-blue-600 text-white"
            onClick={() => { onAction({ entity, field, action: "fix", corrected_op: fixOp }); setShowAdjust(false); }}>
            Save
          </button>
          <button className="text-[10px] text-gray-500 hover:text-gray-300" onClick={() => setShowAdjust(false)}>cancel</button>
        </div>
      )}
    </div>
  );
}

function ReviewSidePanel({
  schema, fixture, pendingActions, onAction, onSave, isSaving, reviewerName, onReviewerChange,
}: {
  schema: ReviewSchema;
  fixture: OracleFixtureDetail;
  pendingActions: ReviewActionPayload[];
  onAction: (a: ReviewActionPayload) => void;
  onSave: () => void;
  isSaving: boolean;
  reviewerName: string;
  onReviewerChange: (name: string) => void;
}) {
  const [note, setNote] = useState("");
  const reviewMap = new Map(fixture.review_items.map(r => [`${r.entity}::${r.field}`, r]));
  const pendingMap = new Map(pendingActions.map(a => [`${a.entity}::${a.field}`, a]));

  const allCells: Array<{ entity: string; field: string; cell: { op: string; confidence: string; oracle_why: string } }> = [];
  for (const [entity, fmap] of Object.entries(fixture.expected)) {
    for (const [field, cell] of Object.entries(fmap as Record<string, { op: string; confidence: string; oracle_why: string }>)) {
      allCells.push({ entity, field, cell });
    }
  }

  const needReviewCount = fixture.review_items.filter(r => r.action == null).length;
  const unsaved = pendingActions.length;

  return (
    <div className="w-80 shrink-0 border-l border-gray-700 flex flex-col bg-gray-900">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-200">Oracle Review</span>
          {unsaved > 0 && (
            <button
              className="text-[10px] px-2.5 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-50 font-semibold"
              disabled={isSaving} onClick={onSave}
            >
              {isSaving ? "Saving…" : `Save ${unsaved}`}
            </button>
          )}
        </div>
        <div className="text-[10px] text-gray-500">
          {allCells.length} cells ·
          {needReviewCount > 0
            ? <span className="text-yellow-400 ml-1">{needReviewCount} need review</span>
            : <span className="text-green-400 ml-1">all reviewed</span>
          }
        </div>
        <input
          className="w-full text-xs bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-300 placeholder-gray-600"
          placeholder="Reviewer name…"
          value={reviewerName}
          onChange={e => onReviewerChange(e.target.value)}
        />
      </div>

      {/* Cell list */}
      <div className="flex-1 overflow-y-auto">
        {allCells.map(({ entity, field, cell }) => (
          <CellReviewItem
            key={`${entity}::${field}`}
            entity={entity} field={field} cell={cell}
            reviewItem={reviewMap.get(`${entity}::${field}`)}
            pendingAction={pendingMap.get(`${entity}::${field}`)}
            onAction={onAction}
            actions={schema.actions}
          />
        ))}
      </div>

      {/* Review notes */}
      <div className="px-3 py-2 border-t border-gray-700 shrink-0">
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Review Notes</div>
        <textarea
          className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-300 placeholder-gray-600 resize-none focus:outline-none focus:border-gray-500"
          rows={3}
          placeholder="Optional notes…"
          value={note}
          onChange={e => setNote(e.target.value)}
        />
      </div>
    </div>
  );
}

// ─── Add / Edit modal ─────────────────────────────────────────────────────────

const INPUT_PLACEHOLDER = `{
  "route": {
    "endpoint": "/orders/{id}",
    "http_method": "DELETE",
    "use_case": "DELETE /orders/{id}"
  },
  "entities": [
    {
      "short_name": "Order",
      "fields": [
        { "name": "id", "db_column": "id", "type": "Long", "annotations": ["@Id"] }
      ]
    }
  ],
  "call_subgraph": {
    "OrderController::deleteOrder": [
      { "from_class": "OrderController", "to_class": "OrderService", "to_method": "deleteOrder" },
      { "from_class": "OrderService", "to_class": "OrderRepository", "to_method": "delete" }
    ]
  }
}`;

function FixtureModal({
  mode, fixture, onClose, onGenerate, isGenerating,
}: {
  mode: "add" | "edit";
  fixture: OracleFixtureDetail | null;
  onClose: () => void;
  onGenerate: (caseId: string, inputData: Record<string, unknown>) => void;
  isGenerating: boolean;
}) {
  const [caseId, setCaseId] = useState(mode === "edit" && fixture ? fixture.fixture_id : "");
  const [inputJson, setInputJson] = useState(
    mode === "edit" && fixture
      ? JSON.stringify(fixture.input_data, null, 2)
      : ""
  );
  const [jsonError, setJsonError] = useState<string | null>(null);

  function handleSubmit() {
    setJsonError(null);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(inputJson);
      if (typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Must be a JSON object");
    } catch (e) {
      setJsonError((e as Error).message);
      return;
    }
    onGenerate(caseId, parsed);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-[720px] max-h-[90vh] flex flex-col bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden">
        {/* Modal header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-gray-100">
              {mode === "add" ? "New Oracle Fixture" : "Edit Oracle Fixture"}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {mode === "add"
                ? "Provide a case ID and route context JSON, then generate the oracle expectation."
                : "Edit the input data and regenerate the oracle expectation."}
            </p>
          </div>
          <button className="text-gray-500 hover:text-gray-300 text-xl leading-none" onClick={onClose}>×</button>
        </div>

        {/* Modal body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* Case ID */}
          <div>
            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
              Case ID
            </label>
            <input
              className="w-full text-sm bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 font-mono placeholder-gray-600 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
              placeholder="e.g. case2_update_order"
              value={caseId}
              onChange={e => setCaseId(e.target.value.replace(/\s+/g, "_"))}
              disabled={mode === "edit"}
            />
          </div>

          {/* Input JSON */}
          <div className="flex-1">
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                Input Data (route_context JSON)
              </label>
              {jsonError && <span className="text-[10px] text-red-400">⚠ {jsonError}</span>}
            </div>
            <div className="flex border border-gray-700 rounded-lg overflow-hidden">
              {/* Line numbers */}
              <div className="shrink-0 bg-gray-900 text-gray-600 text-right px-2 py-3 select-none border-r border-gray-700 text-[10px] leading-5 font-mono min-w-[36px]">
                {inputJson.split("\n").map((_, i) => <div key={i}>{i + 1}</div>)}
              </div>
              <textarea
                className="flex-1 bg-gray-950 text-gray-300 px-4 py-3 text-xs font-mono leading-5 resize-none focus:outline-none min-h-[300px]"
                placeholder={INPUT_PLACEHOLDER}
                value={inputJson}
                onChange={e => { setInputJson(e.target.value); setJsonError(null); }}
                spellCheck={false}
              />
            </div>
          </div>
        </div>

        {/* Modal footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-700 bg-gray-900 shrink-0">
          <button className="text-xs text-gray-500 hover:text-gray-300 transition-colors" onClick={onClose}>
            Cancel
          </button>
          <button
            className="text-xs px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 flex items-center gap-2 transition-colors"
            disabled={!caseId.trim() || !inputJson.trim() || isGenerating}
            onClick={handleSubmit}
          >
            {isGenerating ? <><span className="animate-spin">⟳</span> Generating…</> : <>▶ Generate & Save</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

type CenterTab = "input" | "oracle-gen" | "expectation" | "preview";

export function OracleReviewPage() {
  const { suiteId } = useParams<{ suiteId: string }>();
  const { data: schema } = useOracleSchema();
  const { data: summaries = [], isLoading: loadingList } = useOracleFixtures(suiteId);

  const [selectedId, setSelectedId] = useState<string>("");
  const activeId = selectedId || summaries[0]?.fixture_id || "";

  const { data: fixture, isLoading: loadingFixture } = useOracleFixture(activeId);
  const updateMutation = useUpdateOracleReview(activeId);
  const runMutation = useRunOracle();
  const generateMutation = useGenerateOracle();
  const deleteMutation = useDeleteOracleFixture();

  const [pendingActions, setPendingActions] = useState<ReviewActionPayload[]>([]);
  const [reviewerName, setReviewerName] = useState("");
  const [centerTab, setCenterTab] = useState<CenterTab>("input");
  const [preview, setPreview] = useState<OracleRunPreview | null>(null);
  const [modal, setModal] = useState<"add" | "edit" | null>(null);

  // Reset state when active fixture changes
  const [lastActiveId, setLastActiveId] = useState(activeId);
  if (lastActiveId !== activeId) {
    setLastActiveId(activeId);
    setPendingActions([]);
    setPreview(null);
    setCenterTab("input");
  }

  function handleAction(action: ReviewActionPayload) {
    setPendingActions(prev => {
      const filtered = prev.filter(a => !(a.entity === action.entity && a.field === action.field));
      if (action.action === "approve" && prev.some(a => a.entity === action.entity && a.field === action.field && a.action === "approve"))
        return filtered;
      return [...filtered, action];
    });
  }

  async function handleSave() {
    await updateMutation.mutateAsync({ actions: pendingActions, reviewed_by: reviewerName || undefined });
    setPendingActions([]);
  }

  async function handleRun() {
    setCenterTab("preview");
    setPreview(null);
    const result = await runMutation.mutateAsync(activeId);
    setPreview(result);
  }

  async function handleExport() {
    const data = await apiFetch(`/oracle-review/${activeId}/export`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${activeId}.json`; a.click();
    URL.revokeObjectURL(url);
  }

  async function handleGenerate(caseId: string, inputData: Record<string, unknown>) {
    await generateMutation.mutateAsync({ case_id: caseId, input_data: inputData });
    setModal(null);
    setSelectedId(caseId);
  }

  function handleDelete(id: string) {
    if (!window.confirm(`Delete fixture "${id}"? This cannot be undone.`)) return;
    deleteMutation.mutate(id, {
      onSuccess: () => { if (selectedId === id) setSelectedId(""); },
    });
  }

  const CENTER_TABS: { id: CenterTab; label: string }[] = [
    { id: "input",       label: "Input" },
    { id: "oracle-gen",  label: "Oracle Generation" },
    { id: "expectation", label: "Expectation" },
    { id: "preview",     label: preview ? "Preview ●" : "Preview" },
  ];

  return (
    <div className="h-[calc(100vh-56px)] flex flex-col bg-gray-950">
      {/* Pipeline header */}
      <PipelineHeader fixture={fixture ?? null} />

      {/* Body */}
      <div className="flex-1 min-h-0 flex">
        {/* Left sidebar */}
        <FixtureSidebar
          summaries={summaries}
          activeId={activeId}
          onSelect={id => { setSelectedId(id); setPendingActions([]); setPreview(null); }}
          onAdd={() => setModal("add")}
          onEdit={id => { setSelectedId(id); setModal("edit"); }}
          onDelete={handleDelete}
          isLoading={loadingList}
        />

        {/* Center panel */}
        <div className="flex-1 min-w-0 flex flex-col border-r border-gray-700">
          {/* Center toolbar */}
          {fixture && (
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700 bg-gray-900 shrink-0">
              <div className="flex gap-0">
                {CENTER_TABS.map(tab => (
                  <button key={tab.id} onClick={() => setCenterTab(tab.id)}
                    className={`px-4 py-1.5 text-xs font-semibold transition-colors ${
                      centerTab === tab.id
                        ? "text-indigo-400 border-b-2 border-indigo-400 bg-gray-800"
                        : "text-gray-500 hover:text-gray-300"
                    }`}>
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <button
                  className="text-xs px-3 py-1.5 rounded bg-indigo-700 hover:bg-indigo-600 text-white font-semibold disabled:opacity-50 flex items-center gap-1.5 transition-colors"
                  disabled={runMutation.isPending}
                  onClick={handleRun}
                >
                  {runMutation.isPending
                    ? <><span className="animate-spin">⟳</span> Running…</>
                    : <>▶ Run Oracle</>}
                </button>
                <button className="text-xs px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors" onClick={handleExport}>
                  Export JSON
                </button>
              </div>
            </div>
          )}

          {/* Center content */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {loadingFixture ? (
              <div className="h-full flex items-center justify-center text-gray-500 text-sm">Loading fixture…</div>
            ) : !fixture ? (
              <div className="h-full flex flex-col items-center justify-center text-center gap-3">
                <div className="text-gray-500 text-sm">Select a fixture from the sidebar</div>
                <button className="text-xs px-4 py-2 rounded bg-indigo-700 hover:bg-indigo-600 text-white" onClick={() => setModal("add")}>
                  + Create First Fixture
                </button>
              </div>
            ) : (
              <>
                {centerTab === "input"       && <InputTab fixture={fixture} />}
                {centerTab === "oracle-gen"  && <OracleGenTab fixtureId={activeId} />}
                {centerTab === "expectation" && <ExpectationTab fixture={fixture} />}
                {centerTab === "preview"     && <PreviewTab preview={preview} isRunning={runMutation.isPending} />}
              </>
            )}
          </div>
        </div>

        {/* Right review panel */}
        {fixture && schema ? (
          <ReviewSidePanel
            schema={schema}
            fixture={fixture}
            pendingActions={pendingActions}
            onAction={handleAction}
            onSave={handleSave}
            isSaving={updateMutation.isPending}
            reviewerName={reviewerName}
            onReviewerChange={setReviewerName}
          />
        ) : (
          <div className="w-80 shrink-0 border-l border-gray-700 flex items-center justify-center bg-gray-900 text-gray-600 text-xs">
            {!fixture ? "Select a fixture" : "Loading schema…"}
          </div>
        )}
      </div>

      {/* Add / Edit modal */}
      {modal && (
        <FixtureModal
          mode={modal}
          fixture={modal === "edit" ? (fixture ?? null) : null}
          onClose={() => setModal(null)}
          onGenerate={handleGenerate}
          isGenerating={generateMutation.isPending}
        />
      )}
    </div>
  );
}
