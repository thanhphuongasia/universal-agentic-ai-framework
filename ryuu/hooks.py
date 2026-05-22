"""Backward-compat shim. Canonical source: `ryuu_hooks`.

Old imports continue to work:
    from ryuu.hooks import HookEvent, HookRegistry, PreLLMContext, …

New code should prefer:
    from ryuu_hooks import HookEvent, HookRegistry, PreLLMContext, …
"""

from ryuu_hooks.hooks import *  # noqa: F401,F403
from ryuu_hooks.hooks import __all__ as _hooks_all

__all__ = list(_hooks_all)
