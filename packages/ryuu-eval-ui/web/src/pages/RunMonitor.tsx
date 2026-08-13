import { useState, useCallback, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useCancelRun, useRunStream } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { StopCircle } from "lucide-react";
import type { StreamEvent, RunSummary, CaseStatus } from "@/api/types";

interface LiveCase {
  case_id: string;
  status: CaseStatus;
  score: number | null;
  latency_ms?: number;
  cost_usd?: number;
  error?: string;
}

interface LiveState {
  run_id: string | null;
  status: "running" | "done" | "cancelled" | "error";
  total: number;
  completed: number;
  passed: number;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  cases: Map<string, LiveCase>;
  log: string[];
  current_case_id: string | null;
  summary: RunSummary | null;
}

function fmt_usd(v: number) { return `$${v.toFixed(3)}`; }
function fmt_ms(v: number) { return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`; }

export function RunMonitor({ runId }: { runId: string }) {
  const [searchParams] = useSearchParams();
  const suiteId = searchParams.get("suite_id");
  const navigate = useNavigate();
  const cancelRun = useCancelRun();

  const [state, setState] = useState<LiveState>({
    run_id: runId,
    status: "running",
    total: 0,
    completed: 0,
    passed: 0,
    cost_usd: 0,
    tokens_in: 0,
    tokens_out: 0,
    cases: new Map(),
    log: [],
    current_case_id: null,
    summary: null,
  });
  const [elapsed, setElapsed] = useState(0);
  const [startTime] = useState(Date.now());
  const [streaming, setStreaming] = useState(true);

  // Elapsed timer
  useEffect(() => {
    if (state.status !== "running") return;
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startTime) / 1000)), 1000);
    return () => clearInterval(t);
  }, [state.status, startTime]);

  // Redirect when done
  useEffect(() => {
    if (state.status === "done" || state.status === "cancelled") {
      const t = setTimeout(() => navigate(`/runs/${runId}`), 1500);
      return () => clearTimeout(t);
    }
  }, [state.status, navigate, runId, suiteId]);

  const handleEvent = useCallback((ev: StreamEvent) => {
    setState((prev) => {
      const next = { ...prev };
      const ts = new Date().toISOString().slice(11, 23);

      if (ev.event === "run_start") {
        next.total = ev.total ?? 0;
        next.log = [...prev.log, `${ts} run_start total=${ev.total}`];
      } else if (ev.event === "case_start" && ev.case_id) {
        next.current_case_id = ev.case_id;
        const cases = new Map(prev.cases);
        cases.set(ev.case_id, { case_id: ev.case_id, status: "running", score: null });
        next.cases = cases;
        next.log = [...prev.log.slice(-49), `${ts} [${ev.case_id}] started`];
      } else if (ev.event === "case_done" && ev.result) {
        const r = ev.result;
        const cases = new Map(prev.cases);
        cases.set(r.case_id, {
          case_id: r.case_id,
          status: r.pass ? "pass" : "fail",
          score: r.score,
          latency_ms: r.latency_ms,
          cost_usd: r.cost_usd,
          error: r.error,
        });
        next.cases = cases;
        next.completed = prev.completed + 1;
        next.passed = prev.passed + (r.pass ? 1 : 0);
        next.cost_usd = prev.cost_usd + (r.cost_usd ?? 0);
        next.tokens_in = prev.tokens_in + (r.tokens_in ?? 0);
        next.tokens_out = prev.tokens_out + (r.tokens_out ?? 0);
        const icon = r.pass ? "✅" : "❌";
        next.log = [...prev.log.slice(-49),
          `${ts} [${r.case_id}] ${icon} score=${r.score?.toFixed(2) ?? "?"} ${r.latency_ms ? fmt_ms(r.latency_ms) : ""}`];
        if (next.current_case_id === r.case_id) next.current_case_id = null;
      } else if (ev.event === "run_done") {
        next.status = "done";
        next.summary = ev.summary ?? null;
        setStreaming(false);
        next.log = [...prev.log.slice(-49), `${ts} run_done`];
      } else if (ev.event === "run_cancel") {
        next.status = "cancelled";
        setStreaming(false);
        next.log = [...prev.log.slice(-49), `${ts} run_cancelled`];
      } else if (ev.event === "error") {
        next.status = "error";
        next.log = [...prev.log.slice(-49), `${ts} error: ${ev.error}`];
      }
      return next;
    });
  }, []);

  useRunStream(runId, handleEvent, streaming);

  const progressPct = state.total > 0 ? Math.round((state.completed / state.total) * 100) : 0;

  const caseList = Array.from(state.cases.values());

  async function handleCancel() {
    if (!runId) return;
    await cancelRun.mutateAsync(runId);
    setState((p) => ({ ...p, status: "cancelled" }));
    setStreaming(false);
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            Run Monitor
            {state.status !== "running" && (
              <span className="ml-2"><StatusBadge status={state.status} /></span>
            )}
          </h1>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{runId}</p>
        </div>
        {state.status === "running" && (
          <button
            onClick={handleCancel}
            disabled={cancelRun.isPending}
            className="flex items-center gap-1.5 rounded-md px-3 py-2 text-sm border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-60"
          >
            <StopCircle size={14} />
            Cancel
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">
            {state.completed}/{state.total || "?"} cases
          </span>
          <span className="text-gray-400 tabular-nums text-xs">
            Elapsed {elapsed}s
          </span>
        </div>
        <div className="h-2 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              state.status === "done" ? "bg-green-500" :
              state.status === "cancelled" ? "bg-yellow-400" :
              "bg-purple-500"
            }`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <div className="flex flex-wrap gap-4 text-xs text-gray-500">
          <span>Cost: <strong>{fmt_usd(state.cost_usd)}</strong></span>
          <span>Tokens in: <strong>{state.tokens_in.toLocaleString()}</strong></span>
          <span>Tokens out: <strong>{state.tokens_out.toLocaleString()}</strong></span>
          {state.total > 0 && <span>Pass: <strong>{state.passed}/{state.completed}</strong></span>}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Case list */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-xs font-medium text-gray-500">
            Cases
          </div>
          <div className="divide-y divide-gray-50 dark:divide-gray-800 max-h-72 overflow-y-auto">
            {caseList.length === 0 && (
              <div className="px-4 py-6 text-center text-xs text-gray-400">
                Waiting for first case…
              </div>
            )}
            {caseList.map((c) => (
              <div
                key={c.case_id}
                className={`flex items-center gap-3 px-4 py-2.5 text-sm ${
                  c.case_id === state.current_case_id ? "bg-purple-50 dark:bg-purple-950/30" : ""
                }`}
              >
                <StatusBadge status={c.status} />
                <span className="font-mono text-xs text-gray-500 flex-1">{c.case_id}</span>
                {c.score !== null && <ScoreBar score={c.score} />}
                {c.latency_ms && (
                  <span className="text-xs text-gray-400 tabular-nums">{fmt_ms(c.latency_ms)}</span>
                )}
                {c.cost_usd != null && (
                  <span className="text-xs text-gray-400 tabular-nums">{fmt_usd(c.cost_usd)}</span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Event log */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 text-xs font-medium text-gray-500">
            Event log
          </div>
          <div className="p-3 max-h-72 overflow-y-auto font-mono text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
            {state.log.length === 0 && (
              <div className="text-gray-300 dark:text-gray-600">Connecting…</div>
            )}
            {state.log.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        </div>
      </div>

      {(state.status === "done" || state.status === "cancelled") && (
        <div className="text-center text-sm text-gray-400">
          Redirecting to results…
        </div>
      )}
    </div>
  );
}
