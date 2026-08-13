import { Link } from "react-router-dom";
import { useSuites, useProject, useServerStatus } from "@/api/hooks";
import { StatCardSkeleton, TableSkeleton } from "@/components/Skeleton";
import type { Suite } from "@/api/types";
import { FlaskConical, Play, CheckCircle2, DollarSign, WifiOff } from "lucide-react";
import { useActiveProject } from "@/context/ProjectContext";

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 text-xs mb-1">
        <Icon size={13} />
        {label}
      </div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}

export function Dashboard() {
  const { activeProjectId } = useActiveProject();
  const isLocal = activeProjectId === "local";

  const localSuites = useSuites();
  const remoteProject = useProject(isLocal ? "" : activeProjectId);
  const { data: status } = useServerStatus();

  const suitesLoading = isLocal ? localSuites.isLoading : remoteProject.isLoading;
  const suitesError   = isLocal ? localSuites.error     : remoteProject.error;
  const suites: Suite[] = isLocal
    ? (localSuites.data ?? [])
    : (remoteProject.data?.suites ?? []);
  const isStale = !isLocal && remoteProject.data?.stale;

  const totalSuites = suites.length;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        {status && (
          <span className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" />
            Server online {status.version ? `· v${status.version}` : ""}
          </span>
        )}
      </div>

      {/* Stale cache banner */}
      {isStale && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 dark:border-amber-800
          bg-amber-50 dark:bg-amber-950 px-4 py-2.5 text-sm text-amber-700 dark:text-amber-300">
          <WifiOff size={14} className="shrink-0" />
          <span>
            Remote is offline — showing cached data from{" "}
            {remoteProject.data?.cached_at
              ? new Date(remoteProject.data.cached_at * 1000).toLocaleString()
              : "a previous sync"}
            . Run <strong>Sync</strong> from the project switcher when remote is back online.
          </span>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {suitesLoading ? (
          Array.from({ length: 4 }).map((_, i) => <StatCardSkeleton key={i} />)
        ) : (
          <>
            <StatCard icon={FlaskConical} label="Suites" value={totalSuites} />
            <StatCard icon={Play} label="Runs this week" value="—" sub="API not wired" />
            <StatCard icon={CheckCircle2} label="Pass rate" value="—" sub="run suite first" />
            <StatCard icon={DollarSign} label="Weekly cost" value="—" sub="run suite first" />
          </>
        )}
      </div>

      {/* Suite list */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium text-sm text-gray-700 dark:text-gray-300">Suites</h2>
          <Link
            to="/suites"
            className="text-xs text-purple-600 dark:text-purple-400 hover:underline"
          >
            View all →
          </Link>
        </div>

        {suitesLoading && <TableSkeleton rows={4} />}
        {suitesError && (
          <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 p-4 text-sm text-red-700 dark:text-red-300">
            Failed to load suites: {(suitesError as Error).message}
          </div>
        )}
        {suites && suites.length === 0 && (
          <div className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 p-8 text-center text-sm text-gray-400">
            No suites yet. Suites are created programmatically via
            <code className="mx-1 px-1 rounded bg-gray-100 dark:bg-gray-800">EvalCaseTemplate</code>.
          </div>
        )}
        {suites && suites.length > 0 && (
          <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Suite ID</th>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Title</th>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Tags</th>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Cases</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {suites.map((s: Suite) => (
                  <tr key={s.suite_id} className="hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-gray-600 dark:text-gray-400">{s.suite_id}</td>
                    <td className="px-4 py-3 font-medium">{s.title ?? s.suite_id}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(s.tags ?? []).map((t: string) => (
                          <span key={t} className="rounded px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 text-xs">
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-500 tabular-nums">{s.case_count ?? "—"}</td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        to={`/suites/${s.suite_id}`}
                        className="text-xs text-purple-600 dark:text-purple-400 hover:underline"
                      >
                        Open →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
