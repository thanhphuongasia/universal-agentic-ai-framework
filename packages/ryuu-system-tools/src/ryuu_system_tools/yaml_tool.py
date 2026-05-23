"""Declarative YAML tools — describe a tool with YAML, no Python needed.

Drop `~/.ryuu/system_tools/<name>.yml` (or .yaml) with this schema:

    name: get_weather                  # tool_id surfaced to the LLM
    description: Returns current weather for a city
    parameters:                        # JSON-schema-style; LLM sees this verbatim
      city:
        type: string
        description: City name
        required: true
    exec:                              # one of: http, shell, static
      type: http
      url: https://api.example.com/weather?city={{city}}
      method: GET
      headers:
        Authorization: "Bearer ${WEATHER_API_TOKEN}"   # ${ENV} from os.environ
      timeout: 15

Substitution:
  • `{{arg}}`   — substituted from the tool-call arguments at runtime.
  • `${ENV}`    — substituted from process environment when the file loads.

Supported exec types:
  • static   — return a constant `value` (templated). Useful for stubs / fixtures.
  • shell    — run `command` (str → sh -c, or argv list); returns ok/exit/stdout/stderr.
  • http     — issue HTTP request; returns ok/status/data|text.

Security: shell is full system access. Treat YAML files as code — only put
trusted content in your `~/.ryuu/system_tools/` directory.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _subst(value: Any, args: dict[str, Any]) -> Any:
    """Recursive substitution: {{arg}} from args, ${ENV} from os.environ."""
    if isinstance(value, str):
        s = _VAR_RE.sub(lambda m: str(args.get(m.group(1), "")), value)
        s = _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), s)
        return s
    if isinstance(value, dict):
        return {k: _subst(v, args) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, args) for v in value]
    return value


@dataclass
class YamlTool:
    tool_id: str
    description: str
    parameters: dict[str, Any]
    exec_spec: dict[str, Any]
    source_path: str = ""   # for diagnostics

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.tool_id,
                "description": self.description or f"YAML-defined tool {self.tool_id!r}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        k: {kk: vv for kk, vv in v.items() if kk != "required"}
                        for k, v in (self.parameters or {}).items()
                    },
                    "required": [k for k, v in (self.parameters or {}).items() if v.get("required")],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        args = args or {}
        ex = self.exec_spec or {}
        kind = ex.get("type")
        if kind == "static":
            return _subst(ex.get("value"), args)
        if kind == "shell":
            return await self._run_shell(ex, args)
        if kind == "http":
            return await self._run_http(ex, args)
        return {"error": f"Unknown exec type: {kind!r}", "tool": self.tool_id}

    async def _run_shell(self, ex: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        cmd = ex.get("command")
        if cmd is None:
            return {"ok": False, "error": "shell exec missing 'command'"}
        timeout = float(ex.get("timeout", 30))
        if isinstance(cmd, str):
            argv = ["sh", "-c", _subst(cmd, args)]
        else:
            argv = [_subst(str(c), args) for c in cmd]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"Command not found: {exc}"}
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"timeout after {int(timeout)}s"}
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }

    async def _run_http(self, ex: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        url_tmpl = ex.get("url")
        if not url_tmpl:
            return {"ok": False, "error": "http exec missing 'url'"}
        url = _subst(url_tmpl, args)
        # Auto-encode query params if `query` is a dict
        query = _subst(ex.get("query") or {}, args)
        if query:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(query)

        method = (ex.get("method") or "GET").upper()
        headers = _subst(ex.get("headers") or {}, args)
        body = ex.get("body")
        body_bytes: bytes | None = None
        if body is not None:
            substituted = _subst(body, args)
            if isinstance(substituted, (dict, list)):
                body_bytes = json.dumps(substituted).encode()
                headers.setdefault("Content-Type", "application/json")
            else:
                body_bytes = str(substituted).encode()
        timeout = float(ex.get("timeout", 30))

        def _do_request() -> dict[str, Any]:
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = resp.read()
                    ct = resp.headers.get("Content-Type", "") or ""
                    text = data.decode("utf-8", errors="replace")
                    out: dict[str, Any] = {"ok": True, "status": resp.status}
                    if "json" in ct:
                        try:
                            out["data"] = json.loads(text)
                            return out
                        except Exception:  # noqa: BLE001
                            pass
                    out["text"] = text
                    return out
            except urllib.error.HTTPError as exc:
                return {"ok": False, "status": exc.code, "error": exc.reason,
                        "body": exc.read().decode("utf-8", errors="replace")[:500]}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _do_request)


def load_yaml_tool(path: Path) -> YamlTool | None:
    """Parse a YAML file into a YamlTool. Returns None (with warning) on error."""
    try:
        data = yaml.safe_load(path.read_text())
    except Exception as exc:  # noqa: BLE001
        log.warning("YAML tool %s failed to parse: %s", path, exc)
        return None
    if not isinstance(data, dict):
        log.warning("YAML tool %s is not a mapping at top level — skipped", path)
        return None
    name = data.get("name") or path.stem
    exec_spec = data.get("exec") or {}
    if not isinstance(exec_spec, dict) or not exec_spec.get("type"):
        log.warning("YAML tool %s missing exec.type — skipped", path)
        return None
    return YamlTool(
        tool_id=name,
        description=data.get("description", ""),
        parameters=data.get("parameters") or {},
        exec_spec=exec_spec,
        source_path=str(path),
    )


__all__ = ["YamlTool", "load_yaml_tool"]
