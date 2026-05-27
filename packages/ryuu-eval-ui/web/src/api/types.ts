// Backend dataclass mirrors — keep in sync with ryuu_eval_core/models.py

export interface Template {
  template_id: string;
  suite_id: string;
  title: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  expected_schema?: Record<string, unknown>;
  examples?: Array<{ input: unknown; expected?: unknown }>;
  tags?: string[];
}

export interface Suite {
  suite_id: string;
  title?: string;
  description?: string;
  tags?: string[];
  owner?: string;
  case_count?: number;
  templates?: Template[];
  model?: string;
  default_system_prompt?: string;
  last_run?: {
    run_id?: string;
    passed_count?: number;
    total_count?: number;
    pass_rate?: number;
    total_cost_usd?: number;
    finished_at?: number;
    system_prompt?: string;
  };
}

export interface Case {
  case_id: string;
  suite_id: string;
  input: unknown;
  expected?: unknown;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export type CaseStatus = "queued" | "running" | "pass" | "fail" | "error" | "cancelled";

export interface CaseStep {
  type: "thought" | "tool_call" | "observation" | "llm_input" | "llm_output" | string;
  content?: unknown;
  label?: string;
  ts?: number;
}

export interface CaseResult {
  case_id: string;
  suite_id: string;
  status: CaseStatus;
  score: number | null;
  pass: boolean | null;
  input?: unknown;
  actual?: unknown;
  expected?: unknown;
  error?: string;
  latency_ms?: number;
  cost_usd?: number;
  tokens_in?: number;
  tokens_out?: number;
  metadata?: Record<string, unknown>;
  steps?: CaseStep[];
}

export interface RunHistoryEntry {
  run_id: string;
  model?: string;
  finished_at?: number;
  passed_count: number;
  total_count: number;
  pass_rate?: number;
  total_cost_usd?: number;
  batch_id?: string;
}

export type RunStatus = "pending" | "running" | "done" | "cancelled" | "error";

export interface RunSummary {
  run_id: string;
  suite_id: string;
  status: RunStatus;
  model?: string;
  prompt_version?: string;
  started_at?: string;
  finished_at?: string;
  total_cases: number;
  completed_cases: number;
  passed_cases: number;
  failed_cases: number;
  avg_score?: number;
  total_cost_usd?: number;
  avg_latency_ms?: number;
  error?: string;
}

export interface RunParams {
  model?: string | null;
  system_prompt?: string | null;
  max_tokens?: number | null;
  temperature?: number | null;
  budget_cap_usd?: number | null;
  concurrency?: number | null;
  mode?: "parallel" | "sequential" | null;
  case_ids?: string[] | null;
  started_at?: number | null;
}

export interface RunResult extends RunSummary {
  cases: CaseResult[];
  params?: RunParams;
}

// SSE event shapes from /run/stream/{suite_id}
export type StreamEventType =
  | "run_start"
  | "case_start"
  | "case_done"
  | "run_done"
  | "run_cancel"
  | "error"
  | "llm_token";

export interface StreamEvent {
  event: StreamEventType;
  run_id?: string;
  case_id?: string;
  total?: number;
  result?: CaseResult;
  summary?: RunSummary;
  token?: string;
  error?: string;
}

export interface ServerStatus {
  ok: boolean;
  version?: string;
  features?: Record<string, boolean>;
}

export interface RunConfig {
  suite_id: string;
  model?: string;
  models?: string[];
  prompt?: string;
  temperature?: number;
  max_tokens?: number;
  case_ids?: string[];
  concurrency?: number;
  mode?: "parallel" | "sequential";
  budget_usd?: number;
}

export interface BatchRunEntry {
  run_id: string;
  model: string;
}

export interface BatchRun {
  batch_id: string;
  suite_id: string;
  runs: BatchRunEntry[];
}

export interface RefineHistoryEntry {
  version: string;
  prompt: string;
  created_at: string;
  run_id?: string;
  score?: number;
}

export interface Project {
  project_id: string;
  title: string;
  description?: string;
  remote: boolean;
  base_url?: string;
  suite_count?: number | null;
  suite_ids?: string[];
  cached_at?: number | null;
  stale?: boolean;
  suites?: Suite[];
}

export interface SyncResult {
  project_id: string;
  synced_suites: number;
  synced_cases: number;
  skipped_cases: number;
  suite_ids: string[];
  errors: string[];
}

// ── Oracle Review ─────────────────────────────────────────────────────────────

export type ReviewKind = "table" | "graph" | "tree" | "timeline";

export interface ReviewSchema {
  kind: ReviewKind;
  columns: string[];         // used when kind="table"
  node_fields: string[];     // used when kind="graph"|"tree"
  edge_fields: string[];     // used when kind="graph"
  actions: string[];         // e.g. ["approve","fix","remove"]
  meta: Record<string, unknown>;
}

export type OracleConfidence = "low" | "medium" | "high";
export type ReviewAction = "approve" | "fix" | "remove";

export interface OracleFixtureSummary {
  fixture_id: string;
  prompt_version: string;
  oracle_model: string;
  reviewed_by: string;
  reviewed_at: string;
  pending_review: number;   // count of cells with action=null
}

export interface OracleCellData {
  op: string;
  confidence: OracleConfidence;
  oracle_why: string;
}

export interface OracleReviewItem {
  entity: string;
  field: string;
  op: string;
  confidence: OracleConfidence;
  oracle_why: string;
  action: ReviewAction | null;
  corrected_op: string | null;
}

/** Full fixture returned by GET /oracle-review/{fixture_id} */
export interface OracleFixtureDetail {
  fixture_id: string;
  prompt_version: string;
  oracle_model: string;
  reviewed_by: string;
  reviewed_at: string;
  input_data: Record<string, unknown>;
  /** expected[entity][field] = OracleCellData */
  expected: Record<string, Record<string, OracleCellData>>;
  meta: { valid_fields?: Record<string, string[]>; [k: string]: unknown };
  review_items: OracleReviewItem[];
}

export interface ReviewActionPayload {
  entity: string;
  field: string;
  action: ReviewAction;
  corrected_op?: string;
}

export interface OraclePrompt {
  system: string;
  user: string;
}

export interface OracleRunPreview {
  cells: Record<string, Record<string, OracleCellData>>;
  valid_fields: Record<string, string[]>;
}
