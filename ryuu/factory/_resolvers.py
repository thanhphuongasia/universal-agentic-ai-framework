"""Validation + prompt resolution helpers for Agent factory.

Module-level functions taking Agent instance. Extracted from agent.py to
keep main class file focused. Each function may mutate the Agent's fields
(file paths → str, YAML prompt → resolved system/user_template).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ryuu.prompts.registry import PromptRegistry

if TYPE_CHECKING:
    from ryuu.factory.agent import Agent


def validate(agent: "Agent") -> None:
    """Validate Agent fields. Raises ValueError on misuse.

    Covers:
      - model required, non-empty (or non-empty list)
      - budget_usd / budget_tokens / rate_limit_rps / max_tokens positive
      - max_iterations ≥ 1, temperature ∈ [0, 2]
      - kwargs (thinking_mode / n_samples / adaptive_compute) vs strategy= mutual exclusion
      - n_samples ≥ 1
      - tools= vs tool_registry= mutual exclusion (Mode A/B vs Mode C)
      - instructions vs system mutual exclusion (Mode 1 vs Mode 2)
      - examples item shape: dict with 'user' + 'assistant' keys
    """
    if not agent.model:
        raise ValueError("model is required (non-empty string or list)")
    if isinstance(agent.model, list) and len(agent.model) == 0:
        raise ValueError("model list cannot be empty")
    if agent.budget_usd is not None and agent.budget_usd <= 0:
        raise ValueError(f"budget_usd must be positive, got {agent.budget_usd}")
    if agent.budget_tokens is not None and agent.budget_tokens <= 0:
        raise ValueError(f"budget_tokens must be positive, got {agent.budget_tokens}")
    if agent.rate_limit_rps is not None and agent.rate_limit_rps <= 0:
        raise ValueError(f"rate_limit_rps must be positive, got {agent.rate_limit_rps}")
    if agent.max_tokens is not None and agent.max_tokens <= 0:
        raise ValueError(f"max_tokens must be positive, got {agent.max_tokens}")
    if agent.max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {agent.max_iterations}")
    if not 0.0 <= agent.temperature <= 2.0:
        raise ValueError(f"temperature must be in [0.0, 2.0], got {agent.temperature}")

    # Phase 14.x — kwargs vs strategy= mutual exclusion
    kwargs_active = agent.thinking_mode or agent.n_samples > 1 or agent.adaptive_compute
    if agent.strategy is not None and kwargs_active:
        raise ValueError(
            "Cannot mix `strategy=` (explicit) with kwargs "
            "(thinking_mode / n_samples / adaptive_compute). "
            "Pick one: kwargs convenience OR explicit strategy instance."
        )
    if agent.n_samples < 1:
        raise ValueError(f"n_samples must be >= 1, got {agent.n_samples}")

    # Mode C validation — tools + tool_registry mutually exclusive
    if agent.tools and agent.tool_registry is not None:
        raise ValueError(
            "Cannot mix `tools=` (Mode A/B) and `tool_registry=` (Mode C). "
            "Pick one — pre-built registry skips list introspection."
        )

    # Mode 2 validation — instructions vs system
    if agent.instructions and agent.system is not None:
        raise ValueError(
            "Cannot mix Mode 1 (`instructions=`) and Mode 2 (`system=`). "
            "Pick one — `instructions` is shorthand for `system`."
        )
    if agent.examples is not None:
        for i, ex in enumerate(agent.examples):
            if not isinstance(ex, dict) or "user" not in ex or "assistant" not in ex:
                raise ValueError(
                    f"examples[{i}] malformed: must be dict with `user` "
                    f"and `assistant` keys. Got: {ex!r}"
                )


def resolve_file_paths(agent: "Agent") -> None:
    """Mode 3: if `system` or `user_template` is a Path, read file → str.

    Mutates agent.system and agent.user_template in-place.
    """
    if isinstance(agent.system, Path):
        if not agent.system.exists():
            raise FileNotFoundError(f"system prompt file not found: {agent.system}")
        agent.system = agent.system.read_text()
    if isinstance(agent.user_template, Path):
        if not agent.user_template.exists():
            raise FileNotFoundError(
                f"user_template file not found: {agent.user_template}"
            )
        agent.user_template = agent.user_template.read_text()


def resolve_yaml_prompt(agent: "Agent") -> None:
    """Mode 4: load `system` + `user_template` from YAML registry reference.

    Format: `prompt="project:version:name"`. Mutually exclusive with Mode 1/2
    fields (instructions / system / user_template / examples). Mutates
    agent.system, agent.user_template, agent._yaml_tools_cache.
    """
    if agent.prompt is None:
        return

    # Mutual exclusion check BEFORE loading (so user error surfaces cleanly).
    for field_name, value in (
        ("instructions", agent.instructions),
        ("system", agent.system),
        ("user_template", agent.user_template),
        ("examples", agent.examples),
    ):
        if value:
            raise ValueError(
                f"Cannot mix `prompt=` (Mode 4 YAML reference) with `{field_name}=`. "
                f"YAML provides system + user_template — remove `{field_name}` "
                f"or switch to Mode 1/2."
            )

    # Parse "project:version:name"
    parts = agent.prompt.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"prompt reference must be 'project:version:name', got: {agent.prompt!r}"
        )
    project, version, name = parts

    # Resolve registry — explicit > auto-detect ./prompts/
    registry = agent.prompt_registry
    if registry is None:
        default_root = Path("./prompts")
        if not default_root.exists():
            raise ValueError(
                f"No `prompt_registry=` provided and ./prompts/ does not exist. "
                f"Either pass PromptRegistry(prompts_root=...) or create ./prompts/."
            )
        registry = PromptRegistry(prompts_root=default_root)

    # Load + extract
    cfg = registry.load(project, version)
    template = cfg.get_prompt(name)   # raises KeyError if name missing
    agent.system = template.system
    agent.user_template = template.user
    # Cache YAML tool defs for Mode D pairing in builders.apply_yaml_tool_schemas
    agent._yaml_tools_cache = list(cfg.tools) if cfg.tools else None
