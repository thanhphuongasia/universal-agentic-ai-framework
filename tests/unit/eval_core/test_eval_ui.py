"""Tests for ryuu_eval.http.ui — static UI serving (ryuu-eval-ui package)."""

from __future__ import annotations

import re
import unittest

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from ryuu_eval.http.ui import mount_ui


def _client(prefix: str = "/ui") -> TestClient:
    router = APIRouter()
    mount_ui(router, prefix=prefix)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _js_path_from_html(html: str) -> str | None:
    """Extract first <script src> from index.html (handles hashed Vite filenames)."""
    m = re.search(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html)
    return m.group(1).lstrip("/") if m else None


def _css_path_from_html(html: str) -> str | None:
    """Extract first <link rel=stylesheet> href from index.html."""
    m = re.search(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+\.css)["\']', html)
    if not m:
        m = re.search(r'<link[^>]+href=["\']([^"\']+\.css)["\'][^>]+rel=["\']stylesheet["\']', html)
    return m.group(1).lstrip("/") if m else None


class MountUITests(unittest.TestCase):
    def test_index_html_redirect_then_serve(self) -> None:
        client = _client()
        # /ui (no slash) → 307 redirect
        resp_redir = client.get("/ui", follow_redirects=False)
        assert resp_redir.status_code == 307
        assert resp_redir.headers["location"].endswith("/ui/")
        # /ui/ → 200 HTML
        resp = client.get("/ui/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_index_html_contains_mount_point(self) -> None:
        client = _client()
        resp = client.get("/ui/")
        # Both the old Preact bundle and new React build use this root div.
        assert "ryuu-eval-root" in resp.text

    def test_js_bundle_served(self) -> None:
        client = _client()
        html = client.get("/ui/").text
        js_path = _js_path_from_html(html)
        assert js_path, "index.html must contain a <script src=...js> tag"
        resp = client.get(f"/ui/{js_path}")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]
        assert "cache-control" in resp.headers

    def test_css_served(self) -> None:
        client = _client()
        html = client.get("/ui/").text
        css_path = _css_path_from_html(html)
        assert css_path, "index.html must contain a <link rel=stylesheet> tag"
        resp = client.get(f"/ui/{css_path}")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    def test_path_traversal_rejected(self) -> None:
        client = _client()
        resp = client.get("/ui/../../etc/passwd")
        # FastAPI normalises ".." in URL path → either 404 or 422 — both safe.
        assert resp.status_code in (404, 422)

    def test_unknown_asset_404(self) -> None:
        client = _client()
        resp = client.get("/ui/nonexistent.png")
        assert resp.status_code == 404

    def test_custom_prefix(self) -> None:
        client = _client(prefix="/workbench")
        resp = client.get("/workbench/")
        assert resp.status_code == 200
        # Original /ui must NOT be served under custom prefix.
        resp404 = client.get("/ui/")
        assert resp404.status_code == 404

    def test_hashed_asset_immutable_cache(self) -> None:
        """Vite hashed filenames (contain a hash) get immutable cache headers."""
        client = _client()
        html = client.get("/ui/").text
        js_path = _js_path_from_html(html)
        if js_path and re.search(r"-[A-Za-z0-9]{8,}\.", js_path):
            resp = client.get(f"/ui/{js_path}")
            assert "immutable" in resp.headers.get("cache-control", "")


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
