import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useSuites, useSuite, useCases, useLastRun, useRunHistory, useRefineHistory, useStartRun, useTemplates, useCreateCase, useUpdateCase, useDeleteCase, useProject, useSaveDefaultPrompt, usePromptVersions } from "@/api/hooks";
import { PromptVersionsPanel } from "@/components/PromptVersionsPanel";
import { useActiveProject } from "@/context/ProjectContext";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import { TableSkeleton } from "@/components/Skeleton";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Play, X, FlaskConical, Plus, Pencil, Trash2, ExternalLink, BarChart2, ShieldCheck } from "lucide-react";
import { CallSequenceDiagram } from "@/components/CallSequenceDiagram";
import type { RunConfig, Suite, Case, Template, RunHistoryEntry } from "@/api/types";

// ── Run Config Form ───────────────────────────────────────────────────────────

const COMMON_MODELS = [
  "gpt-4o-mini", "gpt-4o", "gpt-4-turbo",
  "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5",
  "gemini-1.5-flash", "gemini-1.5-pro",
];

const schema = z.object({
  prompt: z.string().optional(),
  temperature: z.number().min(0).max(2).optional(),
  max_tokens: z.number().int().min(64, "max_tokens must be >= 64 (smaller values produce truncated output)").optional(),
  concurrency: z.number().int().min(1).max(16),
  mode: z.enum(["parallel", "sequential"]),
  budget_usd: z.number().min(0).optional(),
  custom_model: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

function RunConfigDialog({
  suiteId,
  defaultPrompt,
  onClose,
}: {
  suiteId: string;
  defaultPrompt?: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const startRun = useStartRun();
  const { data: allCases } = useCases(suiteId);
  const { data: promptVersions } = usePromptVersions(suiteId);
  const [selectedVersion, setSelectedVersion] = useState<string>(""); // "" = default/custom prompt
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const allSelected = !!allCases?.length && selectedIds.size === allCases.length;

  function toggleCase(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (allSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(allCases?.map((c) => c.case_id) ?? []));
  }

  function toggleModel(m: string) {
    setSelectedModels((prev) => {
      const next = new Set(prev);
      next.has(m) ? next.delete(m) : next.add(m);
      return next;
    });
  }

  const { register, handleSubmit, watch } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      prompt: defaultPrompt ?? "",
      concurrency: 4,
      mode: "parallel",
      temperature: 0.0,
      custom_model: "",
    },
  });

  const customModel = watch("custom_model") ?? "";

  async function onSubmit(values: FormValues) {
    const models = [...selectedModels];
    if (customModel.trim() && !models.includes(customModel.trim())) {
      models.push(customModel.trim());
    }
    if (models.length === 0) return;

    const config: RunConfig = {
      suite_id: suiteId,
      models,
      // A selected prompt version drives the run (backend resolves its system
      // prompt); otherwise fall back to the typed prompt text.
      prompt_version: selectedVersion || undefined,
      prompt: selectedVersion ? undefined : (values.prompt || undefined),
      temperature: values.temperature,
      max_tokens: values.max_tokens,
      case_ids: selectedIds.size > 0 ? [...selectedIds] : undefined,
      concurrency: values.concurrency,
      mode: values.mode,
      budget_usd: values.budget_usd,
    };

    const result = await startRun.mutateAsync(config);
    if (result.batch_id && result.runs && result.runs.length > 1) {
      navigate(`/batch/${result.batch_id}/monitor?suite_id=${suiteId}`);
    } else {
      const runId = result.run_id ?? result.runs?.[0]?.run_id;
      if (runId) navigate(`/runs/${runId}/monitor?suite_id=${suiteId}`);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-sm">New Run — {suiteId}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-5 space-y-4 max-h-[85vh] overflow-y-auto">
          {/* Model multi-select */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-400">
                Models
                {selectedModels.size > 1 && (
                  <span className="ml-1.5 text-purple-600 dark:text-purple-400 font-normal">
                    — {selectedModels.size} selected, will run in parallel
                  </span>
                )}
              </label>
            </div>
            <div className="rounded-md border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800 max-h-44 overflow-y-auto">
              {COMMON_MODELS.map((m) => (
                <label
                  key={m}
                  className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50"
                >
                  <input
                    type="checkbox"
                    checked={selectedModels.has(m)}
                    onChange={() => toggleModel(m)}
                    className="accent-purple-600 w-3.5 h-3.5 shrink-0"
                  />
                  <span className="text-xs font-mono text-gray-700 dark:text-gray-300">{m}</span>
                </label>
              ))}
            </div>
            <input
              {...register("custom_model")}
              className="mt-1.5 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="or type a custom model (e.g. gpt-4-turbo, gemini-1.5-pro)"
            />
            {selectedModels.size === 0 && !customModel.trim() && (
              <p className="text-xs text-red-500 mt-1">Select at least one model</p>
            )}
          </div>

          {/* Prompt version (optional — overrides the system prompt below) */}
          {promptVersions && promptVersions.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Prompt version
              </label>
              <select
                value={selectedVersion}
                onChange={(e) => setSelectedVersion(e.target.value)}
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value="">— use the prompt below —</option>
                {promptVersions.map((v) => (
                  <option key={v.id} value={v.version}>
                    {v.version} ({v.status}){v.config?.model ? ` · ${v.config.model}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* System Prompt */}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              System Prompt
              {selectedVersion
                ? <span className="ml-1 font-normal text-gray-400">(ignored — using prompt version {selectedVersion})</span>
                : defaultPrompt
                ? <span className="ml-1 font-normal text-purple-500">(pre-filled from last run — edit to change)</span>
                : <span className="ml-1 font-normal text-gray-400">(instructions sent before every case)</span>
              }
            </label>
            <textarea
              {...register("prompt")}
              rows={4}
              disabled={!!selectedVersion}
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
              placeholder="Leave blank for no system prompt"
            />
          </div>

          {/* Temperature + max_tokens */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Temperature</label>
              <input
                type="number" step="0.1" min="0" max="2"
                {...register("temperature", { valueAsNumber: true })}
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Max tokens</label>
              <input
                type="number" min="1"
                {...register("max_tokens", { valueAsNumber: true })}
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
                placeholder="1024"
              />
            </div>
          </div>

          {/* Mode + Concurrency */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Mode</label>
              <select
                {...register("mode")}
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value="parallel">Parallel</option>
                <option value="sequential">Sequential</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Concurrency</label>
              <input
                type="number" min="1" max="16"
                {...register("concurrency", { valueAsNumber: true })}
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
          </div>

          {/* Case selection */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-400">
                Cases to run
                <span className="ml-1 font-normal text-gray-400">
                  {selectedIds.size === 0
                    ? "(all)"
                    : `(${selectedIds.size} of ${allCases?.length ?? "…"} selected)`}
                </span>
              </label>
              {allCases && allCases.length > 0 && (
                <button
                  type="button"
                  onClick={toggleAll}
                  className="text-xs text-purple-600 dark:text-purple-400 hover:underline"
                >
                  {allSelected ? "Deselect all" : "Select all"}
                </button>
              )}
            </div>
            {allCases && allCases.length > 0 ? (
              <div className="rounded-md border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800 max-h-40 overflow-y-auto">
                {allCases.map((c) => (
                  <label
                    key={c.case_id}
                    className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(c.case_id)}
                      onChange={() => toggleCase(c.case_id)}
                      className="accent-purple-600 w-3.5 h-3.5 shrink-0"
                    />
                    <span className="font-mono text-xs text-gray-500 dark:text-gray-400 shrink-0 w-28 truncate">{c.case_id}</span>
                    <span className="text-xs text-gray-700 dark:text-gray-300 truncate">
                      {typeof c.input === "string" ? c.input : JSON.stringify(c.input)}
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400 italic">No cases yet — all suites will run</p>
            )}
          </div>

          {/* Budget cap */}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Budget cap USD <span className="text-gray-400">(auto-cancel if exceeded)</span>
            </label>
            <input
              type="number" min="0" step="0.01"
              {...register("budget_usd", { valueAsNumber: true })}
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="0.50"
            />
          </div>

          {startRun.error && (
            <p className="text-sm text-red-600 dark:text-red-400">
              {(startRun.error as Error).message}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={startRun.isPending || (selectedModels.size === 0 && !customModel.trim())}
              className="rounded-md px-4 py-2 text-sm bg-purple-600 hover:bg-purple-700 text-white font-medium disabled:opacity-60 flex items-center gap-1.5"
            >
              <Play size={13} />
              {startRun.isPending
                ? "Starting…"
                : selectedModels.size > 1
                  ? `Run ×${selectedModels.size} models${selectedIds.size > 0 ? `, ${selectedIds.size} cases` : ""}`
                  : `Run${selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Case Form Modal ───────────────────────────────────────────────────────────

const caseSchema = z.object({
  case_id: z.string().min(1, "Case ID is required"),
  input: z.string().min(1, "Input is required"),
  expected: z.string().optional(),
  tags_raw: z.string().optional(),
});
type CaseFormValues = z.infer<typeof caseSchema>;

function toDisplayString(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

function parseFieldValue(s: string): unknown {
  try { return JSON.parse(s); } catch { return s; }
}

function CaseFormModal({
  suiteId,
  templateId,
  initialCase,
  onClose,
}: {
  suiteId: string;
  templateId: string;
  initialCase?: Case;
  onClose: () => void;
}) {
  const isEdit = !!initialCase;
  const createCase = useCreateCase(suiteId);
  const updateCase = useUpdateCase(suiteId);
  const { data: templates } = useTemplates();
  const template: Template | undefined = templates?.find((t) => t.template_id === templateId);

  const { register, handleSubmit, setValue, formState: { errors } } = useForm<CaseFormValues>({
    resolver: zodResolver(caseSchema),
    defaultValues: {
      case_id: initialCase?.case_id ?? `case-${Date.now()}`,
      input: initialCase ? toDisplayString(initialCase.input) : "",
      expected: initialCase?.expected !== undefined ? toDisplayString(initialCase.expected) : "",
      tags_raw: initialCase?.tags?.join(", ") ?? "",
    },
  });

  function fillExample(ex: { input: unknown; expected?: unknown }) {
    setValue("input", toDisplayString(ex.input));
    setValue("expected", ex.expected !== undefined ? toDisplayString(ex.expected) : "");
  }

  async function onSubmit(values: CaseFormValues) {
    const tags = values.tags_raw?.split(",").map((t) => t.trim()).filter(Boolean) ?? [];
    const payload: Record<string, unknown> = {
      case_id: values.case_id,
      input: parseFieldValue(values.input),
      expected: values.expected ? parseFieldValue(values.expected) : null,
      metadata: tags.length ? { tags } : {},
    };
    if (isEdit) {
      await updateCase.mutateAsync({ caseId: values.case_id, payload });
    } else {
      await createCase.mutateAsync({ templateId, payload });
    }
    onClose();
  }

  const isPending = createCase.isPending || updateCase.isPending;
  const submitError = createCase.error || updateCase.error;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-sm">{isEdit ? "Edit Case" : "Add Case"} — {suiteId}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={16} /></button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-5 space-y-4 max-h-[80vh] overflow-y-auto">
          {/* Load from example */}
          {!isEdit && template?.examples && template.examples.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Load example</label>
              <select
                defaultValue=""
                onChange={(e) => { const i = parseInt(e.target.value); if (!isNaN(i)) fillExample(template.examples![i]); }}
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value="" disabled>— pick an example to prefill —</option>
                {template.examples.map((ex, i) => (
                  <option key={i} value={i}>{toDisplayString(ex.input).slice(0, 70)}</option>
                ))}
              </select>
            </div>
          )}

          {/* Case ID */}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Case ID</label>
            <input
              {...register("case_id")}
              disabled={isEdit}
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
            />
            {errors.case_id && <p className="text-xs text-red-500 mt-1">{errors.case_id.message}</p>}
          </div>

          {/* Input */}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Input
              {template?.input_schema?.description ? (
                <span className="ml-1 font-normal text-gray-400">— {String(template.input_schema.description)}</span>
              ) : null}
            </label>
            <textarea
              {...register("input")}
              rows={4}
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
            {errors.input && <p className="text-xs text-red-500 mt-1">{errors.input.message}</p>}
          </div>

          {/* Expected */}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Expected <span className="text-gray-400">(optional)</span>
              {template?.expected_schema?.description ? (
                <span className="ml-1 font-normal text-gray-400">— {String(template.expected_schema.description)}</span>
              ) : null}
            </label>
            <textarea
              {...register("expected")}
              rows={2}
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>

          {/* Tags */}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Tags <span className="text-gray-400">(comma-separated)</span>
            </label>
            <input
              {...register("tags_raw")}
              placeholder="smoke, regression, edge_case"
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>

          {submitError && <p className="text-sm text-red-600 dark:text-red-400">{(submitError as Error).message}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800">
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="rounded-md px-4 py-2 text-sm bg-purple-600 hover:bg-purple-700 text-white font-medium disabled:opacity-60 flex items-center gap-1.5"
            >
              {isEdit ? <Pencil size={13} /> : <Plus size={13} />}
              {isPending ? "Saving…" : isEdit ? "Save" : "Add Case"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Case preview helpers ──────────────────────────────────────────────────────

const OP_STYLE: Record<string, string> = {
  C: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300",
  R: "bg-blue-100  dark:bg-blue-900/40  text-blue-700  dark:text-blue-300",
  U: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300",
  D: "bg-red-100   dark:bg-red-900/40   text-red-700   dark:text-red-300",
};

function CaseInputPreview({ input }: { input: unknown }) {
  if (input === null || input === undefined) return <span className="text-xs text-gray-400">—</span>;
  if (typeof input === "string") {
    return <pre className="text-xs bg-gray-950 text-green-300 rounded-lg p-3 overflow-auto max-h-64 font-mono whitespace-pre-wrap break-words">{input}</pre>;
  }
  const obj = input as Record<string, unknown>;
  const snippets = obj.java_snippets as Array<{ filename: string; source: string }> | undefined;
  const route = obj.route as Record<string, string> | undefined;
  const title = obj.title as string | undefined;
  const callSubgraph = obj.call_subgraph as Record<string, Array<{ from_class: string; to_class: string; to_method: string }>> | undefined;
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (!["java_snippets", "route", "title", "template_id", "call_subgraph", "entities"].includes(k)) rest[k] = v;
  }
  return (
    <div className="space-y-3">
      {title && <p className="text-sm font-medium text-gray-700 dark:text-gray-200">{title}</p>}
      {route && (
        <div className="flex items-center gap-2">
          <span className="rounded px-2 py-0.5 bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 text-xs font-mono font-bold">{route.http_method}</span>
          <span className="text-xs font-mono text-gray-600 dark:text-gray-300">{route.endpoint}</span>
        </div>
      )}
      {snippets?.map((s) => (
        <div key={s.filename} className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 dark:bg-gray-950">
            <BarChart2 size={11} className="text-gray-400" />
            <span className="text-xs font-mono text-gray-300">{s.filename}</span>
          </div>
          <pre className="text-xs bg-gray-900 text-green-300 p-3 overflow-auto max-h-64 font-mono whitespace-pre leading-relaxed">{s.source}</pre>
        </div>
      ))}
      {callSubgraph && (
        <div>
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-1.5">Call sequence</div>
          <CallSequenceDiagram subgraph={callSubgraph} />
        </div>
      )}
      {Object.keys(rest).length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 select-none">More fields…</summary>
          <pre className="mt-1.5 bg-gray-50 dark:bg-gray-800 rounded p-2 overflow-auto max-h-48 font-mono text-gray-600 dark:text-gray-400 whitespace-pre-wrap">{JSON.stringify(rest, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

function CaseExpectedPreview({ expected }: { expected: unknown }) {
  if (expected === null || expected === undefined) return <span className="text-xs text-gray-400">—</span>;
  if (typeof expected === "string") {
    return <pre className="text-xs bg-gray-50 dark:bg-gray-800 rounded-lg p-3 overflow-auto max-h-48 font-mono text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">{expected}</pre>;
  }
  const obj = expected as Record<string, unknown>;
  const verdict = obj.verdict as string | undefined;
  const routeLabel = obj.route_label as string | undefined;
  const cells = obj.cells as Array<{ entity: string; column: string; op: string; why?: string }> | undefined;
  const why = obj.why as string | undefined;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        {verdict && (
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${verdict === "populated" ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300" : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400"}`}>
            {verdict}
          </span>
        )}
        {routeLabel && <span className="text-xs font-mono text-gray-600 dark:text-gray-300">{routeLabel}</span>}
      </div>
      {cells && cells.length > 0 && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Entity</th>
                <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Column</th>
                <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Op</th>
                <th className="px-3 py-2 text-left font-medium text-gray-500 dark:text-gray-400">Why</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {cells.map((cell, i) => (
                <tr key={i} className="bg-white dark:bg-gray-900">
                  <td className="px-3 py-2 font-mono text-gray-700 dark:text-gray-300">{cell.entity}</td>
                  <td className="px-3 py-2 font-mono text-gray-600 dark:text-gray-400">{cell.column}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-1.5 py-0.5 font-bold ${OP_STYLE[cell.op] ?? "bg-gray-100 text-gray-600"}`}>{cell.op}</span>
                  </td>
                  <td className="px-3 py-2 text-gray-400 italic">{cell.why ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cells && cells.length === 0 && (
        <div className="text-xs text-gray-400 italic">No cells — empty matrix</div>
      )}
      {why && <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed border-l-2 border-gray-200 dark:border-gray-700 pl-3">{why}</p>}
    </div>
  );
}

// ── Case preview modal ────────────────────────────────────────────────────────

function CasePreviewModal({ c, onClose, onEdit }: { c: Case; onClose: () => void; onEdit: () => void }) {
  const [showJson, setShowJson] = useState(false);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-sm font-mono">{c.case_id}</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowJson((v) => !v)}
              className={`text-xs px-2 py-1 rounded border font-mono transition-colors ${
                showJson
                  ? "border-purple-400 bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-300"
                  : "border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
              }`}
            >
              {"{ } JSON"}
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={16} /></button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          {showJson ? (
            <pre className="text-xs bg-gray-950 text-green-300 rounded-lg p-4 overflow-auto max-h-[60vh] font-mono whitespace-pre leading-relaxed">
              {JSON.stringify({ input: c.input, expected: c.expected }, null, 2)}
            </pre>
          ) : (
            <>
              <div>
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Input</div>
                <CaseInputPreview input={c.input} />
              </div>
              <div>
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Expected</div>
                <CaseExpectedPreview expected={c.expected} />
              </div>
              {(c.tags ?? []).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {(c.tags ?? []).map((t) => (
                    <span key={t} className="rounded px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 text-xs">{t}</span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-100 dark:border-gray-800 flex justify-end gap-2">
          <button
            onClick={onEdit}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <Pencil size={12} /> Edit
          </button>
          <button onClick={onClose} className="rounded-md px-3 py-1.5 text-xs bg-purple-600 text-white hover:bg-purple-700">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Suite Detail Page ─────────────────────────────────────────────────────────

export function SuiteDetail() {
  const { suiteId = "" } = useParams<{ suiteId: string }>();
  const [showRunConfig, setShowRunConfig] = useState(false);
  const [caseModal, setCaseModal] = useState<{ mode: "add" | "edit"; case?: Case } | null>(null);
  const [previewCase, setPreviewCase] = useState<Case | null>(null);

  const { data: suite, isLoading: suiteLoading } = useSuite(suiteId);
  const { data: cases, isLoading: casesLoading } = useCases(suiteId);
  const { data: lastRun } = useLastRun(suiteId);
  const { data: runHistory } = useRunHistory(suiteId);
  const { data: refineHistory } = useRefineHistory(suiteId);
  const deleteCase = useDeleteCase(suiteId);
  const saveDefaultPrompt = useSaveDefaultPrompt(suiteId);

  const [editingPrompt, setEditingPrompt] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState("");

  // Prefer explicit suite config, then last run, then refine history
  const defaultPrompt = suite?.default_system_prompt
    ?? suite?.last_run?.system_prompt
    ?? refineHistory?.[0]?.prompt;
  const templateId = (suite as Suite & { templates?: Array<{ template_id: string }> })?.templates?.[0]?.template_id ?? suiteId;

  async function handleDelete(caseId: string) {
    if (!window.confirm(`Delete case "${caseId}"?`)) return;
    await deleteCase.mutateAsync(caseId);
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">
              {suiteLoading ? "Loading…" : suite?.title ?? suiteId}
            </h1>
            {suite?.tags?.map((t: string) => (
              <span key={t} className="rounded px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 text-xs">
                {t}
              </span>
            ))}
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5 font-mono">{suiteId}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Link
            to={`/suites/${suiteId}/oracle-review`}
            className="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm border border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 font-medium"
          >
            <ShieldCheck size={13} />
            Oracle Review
          </Link>
          <Link
            to={`/suites/${suiteId}/playground`}
            className="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm border border-purple-300 dark:border-purple-700 text-purple-700 dark:text-purple-300 hover:bg-purple-50 dark:hover:bg-purple-900/30 font-medium"
          >
            <FlaskConical size={13} />
            Playground
          </Link>
          <button
            onClick={() => setShowRunConfig(true)}
            className="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm bg-purple-600 hover:bg-purple-700 text-white font-medium"
          >
            <Play size={13} />
            Run
          </button>
        </div>
      </div>

      {/* Last run summary */}
      {lastRun && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 flex flex-wrap gap-5">
          <div>
            <div className="text-xs text-gray-400 mb-0.5">Last run</div>
            <StatusBadge status={lastRun.status} />
          </div>
          <div>
            <div className="text-xs text-gray-400 mb-0.5">Pass</div>
            <span className="font-semibold tabular-nums">
              {lastRun.passed_cases}/{lastRun.total_cases}
            </span>
          </div>
          <div>
            <div className="text-xs text-gray-400 mb-0.5">Score</div>
            <ScoreBar score={lastRun.avg_score ?? null} />
          </div>
          <div>
            <div className="text-xs text-gray-400 mb-0.5">Cost</div>
            <span className="tabular-nums text-sm">
              {lastRun.total_cost_usd != null ? `$${lastRun.total_cost_usd.toFixed(3)}` : "—"}
            </span>
          </div>
          <div>
            <div className="text-xs text-gray-400 mb-0.5">Model</div>
            <span className="text-sm font-mono">{lastRun.model ?? "—"}</span>
          </div>
        </div>
      )}

      {/* System Prompt */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            System Prompt
          </span>
          {!editingPrompt && (
            <button
              onClick={() => { setDraftPrompt(defaultPrompt ?? ""); setEditingPrompt(true); }}
              className="text-xs text-purple-500 hover:text-purple-400"
            >
              {defaultPrompt ? "Edit" : "+ Set prompt"}
            </button>
          )}
        </div>

        {editingPrompt ? (
          <div className="space-y-2">
            <textarea
              value={draftPrompt}
              onChange={(e) => setDraftPrompt(e.target.value)}
              rows={6}
              autoFocus
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="System prompt sent before every case…"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setEditingPrompt(false)}
                className="text-xs px-3 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                disabled={saveDefaultPrompt.isPending}
                onClick={async () => {
                  await saveDefaultPrompt.mutateAsync(draftPrompt);
                  setEditingPrompt(false);
                }}
                className="text-xs px-3 py-1 rounded bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-50"
              >
                {saveDefaultPrompt.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        ) : defaultPrompt ? (
          <pre className="text-xs font-mono text-gray-600 dark:text-gray-300 whitespace-pre-wrap leading-relaxed max-h-32 overflow-y-auto">
            {defaultPrompt}
          </pre>
        ) : (
          <p className="text-xs text-gray-400 italic">No default system prompt — will be blank on run.</p>
        )}
      </div>

      {/* Prompt versions (lifecycle + promote) */}
      <PromptVersionsPanel suiteId={suiteId} />

      {/* Run History */}
      {runHistory && runHistory.length > 0 && (() => {
        // Group entries: batch runs together, solo runs standalone
        type Group = { batch_id: string | null; entries: RunHistoryEntry[] };
        const groups: Group[] = [];
        const batchMap = new Map<string, Group>();
        for (const r of runHistory) {
          if (r.batch_id) {
            let g = batchMap.get(r.batch_id);
            if (!g) { g = { batch_id: r.batch_id, entries: [] }; batchMap.set(r.batch_id, g); groups.push(g); }
            g.entries.push(r);
          } else {
            groups.push({ batch_id: null, entries: [r] });
          }
        }
        return (
          <div>
            <h2 className="font-medium text-sm text-gray-700 dark:text-gray-300 mb-3">
              Run History
              <span className="ml-1.5 text-gray-400 font-normal">({runHistory.length})</span>
            </h2>
            <div className="space-y-3">
              {groups.map((g, gi) => (
                <div key={g.batch_id ?? `solo-${gi}`} className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
                  {g.batch_id && g.entries.length > 1 && (
                    <div className="flex items-center justify-between px-4 py-2 bg-purple-50 dark:bg-purple-950/20 border-b border-purple-100 dark:border-purple-900">
                      <span className="text-xs font-mono text-purple-600 dark:text-purple-400">
                        batch · {g.entries.length} models · {g.batch_id.slice(0, 8)}
                      </span>
                      <Link
                        to={`/batch/${g.batch_id}/compare?suite_id=${suiteId}`}
                        className="inline-flex items-center gap-1 text-xs text-purple-600 dark:text-purple-400 hover:text-purple-800 dark:hover:text-purple-200 font-medium"
                      >
                        <BarChart2 size={11} /> Compare
                      </Link>
                    </div>
                  )}
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-900 text-xs font-medium text-gray-500">
                      <tr>
                        <th className="px-4 py-2 text-left">Date</th>
                        <th className="px-4 py-2 text-left">Model</th>
                        <th className="px-4 py-2 text-left">Pass</th>
                        <th className="px-4 py-2 text-left">Score</th>
                        <th className="px-4 py-2 text-left">Cost</th>
                        <th className="px-4 py-2" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                      {g.entries.map((r) => {
                        const pct = r.total_count > 0
                          ? Math.round(r.passed_count / r.total_count * 100) : 0;
                        return (
                          <tr key={r.run_id} className="hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors">
                            <td className="px-4 py-2.5 text-xs text-gray-500 tabular-nums">
                              {r.finished_at
                                ? new Date(r.finished_at * 1000).toLocaleString()
                                : "—"}
                            </td>
                            <td className="px-4 py-2.5 font-mono text-xs text-gray-700 dark:text-gray-300">
                              {r.model ?? "—"}
                            </td>
                            <td className="px-4 py-2.5 text-xs tabular-nums text-gray-600 dark:text-gray-300">
                              {r.passed_count}/{r.total_count}
                              <span className="ml-1 text-gray-400">({pct}%)</span>
                            </td>
                            <td className="px-4 py-2.5">
                              <ScoreBar score={r.pass_rate ?? null} />
                            </td>
                            <td className="px-4 py-2.5 text-xs tabular-nums text-gray-500">
                              {r.total_cost_usd != null ? `$${r.total_cost_usd.toFixed(4)}` : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right">
                              <Link
                                to={`/runs/${r.run_id}?suite_id=${suiteId}`}
                                className="inline-flex items-center gap-1 text-xs text-purple-600 dark:text-purple-400 hover:underline"
                              >
                                View <ExternalLink size={10} />
                              </Link>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Cases table */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium text-sm text-gray-700 dark:text-gray-300">
            Cases {cases ? `(${cases.length})` : ""}
          </h2>
          <button
            onClick={() => setCaseModal({ mode: "add" })}
            className="flex items-center gap-1 rounded-md px-3 py-1.5 text-xs bg-purple-600 hover:bg-purple-700 text-white font-medium"
          >
            <Plus size={12} />
            Add Case
          </button>
        </div>
        {casesLoading && <TableSkeleton rows={5} />}
        {cases && cases.length === 0 && (
          <div
            onClick={() => setCaseModal({ mode: "add" })}
            className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 p-6 text-center text-sm text-gray-400 cursor-pointer hover:border-purple-400 hover:text-purple-500 transition-colors"
          >
            No cases yet — click to add the first one
          </div>
        )}
        {cases && cases.length > 0 && (
          <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Case ID</th>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Input</th>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Expected</th>
                  <th className="px-4 py-2.5 text-left font-medium text-gray-500 dark:text-gray-400 text-xs">Tags</th>
                  <th className="px-4 py-2.5 text-xs w-16"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {cases.map((c: Case) => (
                  <tr key={c.case_id} onClick={() => setPreviewCase(c)} className="hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors group cursor-pointer">
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">{c.case_id}</td>
                    <td className="px-4 py-3 max-w-xs truncate text-gray-700 dark:text-gray-300">
                      {typeof c.input === "string" ? c.input : JSON.stringify(c.input)}
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate text-gray-500">
                      {c.expected !== undefined
                        ? typeof c.expected === "string" ? c.expected : JSON.stringify(c.expected)
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(c.tags ?? []).map((t: string) => (
                          <span key={t} className="rounded px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 text-xs">
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => setCaseModal({ mode: "edit", case: c })}
                          className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                          title="Edit"
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          onClick={() => handleDelete(c.case_id)}
                          className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-600 dark:hover:text-red-400"
                          title="Delete"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Run config dialog */}
      {showRunConfig && (
        <RunConfigDialog
          suiteId={suiteId}
          defaultPrompt={defaultPrompt}
          onClose={() => setShowRunConfig(false)}
        />
      )}

      {/* Add / Edit case modal */}
      {caseModal && (
        <CaseFormModal
          suiteId={suiteId}
          templateId={templateId}
          initialCase={caseModal.mode === "edit" ? caseModal.case : undefined}
          onClose={() => setCaseModal(null)}
        />
      )}

      {/* Case preview modal */}
      {previewCase && (
        <CasePreviewModal
          c={previewCase}
          onClose={() => setPreviewCase(null)}
          onEdit={() => { setPreviewCase(null); setCaseModal({ mode: "edit", case: previewCase }); }}
        />
      )}
    </div>
  );
}

export function SuiteList() {
  const { activeProjectId } = useActiveProject();
  const isLocal = activeProjectId === "local";

  const localSuites = useSuites();
  const remoteProject = useProject(isLocal ? "" : activeProjectId);

  const isLoading = isLocal ? localSuites.isLoading : remoteProject.isLoading;
  const suites: Suite[] = isLocal
    ? (localSuites.data ?? [])
    : (remoteProject.data?.suites ?? []);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-xl font-semibold mb-5">Suites</h1>
      {isLoading && <TableSkeleton rows={5} />}
      {!isLoading && suites.length === 0 && (
        <div className="text-center text-sm text-gray-400 py-12">No suites found.</div>
      )}
      {suites.length > 0 && (
        <div className="space-y-2">
          {suites.map((s: Suite) => (
            <a
              key={s.suite_id}
              href={`/suites/${s.suite_id}`}
              className="flex items-center justify-between rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-5 py-4 hover:border-purple-400 dark:hover:border-purple-600 transition-colors"
            >
              <div>
                <div className="font-medium">{s.title ?? s.suite_id}</div>
                <div className="text-xs text-gray-400 font-mono mt-0.5">{s.suite_id}</div>
              </div>
              <span className="text-xs text-gray-400">{s.case_count ?? 0} cases →</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
