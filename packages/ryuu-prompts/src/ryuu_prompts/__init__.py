"""ryuu-prompts — Versioned YAML prompt management for the Ryuu framework.

Public API:
    PromptRegistry         — load YAML, cache, build CompletionRequest
    PromptConfig           — parsed config (model, temperature, prompts, tools)
    PromptTemplate         — one system+user template pair with safe formatting
    ToolDefinition         — JSON-schema tool def, → OpenAI function-calling
    make_framework_registry — factory that wires all installed ryuu-* packages
    package_default_root   — resolve a package's shipped prompts/ folder

Multi-root support: pass `prompts_roots=[user_dir, default_dir]` to enable
layered overlay. First match wins, so user dir overrides framework defaults.
"""

from ryuu_prompts.models import (
    PromptConfig,
    PromptTemplate,
    ToolDefinition,
)
from ryuu_prompts.registry import (
    PromptRegistry,
    make_framework_registry,
    package_default_root,
)
from ryuu_prompts.skills import (
    PromptSkill,
    PromptSkillRegistry,
    PromptSkillsToolset,
    list_prompt_skills_tool,
    parse_skill_file,
)

__version__ = "0.3.0a2"

__all__ = [
    "PromptConfig",
    "PromptRegistry",
    "PromptTemplate",
    "ToolDefinition",
    "make_framework_registry",
    "package_default_root",
    # Phase 8.12 — Prompt Skills (Claude Code-style task templates)
    "PromptSkill",
    "PromptSkillRegistry",
    "PromptSkillsToolset",
    "parse_skill_file",
    "list_prompt_skills_tool",
]
