import { useState, Fragment } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useRunResult } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { TableSkeleton, Skeleton } from "@/components/Skeleton";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell
} from "recharts";
import { Download, ChevronUp, ChevronDown, ChevronRight, Terminal } from "lucide-react";
import { DataView } from "@/components/DataView";
import type { CaseResult, RunResult } from "@/api/types";

type SortKey = "score" | "latency_ms" | "cost_usd";

function exportCSV(cases: CaseResult[]) {
  const header = "case_id,pass,score,latency_ms,cost_usd,error";
  const rows = cases.map((c) =>
    [c.case_id, c.pass, c.score, c.latency_ms ?? "", c.cost_usd ?? "", c.error ?? ""].join(",")
  );
  const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "run-results.csv";
  a.click();
}

function ScoreDistChart({ cases }: { cases: CaseResult[] }) {
  const buckets = Array.from({ length: 10 }, (_, i) => ({
    range: `${i * 10}-${(i + 1) * 10}`,
    count: 0,
  }));
  for (const c of cases) {
    if (c.score !== null) {
      const idx = Math.min(Math.floor(c.score * 10), 9);
      buckets[idx].count++;
    }
  }
  return (
    <ResponsiveContainer width="100%" height={80}>
      <BarChart data={buckets} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
        <XAxis dataKey="range" tick={{ fontSize: 10 }} />
        <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
        <Tooltip
          contentStyle={{ fontSize: 12 }}
          formatter={(v: unknown) => [v as number, "cases"]}
        />
        <Bar dataKey="count" radius={[2, 2, 0, 0]}>
          {buckets.map((_, i) => (
            <Cell
              key={i}
              fill={i >= 9 ? "#22c55e" : i >= 7 ? "#a3e635" : i >= 5 ? "#facc15" : "#f87171"}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Run Log / Params panel ────────────────────────────────────────────────────
//
// Shows the exact request the backend received from the Run dialog so the
// user can verify what params were actually applied. "—" means the field
// was NOT sent (server used provider default / skipped enforcement).

function RunLogPanel({ run }: { run: RunResult }) {
  const p = run.params;
  if (!p) {
    return (
      <details className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
        <summary className="px-4 py-3 cursor-pointer select-none text-xs font-medium text-gray-500 uppercase tracking-wide hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center gap-2">
          <Terminal size={12} /> Run Log
          <span className="text-gray-400 normal-case font-normal">— no params (legacy run before logging was added)</span>
        </summary>
      </details>
    );
  }

  const fmt = (v: number | string | null | undefined) =>
    v === null || v === undefined || v === "" ? "—" : String(v);
  const fmtTime = (t?: number | null) =>
    t ? new Date(t * 1000).toLocaleString() : "—";

  const rows: [string, React.ReactNode][] = [
    ["model", <span className="font-mono">{fmt(p.model)}</span>],
    ["mode", <span className="font-mono">{fmt(p.mode)}</span>],
    ["concurrency", <span className="font-mono tabular-nums">{fmt(p.concurrency)}</span>],
    ["max_tokens", <span className="font-mono tabular-nums">{fmt(p.max_tokens)}</span>],
    ["temperature", <span className="font-mono tabular-nums">{fmt(p.temperature)}</span>],
    ["budget_cap_usd", <span className="font-mono tabular-nums">{fmt(p.budget_cap_usd)}</span>],
    ["started_at", <span className="font-mono">{fmtTime(p.started_at)}</span>],
    ["case_ids",
      <span className="font-mono">
        {p.case_ids && p.case_ids.length ? `${p.case_ids.length} selected: ${p.case_ids.join(", ")}` : "all"}
      </span>,
    ],
  ];

  return (
    <details className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden" open>
      <summary className="px-4 py-3 cursor-pointer select-none text-xs font-medium text-gray-500 uppercase tracking-wide hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center gap-2">
        <Terminal size={12} /> Run Log
        <span className="text-gray-400 normal-case font-normal">— params from the Run dialog</span>
      </summary>

      <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-800">
        <table className="text-xs w-full">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="border-b border-gray-50 dark:border-gray-800 last:border-b-0">
                <td className="py-1.5 pr-4 text-gray-500 align-top w-36 font-mono">{k}</td>
                <td className="py-1.5 text-gray-700 dark:text-gray-300 break-all">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {p.system_prompt && (
          <details className="mt-3 border-t border-gray-100 dark:border-gray-800 pt-2">
            <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300">
              system_prompt ({p.system_prompt.length} chars)
            </summary>
            <pre className="mt-2 text-xs font-mono text-gray-600 dark:text-gray-400 max-h-48 overflow-auto whitespace-pre-wrap bg-gray-50 dark:bg-gray-950 rounded p-2">
              {p.system_prompt}
            </pre>
          </details>
        )}

        <p className="mt-3 text-xs text-gray-400 italic">
          "—" means the field was omitted from the request — the provider used its default.
        </p>
      </div>
    </details>
  );
}

export function RunResults({ runId }: { runId: string }) {
  const [searchParams] = useSearchParams();
  const suiteId = searchParams.get("suite_id");
  const { data: run, isLoading, error } = useRunResult(runId);
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortAsc, setSortAsc] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortAsc((p) => !p);
    else { setSortKey(k); setSortAsc(true); }
  }

  const SortIcon = ({ k }: { k: SortKey }) =>
    sortKey === k
      ? sortAsc ? <ChevronUp size={12} /> : <ChevronDown size={12} />
      : null;

  if (isLoading) {
    return (
      <div className="p-6 max-w-5xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20" />)}
        </div>
        <TableSkeleton rows={6} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="rounded-lg border border-red-200 p-4 text-sm text-red-600">
          Failed to load run: {(error as Error).message}
        </div>
      </div>
    );
  }

  if (!run) return null;

  const passRate = run.total_cases > 0
    ? Math.round((run.passed_cases / run.total_cases) * 100)
    : 0;

  const failedCases = run.cases.filter((c: CaseResult) => !c.pass);
  const errorGroups = failedCases.reduce<Record<string, string[]>>((acc: Record<string, string[]>, c: CaseResult) => {
    const key = c.error ?? "Wrong output";
    if (!acc[key]) acc[key] = [];
    acc[key].push(c.case_id);
    return acc;
  }, {});

  const sortedCases = [...run.cases].sort((a, b) => {
    const av = (a[sortKey] ?? 0) as number;
    const bv = (b[sortKey] ?? 0) as number;
    return sortAsc ? av - bv : bv - av;
  });

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            Run Results
            <StatusBadge status={run.status} />
          </h1>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{runId}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => exportCSV(run.cases)}
            className="flex items-center gap-1.5 rounded-md px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <Download size={12} /> Export CSV
          </button>
          {suiteId && (
            <Link
              to={`/suites/${suiteId}`}
              className="rounded-md px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              ← Suite
            </Link>
          )}
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Pass", value: `${run.passed_cases}/${run.total_cases}`, sub: `${passRate}%` },
          { label: "Avg score", value: run.avg_score != null ? run.avg_score.toFixed(3) : "—" },
          { label: "Total cost", value: run.total_cost_usd != null ? `$${run.total_cost_usd.toFixed(4)}` : "—" },
          { label: "Avg latency", value: run.avg_latency_ms != null ? `${Math.round(run.avg_latency_ms)}ms` : "—" },
        ].map(({ label, value, sub }) => (
          <div key={label} className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
            <div className="text-xs text-gray-400 mb-1">{label}</div>
            <div className="text-2xl font-semibold tabular-nums">{value}</div>
            {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
          </div>
        ))}
      </div>

      {/* Run Log — params snapshot from the run dialog */}
      <RunLogPanel run={run} />

      {/* Score distribution */}
      {run.cases.length > 2 && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
          <div className="text-xs font-medium text-gray-500 mb-2">Score distribution</div>
          <ScoreDistChart cases={run.cases} />
        </div>
      )}

      {/* Failure clusters */}
      {failedCases.length > 0 && (
        <div className="rounded-xl border border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950/30 p-4">
          <div className="text-xs font-medium text-yellow-800 dark:text-yellow-300 mb-2">
            Failure clusters ({failedCases.length} failed)
          </div>
          {Object.entries(errorGroups).map(([err, ids]: [string, string[]]) => (
            <div key={err} className="flex gap-3 text-xs mb-1">
              <span className="text-yellow-700 dark:text-yellow-300 font-medium shrink-0">
                {err}
              </span>
              <span className="text-gray-500 font-mono">{ids.join(", ")}</span>
            </div>
          ))}
        </div>
      )}

      {/* Cases table */}
      <div>
        <h2 className="font-medium text-sm text-gray-700 dark:text-gray-300 mb-3">
          Cases ({run.cases.length})
        </h2>
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500">Case ID</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500">Status</th>
                <th
                  className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none"
                  onClick={() => toggleSort("score")}
                >
                  <span className="flex items-center gap-1">Score <SortIcon k="score" /></span>
                </th>
                <th
                  className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none"
                  onClick={() => toggleSort("latency_ms")}
                >
                  <span className="flex items-center gap-1">Latency <SortIcon k="latency_ms" /></span>
                </th>
                <th
                  className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none"
                  onClick={() => toggleSort("cost_usd")}
                >
                  <span className="flex items-center gap-1">Cost <SortIcon k="cost_usd" /></span>
                </th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {sortedCases.map((c) => {
                const isOpen = expanded.has(c.case_id);
                return (
                <Fragment key={c.case_id}>
                <tr className="hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">
                    <button
                      onClick={() => toggleExpand(c.case_id)}
                      className="inline-flex items-center gap-1 hover:text-gray-700 dark:hover:text-gray-300"
                      title={isOpen ? "Hide output" : "Peek output"}
                    >
                      {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      {c.case_id}
                    </button>
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={c.pass ? "pass" : "fail"} /></td>
                  <td className="px-4 py-3"><ScoreBar score={c.score} /></td>
                  <td className="px-4 py-3 text-xs tabular-nums text-gray-500">
                    {c.latency_ms != null ? `${Math.round(c.latency_ms)}ms` : "—"}
                  </td>
                  <td className="px-4 py-3 text-xs tabular-nums text-gray-500">
                    {c.cost_usd != null ? `$${c.cost_usd.toFixed(4)}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/runs/${runId}/cases/${c.case_id}?suite_id=${suiteId ?? ""}`}
                      className="text-xs text-purple-600 dark:text-purple-400 hover:underline"
                    >
                      Detail →
                    </Link>
                  </td>
                </tr>
                {isOpen && (
                  <tr className="bg-gray-50/50 dark:bg-gray-900/30">
                    <td colSpan={6} className="px-4 py-3">
                      <DataView
                        value={c.actual}
                        expected={c.expected}
                        defaultMode="table"
                        maxHeight="max-h-72"
                      />
                    </td>
                  </tr>
                )}
                </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
