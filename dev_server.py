"""Dev server for ryuu-eval-ui.

Run:  python3 dev_server.py
UI:   http://localhost:8001/api/eval/ui
API:  http://localhost:8001/api/eval/status

Or run Vite dev server in parallel for hot-reload:
  cd packages/ryuu-eval-ui/web && npm run dev
  → http://localhost:5173  (proxies /api → localhost:8001)
"""

from __future__ import annotations

import os
from pathlib import Path

# Load .env before anything else so API keys and DATABASE_URL are available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import logging
import functools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ryuu_eval.http import build_eval_router
from ryuu_eval_core.models import ExternalProject
from ryuu_observability_core.logger import StdlibLogger

from eval_suites import TEMPLATES, runner_factory
from eval_consumer.crud_matrix_oracle.strategy import CrudMatrixOracleStrategy
from providers import make_providers, model_catalog

# Eval logger — DEBUG level so _strip_code_fence and per-call logs are visible
_eval_logger = StdlibLogger("eval_suites", level=logging.DEBUG)

# Partial-apply logger so runner_factory signature stays compatible with router
_runner_factory = functools.partial(runner_factory, logger=_eval_logger)

# ---------------------------------------------------------------------------
# Optional Postgres store
# ---------------------------------------------------------------------------

_db_store = None
_prompt_store = None
_test_case_store = None
_run_store = None
_suite_store = None
_PROMPT_DEFAULT_DOMAIN = "eval-default"
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    try:
        from ryuu_storage_postgres import (
            PostgresEvalRunStore,
            PostgresKVStore,
            PostgresPromptStore,
            PostgresSuiteStore,
            PostgresTestCaseStore,
        )
        # NOTE: table renamed from "eval_runs" → "eval_run_blobs". The migration
        # (docs/eval-prompt-store-schema.sql) now owns a NORMALIZED eval_runs table,
        # so the legacy KV run-blob cache must not collide with it.
        _db_store = PostgresKVStore(dsn=_db_url, table="eval_run_blobs")
        _prompt_store = PostgresPromptStore(dsn=_db_url)
        _test_case_store = PostgresTestCaseStore(dsn=_db_url)
        _run_store = PostgresEvalRunStore(dsn=_db_url)
        _suite_store = PostgresSuiteStore(dsn=_db_url)
        print(f"  DB      : PostgreSQL connected ({_db_url[:30]}...)")

    except ImportError:
        print("  DB      : ryuu-storage-postgres not installed, skipping")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

async def _bootstrap_prompt_schema() -> None:
    """Seed systems/domains FK rows so prompt_versions saves don't fail.

    Runs inside uvicorn's event loop — safe to use asyncpg directly.
    Bootstrap failure is non-fatal: warn and continue (prompt store still works
    for suites whose parent rows already exist).
    """
    if not _db_url or _prompt_store is None:
        return
    try:
        import asyncpg
        conn = await asyncpg.connect(_db_url)
        try:
            await conn.execute(
                "INSERT INTO systems(id, name) VALUES('eval', 'Eval')"
                " ON CONFLICT (id) DO NOTHING"
            )
            await conn.execute(
                "INSERT INTO domains(id, system_id, name)"
                " VALUES($1, 'eval', 'Default') ON CONFLICT (id) DO NOTHING",
                _PROMPT_DEFAULT_DOMAIN,
            )
        finally:
            await conn.close()
        print("  startup : prompt-schema bootstrap OK")
    except Exception as exc:
        print(f"  startup : prompt-schema bootstrap warning ({exc})")


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ARG001
    await _bootstrap_prompt_schema()
    yield


app = FastAPI(title="ryuu-eval dev server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:8001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_CODE_ANALYSIS_URL = os.environ.get("CODE_ANALYSIS_URL", "http://localhost:8000/api/eval2")

# Single source of truth for every LLM provider used by this server.
# Both the oracle strategy and the meta-generate endpoint pull from here —
# no module instantiates AnthropicProvider/OpenAIProvider on its own.
PROVIDERS = make_providers()
MODEL_CATALOG = model_catalog()
print(f"  LLM     : {sorted(PROVIDERS.keys()) or '(none — set ANTHROPIC_API_KEY / OPENAI_API_KEY)'}")

app.include_router(
    build_eval_router(
        runner_factory=_runner_factory,
        template_registry=TEMPLATES,
        serve_ui=True,
        kv_store=_db_store,
        prompt_store=_prompt_store,
        prompt_default_domain_id=_PROMPT_DEFAULT_DOMAIN,
        test_case_store=_test_case_store,
        run_store=_run_store,
        suite_store=_suite_store,
        llm_providers=PROVIDERS,
        model_catalog=MODEL_CATALOG,
        oracle_strategy_factory=(
            (lambda: CrudMatrixOracleStrategy(provider=PROVIDERS["anthropic"]))
            if "anthropic" in PROVIDERS else None
        ),
        external_projects=[
            ExternalProject(
                project_id="code-analysis",
                title="prod-grade-code-analysis",
                base_url=_CODE_ANALYSIS_URL,
                description="CRUD matrix LLM eval for Java Spring Boot code analysis",
            )
        ],
    ),
    prefix="/api/eval",
)


if __name__ == "__main__":
    import uvicorn
    print("\n  Backend : http://localhost:8001/api/eval/status")
    print("  UI      : http://localhost:8001/api/eval/ui")
    print("  Dev UI  : cd packages/ryuu-eval-ui/web && npm run dev → :5173\n")
    uvicorn.run("dev_server:app", host="0.0.0.0", port=8001, reload=True)
