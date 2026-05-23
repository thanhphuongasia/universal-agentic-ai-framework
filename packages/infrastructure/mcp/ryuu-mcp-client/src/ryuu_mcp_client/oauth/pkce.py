#!/usr/bin/env python3
"""Generic OAuth 2.0 PKCE bootstrap — one-shot login that saves tokens to disk.

Server-agnostic. Reads a JSON config that describes the OAuth endpoints,
runs the full RFC 7636 PKCE flow (with RFC 7591 dynamic client registration
when no client_id is configured), and writes tokens for the runner to use.

Usage:
    python3 oauth_pkce.py --config ~/.ryuu/oauth_configs/todopro.json

Config schema (keys with "?" are optional):
    {
      "name": "todopro",
      "base_url": "https://todopro.jacons-corp.com",
      "register_path": "/api/oauth/register",        # ? skip if client_id below
      "authorize_path": "/api/oauth/authorize",
      "token_path": "/api/oauth/token",
      "callback_port": 8765,
      "callback_path": "/oauth/callback",
      "scopes": [],                                  # ? optional space-joined
      "client_id": null,                             # ? if set, skip register
      "client_file": "~/.ryuu/credentials/todopro_client.json",   # ? where to cache registration
      "creds_file":  "~/.ryuu/credentials/todopro.json"
    }
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from ryuu_mcp_client.oauth._paths import add_config_args, expand_path, load_config, ryuu_home

_received: dict = {}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _pending_path(cfg: dict) -> Path:
    return ryuu_home() / "credentials" / f"{cfg['name']}_pending.json"


def _write_pending(cfg: dict, data: dict) -> None:
    p = _pending_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def _read_pending(cfg: dict) -> dict:
    p = _pending_path(cfg)
    if not p.exists():
        sys.exit(f"[ryuu-mcp-oauth-pkce] No pending OAuth flow at {p}. Start one first (without --complete).")
    return json.loads(p.read_text())


def _clear_pending(cfg: dict) -> None:
    p = _pending_path(cfg)
    if p.exists():
        p.unlink()


def _exchange_code_for_tokens(cfg: dict, code: str, pending: dict) -> int:
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["redirect_uri"],
        "client_id": pending["client_id"],
        "code_verifier": pending["code_verifier"],
    }).encode()
    req = urllib.request.Request(
        cfg["base_url"] + cfg["token_path"],
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.load(resp)
    tokens["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))
    tokens["client_id"] = pending["client_id"]
    creds_file = expand_path(cfg["creds_file"])
    creds_file.parent.mkdir(parents=True, exist_ok=True)
    creds_file.write_text(json.dumps(tokens, indent=2))
    _clear_pending(cfg)
    print(f"Saved tokens to {creds_file}. Access token valid {tokens.get('expires_in', 3600)}s.", flush=True)
    return 0


def complete_from_url(cfg: dict, callback_url: str) -> int:
    """Finalize a PKCE flow that was started earlier — using a callback URL
    pasted by the user (e.g. when they logged in on a phone and the localhost
    redirect couldn't reach the server)."""
    pending = _read_pending(cfg)
    parsed = urllib.parse.urlparse(callback_url)
    qs = urllib.parse.parse_qs(parsed.query)
    code = (qs.get("code") or [None])[0]
    received_state = (qs.get("state") or [None])[0]
    err = (qs.get("error") or [None])[0]
    if err:
        print(f"OAuth error in callback URL: {err}", file=sys.stderr)
        return 1
    if not code:
        print("Callback URL has no `code` parameter — wrong URL?", file=sys.stderr)
        return 2
    if received_state != pending["state"]:
        print("State mismatch — wrong pending flow or possible CSRF. Aborting.", file=sys.stderr)
        return 3
    return _exchange_code_for_tokens(cfg, code, pending)


def register_or_load_client(cfg: dict, redirect_uri: str) -> str:
    """Return client_id. Either from config, cached file, or dynamic registration."""
    if cfg.get("client_id"):
        return cfg["client_id"]
    client_file = expand_path(cfg["client_file"])
    if client_file.exists():
        return json.loads(client_file.read_text())["client_id"]
    register_path = cfg.get("register_path")
    if not register_path:
        sys.exit("[oauth_pkce] No client_id in config and no register_path — cannot bootstrap")
    req = urllib.request.Request(
        cfg["base_url"] + register_path,
        data=json.dumps({"redirect_uris": [redirect_uri]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    client_file.parent.mkdir(parents=True, exist_ok=True)
    client_file.write_text(json.dumps(data, indent=2))
    return data["client_id"]


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    callback_path: str = "/oauth/callback"

    def do_GET(self) -> None:  # noqa: N802
        if not self.path.startswith(self.callback_path):
            self.send_error(404)
            return
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _received["code"] = qs.get("code", [None])[0]
        _received["state"] = qs.get("state", [None])[0]
        _received["error"] = qs.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = "<h1>Authentication complete</h1><p>You can close this window.</p>"
        if _received["error"]:
            body = f"<h1>OAuth error: {_received['error']}</h1>"
        self.wfile.write(body.encode())

    def log_message(self, *_a, **_k) -> None:
        pass


def run_pkce_flow(cfg: dict) -> int:
    port = int(cfg["callback_port"])
    callback_path = cfg["callback_path"]
    redirect_uri = f"http://localhost:{port}{callback_path}"
    client_id = register_or_load_client(cfg, redirect_uri)

    code_verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())
    state = secrets.token_hex(16)

    # Persist PKCE state BEFORE opening the browser so a manual-paste fallback
    # (--complete <callback-url>) works even if the local callback never fires
    # — e.g. when the user logs in on a different device (phone, remote machine).
    _write_pending(cfg, {
        "code_verifier": code_verifier,
        "state": state,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    })

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    scopes = cfg.get("scopes") or []
    if scopes:
        params["scope"] = " ".join(scopes)
    authorize_url = cfg["base_url"] + cfg["authorize_path"] + "?" + urllib.parse.urlencode(params)

    _CallbackHandler.callback_path = callback_path
    # SO_REUSEADDR avoids "address in use" if a prior failed run left the socket
    # in TIME_WAIT. Doesn't help if another process is actively listening —
    # that's a real conflict and the caller should pick a different port.
    socketserver.TCPServer.allow_reuse_address = True
    try:
        server = socketserver.TCPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as exc:
        print(
            f"[ryuu-mcp-oauth-pkce] Cannot bind to localhost:{port} — {exc}. "
            f"Another process is using this port. Edit callback_port in the "
            f"skill's oauth_config (and re-register the OAuth client) and retry.",
            file=sys.stderr,
        )
        return 4
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"Opening browser. If it doesn't open, paste this URL:\n  {authorize_url}", flush=True)
    try:
        webbrowser.open(authorize_url)
    except Exception:
        pass

    deadline = time.time() + 300
    while time.time() < deadline and not _received.get("code") and not _received.get("error"):
        time.sleep(0.5)
    server.shutdown()

    if _received.get("error"):
        print(f"OAuth error: {_received['error']}", file=sys.stderr)
        return 1
    code = _received.get("code")
    if not code:
        print("Timed out waiting for OAuth callback (5 minutes).", file=sys.stderr)
        return 2
    if _received.get("state") != state:
        print("OAuth state mismatch — aborting (possible CSRF).", file=sys.stderr)
        return 3

    return _exchange_code_for_tokens(cfg, code, {
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "state": state,
    })


def main() -> int:
    ap = argparse.ArgumentParser(description="Generic OAuth 2.0 PKCE bootstrap")
    add_config_args(ap)
    ap.add_argument(
        "--complete",
        metavar="CALLBACK_URL",
        help=(
            "Finalize a pending OAuth flow using a callback URL pasted by the user "
            "(e.g. when they logged in on a phone or remote machine and the localhost "
            "redirect couldn't reach the script). Must be called AFTER a regular run "
            "started the flow."
        ),
    )
    args = ap.parse_args()
    cfg = load_config(args)
    if args.complete:
        return complete_from_url(cfg, args.complete)
    return run_pkce_flow(cfg)


if __name__ == "__main__":
    sys.exit(main())
