"""Tests for the prompt-version endpoints on ryuu_eval.http.router (slice 1).

Uses InMemoryPromptStore as the injected prompt_store, so no database is needed.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ryuu_eval_core import EvalCaseTemplate, EvalRunner
from ryuu_eval.http.router import build_eval_router
from ryuu_prompts import InMemoryPromptStore

SUITE = "suite_a"


def _client(prompt_store=None) -> TestClient:
    tpl = EvalCaseTemplate(
        template_id="tpl_a", suite_id=SUITE, title="Template A",
        input_schema={"type": "object"}, examples=[],
    )
    router = build_eval_router(
        runner_factory=lambda s, p: EvalRunner(suite_id=s, target=None, scorers=[]),
        template_registry={"tpl_a": tpl},
        prompt_store=prompt_store,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/eval")
    return TestClient(app)


def _config(version: str) -> dict:
    return {
        "version": version, "description": f"cfg {version}", "model": "gpt-4o-mini",
        "temperature": 0.1, "max_tokens": 512,
        "prompts": {"extract": {"system": "Extract {x}.", "user": "{query}"}},
        "tools": [],
    }


# --- 501 when no store configured -----------------------------------------


def test_endpoints_501_without_store():
    c = _client(prompt_store=None)
    assert c.get(f"/api/eval/suites/{SUITE}/prompt-versions").status_code == 501


# --- list / save / active / promote / status ------------------------------


def test_full_lifecycle_via_http():
    c = _client(prompt_store=InMemoryPromptStore())

    # empty list, no active
    assert c.get(f"/api/eval/suites/{SUITE}/prompt-versions").json() == []
    assert c.get(f"/api/eval/suites/{SUITE}/prompt-versions/active").status_code == 404

    # save v1 + v2
    r1 = c.post(f"/api/eval/suites/{SUITE}/prompt-versions",
                json={"version": "v1", "config": _config("v1")})
    assert r1.status_code == 200
    assert r1.json()["status"] == "draft"
    assert r1.json()["config"]["model"] == "gpt-4o-mini"
    c.post(f"/api/eval/suites/{SUITE}/prompt-versions",
           json={"version": "v2", "config": _config("v2")})

    listed = c.get(f"/api/eval/suites/{SUITE}/prompt-versions").json()
    assert {v["version"] for v in listed} == {"v1", "v2"}

    # status v2 → staging
    rs = c.patch(f"/api/eval/suites/{SUITE}/prompt-versions/v2/status",
                 json={"status": "staging"})
    assert rs.json()["status"] == "staging"

    # promote v2
    rp = c.post(f"/api/eval/suites/{SUITE}/prompt-versions/v2/promote",
                json={"by": "tester"})
    assert rp.status_code == 200
    assert rp.json()["promoted_by"] == "tester"

    active = c.get(f"/api/eval/suites/{SUITE}/prompt-versions/active").json()
    assert active["version"] == "v2"


# --- validation / error mapping -------------------------------------------


def test_save_requires_version_and_config():
    c = _client(prompt_store=InMemoryPromptStore())
    assert c.post(f"/api/eval/suites/{SUITE}/prompt-versions", json={}).status_code == 400
    assert c.post(f"/api/eval/suites/{SUITE}/prompt-versions",
                  json={"version": "v1"}).status_code == 400


def test_promote_missing_version_404():
    c = _client(prompt_store=InMemoryPromptStore())
    r = c.post(f"/api/eval/suites/{SUITE}/prompt-versions/nope/promote", json={})
    assert r.status_code == 404


def test_promote_archived_400():
    store = InMemoryPromptStore()
    c = _client(prompt_store=store)
    c.post(f"/api/eval/suites/{SUITE}/prompt-versions",
           json={"version": "v1", "config": _config("v1")})
    c.patch(f"/api/eval/suites/{SUITE}/prompt-versions/v1/status",
            json={"status": "archived"})
    r = c.post(f"/api/eval/suites/{SUITE}/prompt-versions/v1/promote", json={})
    assert r.status_code == 400


def test_invalid_status_400():
    c = _client(prompt_store=InMemoryPromptStore())
    c.post(f"/api/eval/suites/{SUITE}/prompt-versions",
           json={"version": "v1", "config": _config("v1")})
    r = c.patch(f"/api/eval/suites/{SUITE}/prompt-versions/v1/status",
                json={"status": "bogus"})
    assert r.status_code == 400
