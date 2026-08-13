export function ScoreBar({ score }: { score: number | null }) {
  if (score === null) return <span className="text-gray-400 text-sm">—</span>;
  const pct = Math.round(score * 100);
  const color =
    pct >= 90 ? "bg-green-500" : pct >= 70 ? "bg-yellow-400" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-600 dark:text-gray-400">
        {(score).toFixed(2)}
      </span>
    </div>
  );
}
