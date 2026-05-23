"""Tests for ryuu_eval.http.ui — Tier 1 frontend serving."""

from __future__ import annotations

import unittest
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ryuu_eval.http.ui import mount_ui


class MountUITests(unittest.TestCase):
    def _client(self, prefix: str = "/ui") -> TestClient:
        router = APIRouter()
        mount_ui(router, prefix=prefix)
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_index_html_served(self) -> None:
        client = self._client()
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "ryuu-eval-root" in resp.text
        assert "ryuu-eval.js" in resp.text

    def test_index_html_trailing_slash(self) -> None:
        client = self._client()
        resp = client.get("/ui/")
        assert resp.status_code == 200
        assert "ryuu-eval-root" in resp.text

    def test_js_bundle_served(self) -> None:
        client = self._client()
        resp = client.get("/ui/ryuu-eval.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]
        assert "EvalApp" in resp.text  # component defined in JS
        # Cache-Control header set
        assert "max-age" in resp.headers.get("cache-control", "")

    def test_css_served(self) -> None:
        client = self._client()
        resp = client.get("/ui/ryuu-eval.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]
        assert ".eval-app" in resp.text  # CSS class defined

    def test_path_traversal_rejected(self) -> None:
        client = self._client()
        resp = client.get("/ui/../../etc/passwd")
        # FastAPI normalizes ".." in URL path → either 404 or 422 — both safe
        assert resp.status_code in (404, 422)

    def test_unknown_asset_404(self) -> None:
        client = self._client()
        resp = client.get("/ui/nonexistent.png")
        assert resp.status_code == 404

    def test_custom_prefix(self) -> None:
        client = self._client(prefix="/workbench")
        resp = client.get("/workbench")
        assert resp.status_code == 200
        # Original /ui must NOT be served
        resp404 = client.get("/ui")
        assert resp404.status_code == 404


class ServeUIFlagTests(unittest.TestCase):
    def test_serve_ui_false_no_routes(self) -> None:
        from ryuu_eval_core import EvalCaseTemplate, EvalRunner
        from ryuu_eval.http import build_eval_router

        tpl = EvalCaseTemplate(template_id="t", suite_id="s", title="T")
        router = build_eval_router(
            runner_factory=lambda s, p: EvalRunner(suite_id=s, target=None, scorers=[]),
            template_registry={"t": tpl},
            serve_ui=False,
        )
        ui_routes = [r.path for r in router.routes if r.path.startswith("/ui")]
        assert ui_routes == []

    def test_serve_ui_true_mounts(self) -> None:
        from ryuu_eval_core import EvalCaseTemplate, EvalRunner
        from ryuu_eval.http import build_eval_router

        tpl = EvalCaseTemplate(template_id="t", suite_id="s", title="T")
        router = build_eval_router(
            runner_factory=lambda s, p: EvalRunner(suite_id=s, target=None, scorers=[]),
            template_registry={"t": tpl},
            serve_ui=True,
        )
        ui_paths = [r.path for r in router.routes if "/ui" in r.path]
        assert any("/ui" == p or "/ui/" == p for p in ui_paths)


if __name__ == "__main__":
    unittest.main()
