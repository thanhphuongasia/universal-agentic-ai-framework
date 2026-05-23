"""Prompt Skills — Claude Code-style task templates (Phase 8.12).

A "prompt skill" is a markdown file with YAML frontmatter declaring:
  • name        — unique slug
  • description — one-liner for the skill catalog
  • triggers    — phrases the LLM matches against the user message
  • requires_tools — tools the skill depends on (informational; LLM checks)

The body (markdown after frontmatter) is the actual instructions the LLM
follows when the user request matches.

Difference vs `PromptRegistry`:
  • PromptRegistry → versioned LLM call templates (YAML, system+user+tools)
                     used by framework primitives (LLMCompactor, etc.)
  • PromptSkill    → user-defined reusable task patterns the LLM picks up
                     autonomously based on conversational triggers

Quick start:

    registry = PromptSkillRegistry.from_dirs([
        Path("~/.ryuu/skills"),         # user shadow (wins on name collision)
        Path("./skills"),                # bundled defaults
    ])
    skill_block = registry.render_context()
    system_prompt = soul + "\\n\\n" + skill_block
"""

from ryuu_prompts.skills.registry import PromptSkillRegistry
from ryuu_prompts.skills.skill import PromptSkill, parse_skill_file
from ryuu_prompts.skills.tools import (
    PromptSkillsToolset,
    list_prompt_skills_tool,
)

__all__ = [
    "PromptSkill",
    "PromptSkillRegistry",
    "parse_skill_file",
    "PromptSkillsToolset",
    "list_prompt_skills_tool",
]
