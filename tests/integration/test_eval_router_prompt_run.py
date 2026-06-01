"""Slice 4 runtime: the active/selected prompt version drives the run.

Requires a live Postgres (DATABASE_URL). Verifies that POST /run resolves the
suite's active promoted prompt version's system prompt (and that an explicit
prompt_version overrides it), feeding it to the runner + recording it on eval_runs.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ryuu_eval_core import EvalCaseTemplate, EvalRunner
from ryuu_eval_core.models import CaseResult, EvalCase
from ryuu_eval.http.router import build_eval_router
from ryuu_prompts import PromptConfig, PromptTemplate, PromptVersion
from ryuu_storage_postgres import (
    PostgresEvalRunStore,
    PostgresPromptStore,
    PostgresTestCaseStore,
    close_all,
)
from ryuu_storage_postgres._pool import get_pool

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres tests",
)

DSN = os.getenv("DATABASE_URL", "")
MIGRATION = Path(__file__).resolve().parents[1].parent / "docs" / "eval-prompt-store-schema.sql"
_EVAL_TABLES = [
    "eval_results", "eval_runs", "test_cases", "templates",
    "prompt_versions", "suites", "domains", "systems", "prompt_active",
]

_seen_prompts: list[str | None] = []


class _StubTarget:
    model = "stub"

    async def run(self, case: EvalCase) -> CaseResult:
        return CaseResult(case=case, output="ok")


def _runner_factory(suite_id, log_path, model=None, system_prompt=None, **_kw):
    _seen_prompts.append(system_prompt)  # capture what the run resolved
    return EvalRunner(suite_id=suite_id, target=_StubTarget(), scorers=[])


def _cfg(system: str) -> PromptConfig:
    return PromptConfig(
        version="v", description="", model="claude-sonnet-4-6",
        temperature=0.0, max_tokens=512,
        prompts={"extract": PromptTemplate(system=system, user="{q}")},
    )


async def _seed(prompt_store: PostgresPromptStore, tc_store: PostgresTestCaseStore) -> str:
    suite = f"suite_{uuid.uuid4().hex}"
    sys_id, dom_id = f"sys_{uuid.uuid4().hex}", f"dom_{uuid.uuid4().hex}"
    pool = await get_pool(DSN)
    async with pool.acquire() as conn:
        for t in _EVAL_TABLES:
            await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        await conn.execute(MIGRATION.read_text())
        await conn.execute("INSERT INTO systems(id, name) VALUES($1, 's')", sys_id)
        await conn.execute(
            "INSERT INTO domains(id, system_id, name) VALUES($1, $2, 'd')", dom_id, sys_id)
        await conn.execute(
            "INSERT INTO suites(id, domain_id, name) VALUES($1, $2, $1)", suite, dom_id)
    await prompt_store.save(PromptVersion(
        id="pv1", suite_id=suite, version="v1", config=_cfg("PROMPT ONE")))
    await prompt_store.save(PromptVersion(
        id="pv2", suite_id=suite, version="v2", config=_cfg("PROMPT TWO")))
    await prompt_store.promote(suite, "v2", by="seed")
    await tc_store.save_case(suite, EvalCase(case_id="c1", input="x", expected="x"))
    return suite


async def test_active_version_drives_run_and_explicit_version_overrides():
    _seen_prompts.clear()
    prompt_store = PostgresPromptStore(dsn=DSN)
    tc_store = PostgresTestCaseStore(dsn=DSN)
    run_store = PostgresEvalRunStore(dsn=DSN)
    suite = await _seed(prompt_store, tc_store)

    tpl = EvalCaseTemplate(template_id="t", suite_id=suite, title="T",
                           input_schema={"type": "object"}, examples=[])
    app = FastAPI()
    app.include_router(build_eval_router(
        runner_factory=_runner_factory, template_registry={"t": tpl},
        prompt_store=prompt_store, test_case_store=tc_store, run_store=run_store,
    ), prefix="/api/eval")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        # no prompt + no version → active version (v2) drives the run
        rid = (await c.post("/api/eval/run", json={"suite_id": suite, "model": "stub"})).json()["run_id"]
        async with c.stream("GET", f"/api/eval/run/stream/{rid}") as r:
            async for _ in r.aiter_lines():
                pass
        # explicit prompt_version=v1 overrides
        rid2 = (await c.post("/api/eval/run",
                json={"suite_id": suite, "model": "stub", "prompt_version": "v1"})).json()["run_id"]
        async with c.stream("GET", f"/api/eval/run/stream/{rid2}") as r:
            async for _ in r.aiter_lines():
                pass
        # poll run_store so prompt_version_id is recorded
        rec = None
        for _ in range(60):
            rec = await run_store.get_run(rid)
            if rec and rec["status"] == "completed":
                break
            await asyncio.sleep(0.05)

    await close_all()

    assert _seen_prompts[0] == "PROMPT TWO"   # active v2
    assert _seen_prompts[1] == "PROMPT ONE"   # explicit v1
    assert rec is not None and rec["prompt_version_id"] == "pv2"
