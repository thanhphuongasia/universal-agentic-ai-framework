"""Path resolution helpers for OAuth scripts.

Convention-based — keeps skill_registry entries portable across machines.

Layout under RYUU_HOME ($RYUU_HOME env var, default ~/.ryuu):
    oauth_configs/<skill>.json   ← OAuth endpoints for the server
    credentials/<skill>.json     ← access_token + refresh_token (rotated)
    credentials/<skill>_client.json   ← cached client_id from dyn registration

Config values may use ${RYUU_HOME} or ${HOME} placeholders, or '~' — all expanded
at load time. If creds_file / client_file are omitted, they default into
RYUU_HOME/credentials/ keyed by the skill name.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def ryuu_home() -> Path:
    """Resolve the user's Ryuu data directory. $RYUU_HOME overrides default ~/.ryuu."""
    env = os.environ.get("RYUU_HOME", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".ryuu"


def expand_path(p: str) -> Path:
    """Expand ~, $HOME, $RYUU_HOME, and any other env var in a path string."""
    if not p:
        return Path()
    p = p.replace("${RYUU_HOME}", str(ryuu_home()))
    p = os.path.expandvars(p)
    return Path(p).expanduser()


def add_config_args(ap: argparse.ArgumentParser) -> None:
    """Register --skill / --config (mutually exclusive) on a parser."""
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--skill", help="Skill name (resolves $RYUU_HOME/oauth_configs/<name>.json)")
    g.add_argument("--config", help="Explicit path to OAuth server config JSON")


def resolve_config_path(args: argparse.Namespace) -> Path:
    """From --skill or --config, return the OAuth config JSON path."""
    if getattr(args, "skill", None):
        return ryuu_home() / "oauth_configs" / f"{args.skill}.json"
    return expand_path(args.config)


def load_config(args_or_path: argparse.Namespace | Path | str) -> dict:
    """Read OAuth config + fill in defaults for creds_file / client_file.

    Accepts either an argparse.Namespace (from add_config_args), a Path, or a string.
    """
    if isinstance(args_or_path, argparse.Namespace):
        path = resolve_config_path(args_or_path)
    elif isinstance(args_or_path, Path):
        path = args_or_path
    else:
        path = expand_path(args_or_path)

    if not path.exists():
        sys.exit(f"[ryuu-mcp-oauth] Config not found: {path}")
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        sys.exit(f"[ryuu-mcp-oauth] Failed to parse {path}: {exc}")

    name = data.get("name") or path.stem
    data["name"] = name

    # Default creds_file / client_file into the standard credentials dir
    creds_default = ryuu_home() / "credentials" / f"{name}.json"
    client_default = ryuu_home() / "credentials" / f"{name}_client.json"
    data["creds_file"] = str(expand_path(data["creds_file"])) if data.get("creds_file") else str(creds_default)
    data["client_file"] = str(expand_path(data["client_file"])) if data.get("client_file") else str(client_default)
    return data
