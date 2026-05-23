"""ITool wrappers around PromptSkillRegistry — let LLM/user inspect skills.

The skills themselves are NOT tools — they're prompt fragments. But "what
skills are available" is useful to expose so the LLM can recommend matching
skills when the user is unsure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ryuu_prompts.skills.registry import PromptSkillRegistry


@dataclass
class _ListPromptSkillsTool:
    registry: PromptSkillRegistry
    tool_id: str = "list_prompt_skills"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "list_prompt_skills",
                "description": (
                    "List reusable task patterns (prompt skills) the bot can apply. "
                    "Use when the user asks 'what can you do', 'list skills', or "
                    "to recommend a workflow matching their need."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "triggers": list(s.triggers),
                    "requires_tools": list(s.requires_tools),
                }
                for s in self.registry
            ],
            "total": len(self.registry),
        }


@dataclass
class _ReloadPromptSkillsTool:
    registry: PromptSkillRegistry
    tool_id: str = "reload_prompt_skills"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "reload_prompt_skills",
                "description": (
                    "Re-scan the skills directories on disk and pick up any new "
                    "or edited *.md skill files. Use after the user mentions they "
                    "edited a skill file or added a new one."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        reloaded = self.registry.reload_if_changed()
        return {
            "ok": True,
            "reloaded": reloaded > 0,
            "total_skills": len(self.registry),
            "skill_names": self.registry.names(),
        }


@dataclass
class PromptSkillsToolset:
    """Bundle of inspection tools for the prompt-skill catalog.

    Drop into `Agent(tools=[..., *skills_toolset.tools])`.
    """
    registry: PromptSkillRegistry
    _tools: list[Any] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._tools = [
            _ListPromptSkillsTool(registry=self.registry),
            _ReloadPromptSkillsTool(registry=self.registry),
        ]

    @property
    def tools(self) -> list[Any]:
        return list(self._tools)


# Convenience function for callers who want just the one tool
def list_prompt_skills_tool(registry: PromptSkillRegistry) -> _ListPromptSkillsTool:
    return _ListPromptSkillsTool(registry=registry)


__all__ = ["PromptSkillsToolset", "list_prompt_skills_tool"]
