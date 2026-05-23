"""SystemToolset — discovers + bundles ITool plug-ins from layered sources.

Three independent extension surfaces, none of which require editing existing
framework or app code:

  1. **Bundled defaults** — *.py files in `ryuu_system_tools.bundled/`.
     Adding a new framework default = drop a file in that directory.
  2. **Entry-points** — any pip-installed package can declare:
         [project.entry-points."ryuu_system_tools.plugins"]
         myname = "my_pkg.module:register"
     Installing the package = the tool is registered. No framework deploy
     needed; no file-path knowledge needed by the app.
  3. **Filesystem plug-ins** — drop *.py into:
         • $RYUU_SYSTEM_TOOLS_DIR (env, colon-separated paths)
         • ~/.ryuu/system_tools/
         • Any `extra_dirs` passed to `from_layered`

Plug-in convention (see package README):
  • Module must expose `TOOLS: list[ITool]` OR `def register() -> list[ITool]`.
  • Filename / entry-point name must not start with `_`.

Import failures are logged and the module is skipped — broken plug-ins never
break the toolset for everyone else.

Lookup order (later wins on tool_id collision — explicit replacement, not
duplicate registration): bundled → entry-points → env-dir → user-dir → extra_dirs.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_BUNDLED_PACKAGE = "ryuu_system_tools.bundled"
_ENTRY_POINT_GROUP = "ryuu_system_tools.plugins"


def _collect_from_package(package_name: str) -> list[Any]:
    """Walk a regular Python package, yield tools from *.py modules AND *.yml files.

    Bundled tools can be either Python (full ITool implementations) or
    declarative YAML — same plug-in convention as ~/.ryuu/system_tools/.
    """
    package = importlib.import_module(package_name)
    found: list[Any] = []

    # Python modules
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        full = f"{package_name}.{info.name}"
        try:
            module = importlib.import_module(full)
        except Exception as exc:  # noqa: BLE001
            log.warning("System tool module %s failed to import: %s", full, exc)
            continue
        found.extend(_extract_tools(module, full))

    # YAML declarative tools bundled alongside the Python modules
    from ryuu_system_tools.yaml_tool import load_yaml_tool
    for pkg_dir in package.__path__:
        pkg_path = Path(pkg_dir)
        for yml in sorted([*pkg_path.glob("*.yml"), *pkg_path.glob("*.yaml")]):
            if yml.name.startswith("_"):
                continue
            tool = load_yaml_tool(yml)
            if tool is not None:
                found.append(tool)
    return found


def _collect_from_dir(directory: Path) -> list[Any]:
    """Scan a filesystem directory for plug-ins (*.py imports + *.yml YAML tools)."""
    if not directory.exists() or not directory.is_dir():
        return []
    found: list[Any] = []

    # Python plug-ins
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"_ryuu_system_tool_{path.stem}_{abs(hash(str(path))) % 10_000_000}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            log.warning("System tool file %s failed to import: %s", path, exc)
            continue
        found.extend(_extract_tools(module, str(path)))

    # YAML-declarative plug-ins (no Python needed)
    from ryuu_system_tools.yaml_tool import load_yaml_tool
    for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]):
        if path.name.startswith("_"):
            continue
        tool = load_yaml_tool(path)
        if tool is not None:
            found.append(tool)
    return found


def _collect_from_entry_points(group: str) -> list[Any]:
    """Discover tools registered by any installed package via Python entry-points.

    Lets a 3rd-party package contribute tools to every Ryuu agent on the box
    just by being pip-installed — no edits to ryuu-system-tools, no edits to
    the host app. Mirrors how pytest, mkdocs, etc. discover plug-ins.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return []
    found: list[Any] = []
    try:
        eps = entry_points(group=group)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to query entry-points group %s: %s", group, exc)
        return []
    for ep in eps:
        if ep.name.startswith("_"):
            continue
        try:
            obj = ep.load()
        except Exception as exc:  # noqa: BLE001
            log.warning("Entry-point %s (%s) failed to load: %s", ep.name, ep.value, exc)
            continue
        if callable(obj):
            try:
                tools = obj()
            except Exception as exc:  # noqa: BLE001
                log.warning("Entry-point %s callable raised: %s", ep.name, exc)
                continue
        else:
            tools = obj
        if tools is None:
            continue
        try:
            found.extend(list(tools))   # type: ignore[arg-type]
        except TypeError:
            log.warning("Entry-point %s yielded non-iterable %r — skipped", ep.name, tools)
    return found


def _extract_tools(module: Any, source_label: str) -> list[Any]:
    """Pull tools out of a module via `register()` (preferred) or `TOOLS`."""
    if callable(getattr(module, "register", None)):
        try:
            tools = module.register()
        except Exception as exc:  # noqa: BLE001
            log.warning("register() in %s raised: %s", source_label, exc)
            return []
    else:
        tools = getattr(module, "TOOLS", None)
    if tools is None:
        log.warning("Module %s exports neither register() nor TOOLS — skipped", source_label)
        return []
    return list(tools)


def _default_user_dirs() -> list[Path]:
    """The standard layered lookup dirs (env + user home)."""
    dirs: list[Path] = []
    env = os.environ.get("RYUU_SYSTEM_TOOLS_DIR", "").strip()
    if env:
        # Allow `:`-separated list (POSIX PATH convention)
        for part in env.split(os.pathsep):
            part = part.strip()
            if part:
                dirs.append(Path(part).expanduser())
    dirs.append(Path.home() / ".ryuu" / "system_tools")
    return dirs


@dataclass
class SystemToolset:
    """Bundle of layered system ITools — bundled defaults + plug-ins."""

    _tools_by_id: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_layered(cls, extra_dirs: list[Path | str] | None = None) -> "SystemToolset":
        """Discover tools across all extension surfaces and merge.

        Order (later layers win on tool_id collision):
          1. Bundled defaults (ships with this package)
          2. Entry-points (any pip-installed package — no deploy of framework)
          3. $RYUU_SYSTEM_TOOLS_DIR (env)
          4. ~/.ryuu/system_tools/ (user)
          5. extra_dirs (caller / per-project)
        """
        layers: list[list[Any]] = [
            _collect_from_package(_BUNDLED_PACKAGE),
            _collect_from_entry_points(_ENTRY_POINT_GROUP),
        ]
        for d in _default_user_dirs():
            layers.append(_collect_from_dir(d))
        for d in extra_dirs or []:
            layers.append(_collect_from_dir(Path(d).expanduser()))

        merged: dict[str, Any] = {}
        for layer in layers:
            for tool in layer:
                tid = getattr(tool, "tool_id", None) or tool.__class__.__name__
                merged[tid] = tool
        return cls(_tools_by_id=merged)

    @property
    def tools(self) -> list[Any]:
        return list(self._tools_by_id.values())

    def tool_ids(self) -> list[str]:
        return sorted(self._tools_by_id.keys())


__all__ = ["SystemToolset"]
