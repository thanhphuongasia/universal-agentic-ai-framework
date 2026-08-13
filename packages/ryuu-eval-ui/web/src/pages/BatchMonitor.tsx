import { useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useBatch, useCancelRun } from "@/api/hooks";
import { useRunStream } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { Skeleton } from "@/components/Skeleton";
import { StopCircle, ExternalLink, BarChart2 } from "lucide-react";
import type { StreamEvent } from "@/api/types";
import { Link } from "react-router-dom";

interface ModelRunState {
  run_id: string;
  model: string;
  status: "running" | "done" | "cancelled" | "error";
  total: number;
  completed: number;
  passed: number;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  avg_score: number | null;
  log: string;
}

function fmt_usd(v: number) { return `$${v.toFixed(4)}`; }

function ModelRow({
  entry,
  suiteId,
  onEvent,
}: {
  entry: ModelRunState;
  suiteId: string | null;
  onEvent: (runId: string, ev: StreamEvent) => void;
}) {
  const pct = entry.total > 0 ? Math.round((entry.completed / entry.total) * 100) : 0;
  const cancelRun = useCancelRun();

  const handleEvent = useCallback(
    (ev: StreamEvent) => onEvent(entry.run_id, ev),
    [entry.run_id, onEvent],
  );

  useRunStream(entry.run_id, handleEvent, entry.status === "running");

  return (
    <tr className="border-b border-gray-100 dark:border-gray-800 last:border-0">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <StatusBadge status={entry.status} />
          <span className="font-mono text-xs font-medium text-gray-800 dark:text-gray-200">{entry.model}</span>
        </div>
        <p className="text-xs text-gray-400 font-mono mt-0.5 truncate max-w-[160px]">{entry.run_id.slice(0, 12)}…</p>
      </td>

      {/* Progress bar */}
      <td className="px-4 py-3 w-48">
        <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
          <span>{entry.completed}/{entry.total || "?"}</span>
          <span>{pct}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              entry.status === "done" ? "bg-green-500" :
              entry.status === "cancelled" ? "bg-yellow-400" :
              entry.status === "error" ? "bg-red-500" : "bg-purple-500"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </td>

      {/* Pass rate */}
      <td className="px-4 py-3 text-xs tabular-nums text-gray-600 dark:text-gray-300">
        {entry.completed > 0 ? (
          <span>{entry.passed}/{entry.completed} <span className="text-gray-400">({Math.round(entry.passed / entry.completed * 100)}%)</span></span>
        ) : "—"}
      </td>

      {/* Avg score */}
      <td className="px-4 py-3">
        {entry.avg_score !== null ? <ScoreBar score={entry.avg_score} /> : <span className="text-xs text-gray-400">—</span>}
      </td>

      {/* Cost */}
      <td className="px-4 py-3 text-xs tabular-nums text-gray-500">
        {entry.cost_usd > 0 ? fmt_usd(entry.cost_usd) : "—"}
      </td>

      {/* Actions */}
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-2">
          {entry.status === "running" && (
            <button
              onClick={() => cancelRun.mutate(entry.run_id)}
              disabled={cancelRun.isPending}
              className="text-red-400 hover:text-red-600 disabled:opacity-40"
              title="Cancel"
            >
              <StopCircle size={13} />
            </button>
          )}
          {entry.status === "done" && (
            <Link
              to={`/runs/${entry.run_id}?suite_id=${suiteId ?? ""}`}
              className="text-xs text-purple-600 dark:text-purple-400 hover:underline flex items-center gap-1"
            >
              Results <ExternalLink size={10} />
            </Link>
          )}
        </div>
      </td>
    </tr>
  );
}

export function BatchMonitor({ batchId }: { batchId: string }) {
  const [searchParams] = useSearchParams();
  const suiteId = searchParams.get("suite_id");
  const { data: batch, isLoading } = useBatch(batchId);

  const [states, setStates] = useState<Map<string, ModelRunState>>(new Map());

  // Initialize state entries when batch data arrives
  const runEntries = batch?.runs ?? [];
  if (runEntries.length > 0 && states.size === 0) {
    const initial = new Map<string, ModelRunState>();
    for (const { run_id, model } of runEntries) {
      initial.set(run_id, {
        run_id, model,
        status: "running",
        total: 0, completed: 0, passed: 0,
        cost_usd: 0, tokens_in: 0, tokens_out: 0,
        avg_score: null,
        log: "",
      });
    }
    setStates(initial);
  }

  const handleEvent = useCallback((runId: string, ev: StreamEvent) => {
    setStates((prev) => {
      const entry = prev.get(runId);
      if (!entry) return prev;
      const next = new Map(prev);
      const updated = { ...entry };

      if (ev.event === "run_start") {
        updated.total = ev.total ?? 0;
      } else if (ev.event === "case_done" && ev.result) {
        const r = ev.result;
        updated.completed += 1;
        updated.passed += r.pass ? 1 : 0;
        updated.cost_usd += r.cost_usd ?? 0;
        updated.tokens_in += r.tokens_in ?? 0;
        updated.tokens_out += r.tokens_out ?? 0;
        updated.avg_score = updated.completed > 0
          ? (updated.avg_score ?? 0) * (updated.completed - 1) / updated.completed
            + (r.score ?? 0) / updated.completed
          : r.score ?? null;
      } else if (ev.event === "run_done") {
        updated.status = "done";
        if (ev.summary) {
          updated.avg_score = ev.summary.avg_score ?? updated.avg_score;
          if (ev.summary.total_cost_usd != null) updated.cost_usd = ev.summary.total_cost_usd;
        }
      } else if (ev.event === "run_cancel") {
        updated.status = "cancelled";
      } else if (ev.event === "error") {
        updated.status = "error";
        updated.log = ev.error ?? "unknown error";
      }

      next.set(runId, updated);
      return next;
    });
  }, []);

  const allDone = states.size > 0 && [...states.values()].every(
    (s) => s.status !== "running",
  );

  if (isLoading) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (!batch) {
    return (
      <div className="p-6 max-w-5xl mx-auto text-sm text-gray-400">
        Batch {batchId} not found.
      </div>
    );
  }

  const stateList = runEntries.map(({ run_id, model }) =>
    states.get(run_id) ?? {
      run_id, model, status: "running" as const,
      total: 0, completed: 0, passed: 0,
      cost_usd: 0, tokens_in: 0, tokens_out: 0, avg_score: null, log: "",
    }
  );

  const runningCount = stateList.filter((s) => s.status === "running").length;
  const totalCost = stateList.reduce((a, s) => a + s.cost_usd, 0);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            Multi-Model Run
            {allDone && <span className="ml-2 text-sm font-normal text-green-600 dark:text-green-400">— all done</span>}
          </h1>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{batchId}</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {runningCount > 0 && (
            <span className="px-2 py-1 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
              {runningCount} running
            </span>
          )}
          <span>{stateList.length} models</span>
          {totalCost > 0 && <span>total {fmt_usd(totalCost)}</span>}
        </div>
      </div>

      {/* Model table */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-900 text-xs font-medium text-gray-500">
            <tr>
              <th className="px-4 py-2.5 text-left">Model</th>
              <th className="px-4 py-2.5 text-left">Progress</th>
              <th className="px-4 py-2.5 text-left">Pass</th>
              <th className="px-4 py-2.5 text-left">Avg Score</th>
              <th className="px-4 py-2.5 text-left">Cost</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {stateList.map((entry) => (
              <ModelRow
                key={entry.run_id}
                entry={entry}
                suiteId={suiteId}
                onEvent={handleEvent}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* All done — compare links */}
      {allDone && (
        <div className="rounded-xl border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/30 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-green-800 dark:text-green-300">All runs complete</p>
            <Link
              to={`/batch/${batchId}/compare?suite_id=${suiteId ?? ""}`}
              className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs bg-purple-600 hover:bg-purple-700 text-white font-medium"
            >
              <BarChart2 size={12} />
              Compare models
            </Link>
          </div>
          <div className="flex flex-wrap gap-2">
            {stateList.filter((s) => s.status === "done").map((s) => (
              <Link
                key={s.run_id}
                to={`/runs/${s.run_id}?suite_id=${suiteId ?? ""}`}
                className="text-xs rounded-md px-3 py-1.5 border border-green-300 dark:border-green-700 text-green-700 dark:text-green-300 hover:bg-green-100 dark:hover:bg-green-900/40 font-mono flex items-center gap-1"
              >
                {s.model} <ExternalLink size={9} />
              </Link>
            ))}
          </div>
          {suiteId && (
            <Link
              to={`/suites/${suiteId}`}
              className="block text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            >
              ← Back to suite
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
