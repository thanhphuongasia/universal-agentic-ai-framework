import { useState, useEffect, type ReactNode } from "react";
import { useParams, Link } from "react-router-dom";
import {
  useSuites, useSuite, useSaveDefaultPrompt,
  useOracleFixtures, useOracleFixture,
  useUpdateOracleReview,
  useGenerateOracle, useDeleteOracleFixture,
  useCreateSuite, useUpdateSuite, useDeleteSuite,
  useLLMProviders, useMetaGenerateOraclePrompt,
  useRunWithPrompt, useSaveStudioFixture, usePromoteToSuite,
  type ProviderInfo,
} from "@/api/hooks";
import type {
  Suite,
  OracleFixtureDetail, OracleReviewItem,
  ReviewActionPayload,
} from "@/api/types";

// ─── Pipeline Header ──────────────────────────────────────────────────────────

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
    <div className="flex items-start gap-0 px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0 overflow-x-auto">
      {PIPE_STEPS.map((step, i) => {
        const s = statuses[i];
        const ringCls =
          s === "done"   ? "bg-green-500 border-green-500 text-white" :
          s === "active" ? "bg-yellow-400 border-yellow-400 text-black" :
          s === "na"     ? "bg-gray-100 dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-400 dark:text-gray-500" :
                           "bg-gray-100 dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-400 dark:text-gray-500";
        const labelCls =
          s === "done"   ? "text-green-600 dark:text-green-400" :
          s === "active" ? "text-yellow-600 dark:text-yellow-400" :
                           "text-gray-400 dark:text-gray-500";
        return (
          <div key={i} className="flex items-start shrink-0">
            <div className="flex flex-col items-center min-w-[100px]">
              <div className={`w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold ${ringCls}`}>
                {s === "done" ? "✓" : i + 1}
              </div>
              <div className="mt-1.5 text-center px-1">
                <div className="text-xs font-semibold text-gray-700 dark:text-gray-200 leading-tight">{step.label}</div>
                <div className="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5 leading-tight">{step.desc}</div>
                <div className={`text-[10px] mt-1 font-medium ${labelCls}`}>{statusLabel[s]}</div>
              </div>
            </div>
            {i < PIPE_STEPS.length - 1 && (
              <div className={`h-px w-8 mt-4 shrink-0 ${s === "done" ? "bg-green-500" : "bg-gray-200 dark:bg-gray-700"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

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

const TABS: { id: TabId; label: string; group: "Preparation" | "Execution" | "Review" }[] = [
  { id: "input",         label: "1. Input",         group: "Preparation" },
  { id: "oracle-prompt", label: "2. Oracle Prompt", group: "Preparation" },
  { id: "expectation",   label: "3. Execution",     group: "Execution" },
  { id: "review",        label: "4. Review & Approve", group: "Review" },
];

function TabBar({ active, onChange }: { active: TabId; onChange: (t: TabId) => void }) {
  const nodes: ReactNode[] = [];
  TABS.forEach((tab, i) => {
    const prevGroup = i > 0 ? TABS[i - 1].group : null;
    if (prevGroup !== null && prevGroup !== tab.group) {
      nodes.push(
        <div
          key={`sep-${tab.id}`}
          className="self-center h-6 mx-1 border-l border-gray-300 dark:border-gray-600"
        />,
      );
    }
    nodes.push(
      <button
        key={tab.id}
        type="button"
        onClick={() => onChange(tab.id)}
        className={`px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px cursor-pointer select-none ${
          active === tab.id
            ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
            : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
        }`}
      >
        <span className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 mr-1.5">
          {tab.group}
        </span>
        {tab.label}
      </button>,
    );
  });
  return (
    <div className="flex items-end border-b border-gray-200 dark:border-gray-700 shrink-0">
      {nodes}
    </div>
  );
}

// ─── Input JSON editor (Tab 1) — edit & save (cells unchanged) ──────────────

function InputJsonEditor({ fixture, suiteId, initialJson }: {
  fixture: OracleFixtureDetail; suiteId: string; initialJson: string;
}) {
  const [value, setValue] = useState(initialJson);
  const [error, setError] = useState<string | null>(null);
  const save = useSaveStudioFixture();

  // Reset when fixture changes
  useEffect(() => { setValue(initialJson); setError(null); }, [initialJson]);

  const isDirty = value.trim() !== initialJson.trim();

  async function handleSave() {
    setError(null);
    let parsed: Record<string, unknown>;
    try {
      const obj = JSON.parse(value);
      if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
        throw new Error("Must be a JSON object");
      }
      parsed = obj as Record<string, unknown>;
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    try {
      // Save in override mode: only input_data changes; existing cells
      // are preserved verbatim. User must re-run Tab 3 if they want new
      // cells for the new input.
      await save.mutateAsync({
        case_id: fixture.fixture_id,
        suite_id: suiteId,
        input_data: parsed,
        expected_override: {
          cells: fixture.expected as Record<string, unknown>,
          valid_fields: fixture.meta?.valid_fields,
        },
        production_prompt: fixture.production_prompt || "",
        oracle_prompt: fixture.oracle_prompt || "",
        oracle_prompt_version: fixture.oracle_prompt_version || "",
        meta_prompt_version: fixture.meta_prompt_version || "",
        oracle_model: fixture.oracle_model,
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center justify-between text-[11px]">
        <p className="text-gray-500 dark:text-gray-400">
          Edit the input JSON. Save persists it without changing existing
          cells — re-run step 3 to refresh the expectation against the new input.
        </p>
        {error && <span className="text-red-500">⚠ {error}</span>}
      </div>
      <textarea
        className="w-full text-xs font-mono bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400 resize-y min-h-[260px]"
        value={value}
        onChange={e => { setValue(e.target.value); setError(null); }}
        spellCheck={false}
      />
      <div className="flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={!isDirty || save.isPending}
          className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 flex items-center gap-1.5 transition-colors"
        >
          {save.isPending ? <><span className="animate-spin">⟳</span> Saving…</> : "💾 Save input"}
        </button>
        {isDirty && (
          <button
            onClick={() => { setValue(initialJson); setError(null); }}
            disabled={save.isPending}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Reset
          </button>
        )}
        {!isDirty && <span className="text-[11px] text-gray-400">No changes</span>}
      </div>
    </div>
  );
}

// ─── Actual Output editor (Tab 1) — local-only, persisted to sessionStorage ──

function ActualOutputEditor({ fixtureId }: { fixtureId: string }) {
  const storageKey = `oracle-actual::${fixtureId}`;
  const [value, setValue] = useState<string>(() => {
    try { return sessionStorage.getItem(storageKey) ?? ""; } catch { return ""; }
  });
  const [saved, setSaved] = useState(false);

  function save() {
    try { sessionStorage.setItem(storageKey, value); } catch { /* ignore */ }
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  return (
    <div className="p-3 space-y-2">
      <p className="text-[11px] text-gray-500 dark:text-gray-400">
        Paste the actual model output here — used in step 4 to compare against expectation.
        Stored locally in your browser only.
      </p>
      <textarea
        className="w-full text-xs font-mono bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400 resize-none"
        rows={8}
        value={value}
        onChange={e => setValue(e.target.value)}
        placeholder={`{\n  "User": {\n    "id": { "op": "R", "confidence": 0.9, "reason": "..." }\n  }\n}`}
        spellCheck={false}
      />
      <div className="flex items-center gap-2">
        <button
          onClick={save}
          className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold transition-colors"
        >Save locally</button>
        {saved && <span className="text-[11px] text-green-600 dark:text-green-400">✓ saved</span>}
        {value && (
          <button
            onClick={() => { setValue(""); try { sessionStorage.removeItem(storageKey); } catch {} }}
            className="ml-auto text-[11px] text-gray-400 hover:text-red-500 transition-colors"
          >Clear</button>
        )}
      </div>
    </div>
  );
}

// ─── Tab 1: Input ─────────────────────────────────────────────────────────────

function Tab1_Input({ fixture, suiteId }: { fixture: OracleFixtureDetail; suiteId: string }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const input = fixture.input_data as any;
  const route    = input?.route;
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

      {/* Route Context — editable */}
      <CollapseSection title="Route Context JSON" badge={routeBadge}>
        <InputJsonEditor fixture={fixture} suiteId={suiteId} initialJson={inputJson} />
      </CollapseSection>

      {/* Actual Output (optional) — for offline comparison */}
      <CollapseSection title="Actual Output (optional)" badge="paste model output">
        <ActualOutputEditor fixtureId={fixture.fixture_id} />
      </CollapseSection>
    </div>
  );
}

// ─── Provider + model selector (shared by Tab 2 + Tab 3) ─────────────────────

// Provider/model dropdowns — models list comes from server's /providers
// endpoint, which reads providers.yaml on the framework side. Adding a new
// model = edit YAML, no frontend change.

function ProviderSelector({
  providers, provider, model, onChange, disabled,
}: {
  providers: import("@/api/hooks").ProviderInfo[];
  provider: string;
  model: string;
  onChange: (p: string, m: string) => void;
  disabled?: boolean;
}) {
  const current = providers.find(p => p.key === provider);
  const knownModels = current?.models ?? [];
  const modelOptions = knownModels.includes(model)
    ? knownModels
    : (model ? [model, ...knownModels] : knownModels);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <select
        value={provider}
        disabled={disabled}
        onChange={e => {
          const next = providers.find(p => p.key === e.target.value);
          onChange(e.target.value, next?.default_model ?? "");
        }}
        className="text-xs border border-gray-200 dark:border-gray-600 rounded px-2 py-1 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-indigo-400 disabled:opacity-50"
      >
        {providers.length === 0 && <option value="">(no providers)</option>}
        {providers.map(p => <option key={p.key} value={p.key}>{p.key}</option>)}
      </select>
      <select
        value={model}
        disabled={disabled || modelOptions.length === 0}
        onChange={e => onChange(provider, e.target.value)}
        className="text-xs border border-gray-200 dark:border-gray-600 rounded px-2 py-1 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 font-mono focus:outline-none focus:border-indigo-400 disabled:opacity-50 min-w-[180px]"
      >
        {modelOptions.length === 0 && <option value="">(no models)</option>}
        {modelOptions.map(m => <option key={m} value={m}>{m}</option>)}
      </select>
    </div>
  );
}

// ─── Tab 2: Oracle Prompt (meta-generate + manual + save) ────────────────────

type PromptMode = "auto" | "manual";

function Tab2_OraclePrompt({
  fixture, productionPrompt, oraclePrompt, onOraclePromptChange, providers,
  provider, model, onProviderModelChange, onGenerated, onSavePrompt, isSaving,
}: {
  fixture: OracleFixtureDetail;
  productionPrompt: string;
  oraclePrompt: string;
  onOraclePromptChange: (v: string) => void;
  providers: ProviderInfo[];
  provider: string;
  model: string;
  onProviderModelChange: (p: string, m: string) => void;
  onGenerated: (result: { version: string; metaVersion: string }) => void;
  onSavePrompt: () => Promise<void>;
  isSaving: boolean;
}) {
  const metaGen = useMetaGenerateOraclePrompt();
  const [mode, setMode] = useState<PromptMode>(
    fixture.oracle_prompt ? "auto" : (oraclePrompt ? "manual" : "auto"),
  );
  const [lastTrace, setLastTrace] = useState<{
    system: string; user: string; rawResponse: string;
    provider: string; model: string; generatedAt: string;
  } | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  useEffect(() => {
    if (!traceOpen) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setTraceOpen(false); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [traceOpen]);

  // Expected output shape — per-fixture, persisted locally. Passed to the
  // meta-prompt so the LLM preserves the project's output schema verbatim
  // (different per project: CRUD matrix vs Anki vs todo classify, etc).
  const schemaKey = `oracle-schema-hint::${fixture.fixture_id}`;
  const [schemaHint, setSchemaHint] = useState<string>(() => {
    try { return localStorage.getItem(schemaKey) ?? ""; } catch { return ""; }
  });
  useEffect(() => {
    try { setSchemaHint(localStorage.getItem(schemaKey) ?? ""); } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixture.fixture_id]);
  useEffect(() => {
    try { localStorage.setItem(schemaKey, schemaHint); } catch { /* ignore */ }
  }, [schemaHint, schemaKey]);

  // localStorage persist — defense against accidental refresh
  const draftKey = `oracle-prompt-draft::${fixture.fixture_id}`;
  useEffect(() => {
    if (!oraclePrompt) {
      try {
        const saved = localStorage.getItem(draftKey);
        if (saved) onOraclePromptChange(saved);
      } catch { /* ignore */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixture.fixture_id]);

  useEffect(() => {
    try { localStorage.setItem(draftKey, oraclePrompt); } catch { /* ignore */ }
  }, [oraclePrompt, draftKey]);

  // Dirty = current text differs from what's persisted on the fixture
  const dirty = oraclePrompt !== (fixture.oracle_prompt || "");

  async function handleGenerate() {
    if (!productionPrompt.trim()) return;  // disabled in UI; defensive guard
    if (dirty && oraclePrompt.trim()) {
      if (!window.confirm("This will overwrite your unsaved edits. Continue?")) return;
    }
    try {
      const result = await metaGen.mutateAsync({
        production_prompt: productionPrompt,
        provider: provider || undefined,
        model: model || undefined,
        project_name: fixture.fixture_id,
        output_schema_hint: schemaHint || undefined,
      });
      onOraclePromptChange(result.oracle_prompt);
      onGenerated({
        version: `auto-${result.generated_at}`,
        metaVersion: result.meta_prompt_version,
      });
      setLastTrace({
        system: result.request_system ?? "",
        user: result.request_user ?? "",
        rawResponse: result.raw_response ?? result.oracle_prompt,
        provider: result.provider,
        model: result.model,
        generatedAt: result.generated_at,
      });
      setMode("auto");
    } catch {
      // surface via metaGen.error
    }
  }

  function handleClear() {
    if (oraclePrompt && !window.confirm("Clear the oracle prompt?")) return;
    onOraclePromptChange("");
  }

  return (
    <div className="space-y-3">
      {/* Mode toggle */}
      <div className="flex items-center gap-1 text-xs">
        <span className="text-gray-500 dark:text-gray-400 mr-2">Mode:</span>
        {(["auto", "manual"] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 rounded-lg border transition-colors ${
              mode === m
                ? "bg-indigo-600 border-indigo-600 text-white font-semibold"
                : "border-gray-200 dark:border-gray-700 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800"
            }`}
          >
            {m === "auto" ? "🤖 Auto-generate" : "✍ Manual"}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-gray-400">
          {dirty
            ? <span className="text-yellow-600 dark:text-yellow-400">● unsaved edits</span>
            : oraclePrompt
              ? <span className="text-green-600 dark:text-green-400">✓ saved</span>
              : <span>empty</span>}
        </span>
      </div>

      {/* Auto-generate panel — only in auto mode */}
      {mode === "auto" && (
        <div className="rounded-lg border border-indigo-200 dark:border-indigo-800 bg-indigo-50/40 dark:bg-indigo-950/20 p-3 space-y-2">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-gray-700 dark:text-gray-200">
                Generate oracle prompt from production prompt
              </div>
              <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                Runs the generic meta-prompt over the production prompt from step 1.
                Result fills the textarea below; you can still edit before step 3.
              </p>
              {!productionPrompt.trim() && (
                <p className="text-[11px] text-yellow-600 dark:text-yellow-400 mt-1">
                  ⚠ No production prompt yet — set the suite's default prompt in step 1.
                </p>
              )}
            </div>
            <button
              onClick={handleGenerate}
              disabled={metaGen.isPending || !productionPrompt.trim()}
              title={!productionPrompt.trim() ? "Set the suite's default production prompt in step 1 first" : undefined}
              className="shrink-0 text-xs px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5 transition-colors"
            >
              {metaGen.isPending
                ? <><span className="animate-spin inline-block">⟳</span> Generating…</>
                : oraclePrompt
                  ? <>↻ Regenerate</>
                  : <>▶ Generate</>}
            </button>
          </div>
          <div className="flex items-center gap-2 text-[11px]">
            <span className="text-gray-500 dark:text-gray-400 w-16">Provider</span>
            <ProviderSelector
              providers={providers}
              provider={provider}
              model={model}
              onChange={onProviderModelChange}
              disabled={metaGen.isPending}
            />
          </div>
          <div>
            <div className="flex items-center justify-between text-[11px] mb-1">
              <span className="text-gray-500 dark:text-gray-400">
                Expected output shape <span className="text-gray-400">(optional — paste a sample of production output JSON so the oracle preserves the EXACT key names + nesting)</span>
              </span>
              {schemaHint && (
                <button
                  onClick={() => setSchemaHint("")}
                  className="text-[10px] text-gray-400 hover:text-red-500"
                >Clear</button>
              )}
            </div>
            <textarea
              value={schemaHint}
              onChange={e => setSchemaHint(e.target.value)}
              placeholder={`Example:\n{\n  "User": {\n    "id": { "op": "R", "confidence": "high", "why": "..." },\n    "email": { "op": "R", ... }\n  }\n}`}
              disabled={metaGen.isPending}
              spellCheck={false}
              className="w-full text-xs font-mono bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded px-2 py-1.5 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400 resize-y min-h-[80px]"
            />
          </div>
          {metaGen.error && (
            <div className="text-[11px] text-red-500">⚠ {metaGen.error.message}</div>
          )}
        </div>
      )}

      {/* Meta-generate trace — shown after a successful generate */}
      {lastTrace && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
            <span className="text-[10px] uppercase font-semibold tracking-wider text-gray-500 dark:text-gray-400">
              Meta-prompt trace
            </span>
            <span className="text-[10px] font-mono text-gray-400">
              {lastTrace.provider}/{lastTrace.model}
            </span>
            <button
              onClick={() => setTraceOpen(true)}
              className="ml-auto text-[10px] px-2 py-0.5 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              title="Open trace in popup"
            >⛶ Popup</button>
          </div>
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            <details className="group">
              <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 hover:bg-gray-50 dark:hover:bg-gray-800/50">
                <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300">
                  meta_input
                </span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400">system (meta-prompt) + user (production_prompt + hints)</span>
                <span className="ml-auto text-[10px] text-gray-400">click to expand</span>
              </summary>
              <div className="p-3 space-y-2 bg-purple-50/30 dark:bg-purple-950/10">
                <CodePane title="meta-prompt system" content={lastTrace.system} maxHeight="220px" />
                <CodePane title="user message (production_prompt + schema_hint + domain_hint)" content={lastTrace.user} maxHeight="280px" />
              </div>
            </details>
            <details className="group">
              <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 hover:bg-gray-50 dark:hover:bg-gray-800/50">
                <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
                  meta_output
                </span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400">raw oracle prompt produced</span>
                <span className="ml-auto text-[10px] text-gray-400">click to expand</span>
              </summary>
              <div className="p-3">
                <CodePane title="oracle_prompt (raw)" content={lastTrace.rawResponse} maxHeight="320px" />
              </div>
            </details>
          </div>
        </div>
      )}

      {/* Meta trace popup */}
      {lastTrace && traceOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setTraceOpen(false)}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          <div className="relative z-10 w-[min(1200px,95vw)] max-h-[92vh] flex flex-col bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-2xl overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">Meta-prompt trace</h2>
                <span className="text-[11px] font-mono text-gray-400">{lastTrace.provider}/{lastTrace.model}</span>
                <span className="text-[10px] text-gray-400">· {lastTrace.generatedAt}</span>
              </div>
              <button onClick={() => setTraceOpen(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-2xl leading-none">×</button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <div>
                <div className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300 inline-block mb-2">meta_input — system</div>
                <CodePane title="" content={lastTrace.system} maxHeight="320px" />
              </div>
              <div>
                <div className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300 inline-block mb-2">meta_input — user</div>
                <CodePane title="" content={lastTrace.user} maxHeight="400px" />
              </div>
              <div>
                <div className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 inline-block mb-2">meta_output — raw oracle prompt</div>
                <CodePane title="" content={lastTrace.rawResponse} maxHeight="420px" />
              </div>
            </div>
            <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 shrink-0 text-[11px] text-gray-400 text-right">Press Esc or click outside to close</div>
          </div>
        </div>
      )}

      {/* Manual mode hint */}
      {mode === "manual" && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-3 text-[11px] text-gray-600 dark:text-gray-400">
          ✍ Manual mode — paste or write your own YAML oracle prompt below.
          Must contain <code className="font-mono bg-gray-200 dark:bg-gray-700 px-1 rounded">system:</code> and{" "}
          <code className="font-mono bg-gray-200 dark:bg-gray-700 px-1 rounded">user_template:</code> keys.
        </div>
      )}

      {/* Editable textarea — always visible */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
            Oracle prompt (YAML)
          </label>
          <span className="text-[10px] text-gray-400">
            {oraclePrompt.length.toLocaleString()} chars
          </span>
        </div>
        <textarea
          value={oraclePrompt}
          onChange={e => onOraclePromptChange(e.target.value)}
          placeholder={mode === "auto"
            ? "Click Generate above — the result lands here, then you can edit."
            : "Paste a YAML oracle prompt with `system:` and `user_template:` keys. Use {{ input_json }} in user_template."}
          spellCheck={false}
          className="w-full text-xs font-mono bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400 resize-y min-h-[280px]"
        />
        <div className="flex items-center gap-2 mt-2">
          <button
            onClick={onSavePrompt}
            disabled={isSaving || !dirty || !oraclePrompt.trim()}
            className="text-xs px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white font-semibold disabled:opacity-40 transition-colors"
          >
            {isSaving ? "Saving…" : "💾 Save prompt"}
          </button>
          {oraclePrompt && (
            <button
              onClick={handleClear}
              className="text-[11px] text-gray-400 hover:text-red-500 transition-colors"
            >
              Clear
            </button>
          )}
          <span className="ml-auto text-[10px] text-gray-400">
            Drafts auto-persist locally per fixture (survives refresh).
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── Tab 3: Execution (run-with-prompt) ──────────────────────────────────────

interface PreviewRun {
  cells: Record<string, Record<string, { op: string; confidence?: string | number; oracle_why?: string; why?: string }>>;
  raw_response: string;
  latency_ms: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  model: string;
  provider: string;
  parse_error?: string;
  // Captured client-side so the trace block can show what we actually sent
  request_system?: string;
  request_user?: string;
}

// Client-side YAML extraction so the trace block shows what was sent.
// Cheap line-based parser — `system: |` and `user_template: |` block scalars.
// Matches what yaml.safe_load would do for the common case.
function extractSystemUser(oraclePrompt: string, inputData: unknown): {
  system: string; user: string;
} {
  try {
    // Minimal YAML — split block scalars by detecting `key: |` headers.
    const lines = oraclePrompt.split("\n");
    const blocks: Record<string, string[]> = {};
    let cur: string | null = null;
    let curIndent = 0;
    for (const line of lines) {
      const m = line.match(/^([a-z_]+):\s*\|\s*$/);
      if (m) {
        cur = m[1];
        blocks[cur] = [];
        curIndent = 0;
        continue;
      }
      // Top-level key without `|` — end any current block
      if (/^[a-z_]+:/.test(line) && !line.startsWith(" ")) {
        cur = null;
        continue;
      }
      if (cur) {
        if (curIndent === 0 && line.trim()) {
          curIndent = line.length - line.trimStart().length;
        }
        blocks[cur].push(curIndent > 0 ? line.slice(curIndent) : line);
      }
    }
    const system = (blocks.system ?? []).join("\n").trimEnd();
    const userTpl = (blocks.user_template ?? []).join("\n").trimEnd();
    const user = userTpl.replace(
      "{{ input_json }}",
      JSON.stringify(inputData, null, 2),
    );
    return { system, user };
  } catch {
    return { system: "(failed to parse)", user: "(failed to parse)" };
  }
}

function Tab3_Execution({
  fixture, oraclePrompt, providers, provider, model, onProviderModelChange,
  preview, setPreview, onSavePreview, isSaving,
  oraclePromptVersion, metaPromptVersion,
}: {
  fixture: OracleFixtureDetail;
  oraclePrompt: string;
  providers: ProviderInfo[];
  provider: string;
  model: string;
  onProviderModelChange: (p: string, m: string) => void;
  preview: PreviewRun | null;
  setPreview: (p: PreviewRun | null) => void;
  onSavePreview: () => Promise<void>;
  isSaving: boolean;
  oraclePromptVersion: string;
  metaPromptVersion: string;
}) {
  const runMut = useRunWithPrompt();
  const [traceOpen, setTraceOpen] = useState(false);
  useEffect(() => {
    if (!traceOpen) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setTraceOpen(false); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [traceOpen]);

  async function handleRun() {
    if (!oraclePrompt.trim()) return;  // button is disabled in UI; defensive
    const { system: reqSystem, user: reqUser } = extractSystemUser(
      oraclePrompt, fixture.input_data,
    );
    try {
      const result = await runMut.mutateAsync({
        oracle_prompt: oraclePrompt,
        input_data: fixture.input_data,
        provider: provider || undefined,
        model: model || undefined,
      });
      setPreview({
        cells: result.cells,
        raw_response: result.raw_response,
        latency_ms: result.latency_ms,
        cost_usd: result.cost_usd,
        input_tokens: result.input_tokens,
        output_tokens: result.output_tokens,
        model: result.model,
        provider: result.provider,
        parse_error: result.parse_error,
        request_system: reqSystem,
        request_user: reqUser,
      });
    } catch (e) {
      // API failed — still record the request so the trace block can show
      // what we sent. The error itself is also surfaced via runMut.error.
      const err = e as Error;
      setPreview({
        cells: {},
        raw_response: "",
        latency_ms: 0,
        cost_usd: 0,
        input_tokens: 0,
        output_tokens: 0,
        model: model,
        provider: provider,
        parse_error: `API call failed: ${err.message}`,
        request_system: reqSystem,
        request_user: reqUser,
      });
    }
  }

  const source = preview ? preview.cells : fixture.expected;
  const entities = Object.keys(source);
  const hasCells = entities.length > 0;

  // Shape detection — the CRUD table assumes {entity: {field: {op, ...}}}.
  // Many domains (sequence/class diagram, summary, classification) emit
  // different shapes. Show table only when CRUD-like; otherwise fall back
  // to formatted JSON + a notice pointing the user to the raw response.
  function looksCrudShape(): boolean {
    if (!hasCells) return false;
    for (const entity of entities) {
      const fields = source[entity];
      if (typeof fields !== "object" || fields === null || Array.isArray(fields)) return false;
      for (const f of Object.values(fields)) {
        if (typeof f !== "object" || f === null) return false;
        const cell = f as Record<string, unknown>;
        // Accept any of these as a cell signature
        if (cell.op == null && cell.score == null && cell.verdict == null && cell.value == null) {
          return false;
        }
      }
    }
    return true;
  }
  const crudShape = looksCrudShape();
  const totalCells = crudShape
    ? entities.reduce((n, e) => n + Object.keys(source[e] as object).length, 0)
    : 0;

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-indigo-200 dark:border-indigo-800 bg-indigo-50/40 dark:bg-indigo-950/20 p-3 space-y-2">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="text-xs font-semibold text-gray-700 dark:text-gray-200">Run oracle prompt</div>
            <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
              Sends the oracle prompt from step 2 + input from step 1 to the
              chosen provider. Result is a <em>preview</em>; click Save to
              persist it as the fixture expectation.
              {preview && (
                <span className="ml-2 text-indigo-600 dark:text-indigo-400 font-medium">
                  Preview shown — not saved yet.
                </span>
              )}
            </p>
          </div>
          <button
            onClick={handleRun}
            disabled={runMut.isPending || !oraclePrompt.trim()}
            className="shrink-0 text-xs px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 flex items-center gap-1.5 transition-colors"
          >
            {runMut.isPending ? <><span className="animate-spin inline-block">⟳</span> Running…</> : <>▶ Run</>}
          </button>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-gray-500 dark:text-gray-400 w-16">Provider</span>
          <ProviderSelector
            providers={providers}
            provider={provider}
            model={model}
            onChange={onProviderModelChange}
            disabled={runMut.isPending}
          />
        </div>
        {runMut.error && (
          <div className="text-[11px] text-red-500">⚠ {runMut.error.message}</div>
        )}
        {preview?.parse_error && (
          <div className="text-[11px] text-yellow-600 dark:text-yellow-400">
            ⚠ LLM returned unparseable JSON: {preview.parse_error}. Check raw response below.
          </div>
        )}
      </div>

      {preview && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 space-y-2">
          <div className="flex items-center gap-4 flex-wrap text-[11px] text-gray-600 dark:text-gray-300">
            <span><span className="text-gray-400">Latency</span> <span className="font-mono">{preview.latency_ms.toFixed(0)}ms</span></span>
            <span><span className="text-gray-400">Cost</span> <span className="font-mono">${preview.cost_usd.toFixed(4)}</span></span>
            <span><span className="text-gray-400">Tokens</span> <span className="font-mono">{preview.input_tokens}/{preview.output_tokens}</span></span>
            <span><span className="text-gray-400">Model</span> <span className="font-mono">{preview.model}</span></span>
            <button
              onClick={onSavePreview}
              disabled={isSaving || !hasCells || !!preview.parse_error}
              className="ml-auto text-xs px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white font-semibold disabled:opacity-40 transition-colors"
              title={oraclePromptVersion ? `Saving with version ${oraclePromptVersion}` : "Will save with generated_at version"}
            >
              {isSaving ? "Saving…" : "💾 Save preview as expectation"}
            </button>
          </div>
          {(oraclePromptVersion || metaPromptVersion) && (
            <div className="text-[10px] text-gray-400 font-mono">
              Will tag fixture with: oracle_prompt_version={oraclePromptVersion || "(blank)"}, meta_prompt_version={metaPromptVersion || "(blank)"}
            </div>
          )}
        </div>
      )}

      {/* Result summary — adapts to parse state + shape detection */}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {hasCells
          ? (crudShape
              ? <>{preview ? "Preview" : "Saved expectation"}: <span className="font-semibold">{entities.length}</span> entities · <span className="font-semibold">{totalCells}</span> cells</>
              : <span className="text-amber-600 dark:text-amber-400">Output shape isn't CRUD-style — showing raw JSON. CRUD table needs {`{entity:{field:{op,...}}}`} shape.</span>)
          : preview
            ? (preview.parse_error
                ? <span className="text-red-500">Run completed but JSON parsing failed — see Run Trace below.</span>
                : <span className="text-yellow-600 dark:text-yellow-400">Run completed but returned 0 cells — see Run Trace below.</span>)
            : "No expectation yet — click Run."}
      </p>

      {/* Non-CRUD shape — show formatted JSON instead of broken table */}
      {hasCells && !crudShape && (
        <div className="overflow-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3">
          <pre className="text-xs font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-all">
            {JSON.stringify(source, null, 2)}
          </pre>
        </div>
      )}

      {hasCells && crudShape && (
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
                Object.entries(source[entity]).map(([field, cell]) => {
                  const why = (cell as { oracle_why?: string; why?: string }).oracle_why
                    ?? (cell as { why?: string }).why ?? "";
                  return (
                    <tr key={`${entity}::${field}`} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                      <td className="px-3 py-2 font-mono font-medium text-gray-700 dark:text-gray-300">{entity}</td>
                      <td className="px-3 py-2 font-mono text-gray-500 dark:text-gray-400">{field}</td>
                      <td className="px-3 py-2"><OpBadge op={String(cell.op ?? "")} /></td>
                      <td className="px-3 py-2"><ConfBadge confidence={String(cell.confidence ?? "")} /></td>
                      <td className="px-3 py-2 text-gray-500 dark:text-gray-400 max-w-[240px] truncate" title={why}>{why}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Run Trace — always visible when there's a preview */}
      {preview && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
            <span className="text-[10px] uppercase font-semibold tracking-wider text-gray-500 dark:text-gray-400">
              Run trace
            </span>
            <span className="text-[10px] font-mono text-gray-400">
              {preview.provider}/{preview.model}
            </span>
            <span className="ml-auto flex items-center gap-2">
              {preview.parse_error
                ? <span className="text-[10px] font-semibold text-red-500 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 px-1.5 py-0.5 rounded">⚠ unparseable</span>
                : hasCells
                  ? <span className="text-[10px] font-semibold text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 px-1.5 py-0.5 rounded">✓ parsed</span>
                  : <span className="text-[10px] font-semibold text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950 border border-yellow-200 dark:border-yellow-800 px-1.5 py-0.5 rounded">⚠ empty</span>}
              <button
                onClick={() => setTraceOpen(true)}
                className="text-[10px] px-2 py-0.5 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                title="Open trace in popup"
              >
                ⛶ Popup
              </button>
            </span>
          </div>
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            <details className="group">
              <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 hover:bg-gray-50 dark:hover:bg-gray-800/50">
                <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300">
                  llm_input
                </span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400">system + rendered user prompt</span>
                <span className="ml-auto text-[10px] text-gray-400">click to expand</span>
              </summary>
              <div className="p-3 space-y-2 bg-purple-50/30 dark:bg-purple-950/10">
                <CodePane title="system" content={preview.request_system ?? "(not captured)"} maxHeight="200px" />
                <CodePane title="user (with input_json substituted)" content={preview.request_user ?? "(not captured)"} maxHeight="240px" />
              </div>
            </details>
            <details className="group" open={!hasCells || !!preview.parse_error}>
              <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 hover:bg-gray-50 dark:hover:bg-gray-800/50">
                <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
                  llm_output
                </span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400">
                  raw response · {preview.output_tokens} tokens
                </span>
                <span className="ml-auto text-[10px] text-gray-400">click to expand</span>
              </summary>
              <div className="p-3">
                <CodePane
                  title="raw_response"
                  content={preview.raw_response || "(empty response)"}
                  maxHeight="320px"
                  badge={preview.parse_error ? "parse failed" : undefined}
                />
                {preview.parse_error && (
                  <div className="mt-2 text-[11px] text-red-500 font-mono">
                    Parse error: {preview.parse_error}
                  </div>
                )}
              </div>
            </details>
          </div>
        </div>
      )}

      {/* Trace popup modal */}
      {preview && traceOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          onClick={() => setTraceOpen(false)}
        >
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          <div
            className="relative z-10 w-[min(1200px,95vw)] max-h-[92vh] flex flex-col bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-2xl overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">Run trace</h2>
                <span className="text-[11px] font-mono text-gray-400">{preview.provider}/{preview.model}</span>
                <span className="text-[10px] text-gray-400">·</span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400">{preview.latency_ms.toFixed(0)}ms · ${preview.cost_usd.toFixed(4)} · {preview.input_tokens}/{preview.output_tokens} tokens</span>
              </div>
              <button onClick={() => setTraceOpen(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-2xl leading-none">×</button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300">llm_input — system</span>
                </div>
                <CodePane title="" content={preview.request_system ?? "(not captured)"} maxHeight="280px" />
              </div>
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300">llm_input — user (with input_json substituted)</span>
                </div>
                <CodePane title="" content={preview.request_user ?? "(not captured)"} maxHeight="360px" />
              </div>
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">llm_output — raw response</span>
                  {preview.parse_error
                    ? <span className="text-[10px] font-semibold text-red-500 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 px-1.5 py-0.5 rounded">⚠ unparseable</span>
                    : <span className="text-[10px] font-semibold text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 px-1.5 py-0.5 rounded">✓ parsed</span>}
                </div>
                <CodePane title="" content={preview.raw_response || "(empty response)"} maxHeight="420px" />
                {preview.parse_error && (
                  <div className="mt-2 text-[11px] text-red-500 font-mono">Parse error: {preview.parse_error}</div>
                )}
              </div>
            </div>
            <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 shrink-0 text-[11px] text-gray-400 text-right">
              Press Esc or click outside to close
            </div>
          </div>
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

function Tab4_Review({
  fixture, pendingActions, onAction, onSave, isSaving,
  reviewerName, onReviewerChange,
  onPromote, isPromoting,
}: {
  fixture: OracleFixtureDetail; pendingActions: ReviewActionPayload[];
  onAction: (a: ReviewActionPayload) => void; onSave: () => void;
  isSaving: boolean; reviewerName: string; onReviewerChange: (s: string) => void;
  onPromote: () => void; isPromoting: boolean;
}) {
  const pendingMap = new Map(pendingActions.map(a => [`${a.entity}::${a.field}`, a]));
  const pendingCount = fixture.review_items.filter(r => r.action == null).length;
  const totalCount = fixture.review_items.length;

  // Pull Actual Output from sessionStorage (saved in step 1)
  const actualRaw = (() => {
    try { return sessionStorage.getItem(`oracle-actual::${fixture.fixture_id}`) ?? ""; } catch { return ""; }
  })();
  const actualParsed = (() => {
    if (!actualRaw.trim()) return null;
    try { return JSON.parse(actualRaw); } catch { return actualRaw; }
  })();

  function approveAll() {
    for (const item of fixture.review_items) {
      if (item.action == null && !pendingMap.has(`${item.entity}::${item.field}`)) {
        onAction({ entity: item.entity, field: item.field, action: "approve" });
      }
    }
  }

  // No-review-items case: still need to surface Promote so user can ship a
  // fixture where every cell is high-confidence (nothing to review by hand).
  if (totalCount === 0) {
    const hasExpectation = Object.keys(fixture.expected || {}).length > 0;
    return (
      <div className="space-y-3">
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50/40 dark:bg-gray-800/30 p-4 text-center">
          {hasExpectation ? (
            <p className="text-sm text-gray-600 dark:text-gray-300">
              ✓ No cells require manual review — all are high-confidence.
            </p>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500">
              No expectation yet — run the oracle in step 3 first.
            </p>
          )}
        </div>
        {hasExpectation && (
          <div className="flex justify-end">
            <button
              onClick={onPromote}
              disabled={isPromoting}
              className="text-sm px-4 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-semibold disabled:opacity-40 transition-colors"
            >
              {isPromoting ? "Promoting…" : "🚀 Promote to suite"}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Compare actual vs expected */}
      {actualParsed != null && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-3 py-2 text-[10px] uppercase font-semibold tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            Actual Output (from step 1)
          </div>
          <pre className="text-xs font-mono p-3 max-h-48 overflow-auto whitespace-pre-wrap break-all bg-white dark:bg-gray-950">
            {typeof actualParsed === "string" ? actualParsed : JSON.stringify(actualParsed, null, 2)}
          </pre>
        </div>
      )}

      {/* Reviewer + actions row */}
      <div className="rounded-lg border border-indigo-200 dark:border-indigo-800 bg-indigo-50/40 dark:bg-indigo-950/20 p-3 space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <input
            className="flex-1 min-w-[180px] text-sm border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:border-indigo-400"
            placeholder="Reviewer name…"
            value={reviewerName}
            onChange={e => onReviewerChange(e.target.value)}
          />
          <span className="text-xs shrink-0 font-semibold">
            {pendingCount > 0
              ? <span className="text-yellow-600 dark:text-yellow-400">{pendingCount}/{totalCount} pending</span>
              : <span className="text-green-600 dark:text-green-400">✓ all reviewed</span>}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={approveAll}
            disabled={pendingCount === 0}
            className="text-xs px-3 py-1.5 rounded-lg border border-green-300 dark:border-green-700 text-green-700 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-950/40 font-semibold disabled:opacity-40 transition-colors"
          >
            ✓ Approve all remaining ({pendingCount})
          </button>
          <button
            onClick={onSave}
            disabled={isSaving || pendingActions.length === 0}
            className="text-sm px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-40 transition-colors"
          >
            {isSaving ? "Saving…" : `Save review (${pendingActions.length})`}
          </button>
          <button
            onClick={onPromote}
            disabled={isPromoting || pendingCount > 0}
            title={
              pendingCount > 0
                ? "Resolve pending reviews before promoting to suite"
                : "Copy this fixture into the target suite's cases dir as a YAML regression case"
            }
            className="ml-auto text-sm px-4 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-semibold disabled:opacity-40 transition-colors"
          >
            {isPromoting ? "Promoting…" : "🚀 Promote to suite"}
          </button>
        </div>
      </div>

      {/* Per-cell review list */}
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

// ─── SuiteDetailPane — shown when suite is expanded but no fixture selected ───

function SuiteDetailPane({ suiteId, onAddCase, onEditSuite, suites }: {
  suiteId: string;
  onAddCase: (suiteId: string) => void;
  onEditSuite: (suite: Suite) => void;
  suites: Suite[];
}) {
  const { data: fixtures = [], isLoading: fixturesLoading } = useOracleFixtures(suiteId);
  const suite = suites.find(s => s.suite_id === suiteId);

  const totalCases = fixtures.length;
  const pendingCount = fixtures.reduce((n, f) => n + f.pending_review, 0);
  const reviewedCount = totalCases - fixtures.filter(f => f.pending_review > 0).length;

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6">
      {/* Suite header */}
      <div className="flex items-start justify-between gap-3 mb-6">
        <div>
          <h2 className="text-base font-semibold text-gray-800 dark:text-gray-100">
            {suite?.title ?? suiteId}
          </h2>
          <p className="text-xs font-mono text-gray-400 mt-0.5">{suiteId}</p>
          {suite?.description && (
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{suite.description}</p>
          )}
        </div>
        {suite && (
          <button
            onClick={() => onEditSuite(suite)}
            className="shrink-0 text-[11px] px-2.5 py-1 rounded border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            ✏ Edit
          </button>
        )}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 text-center">
          <div className="text-lg font-bold text-gray-800 dark:text-gray-100 tabular-nums">
            {fixturesLoading ? "…" : totalCases}
          </div>
          <div className="text-[10px] text-gray-400 uppercase tracking-wider mt-0.5">Cases</div>
        </div>
        <div className="rounded-lg border border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950/30 p-3 text-center">
          <div className="text-lg font-bold text-yellow-700 dark:text-yellow-400 tabular-nums">
            {fixturesLoading ? "…" : pendingCount}
          </div>
          <div className="text-[10px] text-yellow-600 dark:text-yellow-500 uppercase tracking-wider mt-0.5">Pending</div>
        </div>
        <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/30 p-3 text-center">
          <div className="text-lg font-bold text-green-700 dark:text-green-400 tabular-nums">
            {fixturesLoading ? "…" : reviewedCount}
          </div>
          <div className="text-[10px] text-green-600 dark:text-green-500 uppercase tracking-wider mt-0.5">Reviewed</div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => onAddCase(suiteId)}
          className="flex-1 text-sm py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold transition-colors"
        >
          + New Case
        </button>
      </div>

      {/* Case list preview */}
      {totalCases > 0 && (
        <div>
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Cases ({totalCases})
          </div>
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800 overflow-hidden">
            {fixtures.map(f => (
              <div key={f.fixture_id} className="flex items-center gap-2 px-3 py-2 bg-white dark:bg-gray-900">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${f.pending_review > 0 ? "bg-yellow-400" : "bg-green-500"}`} />
                <span className="text-xs font-mono text-gray-600 dark:text-gray-400 truncate flex-1">
                  {f.fixture_id}
                </span>
                {f.pending_review > 0 ? (
                  <span className="text-[10px] text-yellow-600 dark:text-yellow-400">{f.pending_review} pending</span>
                ) : (
                  <span className="text-[10px] text-green-600 dark:text-green-400">✓</span>
                )}
              </div>
            ))}
          </div>
          <p className="text-[11px] text-gray-400 mt-2 text-center">
            Select a case from the sidebar to review
          </p>
        </div>
      )}

      {/* Empty state */}
      {!fixturesLoading && totalCases === 0 && (
        <div className="flex flex-col items-center justify-center flex-1 gap-2 text-center py-8">
          <div className="text-3xl mb-1">🔬</div>
          <p className="text-sm font-medium text-gray-600 dark:text-gray-300">No oracle cases yet</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 max-w-xs">
            Create a case manually or use the oracle to generate expected outputs from your LLM.
          </p>
        </div>
      )}
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
  const [preview, setPreview]                       = useState<PreviewRun | null>(null);
  // Studio state — survives across tabs while the fixture is open
  const [oraclePrompt, setOraclePrompt]             = useState("");
  const [oraclePromptVersion, setOraclePromptVersion] = useState("");
  const [metaPromptVersion, setMetaPromptVersion]   = useState("");
  const [provider, setProvider]                     = useState("");
  const [model, setModel]                           = useState("");

  const { data: fixture, isLoading: loadingFixture } = useOracleFixture(selectedFixtureId);
  const { data: providersResp }                      = useLLMProviders();
  const updateMutation   = useUpdateOracleReview(selectedFixtureId);
  const generateMutation = useGenerateOracle();
  const deleteMutation   = useDeleteOracleFixture();
  const deleteSuite      = useDeleteSuite();
  const saveStudio       = useSaveStudioFixture();
  const promoteMut       = usePromoteToSuite();

  const providers = providersResp?.providers ?? [];

  // Initialize provider/model when the registry loads. Prefer anthropic
  // (meta-prompt + oracle are designed for Opus-class judges); fall back to
  // the first registered provider.
  useEffect(() => {
    if (!provider && providers.length > 0) {
      const preferred = providers.find(p => p.key === "anthropic") ?? providers[0];
      setProvider(preferred.key);
      if (!model) setModel(preferred.default_model || preferred.models[0] || "");
    }
  }, [providers, provider, model]);

  // Reset pending state when fixture changes
  const [lastFixtureId, setLastFixtureId] = useState(selectedFixtureId);
  if (lastFixtureId !== selectedFixtureId) {
    setLastFixtureId(selectedFixtureId);
    setPendingActions([]);
    setPreview(null);
    setActiveTab("input");
    setOraclePrompt("");
    setOraclePromptVersion("");
    setMetaPromptVersion("");
  }

  // Hydrate oracle prompt when fixture loads. Priority order:
  //   1. localStorage draft (preserves unsaved edits across reloads)
  //   2. fixture.oracle_prompt (persisted on backend)
  useEffect(() => {
    if (fixture && fixture.fixture_id === selectedFixtureId) {
      if (!oraclePrompt) {
        let draft = "";
        try { draft = localStorage.getItem(`oracle-prompt-draft::${fixture.fixture_id}`) ?? ""; } catch { /* ignore */ }
        setOraclePrompt(draft || fixture.oracle_prompt || "");
      }
      if (!oraclePromptVersion && fixture.oracle_prompt_version) {
        setOraclePromptVersion(fixture.oracle_prompt_version);
      }
      if (!metaPromptVersion && fixture.meta_prompt_version) {
        setMetaPromptVersion(fixture.meta_prompt_version);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixture?.fixture_id]);

  function handleSelectFixture(suiteId: string, fixtureId: string) {
    setExpandedSuiteId(suiteId);
    setSelectedFixtureId(fixtureId);
    setPendingActions([]);
    setPreview(null);
    setActiveTab("input");
    setOraclePrompt("");
    setOraclePromptVersion("");
    setMetaPromptVersion("");
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

  // Studio: save oracle prompt only (Tab 2 — preserves existing cells)
  async function handleSaveOraclePromptOnly() {
    if (!fixture) return;
    const version = oraclePromptVersion || `manual-${new Date().toISOString()}`;
    await saveStudio.mutateAsync({
      case_id: fixture.fixture_id,
      suite_id: expandedSuiteId,
      input_data: fixture.input_data,
      // Preserve existing cells — pass current fixture.expected so /generate
      // (override mode) doesn't run the strategy and doesn't change cells.
      expected_override: {
        cells: fixture.expected as Record<string, unknown>,
        valid_fields: fixture.meta?.valid_fields,
      },
      production_prompt: fixture.production_prompt || "",
      oracle_prompt: oraclePrompt,
      oracle_prompt_version: version,
      meta_prompt_version: metaPromptVersion || fixture.meta_prompt_version || "",
      oracle_model: fixture.oracle_model,
    });
    setOraclePromptVersion(version);
    try { localStorage.removeItem(`oracle-prompt-draft::${fixture.fixture_id}`); } catch {}
  }

  // Studio: save preview cells from Tab 3 back into the fixture as expectation
  async function handleSavePreview() {
    if (!preview || !fixture) return;
    const version = oraclePromptVersion || `auto-${new Date().toISOString()}`;
    await saveStudio.mutateAsync({
      case_id: fixture.fixture_id,
      suite_id: expandedSuiteId,
      input_data: fixture.input_data,
      expected_override: { cells: preview.cells },
      production_prompt: fixture.production_prompt || "",
      oracle_prompt: oraclePrompt,
      oracle_prompt_version: version,
      meta_prompt_version: metaPromptVersion || "",
      oracle_model: preview.model,
    });
    setOraclePromptVersion(version);
    setPreview(null);  // saved → no longer a preview
  }

  // Studio: promote saved fixture to target suite as a YAML case
  async function handlePromote() {
    if (!fixture) return;
    const targetSuite = window.prompt(
      `Promote ${fixture.fixture_id} to which suite? (cases will land at cases_dir/<suite_id>/)`,
      expandedSuiteId,
    );
    if (!targetSuite) return;
    try {
      const result = await promoteMut.mutateAsync({
        fixture_id: fixture.fixture_id,
        target_suite_id: targetSuite,
        overwrite: false,
      });
      window.alert(`Promoted to ${result.written_path}\n${result.cells_count} cells.`);
    } catch (e) {
      const err = e as Error;
      if (/409/.test(err.message)) {
        if (window.confirm("Case file already exists. Overwrite?")) {
          const result = await promoteMut.mutateAsync({
            fixture_id: fixture.fixture_id,
            target_suite_id: targetSuite,
            overwrite: true,
          });
          window.alert(`Promoted to ${result.written_path}\n${result.cells_count} cells.`);
        }
      } else {
        window.alert(`Promote failed: ${err.message}`);
      }
    }
  }

  function handleProviderModelChange(p: string, m: string) {
    setProvider(p);
    setModel(m);
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
          <SuiteDetailPane
            suiteId={expandedSuiteId}
            onAddCase={suiteId => setFixtureModal({ suiteId })}
            onEditSuite={suite => setSuiteModal({ mode: "edit", suite })}
            suites={suites}
          />
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

            {/* Pipeline header — 6-step Oracle Evaluation Flow */}
            <PipelineHeader fixture={fixture ?? null} />

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
                    <Tab2_OraclePrompt
                      fixture={fixture}
                      productionPrompt={
                        suites.find(s => s.suite_id === expandedSuiteId)?.default_system_prompt
                          ?? fixture.production_prompt
                          ?? ""
                      }
                      oraclePrompt={oraclePrompt}
                      onOraclePromptChange={setOraclePrompt}
                      providers={providers}
                      provider={provider}
                      model={model}
                      onProviderModelChange={handleProviderModelChange}
                      onGenerated={({ version, metaVersion }) => {
                        setOraclePromptVersion(version);
                        setMetaPromptVersion(metaVersion);
                      }}
                      onSavePrompt={handleSaveOraclePromptOnly}
                      isSaving={saveStudio.isPending}
                    />
                  )}
                  {activeTab === "expectation" && (
                    <Tab3_Execution
                      fixture={fixture}
                      oraclePrompt={oraclePrompt}
                      providers={providers}
                      provider={provider}
                      model={model}
                      onProviderModelChange={handleProviderModelChange}
                      preview={preview}
                      setPreview={setPreview}
                      onSavePreview={handleSavePreview}
                      isSaving={saveStudio.isPending}
                      oraclePromptVersion={oraclePromptVersion}
                      metaPromptVersion={metaPromptVersion}
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
                      onPromote={handlePromote}
                      isPromoting={promoteMut.isPending}
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
