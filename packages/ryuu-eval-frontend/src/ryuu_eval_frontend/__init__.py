"""ryuu-eval-frontend — pre-built eval workbench UI.

This package is pure static assets (HTML/JS/CSS) bundled cho ryuu-eval to
serve via FastAPI. No Python code beyond this docstring và data-files loader.

See ``ryuu_eval.http.ui.mount_ui()`` for serving.
"""

from importlib.resources import files

__version__ = "0.1.0a1"


def dist_dir():
    """Return the dist/ resource container (importlib Traversable)."""
    return files("ryuu_eval_frontend") / "dist"


__all__ = ["dist_dir"]
