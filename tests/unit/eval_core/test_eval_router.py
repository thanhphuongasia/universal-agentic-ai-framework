"""Tests for ryuu_eval.http.router — _maybe_await + fixtures + run/single + projects."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ryuu_eval_core import EvalCaseTemplate, EvalRunner, ExternalProject
from ryuu_eval.http.router import build_eval_router, _maybe_await


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _make_router(
    *,
    optimizer_callback=None,
    fixtures_dir: Path | None = None,
    cases_dir: Path | None = None,
    external_projects: list[ExternalProject] | None = None,
    suite_store=None,
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
    if external_projects is not None:
        kwargs["external_projects"] = external_projects
    if suite_store is not None:
        kwargs["suite_store"] = suite_store
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


# ---------------------------------------------------------------------------
# T04 — Gap 1 fix: GET /suites/{id}/cases includes fixtures
# ---------------------------------------------------------------------------


class TestListSuiteCasesIncludesFixtures:
    """GET /suites/{id}/cases must merge cases_dir + fixtures_dir (Gap 1 fix)."""

    def test_returns_only_cases_dir_when_no_fixtures_dir(self, tmp_path):
        suite_dir = tmp_path / "cases" / "suite_a"
        suite_dir.mkdir(parents=True)
        (suite_dir / "c1.yml").write_text("case_id: c1\ninput: {q: hello}\n")

        router = _make_router(cases_dir=tmp_path / "cases")
        client = TestClient(_app(router))
        resp = client.get("/api/eval/suites/suite_a/cases")
        assert resp.status_code == 200
        ids = [c["case_id"] for c in resp.json()]
        assert ids == ["c1"]

    def test_merges_fixtures_when_fixtures_dir_configured(self, tmp_path):
        cases_dir = tmp_path / "cases"
        fixtures_dir = tmp_path / "fixtures"
        (cases_dir / "suite_a").mkdir(parents=True)
        (fixtures_dir / "suite_a").mkdir(parents=True)
        (cases_dir / "suite_a" / "ui_case.yml").write_text("case_id: ui_case\ninput: {q: ui}\n")
        (fixtures_dir / "suite_a" / "fix_case.yml").write_text("case_id: fix_case\ninput: {q: fix}\n")

        router = _make_router(cases_dir=cases_dir, fixtures_dir=fixtures_dir)
        client = TestClient(_app(router))
        resp = client.get("/api/eval/suites/suite_a/cases")
        assert resp.status_code == 200
        ids = {c["case_id"] for c in resp.json()}
        assert ids == {"ui_case", "fix_case"}

    def test_ui_case_wins_on_duplicate_case_id(self, tmp_path):
        cases_dir = tmp_path / "cases"
        fixtures_dir = tmp_path / "fixtures"
        (cases_dir / "suite_a").mkdir(parents=True)
        (fixtures_dir / "suite_a").mkdir(parents=True)
        (cases_dir / "suite_a" / "shared.yml").write_text(
            "case_id: shared\ninput: {source: ui}\n"
        )
        (fixtures_dir / "suite_a" / "shared.yml").write_text(
            "case_id: shared\ninput: {source: fixture}\n"
        )

        router = _make_router(cases_dir=cases_dir, fixtures_dir=fixtures_dir)
        client = TestClient(_app(router))
        resp = client.get("/api/eval/suites/suite_a/cases")
        assert resp.status_code == 200
        cases = resp.json()
        assert len(cases) == 1
        assert cases[0]["input"]["source"] == "ui"


# ---------------------------------------------------------------------------
# T05 — DB-backed suites still expose file-backed prompt config
# ---------------------------------------------------------------------------


class _FakeSuiteStore:
    async def list_suites(self):
        return [{"suite_id": "suite_a", "title": "DB Suite A", "case_count": 0}]

    async def get_suite(self, suite_id: str):
        if suite_id != "suite_a":
            return None
        return {
            "suite_id": suite_id,
            "title": "DB Suite A",
            "case_count": 0,
            "active_prompt_version_id": None,
        }


class TestDbBackedSuitePromptConfig:
    def test_default_prompt_appears_in_db_backed_suite_metadata(self, tmp_path):
        router = _make_router(
            cases_dir=tmp_path / "cases",
            suite_store=_FakeSuiteStore(),
        )
        client = TestClient(_app(router))

        save = client.put(
            "/api/eval/suites/suite_a/default-prompt",
            json={"default_system_prompt": "PROMPT FROM FILE CONFIG"},
        )
        assert save.status_code == 200

        detail = client.get("/api/eval/suites/suite_a")
        assert detail.status_code == 200
        assert detail.json()["default_system_prompt"] == "PROMPT FROM FILE CONFIG"

        listed = client.get("/api/eval/suites")
        assert listed.status_code == 200
        assert listed.json()[0]["default_system_prompt"] == "PROMPT FROM FILE CONFIG"


# ---------------------------------------------------------------------------
# T06 — GET /projects — local project
# ---------------------------------------------------------------------------


class TestListProjectsLocal:
    """GET /projects always includes a 'local' project derived from template_registry."""

    def test_local_project_present(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.get("/api/eval/projects")
        assert resp.status_code == 200
        projects = resp.json()
        ids = [p["project_id"] for p in projects]
        assert "local" in ids

    def test_local_project_lists_suite_from_template(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.get("/api/eval/projects")
        local = next(p for p in resp.json() if p["project_id"] == "local")
        assert "suite_a" in local["suite_ids"]
        assert local["remote"] is False

    def test_get_local_project_detail_returns_suites(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.get("/api/eval/projects/local")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "local"
        assert isinstance(data["suites"], list)
        suite_ids = [s["suite_id"] for s in data["suites"]]
        assert "suite_a" in suite_ids

    def test_unknown_project_returns_404(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.get("/api/eval/projects/no_such_project")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# T07 — GET /projects — external project (mocked httpx)
# ---------------------------------------------------------------------------


class TestExternalProject:
    """GET /projects and GET /projects/{id} with a registered ExternalProject."""

    _REMOTE_SUITES = [
        {"suite_id": "crud_matrix_llm", "templates": [], "suite_count": 3},
    ]

    def _mock_httpx(self, payload):
        """Return a context manager mock that yields a response with payload."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    def test_external_project_appears_in_list(self):
        ep = ExternalProject(
            project_id="code-analysis",
            title="prod-grade-code-analysis",
            base_url="http://localhost:8000/api/eval2",
        )
        router = _make_router(external_projects=[ep])
        client = TestClient(_app(router))
        resp = client.get("/api/eval/projects")
        assert resp.status_code == 200
        ids = [p["project_id"] for p in resp.json()]
        assert "local" in ids
        assert "code-analysis" in ids

    def test_external_project_detail_fetches_remote_suites(self):
        ep = ExternalProject(
            project_id="code-analysis",
            title="prod-grade-code-analysis",
            base_url="http://localhost:8000/api/eval2",
        )
        router = _make_router(external_projects=[ep])
        client = TestClient(_app(router))

        mock_client = self._mock_httpx(self._REMOTE_SUITES)
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/eval/projects/code-analysis")

        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "code-analysis"
        assert data["remote"] is True
        assert data["suites"][0]["suite_id"] == "crud_matrix_llm"

    def test_external_project_returns_502_when_remote_unreachable_and_no_cache(self, tmp_path):
        ep = ExternalProject(
            project_id="code-analysis",
            title="prod-grade-code-analysis",
            base_url="http://localhost:8000/api/eval2",
        )
        # tmp_path isolates the cache dir so no stale cache can exist
        router = _make_router(external_projects=[ep], cases_dir=tmp_path / "cases")
        client = TestClient(_app(router))

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/api/eval/projects/code-analysis")

        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# T08 — GET /projects/{id} stale cache fallback
# ---------------------------------------------------------------------------


class TestExternalProjectCacheFallback:
    """When remote is down, GET /projects/{id} returns cached data with stale=True."""

    _EP = ExternalProject(
        project_id="code-analysis",
        title="prod-grade-code-analysis",
        base_url="http://localhost:8000/api/eval2",
    )
    _REMOTE_SUITES = [{"suite_id": "crud_matrix_llm", "templates": []}]

    def _unreachable_mock(self):
        m = AsyncMock()
        m.get = AsyncMock(side_effect=Exception("connection refused"))
        m.__aenter__ = AsyncMock(return_value=m)
        m.__aexit__ = AsyncMock(return_value=False)
        return m

    def _ok_mock(self, payload):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status = MagicMock()
        m = AsyncMock()
        m.get = AsyncMock(return_value=resp)
        m.__aenter__ = AsyncMock(return_value=m)
        m.__aexit__ = AsyncMock(return_value=False)
        return m

    def test_returns_stale_cache_when_remote_down(self, tmp_path):
        router = _make_router(
            external_projects=[self._EP],
            cases_dir=tmp_path / "cases",
        )
        client = TestClient(_app(router))

        # First call succeeds — seeds the cache
        with patch("httpx.AsyncClient", return_value=self._ok_mock(self._REMOTE_SUITES)):
            r1 = client.get("/api/eval/projects/code-analysis")
        assert r1.status_code == 200
        assert r1.json()["stale"] is False

        # Second call — remote down, should fall back to cache
        with patch("httpx.AsyncClient", return_value=self._unreachable_mock()):
            r2 = client.get("/api/eval/projects/code-analysis")
        assert r2.status_code == 200
        data = r2.json()
        assert data["stale"] is True
        assert data["suites"][0]["suite_id"] == "crud_matrix_llm"

    def test_list_projects_shows_cached_suite_count(self, tmp_path):
        router = _make_router(
            external_projects=[self._EP],
            cases_dir=tmp_path / "cases",
        )
        client = TestClient(_app(router))

        # Seed cache via successful fetch
        with patch("httpx.AsyncClient", return_value=self._ok_mock(self._REMOTE_SUITES)):
            client.get("/api/eval/projects/code-analysis")

        # List projects — should show suite_count from cache without hitting remote
        r = client.get("/api/eval/projects")
        ext = next(p for p in r.json() if p["project_id"] == "code-analysis")
        assert ext["suite_count"] == 1
        assert ext["cached_at"] is not None


# ---------------------------------------------------------------------------
# T09 — POST /projects/{id}/sync
# ---------------------------------------------------------------------------


class TestSyncProject:
    """POST /projects/{id}/sync snapshots remote cases into local cases_dir."""

    _EP = ExternalProject(
        project_id="code-analysis",
        title="prod-grade-code-analysis",
        base_url="http://localhost:8000/api/eval2",
    )
    _SUITES = [{"suite_id": "crud_matrix_llm", "templates": []}]
    _CASES = [
        {"case_id": "case1", "input": {"q": "hello"}, "expected": {"verdict": "populated"}, "metadata": {}},
        {"case_id": "case2", "input": {"q": "world"}, "expected": {"verdict": "empty"}, "metadata": {}},
    ]

    def _sync_mock(self):
        """Mock that returns suites on first call, cases on second call."""
        call_count = 0
        async def _get(url, **_):
            nonlocal call_count
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            if call_count == 0:
                resp.json.return_value = self._SUITES
            else:
                resp.json.return_value = self._CASES
            call_count += 1
            return resp
        m = AsyncMock()
        m.get = _get
        m.__aenter__ = AsyncMock(return_value=m)
        m.__aexit__ = AsyncMock(return_value=False)
        return m

    def test_sync_writes_cases_to_cases_dir(self, tmp_path):
        cases_dir = tmp_path / "cases"
        router = _make_router(external_projects=[self._EP], cases_dir=cases_dir)
        client = TestClient(_app(router))

        with patch("httpx.AsyncClient", return_value=self._sync_mock()):
            resp = client.post("/api/eval/projects/code-analysis/sync", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["synced_suites"] == 1
        assert data["synced_cases"] == 2
        assert data["skipped_cases"] == 0
        assert "crud_matrix_llm" in data["suite_ids"]
        assert (cases_dir / "crud_matrix_llm" / "case1.yml").exists()
        assert (cases_dir / "crud_matrix_llm" / "case2.yml").exists()

    def test_sync_marks_source_metadata(self, tmp_path):
        import yaml as _yaml
        cases_dir = tmp_path / "cases"
        router = _make_router(external_projects=[self._EP], cases_dir=cases_dir)
        client = TestClient(_app(router))

        with patch("httpx.AsyncClient", return_value=self._sync_mock()):
            client.post("/api/eval/projects/code-analysis/sync", json={})

        written = _yaml.safe_load((cases_dir / "crud_matrix_llm" / "case1.yml").read_text())
        assert written["metadata"]["source"] == "remote:code-analysis"

    def test_sync_skips_existing_cases_by_default(self, tmp_path):
        cases_dir = tmp_path / "cases"
        (cases_dir / "crud_matrix_llm").mkdir(parents=True)
        (cases_dir / "crud_matrix_llm" / "case1.yml").write_text("case_id: case1\ninput: {q: existing}\n")

        router = _make_router(external_projects=[self._EP], cases_dir=cases_dir)
        client = TestClient(_app(router))

        with patch("httpx.AsyncClient", return_value=self._sync_mock()):
            resp = client.post("/api/eval/projects/code-analysis/sync", json={})

        data = resp.json()
        assert data["synced_cases"] == 1   # only case2 written
        assert data["skipped_cases"] == 1  # case1 skipped

    def test_sync_overwrites_when_flag_set(self, tmp_path):
        cases_dir = tmp_path / "cases"
        (cases_dir / "crud_matrix_llm").mkdir(parents=True)
        (cases_dir / "crud_matrix_llm" / "case1.yml").write_text("case_id: case1\ninput: {q: old}\n")

        router = _make_router(external_projects=[self._EP], cases_dir=cases_dir)
        client = TestClient(_app(router))

        with patch("httpx.AsyncClient", return_value=self._sync_mock()):
            resp = client.post("/api/eval/projects/code-analysis/sync", json={"overwrite": True})

        data = resp.json()
        assert data["synced_cases"] == 2
        assert data["skipped_cases"] == 0

    def test_sync_unknown_project_returns_404(self):
        router = _make_router()
        client = TestClient(_app(router))
        resp = client.post("/api/eval/projects/no_such/sync", json={})
        assert resp.status_code == 404
