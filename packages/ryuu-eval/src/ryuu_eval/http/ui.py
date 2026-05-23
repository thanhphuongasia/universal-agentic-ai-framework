"""Static UI mount — serves ryuu-eval-frontend dist/ at <prefix>/ui.

Project mounts via ``serve_ui=True`` param on build_eval_router. User opens
``http://localhost:8000/api/eval/ui`` → working eval workbench.

Requires the ``ryuu-eval-frontend`` companion package installed alongside
``ryuu-eval`` (separately versioned for independent UI iteration). When
ryuu-eval-frontend isn't installed, ``serve_ui=True`` raises ImportError
at router build time với install hint.
"""

from __future__ import annotations

import mimetypes
from typing import Any

try:
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import HTMLResponse, Response
except ImportError as exc:
    raise ImportError(
        "FastAPI required for ryuu_eval.http.ui. Install: pip install fastapi"
    ) from exc


def _load_frontend_dist() -> Any:
    """Load ryuu_eval_frontend.dist_dir() — raise actionable error if missing."""
    try:
        from ryuu_eval_frontend import dist_dir
    except ImportError as exc:
        raise ImportError(
            "ryuu-eval-frontend package not installed. To enable serve_ui:\n"
            "    pip install ryuu-eval-frontend\n"
            f"(Original error: {exc})"
        ) from exc
    return dist_dir()


def mount_ui(router: APIRouter, *, prefix: str = "/ui") -> None:
    """Mount static UI files at ``<prefix>``.

    Three routes added:
      GET <prefix>              → index.html
      GET <prefix>/ryuu-eval.js  → JS bundle
      GET <prefix>/ryuu-eval.css → CSS

    Args:
        router: APIRouter to extend (typically from build_eval_router).
        prefix: Mount point relative to router prefix. Default "/ui" →
                if router mounted at "/api/eval" → UI served at "/api/eval/ui".
    """
    dist = _load_frontend_dist()

    # Read once at mount time — files are static, no need to re-read per request
    index_html = (dist / "index.html").read_text(encoding="utf-8")
    js_content = (dist / "ryuu-eval.js").read_text(encoding="utf-8")
    css_content = (dist / "ryuu-eval.css").read_text(encoding="utf-8")

    @router.get(prefix, response_class=HTMLResponse, include_in_schema=False)
    def _serve_index() -> str:
        return index_html

    # Trailing-slash variant (browsers may navigate to /ui/)
    @router.get(f"{prefix}/", response_class=HTMLResponse, include_in_schema=False)
    def _serve_index_slash() -> str:
        return index_html

    @router.get(f"{prefix}/ryuu-eval.js", include_in_schema=False)
    def _serve_js() -> Response:
        return Response(
            content=js_content,
            media_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @router.get(f"{prefix}/ryuu-eval.css", include_in_schema=False)
    def _serve_css() -> Response:
        return Response(
            content=css_content,
            media_type="text/css; charset=utf-8",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # Generic asset fallback (for future assets — images, fonts, etc.)
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
        return Response(
            content=content,
            media_type=mime or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )


__all__ = ["mount_ui"]
