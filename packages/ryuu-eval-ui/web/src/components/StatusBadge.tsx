import type { RunStatus, CaseStatus } from "@/api/types";

type Status = RunStatus | CaseStatus;

const cfg: Record<string, { label: string; cls: string }> = {
  pass:      { label: "Pass",      cls: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200" },
  done:      { label: "Done",      cls: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200" },
  fail:      { label: "Fail",      cls: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200" },
  error:     { label: "Error",     cls: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200" },
  running:   { label: "Running",   cls: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200" },
  queued:    { label: "Queued",    cls: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300" },
  pending:   { label: "Pending",   cls: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300" },
  cancelled: { label: "Cancelled", cls: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200" },
};

export function StatusBadge({ status }: { status: Status }) {
  const { label, cls } = cfg[status] ?? { label: status, cls: "bg-gray-100 text-gray-600" };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status === "running" && (
        <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {label}
    </span>
  );
}
