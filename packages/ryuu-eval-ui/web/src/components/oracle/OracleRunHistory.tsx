/**
 * OracleRunHistory — Tab 3 run history for trace + compare.
 *
 * Every "Execute" (run-with-prompt) call that carries a fixture_id is appended
 * to history server-side (ICollectionStore, JSONL by default). This panel lists
 * past runs newest-first, lets you open a run's raw trace, and diff any two runs'
 * produced cells side-by-side.
 */
import { useMemo, useState, type FC } from "react";
import ReactDiffViewer from "react-diff-viewer-continued";
import { useOracleRuns, type OracleRunRecord } from "@/api/hooks";

const fmtTs = (ts: string) => (ts || "").replace("T", " ").replace("Z", " UTC");
const cellsJson = (r: OracleRunRecord) => JSON.stringify(r.cells ?? {}, null, 2);

const Modal: FC<{ title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }> = ({
  title, onClose, children, wide,
}) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
    <div
      className={`bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 shadow-xl flex flex-col max-h-[85vh] ${wide ? "w-[min(1100px,95vw)]" : "w-[min(720px,95vw)]"}`}
      onClick={e => e.stopPropagation()}
    >
      <div className="px-4 py-2.5 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between shrink-0">
        <span className="text-sm font-semibold text-gray-700 dark:text-gray-200">{title}</span>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
      </div>
      <div className="overflow-auto p-4">{children}</div>
    </div>
  </div>
);

export const OracleRunHistory: FC<{ fixtureId: string }> = ({ fixtureId }) => {
  const { data, isLoading } = useOracleRuns(fixtureId);
  const runs = useMemo(() => data?.runs ?? [], [data]);
  const [selected, setSelected] = useState<string[]>([]);
  const [traceRun, setTraceRun] = useState<OracleRunRecord | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);

  const toggle = (id: string) =>
    setSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : prev.length >= 2 ? [prev[1], id] : [...prev, id],
    );

  const pair = useMemo(
    () => selected.map(id => runs.find(r => r.run_id === id)).filter(Boolean) as OracleRunRecord[],
    [selected, runs],
  );

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
        <span className="text-[10px] uppercase font-semibold tracking-wider text-gray-500 dark:text-gray-400">
          Run history
        </span>
        <span className="text-[10px] text-gray-400">{runs.length} runs</span>
        {selected.length === 2 && (
          <button
            onClick={() => setCompareOpen(true)}
            className="ml-auto text-[11px] px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-semibold"
          >
            ⇄ Compare selected
          </button>
        )}
        {selected.length === 1 && (
          <span className="ml-auto text-[10px] text-gray-400">select one more to compare</span>
        )}
      </div>

      {isLoading ? (
        <div className="p-3 text-xs text-gray-400">Loading history…</div>
      ) : runs.length === 0 ? (
        <div className="p-3 text-xs text-gray-400">No runs yet — click Run above to record one.</div>
      ) : (
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {runs.map(r => {
            const sel = selected.includes(r.run_id);
            return (
              <div
                key={r.run_id}
                className={`flex items-center gap-2 px-3 py-2 text-xs ${sel ? "bg-indigo-50/50 dark:bg-indigo-950/20" : ""}`}
              >
                <input type="checkbox" checked={sel} onChange={() => toggle(r.run_id)} className="shrink-0" />
                <span className="font-mono text-gray-500 dark:text-gray-400 shrink-0">{fmtTs(r.ts)}</span>
                <span className="font-mono text-gray-700 dark:text-gray-300 shrink-0">{r.model}</span>
                <span className={`shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded border ${r.cells_count > 0 ? "text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800" : "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800"}`}>
                  {r.cells_count} cells
                </span>
                {r.parse_error && <span className="shrink-0 text-[10px] text-red-500" title={r.parse_error}>⚠ parse</span>}
                {r.schema_skipped && <span className="shrink-0 text-[10px] text-gray-400" title={r.schema_skipped}>schema-skipped</span>}
                <span className="text-gray-400 shrink-0 ml-auto">${(r.cost_usd ?? 0).toFixed(4)}</span>
                <span className="text-gray-400 shrink-0 tabular-nums">{Math.round(r.latency_ms ?? 0)}ms</span>
                <button
                  onClick={() => setTraceRun(r)}
                  className="shrink-0 text-[11px] px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600 text-gray-500 hover:text-indigo-600 hover:border-indigo-300"
                >
                  trace
                </button>
              </div>
            );
          })}
        </div>
      )}

      {traceRun && (
        <Modal title={`Run trace · ${fmtTs(traceRun.ts)} · ${traceRun.model}`} onClose={() => setTraceRun(null)}>
          <div className="space-y-3">
            <div className="text-[11px] text-gray-500 dark:text-gray-400">
              {traceRun.input_tokens}/{traceRun.output_tokens} tok · ${(traceRun.cost_usd ?? 0).toFixed(4)} · {Math.round(traceRun.latency_ms ?? 0)}ms
              {traceRun.schema_skipped && <> · <span className="italic">{traceRun.schema_skipped}</span></>}
            </div>
            <div>
              <div className="text-[10px] uppercase font-semibold text-gray-500 mb-1">parsed cells</div>
              <pre className="text-xs font-mono bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded p-2 overflow-auto max-h-60 whitespace-pre-wrap break-all">{cellsJson(traceRun)}</pre>
            </div>
            <div>
              <div className="text-[10px] uppercase font-semibold text-gray-500 mb-1">raw response</div>
              <pre className="text-xs font-mono bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-700 rounded p-2 overflow-auto max-h-60 whitespace-pre-wrap break-all">{traceRun.raw_response || "(empty)"}</pre>
            </div>
          </div>
        </Modal>
      )}

      {compareOpen && pair.length === 2 && (
        <Modal title="Compare runs — produced cells" onClose={() => setCompareOpen(false)} wide>
          <div className="flex items-center justify-between text-[11px] text-gray-500 dark:text-gray-400 mb-2 gap-4">
            <span>◀ {fmtTs(pair[0].ts)} · {pair[0].model} · {pair[0].cells_count} cells</span>
            <span>{fmtTs(pair[1].ts)} · {pair[1].model} · {pair[1].cells_count} cells ▶</span>
          </div>
          <div className="text-xs">
            <ReactDiffViewer
              oldValue={cellsJson(pair[0])}
              newValue={cellsJson(pair[1])}
              splitView
              useDarkTheme={document.documentElement.classList.contains("dark")}
            />
          </div>
        </Modal>
      )}
    </div>
  );
};
