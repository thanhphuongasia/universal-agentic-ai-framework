"""Build messages for the generic oracle meta-prompt.

Loads the system + user_template YAMLs once at import; exposes a single
`build_meta_messages(...)` helper that returns an LLM-ready messages list.

Domain stays out of the system prompt — it enters only via the user template
fields (`project_name`, `domain_hint`, `production_prompt_text`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_THIS_DIR = Path(__file__).resolve().parent
_SYSTEM_YAML = _THIS_DIR / "system.yaml"
_USER_YAML = _THIS_DIR / "user_template.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


_SYSTEM_DOC = _load_yaml(_SYSTEM_YAML)
_USER_DOC = _load_yaml(_USER_YAML)

META_PROMPT_VERSION: str = str(_SYSTEM_DOC.get("version", "0.0.0"))
META_PROMPT_MODEL: str = str(_SYSTEM_DOC.get("model", "claude-opus-4-7"))

_SYSTEM_TEXT: str = str(_SYSTEM_DOC.get("system", "")).rstrip()
_USER_TEMPLATE: str = str(_USER_DOC.get("user_template", "")).rstrip()


def render_user_message(
    *,
    production_prompt_text: str,
    project_name: str = "",
    domain_hint: str = "",
    output_schema_hint: str = "",
) -> str:
    """Render the user message by substituting template fields.

    Uses simple Mustache-style `{{ var }}` replacement — no Jinja, since
    the fields are flat strings and any wider templating engine is overkill.
    """
    schema_block = (output_schema_hint.strip()
                    or "(not provided — infer from PRODUCTION PROMPT below)")
    return (
        _USER_TEMPLATE
        .replace("{{ project_name }}", project_name or "(unspecified)")
        .replace("{{ domain_hint }}", domain_hint or "(unspecified)")
        .replace("{{ output_schema_hint }}", schema_block)
        .replace("{{ production_prompt_text }}", production_prompt_text or "")
    )


def build_meta_messages(
    *,
    production_prompt_text: str,
    project_name: str = "",
    domain_hint: str = "",
    output_schema_hint: str = "",
) -> list[dict[str, str]]:
    """Return a `[{role, content}]` list ready for any LLM adapter.

    The list is intentionally provider-neutral — callers convert to
    OpenAI / Anthropic / etc. message shapes as needed.
    """
    if not production_prompt_text or not production_prompt_text.strip():
        raise ValueError("production_prompt_text is required")
    return [
        {"role": "system", "content": _SYSTEM_TEXT},
        {
            "role": "user",
            "content": render_user_message(
                production_prompt_text=production_prompt_text,
                project_name=project_name,
                domain_hint=domain_hint,
                output_schema_hint=output_schema_hint,
            ),
        },
    ]


__all__ = [
    "META_PROMPT_VERSION",
    "META_PROMPT_MODEL",
    "build_meta_messages",
    "render_user_message",
]
