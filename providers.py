"""Central LLM provider registry — YAML-driven, no hardcoded providers.

Reads `providers.yaml` next to this file and constructs each registered
provider class. Adding a new provider = add a YAML entry. No code change.

Skip rules (silently):
  - entry has `env_required` but that env var is unset
  - the provider's Python package is not installed
This way a dev environment with only ANTHROPIC_API_KEY still boots cleanly.

Usage:

    from providers import make_providers
    PROVIDERS = make_providers()        # {"anthropic": ..., "openai": ...}
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).parent / "providers.yaml"
_log = logging.getLogger(__name__)


def _resolve_value(spec: Any) -> Any:
    """Resolve a YAML value — supports literals and {env, fallback} maps."""
    if isinstance(spec, dict) and "env" in spec:
        return os.environ.get(spec["env"], spec.get("fallback", ""))
    return spec


def load_provider_config(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Return raw YAML config so callers can introspect models per provider."""
    path = config_path or _CONFIG_PATH
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def model_catalog(config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return {provider_key: {models: [...], default_model: str}}.

    Used by the HTTP layer to surface model dropdowns to the UI without
    each frontend hardcoding the list.
    """
    catalog: dict[str, dict[str, Any]] = {}
    for entry in load_provider_config(config_path):
        key = entry.get("key")
        if not key:
            continue
        models = entry.get("models") or []
        default_model = (
            entry.get("init_kwargs", {}).get("default_model")
            if isinstance(entry.get("init_kwargs"), dict) else None
        )
        if isinstance(default_model, dict):
            default_model = (
                os.environ.get(default_model.get("env", ""))
                or default_model.get("fallback", "")
            )
        catalog[key] = {
            "models": list(models),
            "default_model": str(default_model or (models[0] if models else "")),
        }
    return catalog


def make_providers(config_path: Path | None = None) -> dict[str, Any]:
    """Return {provider_key: ILLMProvider} parsed from the registry YAML.

    Entries are skipped (not raised) when:
      - the entry's env_required var is missing, OR
      - the entry's Python package isn't installed.
    Misconfigured entries (bad import string, missing key field) DO raise so
    typos surface at boot time.
    """
    path = config_path or _CONFIG_PATH
    if not path.exists():
        _log.warning("providers.yaml not found at %s — no providers loaded", path)
        return {}

    config = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    providers: dict[str, Any] = {}

    for entry in config:
        key = entry.get("key")
        import_spec = entry.get("import")
        if not key or not import_spec:
            raise ValueError(
                f"provider entry missing 'key' or 'import': {entry!r}",
            )

        env_required = entry.get("env_required")
        if env_required and not os.environ.get(env_required):
            _log.debug("skip provider %r — %s not set", key, env_required)
            continue

        module_path, _, class_name = import_spec.partition(":")
        if not class_name:
            raise ValueError(
                f"'import' must be 'module:ClassName', got {import_spec!r}",
            )
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            _log.info("skip provider %r — %s not installed (%s)", key, module_path, exc)
            continue

        try:
            cls = getattr(module, class_name)
        except AttributeError as exc:
            raise ValueError(
                f"{module_path!r} has no attribute {class_name!r}",
            ) from exc

        init_kwargs = {
            k: _resolve_value(v)
            for k, v in (entry.get("init_kwargs") or {}).items()
        }
        providers[key] = cls(**init_kwargs)

    return providers


__all__ = ["make_providers", "model_catalog", "load_provider_config"]
