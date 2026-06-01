"""PromptRegistry — loads versioned YAML prompt configs and builds CompletionRequests.

Supports multi-root layered overlay (E2):

    registry = PromptRegistry(prompts_roots=[
        Path("~/.ryuu/prompts").expanduser(),  # user override (highest priority)
        package_default_root("ryuu_cognitive"),
        package_default_root("ryuu_runtime"),
    ])

For each `load(project, version)` the registry walks roots in order; first
match wins. This lets users shadow framework defaults without touching code.

Backward-compatible single-root API:
    registry = PromptRegistry(prompts_root=Path("./prompts"))

Usage:
    cfg = registry.load("todo_app")           # loads first matching v1.yaml
    cfg = registry.load("todo_app", "v2")     # explicit version
    msgs = registry.messages(cfg, "analyze", context="...", query="...")
    request = registry.build_request(cfg, "analyze", context="...", query="...")
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Any

import yaml

from ryuu_providers.llm import CompletionRequest, Message

from ryuu_prompts.models import PromptConfig


class PromptRegistry:
    """Load + cache YAML prompt configs from one or more roots; render CompletionRequests."""

    def __init__(
        self,
        prompts_root: Path | None = None,
        *,
        prompts_roots: list[Path] | None = None,
    ) -> None:
        """Initialize with either a single root (back-compat) or a list of roots.

        Roots are checked in order — first match wins. Put user-override
        directories FIRST and framework defaults LAST.
        """
        if prompts_root is not None and prompts_roots is not None:
            raise ValueError("Pass either prompts_root or prompts_roots, not both")
        if prompts_roots is None:
            if prompts_root is None:
                raise ValueError("Must provide prompts_root or prompts_roots")
            prompts_roots = [prompts_root]
        self._roots = [Path(p) for p in prompts_roots]
        self._cache: dict[str, PromptConfig] = {}

    # ------------------------------------------------------------------
    # Single-root accessor (back-compat — most existing code uses this name)
    # ------------------------------------------------------------------
    @property
    def prompts_root(self) -> Path:
        """The first root. Kept for back-compat with single-root callers."""
        return self._roots[0]

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, project: str, version: str = "v1") -> PromptConfig:
        """Load (and cache) a prompt config. Walks roots in order — first match wins.

        Looks for: ``{root}/{project}/{version}.yaml`` across all roots.
        """
        cache_key = f"{project}/{version}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        last_path: Path | None = None
        for root in self._roots:
            yaml_path = root / project / f"{version}.yaml"
            last_path = yaml_path
            if yaml_path.exists():
                with yaml_path.open() as fh:
                    raw = yaml.safe_load(fh)
                config = self._parse(raw)
                self._cache[cache_key] = config
                return config

        # Not found in any root — surface the search path that was tried
        searched = "\n  ".join(str(r / project / f"{version}.yaml") for r in self._roots)
        raise FileNotFoundError(
            f"Prompt file '{project}/{version}.yaml' not found in any root.\n"
            f"Searched:\n  {searched}"
        )

    @staticmethod
    def _parse(raw: dict[str, Any]) -> PromptConfig:
        # YAML row and `prompt_versions.config` JSONB share one shape — keep the
        # parse logic in one place (PromptConfig.from_dict).
        return PromptConfig.from_dict(raw)

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
        """Return available version names for *project* (union across all roots)."""
        versions: set[str] = set()
        for root in self._roots:
            project_dir = root / project
            if project_dir.exists():
                versions.update(p.stem for p in project_dir.glob("*.yaml"))
        return sorted(versions)

    def list_projects(self) -> list[str]:
        """Return all project names found in any root."""
        projects: set[str] = set()
        for root in self._roots:
            if root.exists():
                projects.update(d.name for d in root.iterdir() if d.is_dir())
        return sorted(projects)


# ---------------------------------------------------------------------------
# Framework registry factory (E2)
# ---------------------------------------------------------------------------

_FRAMEWORK_PACKAGES = (
    "ryuu_cognitive",
    "ryuu_runtime",
    "ryuu_intent",
)


def package_default_root(package: str) -> Path | None:
    """Return the package's shipped prompts/ dir, or None if it doesn't ship any."""
    try:
        traversable = importlib.resources.files(package) / "prompts"
        # MultiplexedPath / Path — only return if it's a real on-disk Path
        path_str = str(traversable)
        p = Path(path_str)
        return p if p.exists() else None
    except (ModuleNotFoundError, FileNotFoundError):
        return None


def make_framework_registry(
    *,
    user_overrides_root: Path | None = None,
    extra_roots: list[Path] | None = None,
) -> PromptRegistry:
    """Build a registry covering all framework packages + user overrides.

    Search order (first match wins):
      1. user_overrides_root (if provided) — user shadows everything
      2. extra_roots (if provided) — app-specific
      3. ryuu_cognitive package data
      4. ryuu_runtime package data
      5. ryuu_intent package data

    Any non-existent path is silently skipped.
    """
    roots: list[Path] = []
    if user_overrides_root is not None:
        roots.append(Path(user_overrides_root).expanduser())
    if extra_roots:
        roots.extend(Path(p) for p in extra_roots)
    for pkg in _FRAMEWORK_PACKAGES:
        p = package_default_root(pkg)
        if p is not None:
            roots.append(p)
    if not roots:
        raise RuntimeError(
            "make_framework_registry() found no prompt roots. "
            "Ensure at least one ryuu-* package is installed with shipped prompts."
        )
    return PromptRegistry(prompts_roots=roots)
