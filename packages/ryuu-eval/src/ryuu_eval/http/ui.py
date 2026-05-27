"""Static UI mount — serves ryuu-eval-ui dist/ at <prefix>/ui.

Project mounts via ``serve_ui=True`` param on build_eval_router. User opens
``http://localhost:8000/api/eval/ui`` → working eval workbench.

Requires the ``ryuu-eval-ui`` companion package installed alongside
``ryuu-eval`` (separately versioned for independent UI iteration). When
ryuu-eval-ui isn't installed, ``serve_ui=True`` raises ImportError
at router build time with install hint.
"""

from __future__ import annotations

import json
import mimetypes
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse, Response
except ImportError as exc:
    raise ImportError(
        "FastAPI required for ryuu_eval.http.ui. Install: pip install fastapi"
    ) from exc


def _load_frontend_dist() -> Any:
    """Load ryuu_eval_ui.dist_dir() — raise actionable error if missing."""
    try:
        from ryuu_eval_ui import dist_dir
    except ImportError as exc:
        raise ImportError(
            "ryuu-eval-ui package not installed. To enable serve_ui:\n"
            "    pip install ryuu-eval-ui\n"
            f"(Original error: {exc})"
        ) from exc
    return dist_dir()


def _read_vite_manifest(dist: Any) -> dict:
    """Read Vite manifest.json to resolve hashed asset paths.

    Vite 5 writes manifest to dist/.vite/manifest.json.
    Falls back to dist/manifest.json for older Vite configs.
    Returns {} if no manifest found (development / legacy bundle).
    """
    for candidate in [".vite/manifest.json", "manifest.json"]:
        try:
            return json.loads((dist / candidate).read_text(encoding="utf-8"))
        except (FileNotFoundError, TypeError):
            continue
    return {}


def mount_ui(router: APIRouter, *, prefix: str = "/ui") -> None:
    """Mount static UI files at ``<prefix>``.

    Reads Vite's manifest.json to serve hashed asset filenames.
    Falls back to glob-based asset serving when no manifest is present.

    Args:
        router: APIRouter to extend (typically from build_eval_router).
        prefix: Mount point relative to router prefix. Default "/ui" →
                if router mounted at "/api/eval" → UI served at "/api/eval/ui".
    """
    dist = _load_frontend_dist()
    _read_vite_manifest(dist)  # reserved for future asset injection

    # Read once at mount time — files are static, no need to re-read per request.
    index_html = (dist / "index.html").read_text(encoding="utf-8")

    # No-trailing-slash → redirect so browser resolves relative asset URLs correctly.
    @router.get(prefix, include_in_schema=False)
    def _serve_index_redirect(request: Request) -> RedirectResponse:
        target = request.url.path + "/"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(url=target, status_code=307)

    @router.get(f"{prefix}/", response_class=HTMLResponse, include_in_schema=False)
    def _serve_index() -> str:
        return index_html

    # Generic asset handler — covers Vite hashed filenames (index-Cd3j8aXk.js etc.)
    @router.get(prefix + "/{asset_path:path}", include_in_schema=False)
    def _serve_asset(asset_path: str) -> Response:
        # Security: reject path traversal
        if ".." in asset_path or asset_path.startswith("/"):
            raise HTTPException(404, "Not found")
        target = dist / asset_path
        try:
            content = target.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            raise HTTPException(404, f"Asset not found: {asset_path}")
        mime, _ = mimetypes.guess_type(asset_path)
        cache = "no-cache, must-revalidate" if asset_path.endswith((".html", ".json")) else "public, max-age=31536000, immutable"
        return Response(
            content=content,
            media_type=mime or "application/octet-stream",
            headers={"Cache-Control": cache},
        )


__all__ = ["mount_ui"]
