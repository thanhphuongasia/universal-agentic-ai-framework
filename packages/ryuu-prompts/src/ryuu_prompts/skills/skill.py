"""PromptSkill — dataclass + markdown parser.

File format (Claude Code-style):

    ---
    name: article_summary
    description: Tóm tắt bài viết theo template TL;DR + Key Points + Bài học
    triggers: ["tóm tắt bài", "summarize", "tldr"]
    requires_tools: [fetch_fetch]
    ---

    # Body — instructions the LLM follows when matched

    When user posts a URL...

The parser is intentionally simple: YAML frontmatter between two `---` markers
at file top, everything else is the body. No fancy templating — the body is
inlined verbatim into the system prompt so authors have full control over
formatting and tone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("ryuu_prompts.skills")


@dataclass(frozen=True)
class PromptSkill:
    """One reusable task pattern the LLM can match against."""
    name: str
    description: str
    body: str                              # markdown instructions
    triggers: tuple[str, ...] = ()           # phrases LLM watches for
    requires_tools: tuple[str, ...] = ()    # informational tool dependencies
    source_path: Path | None = None         # for debug / hot-reload

    def matches(self, text: str) -> bool:
        """Cheap substring match — case-insensitive.

        Authors use this as a hint in skill listings. The LLM still gets the
        final say (it sees both the user message and the skill catalog).
        """
        if not self.triggers:
            return False
        low = text.lower()
        return any(t.lower() in low for t in self.triggers)


def parse_skill_file(path: Path | str) -> PromptSkill:
    """Read one .md file → PromptSkill.

    Raises ValueError if the file is missing required frontmatter fields.
    """
    p = Path(path).expanduser()
    raw = p.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)

    if not frontmatter:
        raise ValueError(f"Skill file {p} missing YAML frontmatter (between --- markers)")
    if "name" not in frontmatter:
        raise ValueError(f"Skill file {p} missing required field 'name'")

    return PromptSkill(
        name=str(frontmatter["name"]).strip(),
        description=str(frontmatter.get("description", "")).strip(),
        body=body.strip(),
        triggers=_tuple_of_strings(frontmatter.get("triggers", [])),
        requires_tools=_tuple_of_strings(frontmatter.get("requires_tools", [])),
        source_path=p,
    )


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Split `---\\n<yaml>\\n---\\n<body>` → (frontmatter dict, body str).

    If the file doesn't start with `---`, frontmatter is empty and the whole
    raw text is treated as body.
    """
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, raw

    # Find closing ---
    closing = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closing = i
            break
    if closing is None:
        return {}, raw   # malformed, treat as body

    yaml_block = "".join(lines[1:closing])
    body = "".join(lines[closing + 1:])
    try:
        parsed = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as exc:
        log.warning("Failed to parse skill frontmatter: %s", exc)
        return {}, raw
    if not isinstance(parsed, dict):
        return {}, raw
    return parsed, body


def _tuple_of_strings(val: Any) -> tuple[str, ...]:
    if val is None:
        return ()
    if isinstance(val, str):
        return (val,)
    if isinstance(val, (list, tuple)):
        return tuple(str(v) for v in val)
    return ()


__all__ = ["PromptSkill", "parse_skill_file"]
