import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, RefreshCw, WifiOff, Globe, HardDrive, Loader2 } from "lucide-react";
import { useProjects, useSyncProject } from "@/api/hooks";
import { useActiveProject } from "@/context/ProjectContext";
import type { Project } from "@/api/types";

export function ProjectSwitcher() {
  const { data: projects, isLoading } = useProjects();
  const { activeProjectId, setActiveProjectId } = useActiveProject();
  const [open, setOpen] = useState(false);
  const sync = useSyncProject();
  const navigate = useNavigate();

  const active = projects?.find((p) => p.project_id === activeProjectId);
  const label = active?.title ?? activeProjectId;
  const isRemote = active?.remote ?? false;
  const isStale = active?.stale ?? false;

  function handleSelect(p: Project) {
    setActiveProjectId(p.project_id);
    setOpen(false);
    navigate("/suites");
  }

  function handleSync(e: React.MouseEvent, projectId: string) {
    e.stopPropagation();
    sync.mutate({ projectId });
  }

  return (
    <div className="relative px-2 pb-2">
      {/* Trigger */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-left
          bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700
          border border-gray-200 dark:border-gray-700 transition-colors"
      >
        {isRemote ? (
          <Globe size={11} className="shrink-0 text-blue-500" />
        ) : (
          <HardDrive size={11} className="shrink-0 text-gray-400" />
        )}
        <span className="flex-1 truncate font-medium text-gray-700 dark:text-gray-200">
          {isLoading ? "Loading…" : label}
        </span>
        {isStale && (
          <WifiOff size={10} className="shrink-0 text-amber-500" aria-label="Cached — remote offline" />
        )}
        <ChevronDown size={11} className="shrink-0 text-gray-400" />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute left-2 right-2 top-full mt-1 z-50 rounded-lg border
          border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg
          overflow-hidden text-xs">
          {(projects ?? []).map((p) => (
            <div
              key={p.project_id}
              onClick={() => handleSelect(p)}
              className={`flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors
                ${p.project_id === activeProjectId
                  ? "bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                  : "hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300"
                }`}
            >
              {p.remote ? (
                <Globe size={11} className="shrink-0 text-blue-500" />
              ) : (
                <HardDrive size={11} className="shrink-0 text-gray-400" />
              )}
              <span className="flex-1 truncate">{p.title}</span>

              {/* Suite count badge */}
              {p.suite_count != null && (
                <span className="text-gray-400 tabular-nums">{p.suite_count}</span>
              )}

              {/* Stale indicator */}
              {p.remote && p.cached_at && (
                <WifiOff size={10} className="shrink-0 text-amber-400" aria-label="Using cached data" />
              )}

              {/* Sync button — remote only */}
              {p.remote && (
                <button
                  onClick={(e) => handleSync(e, p.project_id)}
                  disabled={sync.isPending}
                  aria-label="Sync cases from remote"
                  className="ml-1 p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700
                    text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-40"
                >
                  {sync.isPending && sync.variables?.projectId === p.project_id ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <RefreshCw size={11} />
                  )}
                </button>
              )}
            </div>
          ))}

          {/* Sync result feedback */}
          {sync.isSuccess && (
            <div className="px-3 py-1.5 bg-green-50 dark:bg-green-900/20 text-green-700
              dark:text-green-400 border-t border-gray-100 dark:border-gray-800">
              Synced {sync.data.synced_cases} cases across {sync.data.synced_suites} suites
              {sync.data.skipped_cases > 0 && ` · ${sync.data.skipped_cases} skipped`}
            </div>
          )}
          {sync.isError && (
            <div className="px-3 py-1.5 bg-red-50 dark:bg-red-900/20 text-red-700
              dark:text-red-400 border-t border-gray-100 dark:border-gray-800">
              Sync failed: {sync.error?.message}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
