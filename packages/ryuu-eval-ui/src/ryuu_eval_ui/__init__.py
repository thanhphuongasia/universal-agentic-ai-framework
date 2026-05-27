"""ryuu-eval-ui — React eval workbench UI.

Static assets (HTML/JS/CSS) built by Vite, served via FastAPI by
``ryuu_eval.http.ui.mount_ui()``.  No Python logic beyond this loader.
"""

from importlib.resources import files

__version__ = "0.2.0a1"


def dist_dir():
    """Return the dist/ resource container (importlib Traversable)."""
    return files("ryuu_eval_ui") / "dist"


__all__ = ["dist_dir"]
