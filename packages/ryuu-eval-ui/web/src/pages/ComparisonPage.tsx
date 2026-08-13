import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import ReactDiffViewer from "react-diff-viewer-continued";
import { useLastRun } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import type { RunSummary } from "@/api/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | undefined | null, decimals = 3, prefix = "") {
  if (n == null) return "—";
  return `${prefix}${n.toFixed(decimals)}`;
}

function delta(a: number | undefined | null, b: number | undefined | null) {
  if (a == null || b == null) return null;
  return b - a;
}

function DeltaBadge({ d, invert = false }: { d: number | null; invert?: boolean }) {
  if (d === null) return <span className="text-gray-400">—</span>;
  const isPositive = invert ? d < 0 : d > 0;
  const isNeg = invert ? d > 0 : d < 0;
  const cls = d === 0
    ? "text-gray-400"
    : isPositive
    ? "text-green-600 dark:text-green-400"
    : isNeg
    ? "text-red-600 dark:text-red-400"
    : "text-gray-400";
  const sign = d > 0 ? "+" : "";
  return <span className={`text-xs tabular-nums font-medium ${cls}`}>{sign}{d.toFixed(3)}</span>;
}

// ── Summary Table ─────────────────────────────────────────────────────────────

function SummaryTable({ a, b }: { a: RunSummary; b: RunSummary }) {
  const passRateA = a.total_cases > 0 ? a.passed_cases / a.total_cases : null;
  const passRateB = b.total_cases > 0 ? b.passed_cases / b.total_cases : null;

  const rows = [
    {
      label: "Pass rate",
      valA: passRateA != null ? `${(passRateA * 100).toFixed(1)}%` : "—",
      valB: passRateB != null ? `${(passRateB * 100).toFixed(1)}%` : "—",
      d: delta(passRateA, passRateB),
    },
    {
      label: "Avg score",
      valA: fmt(a.avg_score, 3),
      valB: fmt(b.avg_score, 3),
      d: delta(a.avg_score, b.avg_score),
    },
    {
      label: "Cost (USD)",
      valA: fmt(a.total_cost_usd, 4, "$"),
      valB: fmt(b.total_cost_usd, 4, "$"),
      d: delta(a.total_cost_usd, b.total_cost_usd),
      invert: true,
    },
    {
      label: "Avg latency (ms)",
      valA: fmt(a.avg_latency_ms, 0),
      valB: fmt(b.avg_latency_ms, 0),
      d: delta(a.avg_latency_ms, b.avg_latency_ms),
      invert: true,
    },
  ];

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 dark:bg-gray-900">
          <tr>
            <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs w-40">Metric</th>
            <th className="px-4 py-2.5 text-right font-medium text-gray-500 dark:text-gray-400 text-xs">Suite A</th>
            <th className="px-4 py-2.5 text-right font-medium text-gray-500 dark:text-gray-400 text-xs">Suite B</th>
            <th className="px-4 py-2.5 text-right font-medium text-gray-500 dark:text-gray-400 text-xs">Δ (B − A)</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
          {rows.map((r) => (
            <tr key={r.label}>
              <td className="px-4 py-3 font-medium text-gray-700 dark:text-gray-300 text-xs">{r.label}</td>
              <td className="px-4 py-3 text-right tabular-nums text-xs">{r.valA}</td>
              <td className="px-4 py-3 text-right tabular-nums text-xs">{r.valB}</td>
              <td className="px-4 py-3 text-right">
                <DeltaBadge d={r.d} invert={r.invert} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Comparison results (needs both runs loaded) ───────────────────────────────

function ComparisonResults({
  suiteIdA,
  suiteIdB,
}: {
  suiteIdA: string;
  suiteIdB: string;
}) {
  const { data: runA, isLoading: loadingA, error: errA } = useLastRun(suiteIdA);
  const { data: runB, isLoading: loadingB, error: errB } = useLastRun(suiteIdB);

  if (loadingA || loadingB) {
    return (
      <div className="p-8 text-center text-sm text-gray-400 animate-pulse">
        Loading runs…
      </div>
    );
  }

  if (errA || errB) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 p-4 text-sm text-red-700 dark:text-red-400">
        {errA ? `Suite A error: ${(errA as Error).message}` : ""}
        {errB ? ` Suite B error: ${(errB as Error).message}` : ""}
      </div>
    );
  }

  if (!runA || !runB) return null;

  const promptA = runA.prompt_version ?? "";
  const promptB = runB.prompt_version ?? "";
  const promptsDiffer = promptA !== promptB && (promptA || promptB);

  return (
    <div className="space-y-6">
      {/* Run header */}
      <div className="grid grid-cols-2 gap-4">
        {[{ label: "Suite A", run: runA }, { label: "Suite B", run: runB }].map(({ label, run }) => (
          <div
            key={label}
            className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 space-y-1"
          >
            <div className="text-xs text-gray-400 font-medium">{label}</div>
            <div className="font-mono text-xs text-gray-500">{run.suite_id}</div>
            <div className="flex items-center gap-2 mt-1">
              <StatusBadge status={run.status} />
              {run.model && (
                <span className="text-xs font-mono text-gray-500">{run.model}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Summary metrics */}
      <div>
        <h2 className="font-medium text-sm text-gray-700 dark:text-gray-300 mb-3">Summary</h2>
        <SummaryTable a={runA} b={runB} />
      </div>

      {/* Prompt diff */}
      {promptsDiffer && (
        <div>
          <h2 className="font-medium text-sm text-gray-700 dark:text-gray-300 mb-3">
            Prompt diff{" "}
            <span className="font-normal text-gray-400">
              (prompt_version: {promptA || "(none)"} → {promptB || "(none)"})
            </span>
          </h2>
          <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden text-xs">
            <ReactDiffViewer
              oldValue={promptA}
              newValue={promptB}
              splitView={false}
              hideLineNumbers={false}
            />
          </div>
        </div>
      )}

      {/* Note: per-case diff requires full RunResult with cases array.
          last_run only returns RunSummary (no cases). Showing a notice instead. */}
      <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-4 text-sm text-amber-700 dark:text-amber-400">
        Per-case diff requires the full run result (
        <code className="font-mono text-xs">GET /runs/{"{run_id}"}</code>
        ). The <code className="font-mono text-xs">/suites/{"{id}"}/last_run</code> endpoint returns
        only the summary. Navigate to each Run Results page to see per-case breakdown.
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function ComparisonPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [inputA, setInputA] = useState(searchParams.get("a") ?? "");
  const [inputB, setInputB] = useState(searchParams.get("b") ?? "");

  const activeA = searchParams.get("a") ?? "";
  const activeB = searchParams.get("b") ?? "";

  function handleCompare() {
    const trimA = inputA.trim();
    const trimB = inputB.trim();
    if (!trimA || !trimB) return;
    setSearchParams({ a: trimA, b: trimB });
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold">Run Comparison</h1>

      {/* Suite ID inputs */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Suite A (suite_id)
            </label>
            <input
              value={inputA}
              onChange={(e) => setInputA(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCompare()}
              placeholder="e.g. my-suite-v1"
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Suite B (suite_id)
            </label>
            <input
              value={inputB}
              onChange={(e) => setInputB(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCompare()}
              placeholder="e.g. my-suite-v2"
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleCompare}
            disabled={!inputA.trim() || !inputB.trim()}
            className="rounded-md px-4 py-2 text-sm bg-purple-600 hover:bg-purple-700 text-white font-medium disabled:opacity-50"
          >
            Compare
          </button>
        </div>
      </div>

      {activeA && activeB && (
        <ComparisonResults suiteIdA={activeA} suiteIdB={activeB} />
      )}
    </div>
  );
}
