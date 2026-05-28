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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ryuu_eval.http import build_eval_router
from ryuu_eval_core.models import ExternalProject
from ryuu_observability_core.logger import StdlibLogger

from eval_suites import TEMPLATES, runner_factory
from eval_consumer.crud_matrix_oracle.strategy import CrudMatrixOracleStrategy
from providers import make_providers

# Eval logger — DEBUG level so _strip_code_fence and per-call logs are visible
_eval_logger = StdlibLogger("eval_suites", level=logging.DEBUG)

# Partial-apply logger so runner_factory signature stays compatible with router
_runner_factory = functools.partial(runner_factory, logger=_eval_logger)

# ---------------------------------------------------------------------------
# Optional Postgres store
# ---------------------------------------------------------------------------

_db_store = None
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    try:
        from ryuu_storage_postgres import PostgresKVStore
        _db_store = PostgresKVStore(dsn=_db_url, table="eval_runs")
        print(f"  DB      : PostgreSQL connected ({_db_url[:30]}...)")
    except ImportError:
        print("  DB      : ryuu-storage-postgres not installed, skipping")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="ryuu-eval dev server")
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
print(f"  LLM     : {sorted(PROVIDERS.keys()) or '(none — set ANTHROPIC_API_KEY / OPENAI_API_KEY)'}")

app.include_router(
    build_eval_router(
        runner_factory=_runner_factory,
        template_registry=TEMPLATES,
        serve_ui=True,
        kv_store=_db_store,
        llm_providers=PROVIDERS,
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
