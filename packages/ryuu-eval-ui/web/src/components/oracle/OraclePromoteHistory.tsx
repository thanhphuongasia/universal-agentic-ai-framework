/**
 * OraclePromoteHistory — Tab 4 promote history + detail.
 *
 * Every "Promote to suite" snapshots the promoted case (target suite, case_id,
 * written path, the exact cells written, audit metadata, ts) into per-fixture
 * history (ICollectionStore, JSONL by default). This panel lists those promotes
 * newest-first and opens a detail view of any one — so you can see exactly what
 * landed in the suite and when, without diffing YAML by hand.
 */
import { useState, type FC } from "react";
import { useOraclePromotes, type OraclePromoteRecord } from "@/api/hooks";

const fmtTs = (ts: string) => (ts || "").replace("T", " ").replace("Z", " UTC");

const DetailModal: FC<{ rec: OraclePromoteRecord; onClose: () => void }> = ({ rec, onClose }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
    <div
      className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 shadow-xl flex flex-col max-h-[85vh] w-[min(760px,95vw)]"
      onClick={e => e.stopPropagation()}
    >
      <div className="px-4 py-2.5 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between shrink-0">
        <span className="text-sm font-semibold text-gray-700 dark:text-gray-200">
          Promote · {fmtTs(rec.ts)} → {rec.target_suite_id}
        </span>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
      </div>
      <div className="overflow-auto p-4 space-y-3">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
          <div><span className="text-gray-400">case_id:</span> <span className="font-mono text-gray-700 dark:text-gray-300">{rec.case_id}</span></div>
          <div><span className="text-gray-400">cells:</span> <span className="font-mono">{rec.cells_count}</span> · verdict {rec.verdict}{rec.overwrite ? " · overwrote" : ""}</div>
          <div className="col-span-2"><span className="text-gray-400">path:</span> <span className="font-mono text-gray-600 dark:text-gray-400 break-all">{rec.written_path}</span></div>
          {Object.entries(rec.metadata || {}).map(([k, v]) => (
            <div key={k} className="col-span-2"><span className="text-gray-400">{k}:</span> <span className="font-mono text-gray-600 dark:text-gray-400 break-all">{String(v)}</span></div>
          ))}
        </div>
        <div>
          <div className="text-[10px] uppercase font-semibold text-gray-500 mb-1">promoted cells ({rec.cells.length})</div>
          <div className="overflow-auto rounded border border-gray-200 dark:border-gray-700">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800 text-left text-gray-500 dark:text-gray-400">
                  {["Entity", "Column", "OP"].map(h => (
                    <th key={h} className="px-3 py-1.5 font-semibold border-b border-gray-200 dark:border-gray-700">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rec.cells.length === 0 ? (
                  <tr><td colSpan={3} className="px-3 py-2 text-gray-400">(empty — no cells written)</td></tr>
                ) : rec.cells.map((c, i) => (
                  <tr key={`${c.entity}.${c.column}.${i}`} className="border-b border-gray-100 dark:border-gray-800">
                    <td className="px-3 py-1.5 font-mono text-gray-700 dark:text-gray-300">{c.entity}</td>
                    <td className="px-3 py-1.5 font-mono text-gray-500 dark:text-gray-400">{c.column}</td>
                    <td className="px-3 py-1.5 font-mono font-semibold">{c.op}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
);

export const OraclePromoteHistory: FC<{ fixtureId: string }> = ({ fixtureId }) => {
  const { data, isLoading } = useOraclePromotes(fixtureId);
  const promotes = data?.promotes ?? [];
  const [detail, setDetail] = useState<OraclePromoteRecord | null>(null);

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
        <span className="text-[10px] uppercase font-semibold tracking-wider text-gray-500 dark:text-gray-400">
          Promote history
        </span>
        <span className="text-[10px] text-gray-400">{promotes.length}</span>
      </div>

      {isLoading ? (
        <div className="p-3 text-xs text-gray-400">Loading…</div>
      ) : promotes.length === 0 ? (
        <div className="p-3 text-xs text-gray-400">Not promoted yet.</div>
      ) : (
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {promotes.map(p => (
            <div key={p.promote_id} className="flex items-center gap-2 px-3 py-2 text-xs">
              <span className="font-mono text-gray-500 dark:text-gray-400 shrink-0">{fmtTs(p.ts)}</span>
              <span className="text-gray-400 shrink-0">→</span>
              <span className="font-mono text-gray-700 dark:text-gray-300 truncate">{p.target_suite_id}/{p.case_id}</span>
              <span className={`shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded border ${p.cells_count > 0 ? "text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800" : "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800"}`}>
                {p.cells_count} cells
              </span>
              {p.overwrite && <span className="shrink-0 text-[10px] text-yellow-600 dark:text-yellow-400" title="overwrote an existing case">overwrote</span>}
              <button
                onClick={() => setDetail(p)}
                className="shrink-0 ml-auto text-[11px] px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600 text-gray-500 hover:text-indigo-600 hover:border-indigo-300"
              >
                detail
              </button>
            </div>
          ))}
        </div>
      )}

      {detail && <DetailModal rec={detail} onClose={() => setDetail(null)} />}
    </div>
  );
};
