"""Backward-compat shim — canonical source is `ryuu-prompts` standalone package.

Old imports continue to work:
    from ryuu.prompts.registry import PromptRegistry      # OK
    from ryuu.prompts.models import PromptConfig          # OK
    from ryuu.prompts import PromptRegistry, PromptConfig # OK (preferred)

New code should use `from ryuu_prompts import ...` directly.
"""

from ryuu_prompts import (
    PromptConfig,
    PromptRegistry,
    PromptTemplate,
    ToolDefinition,
    make_framework_registry,
    package_default_root,
)

__all__ = [
    "PromptConfig",
    "PromptRegistry",
    "PromptTemplate",
    "ToolDefinition",
    "make_framework_registry",
    "package_default_root",
]
