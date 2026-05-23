"""Tests for ryuu_eval.http.router — _maybe_await + fixtures + run/single."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ryuu_eval_core import EvalCase, EvalCaseTemplate, EvalRunner
from ryuu_eval.http.router import build_eval_router, _maybe_await


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _make_router(
    *,
    optimizer_callback=None,
    fixtures_dir: Path | None = None,
    cases_dir: Path | None = None,
):
    tpl = EvalCaseTemplate(
        template_id="tpl_a",
        suite_id="suite_a",
        title="Template A",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "max_tokens": {"type": "integer"},
            },
            "required": ["question"],
        },
        examples=[{"input": {"question": "hello"}, "expected": {"answer": "hi"}}],
    )
    kwargs = dict(
        runner_factory=lambda s, p: EvalRunner(suite_id=s, target=None, scorers=[]),
        template_registry={"tpl_a": tpl},
        optimizer_callback=optimizer_callback,
    )
    if fixtures_dir is not None:
        kwargs["fixtures_dir"] = fixtures_dir
    if cases_dir is not None:
        kwargs["cases_dir"] = cases_dir
    return build_eval_router(**kwargs)


def _app(router) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/eval")
    return app


# ---------------------------------------------------------------------------
# T01 — _maybe_await helper
# ---------------------------------------------------------------------------


class TestMaybeAwait:
    """_maybe_await must handle both sync and async callables transparently."""

    def test_sync_callable_returns_value(self):
        result = asyncio.run(_maybe_await(lambda: 42))
        assert result == 42

    def test_async_callable_returns_value(self):
        async def _afn():
            return "async_ok"

        result = asyncio.run(_maybe_await(_afn))
        assert result == "async_ok"

    def test_sync_callable_with_args(self):
        result = asyncio.run(_maybe_await(lambda x, y: x + y, 3, 4))
        assert result == 7

    def test_async_callable_with_args(self):
        async def _afn(a, b):
            return a * b

        result = asyncio.run(_maybe_await(_afn, 3, 4))
        assert result == 12


class TestOptimizeEndpointCallsMaybeAwait:
    """POST /optimize/{suite_id} must not NameError when optimizer_callback given."""

    def test_sync_optimizer_callback_returns_200(self):
        def _sync_opt(suite_id, params):
            return {"status": "ok", "suite_id": suite_id}

        router = _make_router(optimizer_callback=_sync_opt)
        client = TestClient(_app(router))
        resp = client.post("/api/eval/optimize/suite_a", json={"max_rounds": 1})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_async_optimizer_callback_returns_200(self):
        async def _async_opt(suite_id, params):
            return {"status": "async_ok", "suite_id": suite_id}

        router = _make_router(optimizer_callback=_async_opt)
        client = TestClient(_app(router))
        resp = client.post("/api/eval/optimize/suite_a", json={"max_rounds": 1})
        assert resp.status_code == 200
        assert resp.json()["status"] == "async_ok"

    def test_no_optimizer_returns_501(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.post("/api/eval/optimize/suite_a", json={})
        assert resp.status_code == 501


# ---------------------------------------------------------------------------
# T02 — YAML fixtures backend
# ---------------------------------------------------------------------------


class TestFixturesEndpoint:
    """GET /fixtures/{suite_id} returns [] when fixtures_dir not configured."""

    def test_no_fixtures_dir_returns_empty(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.get("/api/eval/fixtures/suite_a")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_fixtures_dir_nonexistent_suite_returns_empty(self, tmp_path):
        router = _make_router(fixtures_dir=tmp_path)
        client = TestClient(_app(router))
        resp = client.get("/api/eval/fixtures/no_such_suite")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_fixtures_dir_with_yaml_returns_cases(self, tmp_path):
        suite_dir = tmp_path / "suite_a"
        suite_dir.mkdir()
        (suite_dir / "case1.yml").write_text(
            "case_id: c1\ninput: {question: hi}\nexpected: {answer: hello}\n"
        )

        router = _make_router(fixtures_dir=tmp_path)
        client = TestClient(_app(router))
        resp = client.get("/api/eval/fixtures/suite_a")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["case_id"] == "c1"
        assert data[0]["_source"] == "fixture"

    def test_status_shows_fixtures_dir(self, tmp_path):
        router = _make_router(fixtures_dir=tmp_path)
        client = TestClient(_app(router))
        resp = client.get("/api/eval/status")
        assert resp.status_code == 200
        assert "fixtures_dir" in resp.json()


# ---------------------------------------------------------------------------
# T03 — POST /run/single endpoint
# ---------------------------------------------------------------------------


class TestRunSingleEndpoint:
    """POST /run/single runs one ad-hoc case and returns CaseResult."""

    def test_missing_suite_id_returns_400(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.post("/api/eval/run/single", json={"input": {}})
        assert resp.status_code == 400

    def test_valid_case_returns_case_result(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.post(
            "/api/eval/run/single",
            json={
                "suite_id": "suite_a",
                "case_id": "adhoc_1",
                "input": {"question": "hello"},
                "expected": {"answer": "hi"},
            },
        )
        assert resp.status_code == 200
        result = resp.json()
        # CaseResult shape: case_id / passed / scores / cost_usd / latency_ms
        assert "passed" in result
        assert "scores" in result
