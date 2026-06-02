import { useState, useEffect, useCallback } from "react";
import { Link, useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useRunResult, useCaseProvenance } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { Skeleton } from "@/components/Skeleton";
import { DataView } from "@/components/DataView";
import { ChevronLeft, ChevronRight, ThumbsUp, ThumbsDown, ArrowLeft, Terminal, ShieldCheck } from "lucide-react";
import type { CaseResult, CaseStep, RunParams } from "@/api/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function stringify(v: unknown): string {
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}


// ── Step trace row ────────────────────────────────────────────────────────────

const STEP_STYLE: Record<string, string> = {
  thought:     "border-yellow-300 dark:border-yellow-700 bg-yellow-50 dark:bg-yellow-950/30",
  tool_call:   "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-950/30",
  observation: "border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-950/30",
  llm_input:   "border-purple-300 dark:border-purple-700 bg-purple-50 dark:bg-purple-950/30",
  llm_output:  "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900",
  retry:       "border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-950/30",
  error:       "border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-950/30",
};

const STEP_BADGE: Record<string, string> = {
  thought:     "bg-yellow-100 dark:bg-yellow-900/50 text-yellow-800 dark:text-yellow-300",
  tool_call:   "bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-300",
  observation: "bg-green-100 dark:bg-green-900/50 text-green-800 dark:text-green-300",
  llm_input:   "bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-300",
  llm_output:  "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300",
  retry:       "bg-orange-100 dark:bg-orange-900/50 text-orange-800 dark:text-orange-300",
  error:       "bg-red-100 dark:bg-red-900/50 text-red-800 dark:text-red-300",
};

function StepRow({ step, index }: { step: CaseStep; index: number }) {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((v) => !v), []);
  const style = STEP_STYLE[step.type] ?? STEP_STYLE.llm_output;
  const badge = STEP_BADGE[step.type] ?? STEP_BADGE.llm_output;
  const content = stringify(step.content ?? "");
  const preview = content.slice(0, 160);

  return (
    <div className={`rounded-lg border p-3 ${style}`}>
      <div className="flex items-center justify-between cursor-pointer select-none" onClick={toggle}>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 tabular-nums w-5 shrink-0">#{index + 1}</span>
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide ${badge}`}>
            {step.type}
          </span>
          {step.label && (
            <span className="text-xs text-gray-500 dark:text-gray-400 font-mono truncate max-w-xs">
              {step.label}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-400 ml-2">{open ? "▲" : "▼"}</span>
      </div>
      {!open && content && (
        <p className="text-xs mt-1.5 text-gray-500 dark:text-gray-400 font-mono truncate">
          {preview}{content.length > 160 ? "…" : ""}
        </p>
      )}
      {open && (
        <pre className="text-xs mt-2 whitespace-pre-wrap break-words font-mono text-gray-700 dark:text-gray-300 max-h-72 overflow-auto">
          {content}
        </pre>
      )}
    </div>
  );
}

// ── Run params bar ────────────────────────────────────────────────────────────

function RunParamsBar({ params }: { params: RunParams | undefined }) {
  if (!params) return null;
  const fmt = (v: number | string | null | undefined) =>
    v === null || v === undefined || v === "" ? null : String(v);
  const fmtTime = (t?: number | null) =>
    t ? new Date(t * 1000).toLocaleString() : null;

  const chips: [string, string | null][] = [
    ["model", fmt(params.model)],
    ["mode", fmt(params.mode)],
    ["concurrency", fmt(params.concurrency)],
    ["max_tokens", fmt(params.max_tokens)],
    ["temp", fmt(params.temperature)],
    ["budget", params.budget_cap_usd != null ? `$${params.budget_cap_usd}` : null],
    ["started", fmtTime(params.started_at)],
    ["cases", params.case_ids?.length
      ? `${params.case_ids.length} selected`
      : "all"],
  ].filter(([, v]) => v !== null) as [string, string][];

  return (
    <details className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 text-xs overflow-hidden">
      <summary className="px-3 py-2 cursor-pointer select-none flex items-center gap-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
        <Terminal size={11} />
        <span className="font-medium">Run params</span>
        <span className="truncate text-gray-400 font-mono">
          {[fmt(params.model), fmt(params.mode), fmt(params.max_tokens) ? `max_tokens=${params.max_tokens}` : null]
            .filter(Boolean).join("  ·  ")}
        </span>
      </summary>
      <div className="px-3 pb-2 pt-1 border-t border-gray-100 dark:border-gray-800 flex flex-wrap gap-x-4 gap-y-1">
        {chips.map(([k, v]) => (
          <span key={k} className="text-gray-500">
            <span className="font-mono text-gray-400">{k}=</span>
            <span className="font-mono text-gray-700 dark:text-gray-300">{v}</span>
          </span>
        ))}
        {params.system_prompt && (
          <details className="w-full mt-1">
            <summary className="cursor-pointer text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              system_prompt ({params.system_prompt.length} chars)
            </summary>
            <pre className="mt-1 text-xs font-mono text-gray-600 dark:text-gray-400 max-h-32 overflow-auto whitespace-pre-wrap bg-white dark:bg-gray-950 rounded p-2 border border-gray-100 dark:border-gray-800">
              {params.system_prompt}
            </pre>
          </details>
        )}
      </div>
    </details>
  );
}

// ── Human review ──────────────────────────────────────────────────────────────

function useReview(runId: string, caseId: string) {
  const key = `review:${runId}:${caseId}`;
  const [rating, setRating] = useState<"up" | "down" | null>(
    () => (localStorage.getItem(`${key}:rating`) as "up" | "down" | null) ?? null
  );
  const [note, setNote] = useState(() => localStorage.getItem(`${key}:note`) ?? "");

  return {
    rating, note,
    saveRating: (r: "up" | "down") => { setRating(r); localStorage.setItem(`${key}:rating`, r); },
    saveNote: (n: string) => { setNote(n); localStorage.setItem(`${key}:note`, n); },
  };
}

// ── Oracle provenance ─────────────────────────────────────────────────────────

function fmtReviewedAt(s?: string): string {
  if (!s || !s.trim()) return "N/A";
  const d = new Date(s);
  return isNaN(d.getTime()) ? s : d.toLocaleString();
}

function PromptBlock({ label, text }: { label: string; text?: string }) {
  if (!text) {
    return (
      <div className="text-xs">
        <span className="text-gray-500">{label}: </span>
        <span className="text-gray-400 italic">N/A</span>
      </div>
    );
  }
  return (
    <details className="rounded-lg border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-950 overflow-hidden">
      <summary className="px-3 py-2 cursor-pointer select-none text-xs font-medium text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-900">
        {label} <span className="text-gray-400 font-normal">({text.length} chars)</span>
      </summary>
      <pre className="px-3 py-2 text-xs font-mono text-gray-600 dark:text-gray-300 max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-gray-100 dark:border-gray-800">
        {text}
      </pre>
    </details>
  );
}

/** Provenance for an oracle-derived case: approval, the two prompts, and the
 *  approved input/expectation. Renders nothing for hand-written cases. */
function OracleProvenancePanel({ suiteId, caseId }: { suiteId: string | null; caseId: string }) {
  const { data } = useCaseProvenance(suiteId, caseId);
  if (!data || !data.has_oracle) return null;

  const approved = !!(data.reviewed_by?.trim() || data.reviewed_at?.trim());
  const meta: [string, string][] = [
    ["Approved by", data.reviewed_by?.trim() || "N/A"],
    ["Approved at", fmtReviewedAt(data.reviewed_at)],
    ["Oracle model", data.oracle_model?.trim() || "N/A"],
    ["Prompt ver", data.oracle_prompt_version?.trim() || "N/A"],
    ["Fixture", data.source_fixture || "N/A"],
  ];

  return (
    <details open className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
      <summary className="px-4 py-3 cursor-pointer select-none text-xs font-semibold text-gray-500 uppercase tracking-wide hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center gap-2">
        <ShieldCheck size={13} /> Oracle Provenance
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium normal-case ${
          approved
            ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
            : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
        }`}>
          {approved ? "approved" : "not approved"}
        </span>
      </summary>
      <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-800 space-y-3">
        {/* 1. approval / audit */}
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-600 dark:text-gray-300">
          {meta.map(([k, v]) => (
            <span key={k}>
              <span className="text-gray-400">{k}: </span>
              <span className={k === "Prompt ver" || k === "Fixture" ? "font-mono" : ""}>{v}</span>
            </span>
          ))}
        </div>
        {/* 2 + 3. prompts */}
        <PromptBlock label="Production prompt (under test)" text={data.production_prompt} />
        <PromptBlock label="Oracle prompt (generated the ground truth)" text={data.oracle_prompt} />
        {/* 4. input vs approved expectation */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-gray-100 dark:border-gray-800 overflow-hidden">
            <div className="px-3 py-1.5 bg-gray-50 dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 text-xs text-gray-500 font-medium">Input</div>
            <pre className="px-3 py-2 text-xs font-mono text-gray-600 dark:text-gray-300 max-h-56 overflow-auto whitespace-pre-wrap break-words">{stringify(data.input)}</pre>
          </div>
          <div className="rounded-lg border border-gray-100 dark:border-gray-800 overflow-hidden">
            <div className="px-3 py-1.5 bg-gray-50 dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 text-xs text-gray-500 font-medium">Expectation (approved)</div>
            <pre className="px-3 py-2 text-xs font-mono text-gray-600 dark:text-gray-300 max-h-56 overflow-auto whitespace-pre-wrap break-words">{stringify(data.expected)}</pre>
          </div>
        </div>
      </div>
    </details>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function CaseDetail() {
  const { runId = "", caseId = "" } = useParams<{ runId: string; caseId: string }>();
  const [searchParams] = useSearchParams();
  const suiteId = searchParams.get("suite_id");
  const navigate = useNavigate();
  const { data: run, isLoading } = useRunResult(runId);
  const review = useReview(runId, caseId);

  const cases = run?.cases ?? [];
  const idx = cases.findIndex((c: CaseResult) => c.case_id === caseId);
  const current: CaseResult | undefined = cases[idx];
  const prevCase = idx > 0 ? cases[idx - 1] : null;
  const nextCase = idx < cases.length - 1 ? cases[idx + 1] : null;

  function navTo(c: CaseResult) {
    navigate(`/runs/${runId}/cases/${c.case_id}?suite_id=${suiteId ?? ""}`);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft" && prevCase) navTo(prevCase);
      if (e.key === "ArrowRight" && nextCase) navTo(nextCase);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prevCase, nextCase]);

  if (isLoading) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!current) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-3">
        <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-purple-600 dark:hover:text-purple-400">
          <ArrowLeft size={14} /> Back
        </button>
        <p className="text-sm text-gray-400">Case {caseId} not found in run {runId}.</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">

      {/* ── Top nav ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-sm text-gray-500">
          <button
            onClick={() => navigate(-1)}
            className="flex items-center gap-1.5 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-purple-600 dark:hover:text-purple-400"
          >
            <ArrowLeft size={14} /> Back
          </button>
          <span className="text-gray-300 dark:text-gray-700">/</span>
          {suiteId && (
            <Link to={`/suites/${suiteId}`} className="hover:text-purple-600 dark:hover:text-purple-400">
              {suiteId}
            </Link>
          )}
          <span>/</span>
          <Link to={`/runs/${runId}?suite_id=${suiteId ?? ""}`} className="hover:text-purple-600 dark:hover:text-purple-400">
            run
          </Link>
          <span>/</span>
          <span className="font-mono text-gray-700 dark:text-gray-300">{caseId}</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => prevCase && navTo(prevCase)}
            disabled={!prevCase}
            className="p-1.5 rounded border border-gray-200 dark:border-gray-700 disabled:opacity-30 hover:bg-gray-50 dark:hover:bg-gray-800"
            title="Previous (←)"
          >
            <ChevronLeft size={14} />
          </button>
          <span className="px-2 text-xs text-gray-400 tabular-nums">{idx + 1}/{cases.length}</span>
          <button
            onClick={() => nextCase && navTo(nextCase)}
            disabled={!nextCase}
            className="p-1.5 rounded border border-gray-200 dark:border-gray-700 disabled:opacity-30 hover:bg-gray-50 dark:hover:bg-gray-800"
            title="Next (→)"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {/* ── Run params bar ── */}
      <RunParamsBar params={run?.params} />

      {/* ── Status card ── */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 text-sm">
        <StatusBadge status={current.pass ? "pass" : "fail"} />
        <div className="flex items-center gap-1.5 text-gray-500">Score: <ScoreBar score={current.score} /></div>
        {current.latency_ms != null && <span className="text-gray-400">{Math.round(current.latency_ms)}ms</span>}
        {current.cost_usd != null && <span className="text-gray-400">${current.cost_usd.toFixed(4)}</span>}
        {current.error && <span className="text-red-500 text-xs">{current.error}</span>}
      </div>

      {/* ── Oracle provenance (only for oracle-derived cases) ── */}
      <OracleProvenancePanel suiteId={suiteId} caseId={caseId} />

      {/* ── Input ── */}
      {current.input !== undefined && (
        <div className="space-y-2">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Input</span>
          <DataView value={current.input} maxHeight="max-h-72" />
        </div>
      )}

      {/* ── Scoring spec (per-case, drives build_scorers) ── */}
      {current.metadata?.scoring != null && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-3 py-2 bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 text-xs font-medium text-gray-500">
            Scoring spec
          </div>
          <pre className="px-3 py-2 text-xs font-mono text-gray-600 dark:text-gray-300 max-h-48 overflow-auto whitespace-pre-wrap break-words">
            {JSON.stringify(current.metadata.scoring, null, 2)}
          </pre>
        </div>
      )}

      {/* ── Expected vs Actual ── */}
      <div className="space-y-3">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Expected vs Actual</span>
        <DataView
          value={current.actual}
          expected={current.expected}
          defaultMode="table"
          maxHeight="max-h-[60vh]"
        />
      </div>

      {/* ── Steps / Trace ── */}
      <div>
        <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Trace
          {current.steps && current.steps.length > 0 && (
            <span className="ml-1.5 font-normal normal-case text-gray-400">({current.steps.length} steps)</span>
          )}
        </div>

        {current.steps && current.steps.length > 0 ? (
          <div className="space-y-2">
            {current.steps.map((step, i) => (
              <StepRow key={i} step={step} index={i} />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-gray-200 dark:border-gray-700 p-5 space-y-2 text-xs text-gray-400">
            <p className="font-medium text-gray-500 dark:text-gray-300">No trace captured</p>
            <p>
              Populate <code className="font-mono bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">CaseResult.steps</code> from
              your <code className="font-mono bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">EvalTarget</code> to see LLM inputs,
              thoughts, tool calls, and retries here.
            </p>
            <p className="text-gray-400">
              Example steps to emit: <span className="font-mono text-purple-500">llm_input</span> (system+user prompt),{" "}
              <span className="font-mono text-purple-500">llm_output</span> (raw response + tokens),{" "}
              <span className="font-mono text-purple-500">thought</span> (chain-of-thought),{" "}
              <span className="font-mono text-purple-500">retry</span> (parse failure + retry count).
            </p>
          </div>
        )}
      </div>

      {/* ── Human review ── */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 space-y-3">
        <div className="text-xs font-medium text-gray-500">Human review</div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => review.saveRating("up")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-2 text-sm border transition-colors ${
              review.rating === "up"
                ? "border-green-400 bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300"
                : "border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
            }`}
          >
            <ThumbsUp size={13} /> Good
          </button>
          <button
            onClick={() => review.saveRating("down")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-2 text-sm border transition-colors ${
              review.rating === "down"
                ? "border-red-400 bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300"
                : "border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
            }`}
          >
            <ThumbsDown size={13} /> Bad
          </button>
          <input
            value={review.note}
            onChange={(e) => review.saveNote(e.target.value)}
            className="flex-1 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="Add note… (saved locally)"
          />
        </div>
      </div>

    </div>
  );
}
