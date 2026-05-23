"""MCPSkillsLoader — read skills.yaml + build MCPClients.

User edits `~/.ryuu/skills.yaml` (or path of choice) — loader resolves env
vars, instantiates clients, returns ready-to-start collection.

YAML schema:

    mcp_servers:
      filesystem:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

      brave:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-brave-search"]
        env:
          BRAVE_API_KEY: ${BRAVE_API_KEY}
        enabled: true

      legacy:
        command: ...
        enabled: false      # skip — useful while debugging
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from ryuu_mcp_core import MCPServerConfig

from ryuu_mcp_client.client import MCPClient

log = logging.getLogger("ryuu_mcp_client.loader")

_ENV_VAR_PATTERN = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")


def _resolve_env_vars(value: Any) -> Any:
    """Replace ${VAR} or $VAR with env value. Empty string if unset."""
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


class MCPSkillsLoader:
    """Reads skills.yaml + creates MCPClients.

    Usage:
        loader = MCPSkillsLoader.from_path(Path("~/.ryuu/skills.yaml"))
        clients = loader.build_clients()       # not started yet
        toolset = MCPToolset(clients=clients)
        await toolset.start_all()
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._raw = config

    @classmethod
    def from_path(cls, path: Path | str) -> "MCPSkillsLoader":
        p = Path(path).expanduser()
        if not p.exists():
            log.info("Skills config not found at %s — empty config", p)
            return cls({})
        with p.open() as fh:
            return cls(yaml.safe_load(fh) or {})

    @classmethod
    def empty(cls) -> "MCPSkillsLoader":
        return cls({})

    def server_configs(self) -> list[MCPServerConfig]:
        """Parse the YAML into a list of MCPServerConfig (only enabled ones)."""
        servers = self._raw.get("mcp_servers", {}) or {}
        configs: list[MCPServerConfig] = []
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                log.warning("Skipping malformed entry %r — expected dict, got %r", name, type(entry).__name__)
                continue
            if entry.get("enabled") is False:
                log.info("Skipping disabled server %r", name)
                continue
            command = entry.get("command")
            if not command:
                log.warning("Skipping %r — missing 'command'", name)
                continue
            args = tuple(_resolve_env_vars(entry.get("args", [])) or [])
            env = _resolve_env_vars(entry.get("env", {})) or {}
            configs.append(MCPServerConfig(
                name=name,
                command=_resolve_env_vars(command),
                args=args,
                env=env,
                enabled=True,
            ))
        return configs

    def build_clients(self) -> list[MCPClient]:
        """Materialize one MCPClient per enabled server. Not started yet."""
        return [MCPClient(config=cfg) for cfg in self.server_configs()]


__all__ = ["MCPSkillsLoader"]
