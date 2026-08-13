import { useParams, useSearchParams, Link } from "react-router-dom";
import { useBatch, useRunResult } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { Skeleton } from "@/components/Skeleton";
import type { CaseResult, RunResult } from "@/api/types";

// ── Per-model run loader ──────────────────────────────────────────────────────

function useAllRunResults(runIds: string[]) {
  // Call useRunResult for each run — hooks must not be called conditionally,
  // so we cap at 8 models (well above practical use).
  const r0 = useRunResult(runIds[0] ?? "");
  const r1 = useRunResult(runIds[1] ?? "");
  const r2 = useRunResult(runIds[2] ?? "");
  const r3 = useRunResult(runIds[3] ?? "");
  const r4 = useRunResult(runIds[4] ?? "");
  const r5 = useRunResult(runIds[5] ?? "");
  const r6 = useRunResult(runIds[6] ?? "");
  const r7 = useRunResult(runIds[7] ?? "");
  const all = [r0, r1, r2, r3, r4, r5, r6, r7].slice(0, runIds.length);
  return {
    results: all.map((r) => r.data ?? null),
    isLoading: all.some((r) => r.isLoading && !!runIds[all.indexOf(r)]),
  };
}

// ── Cell ─────────────────────────────────────────────────────────────────────

function Cell({
  c,
  runId,
  suiteId,
}: {
  c: CaseResult | undefined;
  runId: string;
  suiteId: string;
}) {
  if (!c) return <td className="px-3 py-2.5 text-xs text-gray-300 dark:text-gray-600 text-center">—</td>;

  const bg = c.pass
    ? "bg-green-50 dark:bg-green-950/20"
    : "bg-red-50 dark:bg-red-950/20";

  const actual = typeof c.actual === "string"
    ? c.actual
    : JSON.stringify(c.actual ?? "");

  return (
    <td className={`px-3 py-2.5 align-top max-w-[200px] ${bg}`}>
      <Link
        to={`/runs/${runId}/cases/${c.case_id}?suite_id=${suiteId}`}
        className="block group"
      >
        <div className="flex items-center gap-1.5 mb-1">
          <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${c.pass ? "bg-green-500" : "bg-red-500"}`} />
          {c.score != null && (
            <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400">
              {c.score.toFixed(2)}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-600 dark:text-gray-300 font-mono line-clamp-3 group-hover:text-purple-600 dark:group-hover:text-purple-400 break-words">
          {actual.slice(0, 180)}{actual.length > 180 ? "…" : ""}
        </p>
      </Link>
    </td>
  );
}

// ── Model header ──────────────────────────────────────────────────────────────

function ModelHeader({ run, model, suiteId }: { run: RunResult | null; model: string; suiteId: string }) {
  const passRate = run && run.total_cases > 0
    ? Math.round(run.passed_cases / run.total_cases * 100) : null;

  return (
    <th className="px-3 py-2.5 text-left min-w-[180px]">
      <div className="font-mono text-xs font-semibold text-gray-700 dark:text-gray-300 truncate">{model}</div>
      {run ? (
        <div className="flex items-center gap-2 mt-1">
          <StatusBadge status={run.status} />
          {passRate != null && (
            <span className="text-xs text-gray-500 tabular-nums">
              {run.passed_cases}/{run.total_cases} ({passRate}%)
            </span>
          )}
        </div>
      ) : (
        <span className="text-xs text-gray-400">loading…</span>
      )}
      {run && (
        <div className="mt-1">
          <ScoreBar score={run.avg_score ?? null} />
        </div>
      )}
      {run && (
        <Link
          to={`/runs/${run.run_id}?suite_id=${suiteId}`}
          className="text-xs text-purple-600 dark:text-purple-400 hover:underline mt-0.5 inline-block"
        >
          Full results →
        </Link>
      )}
    </th>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function BatchComparePage() {
  const { batchId = "" } = useParams<{ batchId: string }>();
  const [searchParams] = useSearchParams();
  const suiteId = searchParams.get("suite_id") ?? "";

  const { data: batch, isLoading: batchLoading } = useBatch(batchId);
  const runEntries = batch?.runs ?? [];
  const runIds = runEntries.map((r) => r.run_id);

  const { results, isLoading: runsLoading } = useAllRunResults(runIds);

  if (batchLoading) {
    return (
      <div className="p-6 max-w-7xl mx-auto space-y-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!batch) {
    return <div className="p-6 text-sm text-gray-400">Batch {batchId} not found.</div>;
  }

  // Build case list from first loaded run; fallback to others
  const caseIds: string[] = [];
  for (const run of results) {
    if (run?.cases?.length) {
      for (const c of run.cases) {
        if (!caseIds.includes(c.case_id)) caseIds.push(c.case_id);
      }
      break;
    }
  }

  // Map each run to a lookup: case_id → CaseResult
  const caseMaps: Map<string, CaseResult>[] = results.map((run) => {
    const m = new Map<string, CaseResult>();
    for (const c of run?.cases ?? []) m.set(c.case_id, c);
    return m;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">Model Comparison</h1>
          <span className="text-sm text-gray-400">{runEntries.length} models</span>
        </div>
        <p className="text-xs font-mono text-gray-400 mt-0.5">{batchId}</p>
        {suiteId && (
          <Link to={`/suites/${suiteId}`} className="text-xs text-gray-400 hover:text-purple-600 dark:hover:text-purple-400 mt-0.5 inline-block">
            ← Back to {suiteId}
          </Link>
        )}
      </div>

      {/* Summary bar */}
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${runEntries.length}, minmax(0, 1fr))` }}>
        {runEntries.map(({ run_id, model }, i) => {
          const run = results[i];
          if (!run) return (
            <div key={run_id} className="rounded-xl border border-gray-200 dark:border-gray-800 p-3 space-y-1 animate-pulse">
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
              <div className="h-3 bg-gray-100 dark:bg-gray-800 rounded w-1/2" />
            </div>
          );
          const passRate = run.total_cases > 0 ? run.passed_cases / run.total_cases : 0;
          return (
            <div key={run_id} className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-3">
              <div className="font-mono text-xs font-semibold text-gray-700 dark:text-gray-200 truncate">{model}</div>
              <div className="mt-1.5">
                <ScoreBar score={run.avg_score ?? null} />
              </div>
              <div className="text-xs text-gray-500 mt-1 tabular-nums">
                {run.passed_cases}/{run.total_cases} pass · {(passRate * 100).toFixed(0)}%
                {run.total_cost_usd != null && (
                  <span className="ml-2">${run.total_cost_usd.toFixed(4)}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Grid table */}
      {runsLoading && caseIds.length === 0 ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
              <tr>
                <th className="px-3 py-2.5 text-left text-xs font-medium text-gray-500 w-36 shrink-0 sticky left-0 bg-gray-50 dark:bg-gray-900">
                  Case ID
                </th>
                {runEntries.map(({ run_id, model }, i) => (
                  <ModelHeader
                    key={run_id}
                    run={results[i]}
                    model={model}
                    suiteId={suiteId}
                  />
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {caseIds.map((caseId) => (
                <tr key={caseId} className="hover:bg-gray-50/50 dark:hover:bg-gray-900/30">
                  <td className="px-3 py-2.5 font-mono text-xs text-gray-500 align-top sticky left-0 bg-white dark:bg-gray-950 border-r border-gray-100 dark:border-gray-800">
                    {caseId}
                  </td>
                  {runEntries.map(({ run_id }, i) => (
                    <Cell
                      key={run_id}
                      c={caseMaps[i]?.get(caseId)}
                      runId={run_id}
                      suiteId={suiteId}
                    />
                  ))}
                </tr>
              ))}
              {caseIds.length === 0 && (
                <tr>
                  <td
                    colSpan={runEntries.length + 1}
                    className="px-4 py-8 text-center text-sm text-gray-400"
                  >
                    Run results not loaded yet. Wait for runs to complete.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
