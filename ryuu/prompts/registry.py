"""Backward-compat shim. Canonical source: `ryuu_prompts.registry`."""

from ryuu_prompts.registry import (
    PromptRegistry,
    make_framework_registry,
    package_default_root,
)

__all__ = ["PromptRegistry", "make_framework_registry", "package_default_root"]
