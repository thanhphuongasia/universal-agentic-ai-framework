import { useState } from "react";
import { useParams } from "react-router-dom";
import { Play } from "lucide-react";
import { useCases, useRefineHistory, useRunSingle } from "@/api/hooks";
import { StatusBadge } from "@/components/StatusBadge";
import { ScoreBar } from "@/components/ScoreBar";
import type { CaseResult } from "@/api/types";

// ── Left Panel: Prompt + History ──────────────────────────────────────────────

function PromptPanel({
  suiteId,
  prompt,
  onPromptChange,
}: {
  suiteId: string;
  prompt: string;
  onPromptChange: (p: string) => void;
}) {
  const { data: history, isLoading, error } = useRefineHistory(suiteId);

  return (
    <div className="flex flex-col gap-3 h-full">
      <div>
        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
          System Prompt
        </label>
        <textarea
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          rows={10}
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500 resize-y"
          placeholder="Enter prompt…"
        />
      </div>

      <div>
        <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
          Version History
        </div>
        {isLoading && (
          <div className="text-xs text-gray-400 animate-pulse">Loading history…</div>
        )}
        {error && (
          <div className="text-xs text-red-500">{(error as Error).message}</div>
        )}
        {history && history.length === 0 && (
          <div className="text-xs text-gray-400">No history yet.</div>
        )}
        {history && history.length > 0 && (
          <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
            {history.map((entry) => (
              <button
                key={entry.version}
                onClick={() => onPromptChange(entry.prompt)}
                className="w-full text-left rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-purple-400 dark:hover:border-purple-600 px-3 py-2 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-medium text-gray-700 dark:text-gray-300">
                    {entry.version}
                  </span>
                  {entry.score != null && (
                    <ScoreBar score={entry.score} />
                  )}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">
                  {new Date(entry.created_at).toLocaleString()}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Center Panel: Case Picker ─────────────────────────────────────────────────

function CasePickerPanel({
  suiteId,
  selectedCaseId,
  onSelectCase,
  onRun,
  isRunning,
}: {
  suiteId: string;
  selectedCaseId: string;
  onSelectCase: (id: string) => void;
  onRun: () => void;
  isRunning: boolean;
}) {
  const { data: cases, isLoading, error } = useCases(suiteId);
  const [freeText, setFreeText] = useState("");

  // Use dropdown selection or free-text, whichever is non-empty
  const effectiveCaseId = freeText.trim() || selectedCaseId;

  function handleRun() {
    const id = freeText.trim() || selectedCaseId;
    if (id) {
      onSelectCase(id);
      onRun();
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
        Select Case
      </div>

      {isLoading && (
        <div className="text-xs text-gray-400 animate-pulse">Loading cases…</div>
      )}
      {error && (
        <div className="text-xs text-red-500">{(error as Error).message}</div>
      )}

      {cases && cases.length > 0 && (
        <div>
          <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
            From suite cases
          </label>
          <select
            value={selectedCaseId}
            onChange={(e) => {
              onSelectCase(e.target.value);
              setFreeText("");
            }}
            className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          >
            <option value="">— pick a case —</option>
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id}
              </option>
            ))}
          </select>
        </div>
      )}

      <div>
        <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
          Or enter case ID directly
        </label>
        <input
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleRun()}
          placeholder="case-id"
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
      </div>

      <button
        onClick={handleRun}
        disabled={!effectiveCaseId || isRunning}
        className="flex items-center justify-center gap-1.5 rounded-md px-4 py-2 text-sm bg-purple-600 hover:bg-purple-700 text-white font-medium disabled:opacity-50 mt-1"
      >
        <Play size={13} />
        {isRunning ? "Running…" : "Run single"}
      </button>
    </div>
  );
}

// ── Right Panel: Output ───────────────────────────────────────────────────────

function OutputPanel({
  result,
  isLoading,
  error,
}: {
  result: CaseResult | null;
  isLoading: boolean;
  error: Error | null;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-gray-400 animate-pulse">
        Running…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 p-4 text-sm text-red-700 dark:text-red-400">
        {error.message}
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-gray-400">
        Output will appear here after running.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Status row */}
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={result.status} />
        {result.score != null && <ScoreBar score={result.score} />}
        {result.latency_ms != null && (
          <span className="text-xs text-gray-500 tabular-nums">
            {result.latency_ms.toFixed(0)} ms
          </span>
        )}
        {result.cost_usd != null && (
          <span className="text-xs text-gray-500 tabular-nums">
            ${result.cost_usd.toFixed(5)}
          </span>
        )}
      </div>

      {/* Actual output */}
      <div>
        <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
          Actual output
        </div>
        <pre className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3 text-xs font-mono whitespace-pre-wrap overflow-auto max-h-64 text-gray-800 dark:text-gray-200">
          {result.actual !== undefined
            ? typeof result.actual === "string"
              ? result.actual
              : JSON.stringify(result.actual, null, 2)
            : "(empty)"}
        </pre>
      </div>

      {/* Expected output */}
      {result.expected !== undefined && (
        <div>
          <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
            Expected
          </div>
          <pre className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3 text-xs font-mono whitespace-pre-wrap overflow-auto max-h-32 text-gray-800 dark:text-gray-200">
            {typeof result.expected === "string"
              ? result.expected
              : JSON.stringify(result.expected, null, 2)}
          </pre>
        </div>
      )}

      {/* Error */}
      {result.error && (
        <div className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 p-3 text-xs text-red-700 dark:text-red-400 font-mono">
          {result.error}
        </div>
      )}

      {/* Tokens */}
      {(result.tokens_in != null || result.tokens_out != null) && (
        <div className="text-xs text-gray-400 tabular-nums">
          Tokens: {result.tokens_in ?? "?"} in / {result.tokens_out ?? "?"} out
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function PlaygroundPage() {
  const { suiteId = "" } = useParams<{ suiteId: string }>();
  const [prompt, setPrompt] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState("");

  const runSingle = useRunSingle();

  function handleRun() {
    if (!selectedCaseId) return;
    runSingle.mutate({
      suite_id: suiteId,
      case_id: selectedCaseId,
      prompt: prompt.trim() || undefined,
    });
  }

  const result = runSingle.data?.result as CaseResult | undefined;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Playground</h1>
        <span className="rounded px-2 py-0.5 bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 text-xs font-mono">
          {suiteId}
        </span>
      </div>

      {/* 3-panel layout */}
      <div className="grid grid-cols-3 gap-5">
        {/* Left: Prompt */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
          <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
            Prompt
          </div>
          <PromptPanel
            suiteId={suiteId}
            prompt={prompt}
            onPromptChange={setPrompt}
          />
        </div>

        {/* Center: Case picker */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
          <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
            Case
          </div>
          <CasePickerPanel
            suiteId={suiteId}
            selectedCaseId={selectedCaseId}
            onSelectCase={setSelectedCaseId}
            onRun={handleRun}
            isRunning={runSingle.isPending}
          />
        </div>

        {/* Right: Output */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
          <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
            Output
          </div>
          <OutputPanel
            result={result ?? null}
            isLoading={runSingle.isPending}
            error={runSingle.error}
          />
        </div>
      </div>
    </div>
  );
}
