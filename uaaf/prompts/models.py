"""Prompt versioning models — PromptConfig, PromptTemplate, ToolDefinition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromptTemplate:
    """One named prompt with a system and optional user template."""
    system: str
    user: str = "{query}"

    def render_system(self, **variables: Any) -> str:
        return _safe_format(self.system, **variables)

    def render_user(self, **variables: Any) -> str:
        return _safe_format(self.user, **variables)


@dataclass(frozen=True)
class ToolDefinition:
    """Schema (JSON Schema) for one LLM tool — maps to OpenAI function calling format."""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_openai_schema(self) -> dict[str, Any]:
        """Return the dict that OpenAI's `tools` parameter expects."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class PromptConfig:
    """Fully loaded prompt configuration for one project version."""
    version: str
    description: str
    model: str
    temperature: float
    max_tokens: int
    prompts: dict[str, PromptTemplate]
    tools: list[ToolDefinition] = field(default_factory=list)

    def get_prompt(self, name: str) -> PromptTemplate:
        if name not in self.prompts:
            raise KeyError(f"Prompt '{name}' not found. Available: {list(self.prompts)}")
        return self.prompts[name]

    def tools_schema(self) -> list[dict[str, Any]]:
        """Return all tool schemas in OpenAI function-calling format."""
        return [t.to_openai_schema() for t in self.tools]

    def tool_by_name(self, name: str) -> ToolDefinition | None:
        return next((t for t in self.tools if t.name == name), None)


# ---------------------------------------------------------------------------
# Template rendering — safe: unknown variables stay as {placeholder}
# ---------------------------------------------------------------------------

import string  # noqa: E402


class _SafeFormatter(string.Formatter):
    """Formatter that leaves unknown {placeholders} intact."""

    def get_value(self, key: int | str, args: Any, kwargs: Any) -> Any:
        try:
            return super().get_value(key, args, kwargs)
        except (KeyError, IndexError):
            return "{" + str(key) + "}"


_formatter = _SafeFormatter()


def _safe_format(template: str, **variables: Any) -> str:
    """Format *template* with *variables*, leaving unknown placeholders unchanged."""
    return _formatter.format(template, **variables)
