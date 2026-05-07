"""PromptRegistry — loads versioned YAML prompt configs and builds CompletionRequests.

Usage::

    registry = PromptRegistry(prompts_root=Path("prompts"))
    cfg = registry.load("todo_app")           # loads prompts/todo_app/v1.yaml by default
    cfg = registry.load("todo_app", "v2")     # explicit version

    messages = registry.messages(cfg, "analyze", context="...", query="...")
    request = registry.build_request(cfg, "analyze", context="...", query="...")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from uaaf.prompts.models import PromptConfig, PromptTemplate, ToolDefinition
from uaaf.providers.llm import CompletionRequest, Message


class PromptRegistry:
    """Load + cache YAML prompt configs; render CompletionRequests."""

    def __init__(self, prompts_root: Path) -> None:
        self._root = prompts_root
        self._cache: dict[str, PromptConfig] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, project: str, version: str = "v1") -> PromptConfig:
        """Load (and cache) a prompt config.

        Looks for: ``{prompts_root}/{project}/{version}.yaml``
        """
        cache_key = f"{project}/{version}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        yaml_path = self._root / project / f"{version}.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {yaml_path}\n"
                f"Create it or check prompts_root={self._root}"
            )

        with yaml_path.open() as fh:
            raw = yaml.safe_load(fh)

        config = self._parse(raw)
        self._cache[cache_key] = config
        return config

    @staticmethod
    def _parse(raw: dict[str, Any]) -> PromptConfig:
        prompts: dict[str, PromptTemplate] = {}
        for name, tmpl in raw.get("prompts", {}).items():
            prompts[name] = PromptTemplate(
                system=tmpl.get("system", ""),
                user=tmpl.get("user", "{query}"),
            )

        tools: list[ToolDefinition] = []
        for t in raw.get("tools", []):
            tools.append(ToolDefinition(
                name=t["name"],
                description=t["description"],
                parameters=t.get("parameters", {}),
            ))

        return PromptConfig(
            version=str(raw.get("version", "1.0")),
            description=raw.get("description", ""),
            model=raw.get("model", "gpt-4o-mini"),
            temperature=float(raw.get("temperature", 0.1)),
            max_tokens=int(raw.get("max_tokens", 1024)),
            prompts=prompts,
            tools=tools,
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def messages(
        self,
        config: PromptConfig,
        prompt_name: str,
        **variables: Any,
    ) -> list[Message]:
        """Render system + user messages for *prompt_name* with *variables*."""
        tmpl = config.get_prompt(prompt_name)
        return [
            Message(role="system", content=tmpl.render_system(**variables)),
            Message(role="user", content=tmpl.render_user(**variables)),
        ]

    def build_request(
        self,
        config: PromptConfig,
        prompt_name: str,
        include_tools: bool = True,
        extra_messages: list[Message] | None = None,
        **variables: Any,
    ) -> CompletionRequest:
        """Build a ready-to-send CompletionRequest."""
        msgs = self.messages(config, prompt_name, **variables)
        if extra_messages:
            msgs = msgs + extra_messages

        return CompletionRequest(
            messages=msgs,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            tools=config.tools_schema() if include_tools and config.tools else None,
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_versions(self, project: str) -> list[str]:
        """Return available version names for *project*."""
        project_dir = self._root / project
        if not project_dir.exists():
            return []
        return sorted(p.stem for p in project_dir.glob("*.yaml"))

    def list_projects(self) -> list[str]:
        """Return all project names in the registry."""
        return sorted(d.name for d in self._root.iterdir() if d.is_dir())
