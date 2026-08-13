"""Prompt loader for base investigator templates."""

from __future__ import annotations

from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent


def load_base_prompt(version: str = "v1") -> str:
    """Load base system prompt template with {domain_rules} slot unfilled."""
    path = _PROMPTS_DIR / f"base_investigator.{version}.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return str(data["system"])


def compose(base: str, domain_rules: str) -> str:
    """Substitute {domain_rules} slot."""
    return base.replace("{domain_rules}", domain_rules)


__all__ = ["load_base_prompt", "compose"]
