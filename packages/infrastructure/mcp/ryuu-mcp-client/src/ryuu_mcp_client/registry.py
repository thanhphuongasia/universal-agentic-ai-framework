"""SkillRegistry — curated catalog of installable MCP skills.

Phase 8.11 — `add_skill("github")` looks up the registry, renders an
MCPServerConfig from the spec + user-supplied params, and hands off to
MCPSkillsLoader (which writes skills.yaml + boots a client).

Why a registry vs. ad-hoc YAML edits:
  • Discoverability — LLM (or user) can `list_available_skills()`
  • Validation — required env vars / params checked before spawn
  • Safety — only servers in the catalog can be installed via chat. Spawning
    arbitrary subprocesses from LLM tool calls is a sharp foot-gun otherwise.

The catalog ships as JSON in `data/registry.json`. Custom catalogs:

    SkillRegistry.from_path("~/.ryuu/my_registry.json")
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ryuu_mcp_core import MCPServerConfig


@dataclass(frozen=True)
class SkillParam:
    """One user-supplied parameter for installing a skill.

    `append_to_args=True` means the param's value is appended to the server
    command's argv (e.g. filesystem's allowed paths). Otherwise it's surfaced
    in env (rare — most env vars come from `env_required`).
    """
    name: str
    type: str            # informational only ("str", "list[str]", "int")
    required: bool
    description: str
    append_to_args: bool = False


@dataclass(frozen=True)
class SkillEnvVar:
    """An environment variable the skill needs.

    `from_env` is the variable name in the bot's host env. `name` is what the
    MCP server expects in its own env (often differ — e.g. server wants
    `GITHUB_PERSONAL_ACCESS_TOKEN` but user sets `GITHUB_TOKEN` in their shell).
    """
    name: str            # name as the MCP server expects in its env
    from_env: str        # host env var name to read from
    description: str


@dataclass(frozen=True)
class SkillSpec:
    """One installable skill from the registry catalog."""
    key: str             # registry lookup key (e.g. "github")
    description: str
    command: str
    args: tuple[str, ...]
    params: tuple[SkillParam, ...] = ()
    env_required: tuple[SkillEnvVar, ...] = ()
    homepage: str = ""
    # Optional one-shot command for re-authentication (e.g. OAuth refresh).
    # Empty tuple means the skill has no separate auth step. Example for gmail:
    # ("npx", "-y", "@gongrzhe/server-gmail-autoauth-mcp", "auth")
    auth_command: tuple[str, ...] = ()

    def missing_env_vars(self) -> list[SkillEnvVar]:
        """Return env vars that aren't satisfied by os.environ — caller
        should ask the user to set these before install."""
        return [e for e in self.env_required if not os.environ.get(e.from_env, "").strip()]

    def render_config(self, params: dict[str, Any] | None = None) -> MCPServerConfig:
        """Build a concrete MCPServerConfig from this spec + user-supplied params.

        Raises:
            ValueError — if a required param is missing or env var is unsatisfied.
        """
        params = params or {}

        # Validate required params present
        for p in self.params:
            if p.required and p.name not in params:
                raise ValueError(
                    f"Skill {self.key!r} requires param {p.name!r} ({p.type}): {p.description}"
                )

        # Render argv: spec args + any append_to_args params
        argv: list[str] = list(self.args)
        for p in self.params:
            if not p.append_to_args:
                continue
            val = params.get(p.name)
            if val is None:
                continue
            if isinstance(val, (list, tuple)):
                argv.extend(str(v) for v in val)
            else:
                argv.append(str(val))

        # Resolve env: env_required → host env lookup
        # NB: missing env vars raise here — caller should call missing_env_vars()
        # first to surface a friendly message instead of this exception.
        env: dict[str, str] = {}
        for e in self.env_required:
            val = os.environ.get(e.from_env, "").strip()
            if not val:
                raise ValueError(
                    f"Skill {self.key!r} requires env var {e.from_env!r}: {e.description}"
                )
            env[e.name] = val

        return MCPServerConfig(
            name=self.key,
            command=self.command,
            args=tuple(argv),
            env=env,
            enabled=True,
        )

    def to_yaml_dict(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render this spec as a dict suitable for serializing into skills.yaml.

        Uses ${ENV_VAR} placeholders for env values (resolved at load time)
        rather than the actual secret — so skills.yaml stays safe to commit.
        """
        params = params or {}
        argv: list[str] = list(self.args)
        for p in self.params:
            if not p.append_to_args:
                continue
            val = params.get(p.name)
            if val is None:
                continue
            if isinstance(val, (list, tuple)):
                argv.extend(str(v) for v in val)
            else:
                argv.append(str(val))

        out: dict[str, Any] = {
            "command": self.command,
            "args": argv,
        }
        if self.env_required:
            out["env"] = {e.name: f"${{{e.from_env}}}" for e in self.env_required}
        return out


_BUNDLED_REGISTRY_PATH = Path(__file__).parent / "data" / "registry.json"


@dataclass
class SkillRegistry:
    """Catalog of installable MCP skills.

    Default load: bundled `data/registry.json`. Users can override / extend
    by pointing to a custom file via env `RYUU_SKILL_REGISTRY` or passing a
    path to `from_path`.
    """
    _skills: dict[str, SkillSpec] = field(default_factory=dict)

    @classmethod
    def from_bundled(cls) -> "SkillRegistry":
        """Load the registry shipped inside the package."""
        return cls.from_path(_BUNDLED_REGISTRY_PATH)

    @classmethod
    def from_layered(cls, user_paths: list[Path | str] | None = None) -> "SkillRegistry":
        """Bundled + user overrides. Later paths win on key collision.

        Default user lookup order (later wins):
          1. $RYUU_SKILL_REGISTRY (explicit path — file or directory)
          2. ~/.ryuu/skill_registry.json        (legacy monolithic file)
          3. ~/.ryuu/skill_registry.d/*.json    (modular: one file per skill)

        The .d/ directory is the recommended layout — editing one skill never
        risks touching others. Files in .d/ can be either:
          • bare form  → `{"description": ..., "command": ...}` with skill key
            inferred from filename (e.g. gmail.json → key "gmail").
          • envelope   → `{"skills": {"gmail": {...}}}` — same schema as monolithic.

        Missing files / dirs are silently skipped. Bundled always loads first.
        """
        merged = cls.from_bundled()._skills.copy()
        candidates: list[Path] = []
        if user_paths is not None:
            candidates.extend(Path(p).expanduser() for p in user_paths)
        else:
            env_path = os.environ.get("RYUU_SKILL_REGISTRY", "").strip()
            if env_path:
                candidates.append(Path(env_path).expanduser())
            candidates.append(Path.home() / ".ryuu" / "skill_registry.json")
            candidates.append(Path.home() / ".ryuu" / "skill_registry.d")
        for p in candidates:
            if not p.exists():
                continue
            if p.is_dir():
                # Modular layout — load every *.json in deterministic order
                for json_path in sorted(p.glob("*.json")):
                    override = cls._from_file_inferring_key(json_path)
                    merged.update(override._skills)
            else:
                override = cls.from_path(p)
                merged.update(override._skills)
        return cls(_skills=merged)

    @classmethod
    def _from_file_inferring_key(cls, path: Path) -> "SkillRegistry":
        """Load a single per-skill JSON file. Accepts envelope or bare form.

        Bare form: file contents are the skill body directly, key = filename stem.
        Envelope form: same shape as the monolithic registry file.
        """
        if not path.exists():
            return cls()
        try:
            with path.open() as fh:
                data = json.load(fh)
        except Exception:
            return cls()
        if not isinstance(data, dict):
            return cls()
        if "skills" in data and isinstance(data["skills"], dict):
            return cls._from_dict(data)
        if "command" in data:
            # Bare form — wrap with filename-derived key
            return cls._from_dict({"skills": {path.stem: data}})
        return cls()

    @classmethod
    def from_path(cls, path: Path | str) -> "SkillRegistry":
        p = Path(path).expanduser()
        if not p.exists():
            return cls()
        with p.open() as fh:
            data = json.load(fh)
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "SkillRegistry":
        skills_data = data.get("skills", {}) or {}
        skills: dict[str, SkillSpec] = {}
        for key, raw in skills_data.items():
            params = tuple(
                SkillParam(
                    name=p["name"],
                    type=p.get("type", "str"),
                    required=bool(p.get("required", False)),
                    description=p.get("description", ""),
                    append_to_args=bool(p.get("append_to_args", False)),
                )
                for p in raw.get("params", []) or []
            )
            env_required = tuple(
                SkillEnvVar(
                    name=e["name"],
                    from_env=e.get("from_env", e["name"]),
                    description=e.get("description", ""),
                )
                for e in raw.get("env_required", []) or []
            )
            skills[key] = SkillSpec(
                key=key,
                description=raw.get("description", ""),
                command=raw["command"],
                args=tuple(raw.get("args", []) or []),
                params=params,
                env_required=env_required,
                homepage=raw.get("homepage", ""),
                auth_command=tuple(raw.get("auth_command", []) or []),
            )
        return cls(_skills=skills)

    def __iter__(self):
        return iter(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, key: str) -> bool:
        return key in self._skills

    def get(self, key: str) -> SkillSpec | None:
        return self._skills.get(key)

    def names(self) -> list[str]:
        return sorted(self._skills.keys())


__all__ = ["SkillRegistry", "SkillSpec", "SkillParam", "SkillEnvVar"]
