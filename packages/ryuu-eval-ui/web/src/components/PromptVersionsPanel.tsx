import { useState } from "react";
import {
  usePromptVersions,
  useActivePromptVersion,
  usePromotePromptVersion,
  useSetPromptVersionStatus,
  useSavePromptVersion,
} from "@/api/hooks";
import type { PromptStatus } from "@/api/types";

const STATUS_CLS: Record<PromptStatus, string> = {
  draft: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  staging: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  archived: "bg-gray-200 text-gray-500 dark:bg-gray-700 dark:text-gray-400 line-through",
};

function StatusChip({ status }: { status: PromptStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_CLS[status]}`}>
      {status}
    </span>
  );
}

/** Prompt version lifecycle for a suite: list, status transitions, promote-to-live. */
export function PromptVersionsPanel({ suiteId }: { suiteId: string }) {
  const { data: versions, isLoading } = usePromptVersions(suiteId);
  const { data: active } = useActivePromptVersion(suiteId);
  const promote = usePromotePromptVersion(suiteId);
  const setStatus = useSetPromptVersionStatus(suiteId);
  const save = useSavePromptVersion(suiteId);

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ version: "", model: "claude-sonnet-4-6", system: "" });

  const busy = promote.isPending || setStatus.isPending || save.isPending;

  function submitNew() {
    if (!form.version.trim()) return;
    save.mutate(
      {
        version: form.version.trim(),
        config: {
          version: form.version.trim(),
          description: "",
          model: form.model,
          temperature: 0.0,
          max_tokens: 2048,
          prompts: { system: { system: form.system, user: "{query}" } },
          tools: [],
        },
      },
      { onSuccess: () => { setCreating(false); setForm({ version: "", model: form.model, system: "" }); } },
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Prompt versions</h3>
        <div className="flex items-center gap-3">
          {active && (
            <span className="text-xs text-gray-500">
              live: <span className="font-mono">{active.version}</span>
            </span>
          )}
          <button
            onClick={() => setCreating((v) => !v)}
            className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            {creating ? "Cancel" : "+ New version"}
          </button>
        </div>
      </div>

      {creating && (
        <div className="mb-3 space-y-2 rounded-md border border-gray-100 dark:border-gray-800 p-3">
          <div className="flex gap-2">
            <input
              value={form.version}
              onChange={(e) => setForm({ ...form, version: e.target.value })}
              placeholder="version (e.g. v3)"
              className="flex-1 rounded border border-gray-300 dark:border-gray-600 bg-transparent px-2 py-1 text-sm"
            />
            <input
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder="model"
              className="flex-1 rounded border border-gray-300 dark:border-gray-600 bg-transparent px-2 py-1 text-sm font-mono"
            />
          </div>
          <textarea
            value={form.system}
            onChange={(e) => setForm({ ...form, system: e.target.value })}
            placeholder="system prompt"
            rows={4}
            className="w-full rounded border border-gray-300 dark:border-gray-600 bg-transparent px-2 py-1 text-sm font-mono"
          />
          <button
            disabled={busy || !form.version.trim()}
            onClick={submitNew}
            className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Create draft
          </button>
        </div>
      )}

      {isLoading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : !versions || versions.length === 0 ? (
        <p className="text-xs text-gray-400 italic">
          No prompt versions for this suite. Seed or create one to enable promotion.
        </p>
      ) : (
        <ul className="space-y-2">
          {versions.map((v) => {
            const isLive = active?.version === v.version;
            return (
              <li
                key={v.id}
                className="flex items-center gap-3 rounded-md border border-gray-100 dark:border-gray-800 px-3 py-2"
              >
                <span className="font-mono text-sm text-gray-800 dark:text-gray-100">{v.version}</span>
                <StatusChip status={v.status} />
                {isLive && (
                  <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-800 dark:bg-green-900 dark:text-green-200">
                    LIVE
                  </span>
                )}
                <span className="text-xs text-gray-400 font-mono">{v.config.model}</span>
                {v.promoted_by && (
                  <span className="text-xs text-gray-400">by {v.promoted_by}</span>
                )}

                <div className="ml-auto flex gap-1.5">
                  {v.status === "draft" && (
                    <button
                      disabled={busy}
                      onClick={() => setStatus.mutate({ version: v.version, status: "staging" })}
                      className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                    >
                      → staging
                    </button>
                  )}
                  {v.status !== "archived" && !isLive && (
                    <button
                      disabled={busy}
                      onClick={() => setStatus.mutate({ version: v.version, status: "archived" })}
                      className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                    >
                      archive
                    </button>
                  )}
                  {v.status !== "archived" && !isLive && (
                    <button
                      disabled={busy}
                      onClick={() => promote.mutate({ version: v.version })}
                      className="text-xs px-2 py-1 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                    >
                      Promote
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {(promote.error || setStatus.error) && (
        <p className="mt-2 text-xs text-red-600">
          {(promote.error || setStatus.error)?.message}
        </p>
      )}
    </div>
  );
}
