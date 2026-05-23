"""PromptSkillRegistry — layered skill loader + system-prompt renderer.

Loads `*.md` files from one or more directories, parses each via
`parse_skill_file`, and exposes:

  • render_context() → markdown block to inject into the system prompt
  • get(name)        → single skill (for debugging or programmatic use)
  • matching(text)   → skills whose triggers match (hint to user, LLM decides)
  • reload_if_changed() → check mtime, re-parse changed files (hot-reload)

Layering: later dirs override earlier ones on name collision. Pass user-shadow
dirs FIRST so they win:

    PromptSkillRegistry.from_dirs([
        Path("~/.ryuu/skills"),    # user wins
        bundled_dir,                # default
    ])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ryuu_prompts.skills.skill import PromptSkill, parse_skill_file

log = logging.getLogger("ryuu_prompts.skills.registry")


@dataclass
class _SkillEntry:
    """Internal — tracks the source file and mtime for hot-reload."""
    skill: PromptSkill
    mtime_ns: int   # for change detection


@dataclass
class PromptSkillRegistry:
    """Catalog of PromptSkills loaded from one or more directories.

    Construction is via `from_dirs` (preferred) or by passing pre-built
    skill list to the constructor for tests.
    """
    dirs: list[Path] = field(default_factory=list)
    _entries: dict[str, _SkillEntry] = field(default_factory=dict)

    @classmethod
    def from_dirs(cls, dirs: list[Path | str]) -> "PromptSkillRegistry":
        """Load all .md files from each dir. Later dirs override earlier ones."""
        resolved = [Path(d).expanduser() for d in dirs]
        reg = cls(dirs=resolved)
        reg._scan_all()
        return reg

    def _scan_all(self) -> None:
        """Walk dirs in given order, later wins on name collision.

        Files in `dirs[i]` with the same skill name as a later file get
        overwritten. So caller should pass user dir first if user-shadow.

        Wait — actually we want USER (first) to WIN. So we walk REVERSED:
        load defaults first, then user shadows over them. That way `_entries`
        ends up with user's version.
        """
        self._entries.clear()
        # Walk in reverse — later passed dirs are defaults, earlier dirs override
        for d in reversed(self.dirs):
            if not d.exists() or not d.is_dir():
                continue
            for path in sorted(d.glob("*.md")):
                try:
                    skill = parse_skill_file(path)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Skipping bad skill file %s: %s", path, exc)
                    continue
                self._entries[skill.name] = _SkillEntry(
                    skill=skill,
                    mtime_ns=path.stat().st_mtime_ns,
                )
        log.info("PromptSkillRegistry loaded %d skills from %d dirs",
                 len(self._entries), len(self.dirs))

    def reload_if_changed(self) -> int:
        """Re-scan all dirs if ANY file changed mtime. Returns # skills reloaded.

        Cheap to call every turn — only does work if something actually changed.
        """
        changed = False
        for d in self.dirs:
            if not d.exists():
                continue
            for path in d.glob("*.md"):
                mtime = path.stat().st_mtime_ns
                existing = self._entries.get(path.stem)
                if existing is None or existing.skill.source_path != path or existing.mtime_ns != mtime:
                    # New file, moved file, or modified — full rescan is cheap
                    changed = True
                    break
            if changed:
                break
        # Also catches deletions: count drift between disk and registry
        if not changed:
            on_disk = sum(
                1 for d in self.dirs if d.exists()
                for _ in d.glob("*.md")
            )
            if on_disk != len(self._entries):
                changed = True
        if changed:
            self._scan_all()
            return len(self._entries)
        return 0

    # ----- Public API -------------------------------------------------- #

    def __iter__(self):
        return (e.skill for e in self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def get(self, name: str) -> PromptSkill | None:
        e = self._entries.get(name)
        return e.skill if e else None

    def names(self) -> list[str]:
        return sorted(self._entries.keys())

    def matching(self, text: str) -> list[PromptSkill]:
        """Skills whose triggers fire on the given text. Hint-only — LLM
        decides which (if any) to actually apply."""
        return [e.skill for e in self._entries.values() if e.skill.matches(text)]

    def render_context(self, max_chars: int = 8000) -> str:
        """Render the full skill catalog as a markdown block for the system prompt.

        Output structure:

            ## Available Skills

            You have access to these reusable task patterns. When the user's
            request matches a skill's triggers, follow its instructions strictly.

            ### article_summary
            Triggers: tóm tắt bài, summarize, tldr
            <body markdown>

            ### flashcard_gen
            ...

        Truncates per-skill bodies if total exceeds max_chars (rare; safety net).
        """
        if not self._entries:
            return ""

        parts: list[str] = [
            "## Available Skills",
            "",
            ("You have access to these reusable task patterns. When the user's "
             "request matches a skill's triggers or intent, follow that skill's "
             "instructions strictly — including output format. If no skill matches, "
             "respond normally."),
            "",
        ]
        for skill in self._entries.values():
            triggers_str = ", ".join(skill.skill.triggers) if skill.skill.triggers else "(no triggers — manual)"
            parts.append(f"### {skill.skill.name}")
            parts.append(f"**Description:** {skill.skill.description}")
            parts.append(f"**Triggers:** {triggers_str}")
            if skill.skill.requires_tools:
                parts.append(f"**Requires tools:** {', '.join(skill.skill.requires_tools)}")
            parts.append("")
            parts.append(skill.skill.body)
            parts.append("")
            parts.append("---")
            parts.append("")

        out = "\n".join(parts)
        if len(out) > max_chars:
            out = out[:max_chars] + "\n…(truncated)"
        return out


__all__ = ["PromptSkillRegistry"]
