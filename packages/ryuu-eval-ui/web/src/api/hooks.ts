import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useCallback } from "react";
import { apiFetch, apiUrl } from "./client";
import type {
  Suite, Case, Template, RunSummary, RunResult, RunConfig,
  ServerStatus, RefineHistoryEntry, StreamEvent, RunHistoryEntry,
  Project, SyncResult,
} from "./types";

// ── Suites ───────────────────────────────────────────────────────────────────

export function useSuites() {
  return useQuery<Suite[]>({
    queryKey: ["suites"],
    queryFn: () => apiFetch("/suites"),
  });
}

export function useSuite(suiteId: string) {
  return useQuery<Suite>({
    queryKey: ["suite", suiteId],
    queryFn: () => apiFetch(`/suites/${suiteId}`),
    enabled: !!suiteId,
  });
}

export function useSaveDefaultPrompt(suiteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (prompt: string) =>
      apiFetch(`/suites/${suiteId}/default-prompt`, {
        method: "PUT",
        body: JSON.stringify({ default_system_prompt: prompt }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["suite", suiteId] }),
  });
}

export function useCases(suiteId: string) {
  return useQuery<Case[]>({
    queryKey: ["cases", suiteId],
    queryFn: () => apiFetch(`/suites/${suiteId}/cases`),
    enabled: !!suiteId,
  });
}

export function useLastRun(suiteId: string) {
  return useQuery<RunSummary>({
    queryKey: ["lastRun", suiteId],
    queryFn: () => apiFetch(`/suites/${suiteId}/last_run`),
    enabled: !!suiteId,
  });
}

export function useRunHistory(suiteId: string, limit = 20) {
  return useQuery<RunHistoryEntry[]>({
    queryKey: ["runHistory", suiteId, limit],
    queryFn: () => apiFetch(`/suites/${suiteId}/runs?limit=${limit}`),
    enabled: !!suiteId,
    staleTime: 10_000,
  });
}

// ── Runs ─────────────────────────────────────────────────────────────────────

export function useRunResult(runId: string) {
  return useQuery<RunResult>({
    queryKey: ["run", runId],
    queryFn: () => apiFetch(`/runs/${runId}`),
    enabled: !!runId,
  });
}

export function useRefineHistory(suiteId: string) {
  return useQuery<RefineHistoryEntry[]>({
    queryKey: ["refineHistory", suiteId],
    queryFn: () => apiFetch(`/refine_history/${suiteId}`),
    enabled: !!suiteId,
  });
}

export function useStartRun() {
  return useMutation<{ run_id?: string; batch_id?: string; runs?: import("./types").BatchRunEntry[]; suite_id: string }, Error, RunConfig>({
    mutationFn: (config) =>
      apiFetch("/run", { method: "POST", body: JSON.stringify(config) }),
  });
}

export function useBatch(batchId: string) {
  return useQuery<import("./types").BatchRun>({
    queryKey: ["batch", batchId],
    queryFn: () => apiFetch(`/batch/${batchId}`),
    enabled: !!batchId,
  });
}

export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (runId) => apiFetch(`/run/cancel/${runId}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["suites"] }),
  });
}

export function useRunSingle() {
  return useMutation<{ result: unknown }, Error, { suite_id: string; case_id: string; prompt?: string; model?: string }>({
    mutationFn: (payload) =>
      apiFetch("/run/single", { method: "POST", body: JSON.stringify(payload) }),
  });
}

// ── Templates ────────────────────────────────────────────────────────────────

export function useTemplates() {
  return useQuery<Template[]>({
    queryKey: ["templates"],
    queryFn: () => apiFetch("/templates"),
  });
}

// ── Case CRUD ────────────────────────────────────────────────────────────────

export function useCreateCase(suiteId: string) {
  const qc = useQueryClient();
  return useMutation<{ ok: boolean }, Error, { templateId: string; payload: Record<string, unknown> }>({
    mutationFn: ({ templateId, payload }) =>
      apiFetch(`/templates/${templateId}/cases`, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cases", suiteId] }),
  });
}

export function useUpdateCase(suiteId: string) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { caseId: string; payload: Record<string, unknown> }>({
    mutationFn: ({ caseId, payload }) =>
      apiFetch(`/suites/${suiteId}/cases/${caseId}`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cases", suiteId] }),
  });
}

export function useDeleteCase(suiteId: string) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (caseId) =>
      apiFetch(`/suites/${suiteId}/cases/${caseId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cases", suiteId] }),
  });
}

// ── Projects ──────────────────────────────────────────────────────────────────

export function useProjects() {
  return useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => apiFetch("/projects"),
    staleTime: 30_000,
  });
}

export function useProject(projectId: string) {
  return useQuery<Project>({
    queryKey: ["project", projectId],
    queryFn: () => apiFetch(`/projects/${projectId}`),
    enabled: !!projectId,
    staleTime: 30_000,
    retry: false,
  });
}

export function useSyncProject() {
  const qc = useQueryClient();
  return useMutation<SyncResult, Error, { projectId: string; overwrite?: boolean }>({
    mutationFn: ({ projectId, overwrite }) =>
      apiFetch(`/projects/${projectId}/sync`, {
        method: "POST",
        body: JSON.stringify({ overwrite: overwrite ?? false }),
      }),
    onSuccess: (_data, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["suites"] });
    },
  });
}

// ── Status ────────────────────────────────────────────────────────────────────

export function useServerStatus() {
  return useQuery<ServerStatus>({
    queryKey: ["status"],
    queryFn: () => apiFetch("/status"),
    staleTime: 60_000,
  });
}

// ── SSE Stream ────────────────────────────────────────────────────────────────

export function useRunStream(
  runId: string | null,
  onEvent: (event: StreamEvent) => void,
  enabled: boolean = true
) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const stop = useCallback(() => {}, []);

  useEffect(() => {
    if (!runId || !enabled) return;
    const es = new EventSource(apiUrl(`/run/stream/${runId}`));

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as StreamEvent;
        onEventRef.current(data);
      } catch {
        // skip malformed events
      }
    };

    es.onerror = () => es.close();

    return () => es.close();
  }, [runId, enabled]);

  return { stop };
}

// ── Oracle Review ─────────────────────────────────────────────────────────────

import type {
  OracleFixtureSummary,
  OracleFixtureDetail,
  ReviewActionPayload,
  ReviewSchema,
} from "./types";

export function useOracleSchema() {
  return useQuery<ReviewSchema>({
    queryKey: ["oracle-schema"],
    queryFn: () => apiFetch("/oracle-review/schema"),
    staleTime: Infinity, // schema doesn't change at runtime
  });
}

export function useOracleFixtures(suiteId?: string) {
  const path = suiteId ? `/oracle-review/?suite_id=${suiteId}` : "/oracle-review/";
  return useQuery<OracleFixtureSummary[]>({
    queryKey: ["oracle-fixtures", suiteId],
    queryFn: () => apiFetch(path),
  });
}

export function useOracleFixture(fixtureId: string) {
  return useQuery<OracleFixtureDetail>({
    queryKey: ["oracle-fixture", fixtureId],
    queryFn: () => apiFetch(`/oracle-review/${fixtureId}`),
    enabled: !!fixtureId,
  });
}

export function useUpdateOracleReview(fixtureId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { actions: ReviewActionPayload[]; reviewed_by?: string }) =>
      apiFetch(`/oracle-review/${fixtureId}/review`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["oracle-fixture", fixtureId] });
      qc.invalidateQueries({ queryKey: ["oracle-fixtures"] });
    },
  });
}
