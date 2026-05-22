"""ryuu-hooks — Hook System for dynamic lifecycle injection.

Pattern inspired by Claude Agent SDK. Hooks let product code inject behavior
at agent lifecycle points without subclassing BaseAgent. Common use cases:
PII scrub, approval workflow, custom metric emission, request modification.

Re-exports the whole public API of `ryuu_hooks.hooks`:
    from ryuu_hooks import HookEvent, HookRegistry, PreLLMContext, …
"""

from ryuu_hooks.hooks import *  # noqa: F401,F403
from ryuu_hooks.hooks import __all__ as _hooks_all

__version__ = "0.3.0a1"

__all__ = list(_hooks_all)
