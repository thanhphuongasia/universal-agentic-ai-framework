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
  const [expanded, setExpanded] = useState<string | null>(null);
  // editing: id of the version row being edited inline
  const [editing, setEditing] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ model: "", system: "" });

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

  function startEdit(v: { id: string; version: string; config: { model: string; prompts?: { system?: { system?: string } } } }, fork: boolean) {
    const sys = v.config?.prompts?.system?.system ?? "";
    if (fork) {
      // pre-fill create-new form
      setForm({ version: "", model: v.config.model, system: sys });
      setCreating(true);
    } else {
      setEditForm({ model: v.config.model, system: sys });
      setEditing(v.id);
      setExpanded(v.id);
    }
  }

  function submitEdit(v: { id: string; version: string }) {
    save.mutate(
      {
        version: v.version,
        config: {
          version: v.version,
          description: "",
          model: editForm.model,
          temperature: 0.0,
          max_tokens: 2048,
          prompts: { system: { system: editForm.system, user: "{query}" } },
          tools: [],
        },
      },
      { onSuccess: () => setEditing(null) },
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
            const isExpanded = expanded === v.id;
            const isEditingThis = editing === v.id;
            const systemPrompt = v.config?.prompts?.system?.system ?? "";
            return (
              <li
                key={v.id}
                className="rounded-md border border-gray-100 dark:border-gray-800 overflow-hidden"
              >
                {/* Row header — click to expand */}
                <div
                  className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50 select-none"
                  onClick={() => { setExpanded(isExpanded ? null : v.id); setEditing(null); }}
                >
                  <span className="text-xs text-gray-400">{isExpanded ? "▲" : "▼"}</span>
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

                  <div className="ml-auto flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                    {/* Edit (draft) or Fork (staging/live) */}
                    {v.status === "draft" ? (
                      <button
                        disabled={busy}
                        onClick={() => startEdit(v, false)}
                        className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                      >
                        ✏ Edit
                      </button>
                    ) : (
                      <button
                        disabled={busy}
                        onClick={() => startEdit(v, true)}
                        className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                        title="Copy into a new draft"
                      >
                        ⎘ Fork
                      </button>
                    )}
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
                </div>

                {/* Expanded: view or inline edit */}
                {isExpanded && (
                  <div className="border-t border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 px-3 py-3 space-y-2">
                    {isEditingThis ? (
                      <>
                        <input
                          value={editForm.model}
                          onChange={(e) => setEditForm({ ...editForm, model: e.target.value })}
                          className="w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs font-mono"
                          placeholder="model"
                        />
                        <textarea
                          value={editForm.system}
                          onChange={(e) => setEditForm({ ...editForm, system: e.target.value })}
                          rows={6}
                          className="w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-xs font-mono resize-y"
                        />
                        <div className="flex gap-2">
                          <button
                            disabled={busy}
                            onClick={() => submitEdit(v)}
                            className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                          >
                            {busy ? "Saving…" : "Save"}
                          </button>
                          <button
                            onClick={() => setEditing(null)}
                            className="text-xs px-3 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800"
                          >
                            Cancel
                          </button>
                        </div>
                      </>
                    ) : (
                      systemPrompt ? (
                        <pre className="text-xs font-mono text-gray-600 dark:text-gray-300 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                          {systemPrompt}
                        </pre>
                      ) : (
                        <span className="text-xs text-gray-400 italic">No system prompt content.</span>
                      )
                    )}
                  </div>
                )}
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
