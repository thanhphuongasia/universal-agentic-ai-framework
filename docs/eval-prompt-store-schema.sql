-- =============================================================================
-- Eval & Prompt Store — Migration (Phương án A: Postgres + JSONB)
-- Khớp 1-1 với docs/eval-prompt-store-schema.md (ERD 8 bảng).
--
--   7 bảng "spine" (quan hệ + FK)  : systems → domains → suites → prompt_versions
--                                     / templates / test_cases / eval_runs
--   1 bảng "rides PostgresCollectionStore" : eval_results
--
-- Idempotent: chạy lại nhiều lần an toàn (CREATE TABLE IF NOT EXISTS).
-- Postgres >= 13.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- systems — top of the tree (slug-based id, ví dụ 'code-analysis')
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS systems (
    id          TEXT        PRIMARY KEY,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- domains — con của system; tên unique trong 1 system
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS domains (
    id          TEXT        PRIMARY KEY,
    system_id   TEXT        NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (system_id, name)
);
CREATE INDEX IF NOT EXISTS domains_system_idx ON domains(system_id);

-- -----------------------------------------------------------------------------
-- suites — con của domain. active_prompt_version_id = con trỏ DUY NHẤT cho 'live'.
-- FK vòng (suites ↔ prompt_versions) → thêm sau bằng ALTER + DEFERRABLE.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS suites (
    id                       TEXT        PRIMARY KEY,
    domain_id                TEXT        NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    name                     TEXT        NOT NULL,
    active_prompt_version_id TEXT,  -- FK thêm ở cuối (DEFERRABLE)
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain_id, name)
);
CREATE INDEX IF NOT EXISTS suites_domain_idx ON suites(domain_id);

-- -----------------------------------------------------------------------------
-- prompt_versions — config JSONB = ryuu_prompts.PromptConfig serialize.
-- status KHÔNG có 'production' — production là phái sinh từ suites.active_*.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prompt_versions (
    id          TEXT        PRIMARY KEY,
    suite_id    TEXT        NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
    version     TEXT        NOT NULL,
    config      JSONB       NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'staging', 'archived')),
    promoted_at TIMESTAMPTZ,
    promoted_by TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (suite_id, version)
);
CREATE INDEX IF NOT EXISTS prompt_versions_suite_idx ON prompt_versions(suite_id);

-- FK vòng: giờ prompt_versions đã tồn tại → gắn con trỏ active.
-- DEFERRABLE INITIALLY DEFERRED: cho phép tạo suite + version trong cùng 1 txn.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'suites_active_prompt_fk'
    ) THEN
        ALTER TABLE suites
            ADD CONSTRAINT suites_active_prompt_fk
            FOREIGN KEY (active_prompt_version_id)
            REFERENCES prompt_versions(id) ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- templates — = ryuu_eval_core.EvalCaseTemplate. *_schema = JSON Schema → UI form.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS templates (
    id              TEXT        PRIMARY KEY,
    suite_id        TEXT        NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
    title           TEXT        NOT NULL,
    description     TEXT        NOT NULL DEFAULT '',
    input_schema    JSONB       NOT NULL DEFAULT '{}',
    expected_schema JSONB       NOT NULL DEFAULT '{}',
    tags            JSONB       NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS templates_suite_idx ON templates(suite_id);

-- -----------------------------------------------------------------------------
-- test_cases — = ryuu_eval_core.EvalCase. scoring = spec cho build_scorers().
-- prompt_override_id NULL = dùng suite.active_prompt_version_id.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_cases (
    id                 TEXT        NOT NULL,
    suite_id           TEXT        NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
    template_id        TEXT        REFERENCES templates(id) ON DELETE SET NULL,
    name               TEXT        NOT NULL,
    input              JSONB       NOT NULL DEFAULT '{}',
    expected           JSONB       NOT NULL DEFAULT '{}',
    scoring            JSONB       NOT NULL DEFAULT '{}',
    prompt_override_id TEXT        REFERENCES prompt_versions(id) ON DELETE SET NULL,
    metadata           JSONB       NOT NULL DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- case_id is unique WITHIN a suite (matches the file model suite/<case_id>.yml),
    -- not globally — so the same case_id may appear in different suites.
    PRIMARY KEY (suite_id, id)
);
CREATE INDEX IF NOT EXISTS test_cases_suite_idx    ON test_cases(suite_id);
CREATE INDEX IF NOT EXISTS test_cases_template_idx ON test_cases(template_id);

-- -----------------------------------------------------------------------------
-- eval_runs — 1 lần chạy suite. summary = SuiteResult, approval = review state.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_runs (
    id                TEXT        PRIMARY KEY,
    suite_id          TEXT        NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
    prompt_version_id TEXT        REFERENCES prompt_versions(id) ON DELETE SET NULL,
    triggered_by      TEXT        NOT NULL DEFAULT '',
    trigger_type      TEXT        NOT NULL DEFAULT 'manual'
                                  CHECK (trigger_type IN ('manual', 'scheduled')),
    status            TEXT        NOT NULL DEFAULT 'running'
                                  CHECK (status IN ('running', 'completed', 'failed')),
    summary           JSONB       NOT NULL DEFAULT '{}',
    approval          JSONB       NOT NULL DEFAULT '{}',
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS eval_runs_suite_idx  ON eval_runs(suite_id, started_at DESC);
CREATE INDEX IF NOT EXISTS eval_runs_prompt_idx ON eval_runs(prompt_version_id);

-- -----------------------------------------------------------------------------
-- eval_results — KHÔNG quản thủ công: PostgresCollectionStore tự tạo bảng này
-- (id / scope_key / content / metadata / created_at) khi khởi tạo store với
-- table='eval_results'. Khối dưới chỉ để (1) tài liệu hoá, (2) khớp y hệt store,
-- (3) thêm GIN index trên metadata mà store KHÔNG tạo — tăng tốc lọc theo
-- {test_case_id, passed, resolved_prompt_version_id}.
-- scope_key = run_id (join logic về eval_runs.id ở tầng app, không FK cứng).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_results (
    id         TEXT        PRIMARY KEY,
    scope_key  TEXT        NOT NULL,
    content    TEXT        NOT NULL,
    metadata   JSONB       DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eval_results_scope_idx ON eval_results(scope_key, created_at DESC);
CREATE INDEX IF NOT EXISTS eval_results_meta_gin  ON eval_results USING GIN (metadata);

COMMIT;
