"""SkillManager — install/uninstall MCP skills at runtime.

Phase 8.11 — exposes ITool-compatible objects (`install_skill`,
`uninstall_skill`, `list_available_skills`, `list_installed_skills`) so the
LLM can manage capabilities via chat. No code edits, no restart.

Flow when LLM calls `install_skill("github")`:
    1. Registry lookup → SkillSpec
    2. Validate required env vars / params  → friendly error if missing
    3. Render MCPServerConfig (host env values inlined into env dict)
    4. Append entry (with ${ENV_VAR} placeholders) to skills.yaml
    5. MCPToolset.add_server() → spawn subprocess, list_tools, register
    6. Notify listeners → host invalidates cached Agent so next turn sees
       the new tools.

Safety: only skills present in the registry catalog can be installed.
Spawning arbitrary subprocesses from chat would be too dangerous.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ryuu_mcp_client.registry import SkillRegistry, SkillSpec
from ryuu_mcp_client.toolset import MCPToolset

log = logging.getLogger("ryuu_mcp_client.skill_manager")


@dataclass
class SkillManager:
    """Orchestrates skill install/uninstall against a live MCPToolset.

    Owns:
      • registry — read-only catalog
      • toolset  — mutable runtime
      • yaml_path — persistent config file
    """
    registry: SkillRegistry
    toolset: MCPToolset
    yaml_path: Path

    def __post_init__(self) -> None:
        self.yaml_path = Path(self.yaml_path).expanduser()

    # ----- Public API --------------------------------------------------- #

    async def install(self, skill_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Install a skill by registry key. Returns summary dict.

        Validation runs BEFORE the subprocess is spawned, so the LLM gets
        actionable errors instead of opaque "failed to start" messages.
        """
        spec = self.registry.get(skill_name)
        if spec is None:
            return {
                "ok": False,
                "error": f"Skill {skill_name!r} not in registry",
                "hint": f"Run list_available_skills to see installable names. "
                        f"Known: {', '.join(self.registry.names())}",
            }

        if self.toolset.has_server(skill_name):
            return {
                "ok": False,
                "error": f"Skill {skill_name!r} is already installed",
                "hint": "Use uninstall_skill first if you want to reconfigure it",
            }

        missing_env = spec.missing_env_vars()
        if missing_env:
            return {
                "ok": False,
                "error": f"Skill {skill_name!r} needs env vars not set in the bot's environment",
                "missing": [
                    {"env_var": e.from_env, "description": e.description}
                    for e in missing_env
                ],
                "hint": "Set these in your shell before restarting the bot, then retry install.",
            }

        # Render config — raises ValueError on missing required params
        try:
            config = spec.render_config(params)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "params_needed": [
                {"name": p.name, "type": p.type, "required": p.required, "description": p.description}
                for p in spec.params
            ]}

        # Persist to YAML BEFORE starting client. If start fails, we roll
        # back the YAML write too.
        try:
            self._persist_skill_to_yaml(spec, params)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Failed to write {self.yaml_path}: {exc}"}

        try:
            specs = await self.toolset.add_server(config)
        except Exception as exc:  # noqa: BLE001
            self._remove_skill_from_yaml(skill_name)   # roll back YAML
            hint = "Common causes: npx package not found, env credentials invalid"
            if spec.auth_command:
                # OAuth-based skills need a one-shot login before the server can boot.
                # Calling reauth_skill bootstraps creds AND adds the server in one step,
                # so the LLM should redirect to it instead of retrying install.
                hint = (
                    f"This skill uses OAuth — bootstrap with reauth_skill({skill_name!r}) instead. "
                    f"That command opens a browser, completes login, AND adds the server "
                    f"(install_skill won't work because the run wrapper needs credentials first)."
                )
            return {"ok": False, "error": f"Server failed to start: {exc}", "hint": hint}

        return {
            "ok": True,
            "skill": skill_name,
            "tools_added": len(specs),
            "tool_names": [s.qualified_name for s in specs],
            "yaml": str(self.yaml_path),
        }

    async def uninstall(self, skill_name: str) -> dict[str, Any]:
        """Remove a skill from the live toolset + skills.yaml."""
        if not self.toolset.has_server(skill_name):
            return {"ok": False, "error": f"Skill {skill_name!r} is not installed"}
        removed = await self.toolset.remove_server(skill_name)
        self._remove_skill_from_yaml(skill_name)
        return {"ok": True, "skill": skill_name, "tools_removed": removed}

    def list_available(self) -> dict[str, Any]:
        """Catalog dump — what can be installed."""
        return {
            "available": [
                {
                    "name": s.key,
                    "description": s.description,
                    "needs_params": [p.name for p in s.params if p.required],
                    "needs_env": [e.from_env for e in s.env_required],
                    "homepage": s.homepage,
                    "installed": self.toolset.has_server(s.key),
                }
                for s in self.registry
            ],
        }

    def list_installed(self) -> dict[str, Any]:
        """What's currently active in the bot."""
        summary = self.toolset.server_summary()
        return {
            "installed": [
                {"name": name, "tool_count": count} for name, count in sorted(summary.items())
            ],
            "total_tools": sum(summary.values()),
        }

    async def reauth(self, skill_name: str, timeout: float = 300.0) -> dict[str, Any]:
        """Re-run an installed skill's auth_command, then respawn its server.

        Use case: OAuth tokens expire (Google Testing-mode tokens expire after
        7 days). Bot detects an auth error from a tool call, asks LLM to call
        `reauth_skill("gmail")`. We:
          1. Stop the current MCP subprocess (so it releases credential files).
          2. Spawn `auth_command` synchronously — opens browser, user completes
             OAuth flow, subprocess writes fresh token then exits.
          3. Respawn the MCP server — it now reads the new token at startup.

        Returns a dict so the LLM can describe the outcome to the user.
        Stdout/stderr from the auth subprocess are captured for diagnostics.
        """
        spec = self.registry.get(skill_name)
        if spec is None:
            return {"ok": False, "error": f"Skill {skill_name!r} not in registry"}
        if not spec.auth_command:
            return {
                "ok": False,
                "error": f"Skill {skill_name!r} has no auth_command — nothing to re-authenticate",
                "hint": "Add 'auth_command' to the skill's registry entry if it has a separate OAuth/login step.",
            }

        was_installed = self.toolset.has_server(skill_name)
        if was_installed:
            await self.toolset.remove_server(skill_name)

        cmd = list(spec.auth_command)

        # If a prior reauth subprocess is still running (e.g. user gave up
        # mid-OAuth and retried), it holds the localhost callback port and the
        # next bind will fail with EADDRINUSE. Kill any process matching this
        # skill's auth command before spawning a fresh one.
        await self._kill_stale_auth_procs(cmd, skill_name)

        log.info("Spawning auth command for %s: %s", skill_name, " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "ok": False,
                    "error": f"Auth command timed out after {int(timeout)}s",
                    "hint": "Did you complete the browser OAuth flow? Try again and finish the consent screen within the time limit.",
                }
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"Auth command not found: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Auth command failed to spawn: {exc}"}

        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": f"Auth command exited with code {proc.returncode}",
                "stdout_tail": out_text[-500:],
                "stderr_tail": err_text[-500:],
            }

        # Re-spawn the MCP server with the freshened credentials.
        try:
            config = spec.render_config()
        except ValueError as exc:
            return {"ok": False, "error": f"Cannot re-render config: {exc}"}
        try:
            specs = await self.toolset.add_server(config)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Re-installed auth but server failed to restart: {exc}"}

        # Persist so the next bot restart picks the skill up automatically.
        try:
            self._persist_skill_to_yaml(spec, None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to persist %s to skills.yaml: %s", skill_name, exc)

        return {
            "ok": True,
            "skill": skill_name,
            "tools_available": len(specs),
            "stdout_tail": out_text[-200:] if out_text else "",
            "note": "Auth refreshed and server respawned. Tools should work now.",
        }

    async def _kill_stale_auth_procs(self, cmd: list[str], skill_name: str) -> None:
        """Best-effort kill of any prior auth subprocess for this skill.

        Matches by `<binary> ... <skill_name>` so we don't accidentally kill
        auth flows for other skills running in parallel. Silent on failure —
        if pkill isn't installed (non-POSIX) we just continue; the bind error
        from the new subprocess will surface the conflict.
        """
        if not cmd:
            return
        # Pattern matches the full argv: e.g. "ryuu-mcp-oauth-pkce.*todopro"
        pattern = f"{Path(cmd[0]).name}.*{skill_name}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "pkill", "-f", pattern,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
        except FileNotFoundError:
            return   # pkill not present — non-POSIX environment
        # Give the OS a moment to release the listening socket.
        await asyncio.sleep(0.3)

    async def complete_oauth(self, skill_name: str, callback_url: str) -> dict[str, Any]:
        """Finalize a pending OAuth flow with a callback URL the user pasted.

        Use case: user started reauth_skill on phone or remote machine, the local
        callback couldn't fire (different device, different network), they copied
        the failed redirect URL from the browser address bar. This re-invokes the
        auth_command in --complete mode so the persisted code_verifier can be
        used to exchange the code for tokens, then respawns the MCP server.
        """
        spec = self.registry.get(skill_name)
        if spec is None:
            return {"ok": False, "error": f"Skill {skill_name!r} not in registry"}
        if not spec.auth_command:
            return {"ok": False, "error": f"Skill {skill_name!r} has no auth_command"}

        # Append --complete <url> to the auth_command. Assumes the script supports
        # this flag (ryuu-mcp-oauth-pkce does; custom scripts may not).
        cmd = list(spec.auth_command) + ["--complete", callback_url]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Token exchange timed out (30s)"}
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"Auth command not found: {exc}"}

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": f"Token exchange failed (exit {proc.returncode})",
                "stdout_tail": out[-500:],
                "stderr_tail": err[-500:],
                "hint": "If state mismatch: the pending flow was for a different attempt. Run reauth_skill again.",
            }

        # Spawn the MCP server now that creds exist.
        try:
            config = spec.render_config()
        except ValueError as exc:
            return {"ok": False, "error": f"Cannot render server config: {exc}"}
        if self.toolset.has_server(skill_name):
            await self.toolset.remove_server(skill_name)
        try:
            specs = await self.toolset.add_server(config)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Tokens saved but server failed to start: {exc}"}

        try:
            self._persist_skill_to_yaml(spec, None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to persist %s to skills.yaml: %s", skill_name, exc)

        return {
            "ok": True,
            "skill": skill_name,
            "tools_available": len(specs),
            "note": "OAuth complete via manual paste; server respawned with fresh tokens.",
        }

    async def reload_from_yaml(self) -> dict[str, Any]:
        """Re-read skills.yaml and hot-add any servers not yet running.

        Escape hatch for skills NOT in the registry — user edits skills.yaml
        directly (writing command/args/env themselves), then calls reload_skills
        in chat. The bot picks up the new entries without restart.

        Only ADDITIVE — existing servers stay, and entries deleted from YAML
        are NOT auto-uninstalled (use uninstall_skill explicitly for that).
        Bypasses the registry safety catalog by design — user is taking
        responsibility by writing the YAML.
        """
        from ryuu_mcp_client.loader import MCPSkillsLoader   # local import

        loader = MCPSkillsLoader.from_path(self.yaml_path)
        configs = loader.server_configs()

        added: list[str] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []
        for cfg in configs:
            if self.toolset.has_server(cfg.name):
                skipped.append(cfg.name)
                continue
            try:
                specs = await self.toolset.add_server(cfg)
                added.append(f"{cfg.name} ({len(specs)} tools)")
            except Exception as exc:  # noqa: BLE001
                errors.append({"server": cfg.name, "error": str(exc)})

        return {
            "ok": True,
            "added": added,
            "already_running": skipped,
            "errors": errors,
            "yaml_path": str(self.yaml_path),
            "hint": (
                "To add a server NOT in the registry: edit skills.yaml directly "
                "with command/args/env, then call reload_skills again. The YAML "
                "schema is documented in ryuu-mcp-client's README."
            ) if not added and not errors else None,
        }

    # ----- YAML persistence -------------------------------------------- #

    def _persist_skill_to_yaml(self, spec: SkillSpec, params: dict[str, Any] | None) -> None:
        """Append `mcp_servers.<spec.key>` to skills.yaml. Creates file if missing.

        Uses ${ENV_VAR} placeholders for secrets (not the resolved value), so
        the YAML stays safe to commit / share. The loader re-resolves at boot.
        """
        data = self._read_yaml()
        servers = data.setdefault("mcp_servers", {})
        servers[spec.key] = spec.to_yaml_dict(params)
        self._write_yaml(data)

    def _remove_skill_from_yaml(self, skill_name: str) -> None:
        data = self._read_yaml()
        servers = data.get("mcp_servers", {}) or {}
        if skill_name in servers:
            del servers[skill_name]
            self._write_yaml(data)

    def _read_yaml(self) -> dict[str, Any]:
        if not self.yaml_path.exists():
            return {}
        try:
            with self.yaml_path.open() as fh:
                return yaml.safe_load(fh) or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to read %s — starting fresh: %s", self.yaml_path, exc)
            return {}

    def _write_yaml(self, data: dict[str, Any]) -> None:
        self.yaml_path.parent.mkdir(parents=True, exist_ok=True)
        with self.yaml_path.open("w") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# ITool wrappers — what gets registered with Agent(tools=[...])
# ---------------------------------------------------------------------------

@dataclass
class _InstallSkillTool:
    manager: SkillManager
    tool_id: str = "install_skill"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "install_skill",
                "description": (
                    "Install a new MCP skill (capability) into the bot at runtime — "
                    "no restart. Examples: 'github', 'fetch', 'brave', 'filesystem'. "
                    "Run list_available_skills first to see options and what params/env "
                    "each one needs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Registry key of the skill (e.g. 'github')",
                        },
                        "params": {
                            "type": "object",
                            "description": (
                                "Optional params some skills need. Examples: "
                                "filesystem → {paths: ['/Users/me/docs']}, "
                                "sqlite → {db_path: '/path/to.db'}"
                            ),
                            "additionalProperties": True,
                        },
                    },
                    "required": ["name"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        name = args.get("name", "")
        params = args.get("params") or {}
        return await self.manager.install(name, params)


@dataclass
class _UninstallSkillTool:
    manager: SkillManager
    tool_id: str = "uninstall_skill"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "uninstall_skill",
                "description": "Remove a previously installed MCP skill. Tools from that server immediately disappear.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill key to uninstall"},
                    },
                    "required": ["name"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return await self.manager.uninstall(args.get("name", ""))


@dataclass
class _ListAvailableSkillsTool:
    manager: SkillManager
    tool_id: str = "list_available_skills"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "list_available_skills",
                "description": "List MCP skills that can be installed via install_skill. Shows which are already active and what env/params each needs.",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return self.manager.list_available()


@dataclass
class _ListInstalledSkillsTool:
    manager: SkillManager
    tool_id: str = "list_installed_skills"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "list_installed_skills",
                "description": "List MCP skills currently active in the bot, with tool counts.",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return self.manager.list_installed()


@dataclass
class _ReloadSkillsTool:
    manager: SkillManager
    tool_id: str = "reload_skills"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "reload_skills",
                "description": (
                    "Re-read skills.yaml and hot-add any new MCP servers. Use this "
                    "AFTER the user edits ~/.ryuu/skills.yaml directly to add a "
                    "custom MCP server that isn't in the curated registry. Only "
                    "adds new servers — does not remove or modify existing ones."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return await self.manager.reload_from_yaml()


@dataclass
class _ReauthSkillTool:
    manager: SkillManager
    tool_id: str = "reauth_skill"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "reauth_skill",
                "description": (
                    "Re-authenticate an installed skill (e.g. refresh OAuth token). "
                    "Call this when a skill's tool returns an authentication / "
                    "permission / 'not logged in' error — typical for Gmail when "
                    "tokens expire (every 7 days while the OAuth app is in Testing "
                    "mode). This will: (1) stop the skill's MCP server, "
                    "(2) run the skill's auth command — for Gmail this opens a "
                    "browser for the user to complete OAuth, (3) restart the server "
                    "with the new credentials. Only works for skills that declare "
                    "an auth_command in the registry."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Skill key (e.g. 'gmail') to re-authenticate",
                        },
                    },
                    "required": ["name"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return await self.manager.reauth(args.get("name", ""))


@dataclass
class _CompleteOAuthTool:
    manager: SkillManager
    tool_id: str = "complete_oauth"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "complete_oauth",
                "description": (
                    "Finalize a pending OAuth flow by pasting the callback URL the user "
                    "received in their browser. Use this when reauth_skill was started but "
                    "the localhost callback could not fire — e.g. user logged in on a phone "
                    "and got a 'cannot connect to localhost' error, OR user has the URL like "
                    "'localhost:PORT/oauth/callback?code=...&state=...'. The URL must contain "
                    "the `code` and `state` query parameters from the OAuth provider's redirect."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill key (e.g. 'todopro')"},
                        "callback_url": {
                            "type": "string",
                            "description": "The full callback URL (with code & state params) that the user pasted",
                        },
                    },
                    "required": ["name", "callback_url"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        return await self.manager.complete_oauth(
            args.get("name", ""),
            args.get("callback_url", ""),
        )


@dataclass
class SkillManagerToolset:
    """Bundle of 5 ITool instances around a SkillManager.

    Drop into `Agent(tools=[*memory.tools, *mcp.tools, *skills.tools])` and
    the LLM can manage skills via chat — install from the curated registry,
    or reload custom YAML entries the user wrote themselves.
    """
    manager: SkillManager
    _tools: list[Any] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._tools = [
            _ListAvailableSkillsTool(manager=self.manager),
            _ListInstalledSkillsTool(manager=self.manager),
            _InstallSkillTool(manager=self.manager),
            _UninstallSkillTool(manager=self.manager),
            _ReloadSkillsTool(manager=self.manager),
            _ReauthSkillTool(manager=self.manager),
            _CompleteOAuthTool(manager=self.manager),
        ]

    @property
    def tools(self) -> list[Any]:
        return list(self._tools)


__all__ = ["SkillManager", "SkillManagerToolset"]
