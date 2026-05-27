import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import {
  useSuites, useSuite, useSaveDefaultPrompt,
  useOracleFixtures, useOracleFixture,
  useUpdateOracleReview, useOraclePrompt, useRunOracle,
  useGenerateOracle, useDeleteOracleFixture,
  useCreateSuite, useUpdateSuite, useDeleteSuite,
} from "@/api/hooks";
import type {
  Suite,
  OracleFixtureDetail, OracleReviewItem,
  ReviewActionPayload, OracleRunPreview,
} from "@/api/types";

// ─── CollapseSection ──────────────────────────────────────────────────────────

function CollapseSection({ title, badge, children, defaultOpen = false, onOpen }: {
  title: string; badge?: string; children: React.ReactNode;
  defaultOpen?: boolean; onOpen?: () => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  function toggle() {
    if (!open && onOpen) onOpen();
    setOpen(o => !o);
  }
  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={toggle}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className={`text-[10px] transition-transform duration-150 ${open ? "rotate-90" : ""}`}>▶</span>
          <span>{title}</span>
          {badge && (
            <span className="text-[10px] font-mono bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 px-1.5 py-0.5 rounded">
              {badge}
            </span>
          )}
        </div>
        <span className="text-[10px] text-gray-400">{open ? "collapse" : "expand"}</span>
      </button>
      {open && <div className="bg-white dark:bg-gray-900">{children}</div>}
    </div>
  );
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
    <div className="flex flex-col border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      {(title || badge) && (
        <div className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            {title && <span className="text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">{title}</span>}
            {badge && (
              <span className="text-[10px] text-gray-400 font-mono bg-gray-100 dark:bg-gray-900 px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-700">
                {badge}
              </span>
            )}
          </div>
          <button className="text-[10px] text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 font-mono transition-colors" onClick={copy}>
            {copied ? "✓ copied" : "copy"}
          </button>
        </div>
      )}
      <div className="flex min-h-0 overflow-y-auto" style={{ maxHeight }}>
        <div className="shrink-0 bg-gray-50 dark:bg-gray-900 text-gray-400 text-right px-2.5 py-3 select-none border-r border-gray-200 dark:border-gray-700 text-[10px] leading-5 font-mono min-w-[36px]">
          {lines.map((_, i) => <div key={i}>{i + 1}</div>)}
        </div>
        <pre className="flex-1 bg-white dark:bg-gray-950 text-gray-800 dark:text-gray-300 px-4 py-3 overflow-x-auto text-xs leading-5 font-mono whitespace-pre">
          {content}
        </pre>
      </div>
    </div>
  );
}

// ─── OpBadge / ConfBadge ──────────────────────────────────────────────────────

function OpBadge({ op }: { op: string }) {
  const colors: Record<string, string> = {
    C: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 border-green-200 dark:border-green-700",
    R: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-700",
    U: "bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300 border-yellow-200 dark:border-yellow-700",
    D: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300 border-red-200 dark:border-red-700",
  };
  if (!op) return (
    <span className="text-gray-400 font-mono text-xs border border-gray-200 dark:border-gray-700 px-1.5 py-0.5 rounded">—</span>
  );
  return (
    <span className="flex gap-0.5">
      {op.split("").map(ch => (
        <span key={ch} className={`font-mono text-xs font-bold px-1.5 py-0.5 rounded border ${colors[ch] ?? "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-600"}`}>
          {ch}
        </span>
      ))}
    </span>
  );
}

function ConfBadge({ confidence }: { confidence: string }) {
  const cls =
    confidence === "high"   ? "text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800" :
    confidence === "medium" ? "text-yellow-700 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950 border-yellow-200 dark:border-yellow-800" :
                              "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800";
  return (
    <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${cls}`}>{confidence}</span>
  );
}

// ─── TabBar ───────────────────────────────────────────────────────────────────

type TabId = "input" | "oracle-prompt" | "expectation" | "review";

const TABS: { id: TabId; label: string }[] = [
  { id: "input",         label: "1. Input" },
  { id: "oracle-prompt", label: "2. Oracle Prompt" },
  { id: "expectation",   label: "3. Expectation" },
  { id: "review",        label: "4. Review" },
];

function TabBar({ active, onChange }: { active: TabId; onChange: (t: TabId) => void }) {
  return (
    <div className="flex border-b border-gray-200 dark:border-gray-700 shrink-0">
      {TABS.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px ${
            active === tab.id
              ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
              : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ─── Tab 1: Input ─────────────────────────────────────────────────────────────

function Tab1_Input({ fixture, suiteId }: { fixture: OracleFixtureDetail; suiteId: string }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const input = fixture.input_data as any;
  const route    = input?.route;
  const entities = input?.entities ?? [];
  const routeBadge = route ? `${route.http_method ?? ""} ${route.endpoint ?? ""}`.trim() : undefined;
  const inputJson  = JSON.stringify(fixture.input_data, null, 2);

  const { data: suite } = useSuite(suiteId);
  const saveMutation = useSaveDefaultPrompt(suiteId);
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [promptDraft, setPromptDraft] = useState("");
  const productionPrompt = suite?.default_system_prompt ?? "";

  function startEdit() {
    setPromptDraft(productionPrompt);
    setEditingPrompt(true);
  }

  async function savePrompt() {
    await saveMutation.mutateAsync(promptDraft);
    setEditingPrompt(false);
  }

  return (
    <div className="space-y-3">
      {/* Fixture meta */}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-500 dark:text-gray-400 pb-1">
        <span><span className="font-medium text-gray-700 dark:text-gray-300">ID</span>{" "}{fixture.fixture_id}</span>
        <span><span className="font-medium text-gray-700 dark:text-gray-300">Model</span>{" "}{fixture.oracle_model}</span>
        <span><span className="font-medium text-gray-700 dark:text-gray-300">Prompt ver.</span>{" "}{fixture.prompt_version}</span>
        <span>
          <span className="font-medium text-gray-700 dark:text-gray-300">Review</span>{" "}
          {fixture.review_items.filter(r => r.action == null).length} pending / {fixture.review_items.length} total
        </span>
      </div>

      {/* Production Prompt — shared with SuiteDetail */}
      <CollapseSection title="Production Prompt (System)">
        {editingPrompt ? (
          <div className="p-3 space-y-2">
            <textarea
              className="w-full text-xs font-mono bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400 resize-none"
              rows={8}
              value={promptDraft}
              onChange={e => setPromptDraft(e.target.value)}
              placeholder="Enter the production system prompt…"
            />
            <div className="flex gap-2">
              <button
                className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 transition-colors"
                disabled={saveMutation.isPending}
                onClick={savePrompt}
              >{saveMutation.isPending ? "Saving…" : "Save"}</button>
              <button
                className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                onClick={() => setEditingPrompt(false)}
              >Cancel</button>
            </div>
          </div>
        ) : productionPrompt ? (
          <div className="relative">
            <CodePane title="" content={productionPrompt} maxHeight="280px" />
            <button
              className="absolute top-2 right-12 text-[10px] px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-500 dark:text-gray-300 transition-colors"
              onClick={startEdit}
            >✏ Edit</button>
          </div>
        ) : (
          <div className="px-4 py-3 flex items-center gap-3 text-xs text-gray-400">
            <span>No production prompt set for this suite.</span>
            <button
              className="px-2 py-1 rounded bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-700 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 transition-colors font-medium"
              onClick={startEdit}
            >+ Add prompt</button>
          </div>
        )}
      </CollapseSection>

      {/* Route Context */}
      <CollapseSection title="Route Context JSON" badge={routeBadge}>
        <div className="p-3">
          <CodePane title="input_data" content={inputJson} maxHeight="300px" />
        </div>
      </CollapseSection>

      {/* Entities */}
      {entities.length > 0 && (
        <CollapseSection title="Entities" badge={`${entities.length}`}>
          <div className="p-3 space-y-2">
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            {entities.map((e: any) => (
              <div key={e.short_name ?? e.name} className="border border-gray-100 dark:border-gray-800 rounded-lg p-3 bg-gray-50 dark:bg-gray-800">
                <div className="text-xs font-semibold text-gray-700 dark:text-gray-200 mb-1">{e.short_name ?? e.name}</div>
                <div className="flex flex-wrap gap-1">
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {(e.fields ?? []).map((f: any) => (
                    <span key={f.name} className="text-[10px] font-mono bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 px-1.5 py-0.5 rounded text-gray-600 dark:text-gray-400">
                      {f.name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </CollapseSection>
      )}
    </div>
  );
}

// ─── Tab 2: Oracle Prompt ─────────────────────────────────────────────────────

function Tab2_OraclePrompt({ fixtureId }: { fixtureId: string }) {
  const [promptEnabled, setPromptEnabled] = useState(false);
  const { data: prompt, isLoading, isError } = useOraclePrompt(fixtureId, promptEnabled);
  function enable() { setPromptEnabled(true); }

  function Content({ text }: { text: string }) {
    return <div className="p-3"><CodePane title="" content={text} maxHeight="320px" /></div>;
  }
  function Status() {
    if (isLoading) return <div className="px-4 py-3 text-xs text-gray-400 animate-pulse">Loading…</div>;
    if (isError || !prompt) return <div className="px-4 py-3 text-xs text-red-500">Failed — check that oracle_strategy_factory implements render_prompt().</div>;
    return null;
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Rendered by <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">render_prompt(input_data)</code> on the oracle strategy.
        Expand a section to fetch, or paste manually below.
      </p>
      <CollapseSection title="System Prompt" onOpen={enable}>
        {!promptEnabled ? <div className="px-4 py-3 text-xs text-gray-400">Expanding will fetch from server…</div>
          : !prompt ? <Status /> : <Content text={prompt.system} />}
      </CollapseSection>
      <CollapseSection title="User Prompt" onOpen={enable}>
        {!promptEnabled ? <div className="px-4 py-3 text-xs text-gray-400">Expanding will fetch from server…</div>
          : !prompt ? <Status /> : <Content text={prompt.user} />}
      </CollapseSection>
      <CollapseSection title="Manual Override (optional)">
        <div className="p-3">
          <textarea
            className="w-full text-xs font-mono bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400 resize-none"
            rows={5}
            placeholder="Paste a custom prompt here to override the auto-generated one when running the oracle…"
          />
        </div>
      </CollapseSection>
    </div>
  );
}

// ─── Tab 3: Expectation ───────────────────────────────────────────────────────

function Tab3_Expectation({ fixture, onRun, isRunning, preview }: {
  fixture: OracleFixtureDetail; onRun: () => void; isRunning: boolean; preview: OracleRunPreview | null;
}) {
  const source = preview ? preview.cells : fixture.expected;
  const entities = Object.keys(source);
  const hasCells = entities.length > 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {hasCells
            ? <>{entities.length} entities · {entities.reduce((n, e) => n + Object.keys(source[e]).length, 0)} cells</>
            : "No expectation yet — run the oracle to generate."}
          {preview && <span className="ml-2 text-indigo-600 dark:text-indigo-400 font-medium">(preview · not saved)</span>}
        </p>
        <button
          onClick={onRun} disabled={isRunning}
          className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 flex items-center gap-1.5 transition-colors"
        >
          {isRunning ? <><span className="animate-spin inline-block">⟳</span> Running…</> : <>▶ Run Oracle</>}
        </button>
      </div>

      {hasCells && (
        <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="w-full text-xs min-w-[560px]">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-left">
                {["Entity", "Field", "OP", "Confidence", "Reasoning"].map(h => (
                  <th key={h} className="px-3 py-2 font-semibold text-gray-600 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entities.flatMap(entity =>
                Object.entries(source[entity]).map(([field, cell]) => (
                  <tr key={`${entity}::${field}`} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                    <td className="px-3 py-2 font-mono font-medium text-gray-700 dark:text-gray-300">{entity}</td>
                    <td className="px-3 py-2 font-mono text-gray-500 dark:text-gray-400">{field}</td>
                    <td className="px-3 py-2"><OpBadge op={cell.op} /></td>
                    <td className="px-3 py-2"><ConfBadge confidence={cell.confidence} /></td>
                    <td className="px-3 py-2 text-gray-500 dark:text-gray-400 max-w-[240px] truncate" title={cell.oracle_why}>{cell.oracle_why}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Tab 4: Human Review ──────────────────────────────────────────────────────

function ReviewCell({ item, pending, onAction }: {
  item: OracleReviewItem; pending: ReviewActionPayload | undefined; onAction: (a: ReviewActionPayload) => void;
}) {
  const current = pending?.action ?? item.action;
  const [showFix, setShowFix] = useState(false);
  const [customOp, setCustomOp] = useState(pending?.corrected_op ?? item.corrected_op ?? "");

  const wrapCls =
    current === "approve" ? "border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/30" :
    current === "remove"  ? "border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30" :
    current === "fix"     ? "border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950/30" :
                            "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900";

  return (
    <div className={`p-3 rounded-lg border transition-colors ${wrapCls}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 font-mono">{item.entity}</span>
            <span className="text-gray-300 dark:text-gray-600">·</span>
            <span className="text-xs font-mono text-gray-500 dark:text-gray-400">{item.field}</span>
            <OpBadge op={item.op} />
            <ConfBadge confidence={item.confidence} />
          </div>
          <p className="text-[11px] text-gray-500 dark:text-gray-400 leading-relaxed line-clamp-2">{item.oracle_why}</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button onClick={() => onAction({ entity: item.entity, field: item.field, action: "approve" })}
            className={`text-[11px] px-2 py-1 rounded border transition-colors font-medium ${current === "approve" ? "bg-green-500 border-green-500 text-white" : "border-gray-200 dark:border-gray-600 text-gray-500 hover:border-green-300 hover:text-green-600"}`}>
            ✓ Approve</button>
          <button onClick={() => setShowFix(f => !f)}
            className={`text-[11px] px-2 py-1 rounded border transition-colors font-medium ${current === "fix" ? "bg-yellow-500 border-yellow-500 text-white" : "border-gray-200 dark:border-gray-600 text-gray-500 hover:border-yellow-300 hover:text-yellow-600"}`}>
            ✏ Fix</button>
          <button onClick={() => onAction({ entity: item.entity, field: item.field, action: "remove" })}
            className={`text-[11px] px-2 py-1 rounded border transition-colors font-medium ${current === "remove" ? "bg-red-500 border-red-500 text-white" : "border-gray-200 dark:border-gray-600 text-gray-500 hover:border-red-300 hover:text-red-600"}`}>
            ✕ Remove</button>
        </div>
      </div>
      {showFix && (
        <div className="mt-2 flex items-center gap-2">
          <input
            className="flex-1 text-xs border border-gray-200 dark:border-gray-600 rounded px-2 py-1 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 font-mono focus:outline-none focus:border-yellow-400"
            placeholder="Corrected op (e.g. CU)"
            value={customOp}
            onChange={e => setCustomOp(e.target.value.toUpperCase())}
          />
          <button
            className="text-xs px-2 py-1 rounded bg-yellow-500 text-white font-semibold disabled:opacity-50"
            disabled={!customOp.trim()}
            onClick={() => { onAction({ entity: item.entity, field: item.field, action: "fix", corrected_op: customOp }); setShowFix(false); }}
          >Apply</button>
        </div>
      )}
    </div>
  );
}

function Tab4_Review({ fixture, pendingActions, onAction, onSave, isSaving, reviewerName, onReviewerChange }: {
  fixture: OracleFixtureDetail; pendingActions: ReviewActionPayload[];
  onAction: (a: ReviewActionPayload) => void; onSave: () => void;
  isSaving: boolean; reviewerName: string; onReviewerChange: (s: string) => void;
}) {
  const pendingMap = new Map(pendingActions.map(a => [`${a.entity}::${a.field}`, a]));
  const pendingCount = fixture.review_items.filter(r => r.action == null).length;

  if (fixture.review_items.length === 0) {
    return (
      <p className="text-sm text-center py-8 text-gray-400 dark:text-gray-500">
        No review items — all cells are high-confidence or expectation not yet generated.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <input
          className="flex-1 text-sm border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400"
          placeholder="Reviewer name…"
          value={reviewerName}
          onChange={e => onReviewerChange(e.target.value)}
        />
        <span className="text-xs shrink-0">
          {pendingCount > 0
            ? <span className="text-yellow-600 dark:text-yellow-400">{pendingCount} pending</span>
            : <span className="text-green-600 dark:text-green-400">✓ all reviewed</span>}
        </span>
        <button
          onClick={onSave}
          disabled={isSaving || pendingActions.length === 0}
          className="text-sm px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-40 transition-colors shrink-0"
        >
          {isSaving ? "Saving…" : `Save (${pendingActions.length})`}
        </button>
      </div>
      <div className="space-y-2">
        {fixture.review_items.map(item => (
          <ReviewCell
            key={`${item.entity}::${item.field}`}
            item={item}
            pending={pendingMap.get(`${item.entity}::${item.field}`)}
            onAction={onAction}
          />
        ))}
      </div>
    </div>
  );
}

// ─── Fixture list (within an expanded suite) ──────────────────────────────────

function SuiteFixtures({ suiteId, selectedId, onSelect, onDelete }: {
  suiteId: string; selectedId: string;
  onSelect: (id: string) => void; onDelete: (id: string) => void;
}) {
  const { data: fixtures = [], isLoading } = useOracleFixtures(suiteId);

  if (isLoading) return <div className="px-5 py-2 text-[10px] text-gray-400 animate-pulse">Loading…</div>;
  if (fixtures.length === 0) return (
    <div className="px-5 py-2 text-[10px] text-gray-400">No cases yet</div>
  );

  return (
    <>
      {fixtures.map(f => (
        <div
          key={f.fixture_id}
          onClick={() => onSelect(f.fixture_id)}
          className={`pl-8 pr-3 py-2 cursor-pointer flex items-center gap-2 transition-colors ${
            f.fixture_id === selectedId
              ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300"
              : "hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
          }`}
        >
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${f.pending_review > 0 ? "bg-yellow-400" : "bg-green-500"}`} />
          <span className="text-xs truncate flex-1" title={f.fixture_id}>{f.fixture_id}</span>
          {f.fixture_id === selectedId && (
            <button
              className="text-[10px] px-1 py-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900 text-gray-400 hover:text-red-500 transition-colors"
              onClick={e => { e.stopPropagation(); onDelete(f.fixture_id); }}
            >🗑</button>
          )}
        </div>
      ))}
    </>
  );
}

// ─── Sidebar tree ─────────────────────────────────────────────────────────────

function OracleTree({ suites, expandedId, selectedFixtureId, onToggleSuite, onSelectFixture,
  onAddSuite, onEditSuite, onDeleteSuite, onAddCase, onDeleteCase, isLoadingSuites }: {
  suites: Suite[]; expandedId: string; selectedFixtureId: string;
  onToggleSuite: (id: string) => void; onSelectFixture: (suiteId: string, fixtureId: string) => void;
  onAddSuite: () => void; onEditSuite: (suite: Suite) => void; onDeleteSuite: (id: string) => void;
  onAddCase: (suiteId: string) => void; onDeleteCase: (suiteId: string, fixtureId: string) => void;
  isLoadingSuites: boolean;
}) {
  return (
    <aside className="w-60 shrink-0 border-r border-gray-200 dark:border-gray-700 flex flex-col bg-white dark:bg-gray-900 overflow-hidden">
      <div className="px-3 py-2.5 border-b border-gray-200 dark:border-gray-700 shrink-0">
        <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Oracle Review</div>
        <button
          onClick={onAddSuite}
          className="w-full text-xs py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold transition-colors"
        >+ New Suite</button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoadingSuites ? (
          <div className="p-4 text-xs text-gray-400 text-center animate-pulse">Loading…</div>
        ) : suites.length === 0 ? (
          <div className="p-4 text-xs text-gray-400 text-center">No suites yet</div>
        ) : suites.map(suite => {
          const isExpanded = suite.suite_id === expandedId;
          return (
            <div key={suite.suite_id}>
              {/* Suite row */}
              <div
                className={`px-3 py-2.5 flex items-center gap-2 cursor-pointer group transition-colors ${
                  isExpanded ? "bg-gray-50 dark:bg-gray-800" : "hover:bg-gray-50 dark:hover:bg-gray-800"
                }`}
                onClick={() => onToggleSuite(suite.suite_id)}
              >
                <span className={`text-[10px] text-gray-400 transition-transform duration-150 shrink-0 ${isExpanded ? "rotate-90" : ""}`}>▶</span>
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 truncate flex-1">
                  {suite.title ?? suite.suite_id}
                </span>
                <div className="hidden group-hover:flex items-center gap-0.5 shrink-0" onClick={e => e.stopPropagation()}>
                  <button
                    className="text-[10px] p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-400 hover:text-gray-600 transition-colors"
                    onClick={() => onEditSuite(suite)}
                    title="Edit suite"
                  >✏</button>
                  <button
                    className="text-[10px] p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900 text-gray-400 hover:text-red-500 transition-colors"
                    onClick={() => onDeleteSuite(suite.suite_id)}
                    title="Delete suite"
                  >🗑</button>
                </div>
              </div>

              {/* Expanded: fixtures + add button */}
              {isExpanded && (
                <>
                  <SuiteFixtures
                    suiteId={suite.suite_id}
                    selectedId={selectedFixtureId}
                    onSelect={id => onSelectFixture(suite.suite_id, id)}
                    onDelete={id => onDeleteCase(suite.suite_id, id)}
                  />
                  <div className="pl-8 pr-3 py-1.5">
                    <button
                      onClick={() => onAddCase(suite.suite_id)}
                      className="w-full text-[10px] py-1 rounded border border-dashed border-gray-300 dark:border-gray-600 text-gray-400 hover:text-indigo-500 hover:border-indigo-300 dark:hover:border-indigo-600 transition-colors"
                    >+ New Case</button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

// ─── Suite modal (create / edit) ──────────────────────────────────────────────

function SuiteModal({ mode, suite, onClose }: {
  mode: "create" | "edit"; suite?: Suite; onClose: () => void;
}) {
  const [suiteId, setSuiteId] = useState(suite?.suite_id ?? "");
  const [title, setTitle]     = useState(suite?.title ?? suite?.suite_id ?? "");
  const [prompt, setPrompt]   = useState(suite?.default_system_prompt ?? "");

  const createMutation = useCreateSuite();
  const updateMutation = useUpdateSuite(suite?.suite_id ?? "");

  async function handleSubmit() {
    if (mode === "create") {
      await createMutation.mutateAsync({ suite_id: suiteId, title: title || undefined, default_system_prompt: prompt || undefined });
    } else {
      await updateMutation.mutateAsync({ title: title || undefined, default_system_prompt: prompt || undefined });
    }
    onClose();
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-[580px] max-h-[88vh] flex flex-col bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
            {mode === "create" ? "New Suite" : `Edit Suite — ${suite?.suite_id}`}
          </h2>
          <button className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none" onClick={onClose}>×</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {mode === "create" && (
            <div>
              <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Suite ID</label>
              <input
                className="w-full text-sm border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 font-mono placeholder-gray-400 focus:outline-none focus:border-indigo-400"
                placeholder="e.g. crud_matrix_llm"
                value={suiteId}
                onChange={e => setSuiteId(e.target.value.replace(/\s+/g, "_"))}
              />
            </div>
          )}
          <div>
            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Title</label>
            <input
              className="w-full text-sm border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:border-indigo-400"
              placeholder="e.g. CRUD Matrix LLM"
              value={title}
              onChange={e => setTitle(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
              Production System Prompt <span className="font-normal text-gray-400 normal-case">(optional — shared with SuiteDetail)</span>
            </label>
            <textarea
              className="w-full text-xs font-mono border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400 resize-none"
              rows={8}
              placeholder="Paste your production system prompt here…"
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
            />
          </div>
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-200 dark:border-gray-700 shrink-0">
          <button className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors" onClick={onClose}>Cancel</button>
          <button
            className="text-xs px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 transition-colors"
            disabled={isPending || (mode === "create" && !suiteId.trim())}
            onClick={handleSubmit}
          >
            {isPending ? "Saving…" : mode === "create" ? "Create Suite" : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Fixture (case) modal ─────────────────────────────────────────────────────

const INPUT_PLACEHOLDER = `{
  "route": {
    "endpoint": "/orders/{id}",
    "http_method": "DELETE",
    "use_case": "Delete an order"
  },
  "entities": [
    { "short_name": "Order", "fields": [{ "name": "id" }, { "name": "status" }] }
  ],
  "call_subgraph": {}
}`;

function FixtureModal({ suiteId, fixture, onClose, onGenerate, isGenerating }: {
  suiteId: string; fixture?: OracleFixtureDetail;
  onClose: () => void; onGenerate: (caseId: string, inputData: Record<string, unknown>) => void;
  isGenerating: boolean;
}) {
  const isEdit = !!fixture;
  const [caseId, setCaseId]     = useState(fixture?.fixture_id ?? "");
  const [inputJson, setInputJson] = useState(fixture ? JSON.stringify(fixture.input_data, null, 2) : "");
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
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-[700px] max-h-[90vh] flex flex-col bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
              {isEdit ? "Edit Oracle Case" : "New Oracle Case"}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">Suite: <code className="font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">{suiteId}</code></p>
          </div>
          <button className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none" onClick={onClose}>×</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <div>
            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Case ID</label>
            <input
              className="w-full text-sm border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 font-mono placeholder-gray-400 focus:outline-none focus:border-indigo-400 disabled:opacity-50"
              placeholder="e.g. case2_delete_order"
              value={caseId}
              onChange={e => setCaseId(e.target.value.replace(/\s+/g, "_"))}
              disabled={isEdit}
            />
          </div>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Input Data (JSON)</label>
              {jsonError && <span className="text-[10px] text-red-500">⚠ {jsonError}</span>}
            </div>
            <div className="flex border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
              <div className="shrink-0 bg-gray-50 dark:bg-gray-900 text-gray-400 text-right px-2 py-3 select-none border-r border-gray-200 dark:border-gray-700 text-[10px] leading-5 font-mono min-w-[36px]">
                {inputJson.split("\n").map((_, i) => <div key={i}>{i + 1}</div>)}
              </div>
              <textarea
                className="flex-1 bg-white dark:bg-gray-950 text-gray-800 dark:text-gray-300 px-4 py-3 text-xs font-mono leading-5 resize-none focus:outline-none min-h-[280px]"
                placeholder={INPUT_PLACEHOLDER}
                value={inputJson}
                onChange={e => { setInputJson(e.target.value); setJsonError(null); }}
                spellCheck={false}
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-200 dark:border-gray-700 shrink-0">
          <button className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors" onClick={onClose}>Cancel</button>
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

// ─── Main Page ────────────────────────────────────────────────────────────────

export function OracleReviewPage() {
  const { suiteId: urlSuiteId } = useParams<{ suiteId?: string }>();
  const { data: suites = [], isLoading: loadingSuites } = useSuites();

  const [expandedSuiteId, setExpandedSuiteId]       = useState(urlSuiteId ?? "");

  // Sync URL suiteId → auto-expand on navigation
  useEffect(() => {
    if (urlSuiteId) setExpandedSuiteId(urlSuiteId);
  }, [urlSuiteId]);
  const [selectedFixtureId, setSelectedFixtureId]   = useState("");
  const [activeTab, setActiveTab]                   = useState<TabId>("input");
  const [suiteModal, setSuiteModal]                 = useState<null | { mode: "create" } | { mode: "edit"; suite: Suite }>(null);
  const [fixtureModal, setFixtureModal]             = useState<null | { suiteId: string; fixture?: OracleFixtureDetail }>(null);
  const [pendingActions, setPendingActions]         = useState<ReviewActionPayload[]>([]);
  const [reviewerName, setReviewerName]             = useState("");
  const [preview, setPreview]                       = useState<OracleRunPreview | null>(null);

  const { data: fixture, isLoading: loadingFixture } = useOracleFixture(selectedFixtureId);
  const updateMutation   = useUpdateOracleReview(selectedFixtureId);
  const runMutation      = useRunOracle();
  const generateMutation = useGenerateOracle();
  const deleteMutation   = useDeleteOracleFixture();
  const deleteSuite      = useDeleteSuite();

  // Reset pending state when fixture changes
  const [lastFixtureId, setLastFixtureId] = useState(selectedFixtureId);
  if (lastFixtureId !== selectedFixtureId) {
    setLastFixtureId(selectedFixtureId);
    setPendingActions([]);
    setPreview(null);
    setActiveTab("input");
  }

  function handleSelectFixture(suiteId: string, fixtureId: string) {
    setExpandedSuiteId(suiteId);
    setSelectedFixtureId(fixtureId);
    setPendingActions([]);
    setPreview(null);
    setActiveTab("input");
  }

  function handleToggleSuite(suiteId: string) {
    if (expandedSuiteId === suiteId) {
      setExpandedSuiteId("");
    } else {
      setExpandedSuiteId(suiteId);
      setSelectedFixtureId("");
    }
  }

  function handleAction(action: ReviewActionPayload) {
    setPendingActions(prev => [
      ...prev.filter(a => !(a.entity === action.entity && a.field === action.field)),
      action,
    ]);
  }

  async function handleSave() {
    await updateMutation.mutateAsync({ actions: pendingActions, reviewed_by: reviewerName || undefined });
    setPendingActions([]);
  }

  async function handleRun() {
    setPreview(null);
    const result = await runMutation.mutateAsync(selectedFixtureId);
    setPreview(result);
  }

  async function handleGenerate(caseId: string, inputData: Record<string, unknown>) {
    const suiteId = fixtureModal?.suiteId ?? expandedSuiteId;
    await generateMutation.mutateAsync({ case_id: caseId, suite_id: suiteId, input_data: inputData });
    setFixtureModal(null);
    setExpandedSuiteId(suiteId);
    setSelectedFixtureId(caseId);
  }

  function handleDeleteCase(_suiteId: string, fixtureId: string) {
    if (!window.confirm(`Delete case "${fixtureId}"?`)) return;
    deleteMutation.mutate(fixtureId, {
      onSuccess: () => { if (selectedFixtureId === fixtureId) setSelectedFixtureId(""); },
    });
  }

  function handleDeleteSuite(suiteId: string) {
    if (!window.confirm(`Delete suite "${suiteId}" and all its cases?`)) return;
    deleteSuite.mutate(suiteId, {
      onSuccess: () => {
        if (expandedSuiteId === suiteId) { setExpandedSuiteId(""); setSelectedFixtureId(""); }
      },
    });
  }

  const hasCells     = fixture ? Object.keys(fixture.expected).length > 0 : false;
  const pendingCount = fixture ? fixture.review_items.filter(r => r.action == null).length : 0;

  return (
    <div className="h-[calc(100vh-56px)] flex bg-gray-50 dark:bg-gray-950">
      <OracleTree
        suites={suites}
        expandedId={expandedSuiteId}
        selectedFixtureId={selectedFixtureId}
        onToggleSuite={handleToggleSuite}
        onSelectFixture={handleSelectFixture}
        onAddSuite={() => setSuiteModal({ mode: "create" })}
        onEditSuite={suite => setSuiteModal({ mode: "edit", suite })}
        onDeleteSuite={handleDeleteSuite}
        onAddCase={suiteId => setFixtureModal({ suiteId })}
        onDeleteCase={handleDeleteCase}
        isLoadingSuites={loadingSuites}
      />

      <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {!expandedSuiteId ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <p className="text-sm text-gray-400 dark:text-gray-500">Select a suite from the sidebar</p>
            <button
              className="text-sm px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold transition-colors"
              onClick={() => setSuiteModal({ mode: "create" })}
            >+ Create First Suite</button>
          </div>
        ) : !selectedFixtureId ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <p className="text-sm text-gray-400 dark:text-gray-500">Select a case or create one</p>
            <button
              className="text-sm px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold transition-colors"
              onClick={() => setFixtureModal({ suiteId: expandedSuiteId })}
            >+ New Case</button>
          </div>
        ) : (
          <>
            {/* Header breadcrumb */}
            <div className="px-6 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <Link
                to={`/suites/${expandedSuiteId}`}
                className="font-semibold text-gray-700 dark:text-gray-200 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
              >
                {suites.find(s => s.suite_id === expandedSuiteId)?.title ?? expandedSuiteId}
              </Link>
              <span>›</span>
              <span className="font-mono text-gray-500">{selectedFixtureId}</span>
              {hasCells && pendingCount === 0 && (
                <span className="ml-auto text-[10px] font-semibold text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-700 px-2 py-0.5 rounded-full">✓ reviewed</span>
              )}
              {pendingCount > 0 && (
                <span className="ml-auto text-[10px] font-semibold text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950 border border-yellow-200 dark:border-yellow-700 px-2 py-0.5 rounded-full">{pendingCount} pending</span>
              )}
            </div>

            {/* Tabs */}
            <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 shrink-0">
              <TabBar active={activeTab} onChange={setActiveTab} />
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto p-6">
              {loadingFixture ? (
                <div className="flex items-center justify-center h-32 text-sm text-gray-400">Loading…</div>
              ) : !fixture ? (
                <div className="flex items-center justify-center h-32 text-sm text-gray-400">Fixture not found</div>
              ) : (
                <div className="max-w-3xl mx-auto">
                  {activeTab === "input" && (
                    <Tab1_Input fixture={fixture} suiteId={expandedSuiteId} />
                  )}
                  {activeTab === "oracle-prompt" && (
                    <Tab2_OraclePrompt fixtureId={selectedFixtureId} />
                  )}
                  {activeTab === "expectation" && (
                    <Tab3_Expectation
                      fixture={fixture}
                      onRun={handleRun}
                      isRunning={runMutation.isPending}
                      preview={preview}
                    />
                  )}
                  {activeTab === "review" && (
                    <Tab4_Review
                      fixture={fixture}
                      pendingActions={pendingActions}
                      onAction={handleAction}
                      onSave={handleSave}
                      isSaving={updateMutation.isPending}
                      reviewerName={reviewerName}
                      onReviewerChange={setReviewerName}
                    />
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </main>

      {suiteModal && (
        <SuiteModal
          mode={suiteModal.mode}
          suite={suiteModal.mode === "edit" ? suiteModal.suite : undefined}
          onClose={() => setSuiteModal(null)}
        />
      )}

      {fixtureModal && (
        <FixtureModal
          suiteId={fixtureModal.suiteId}
          fixture={fixtureModal.fixture}
          onClose={() => setFixtureModal(null)}
          onGenerate={handleGenerate}
          isGenerating={generateMutation.isPending}
        />
      )}
    </div>
  );
}
