#!/usr/bin/env python3
"""Generic MCP server runner with OAuth auto-refresh.

Spawned by ryuu-mcp-client as the MCP server subprocess for any OAuth-based
remote MCP. Reads credentials saved by ryuu-mcp-oauth-pkce, refreshes the
access token if near expiry, then execs `npx mcp-remote` so the bot's stdin/
stdout flow straight to the remote server.

Usage (in skill_registry entry — portable, no hardcoded paths):
    "command": "ryuu-mcp-oauth-run",
    "args": ["--skill", "todopro"]

Or with an explicit config path (e.g. when not living under $RYUU_HOME):
    "args": ["--config", "/path/to/oauth_config.json"]

Exits non-zero with a clear hint when credentials are missing — the bot then
knows to surface `reauth_skill('<name>')` to the user.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from ryuu_mcp_client.oauth._paths import add_config_args, expand_path, load_config

REFRESH_LEEWAY_S = 60   # refresh if access_token expires in <60s


def _die(msg: str, code: int = 2) -> None:
    print(f"[ryuu-mcp-oauth-run] {msg}", file=sys.stderr)
    sys.exit(code)


def load_creds(cfg: dict) -> dict:
    creds_file = expand_path(cfg["creds_file"])
    if not creds_file.exists():
        name = cfg.get("name", "this-skill")
        _die(
            f"No credentials at {creds_file}. "
            f"Ask the bot: reauth_skill('{name}') to OAuth first.",
            code=2,
        )
    try:
        return json.loads(creds_file.read_text())
    except Exception as exc:  # noqa: BLE001
        _die(f"Failed to parse {creds_file}: {exc}", code=2)
        return {}  # unreachable


def refresh_if_needed(cfg: dict, tokens: dict) -> dict:
    expires_at = int(tokens.get("expires_at", 0))
    if expires_at > int(time.time()) + REFRESH_LEEWAY_S:
        return tokens
    if "refresh_token" not in tokens or "client_id" not in tokens:
        _die("Stored credentials missing refresh_token / client_id — re-run OAuth.", code=3)
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": tokens["client_id"],
    }).encode()
    req = urllib.request.Request(
        cfg["base_url"] + cfg["token_path"],
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            new = json.load(resp)
    except Exception as exc:  # noqa: BLE001
        name = cfg.get("name", "this-skill")
        _die(f"Refresh failed: {exc}. Run reauth_skill('{name}').", code=3)
        return {}  # unreachable

    # refresh_token typically rotates — persist the new bundle.
    new["expires_at"] = int(time.time()) + int(new.get("expires_in", 3600))
    new["client_id"] = tokens["client_id"]
    creds_file = expand_path(cfg["creds_file"])
    creds_file.write_text(json.dumps(new, indent=2))
    return new


def main() -> None:
    ap = argparse.ArgumentParser(description="Generic OAuth MCP runner (auto-refresh + mcp-remote)")
    add_config_args(ap)
    args = ap.parse_args()

    cfg = load_config(args)
    for k in ("base_url", "mcp_url", "token_path", "creds_file"):
        if k not in cfg:
            _die(f"Config missing required key: {k}", code=2)

    tokens = refresh_if_needed(cfg, load_creds(cfg))
    bearer = f"Authorization: Bearer {tokens['access_token']}"
    # Replace this process — stdio of mcp-remote becomes our stdio.
    os.execvp("npx", ["npx", "-y", "mcp-remote", cfg["mcp_url"], "--header", bearer])


if __name__ == "__main__":
    main()
