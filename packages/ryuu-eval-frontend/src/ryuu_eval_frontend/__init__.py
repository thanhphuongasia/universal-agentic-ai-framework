"""DEPRECATED — use ryuu-eval-ui instead.

This package is a backward-compatibility shim. It re-exports ``dist_dir``
from ``ryuu_eval_ui`` so that existing code continues to work without changes
for one release cycle.

Migration:
    pip uninstall ryuu-eval-frontend
    pip install ryuu-eval-ui
    # In code: change ``from ryuu_eval_frontend import dist_dir``
    #       to ``from ryuu_eval_ui import dist_dir``
"""

import warnings

warnings.warn(
    "ryuu-eval-frontend is deprecated. Use ryuu-eval-ui instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ryuu_eval_ui import dist_dir as dist_dir  # noqa: E402, F401

__version__ = "0.2.0"
__all__ = ["dist_dir"]
