"""FixtureLoader — load EvalCase + EvalCaseTemplate từ JSON/YAML.

Step 7 (Q4 = C — YAML primary, Python escape hatch):
  - YAML cho declarative cases (UI-editable)
  - ``!py "expression"`` tag cho computed values (e.g. datetime.now())
  - JSON fallback (legacy support)
  - ``list_templates(suite_dir)`` discovers templates.yml files for UI gallery
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from ryuu_eval_core.models import EvalCase, EvalCaseTemplate

# ----------------------------------------------------------------------------
# Python escape hatch — restricted eval for !py tag
# ----------------------------------------------------------------------------

_SAFE_BUILTINS = {
    "True": True, "False": False, "None": None,
    "int": int, "float": float, "str": str, "list": list, "dict": dict,
    "len": len, "range": range, "sum": sum, "min": min, "max": max,
}

_SAFE_MODULES = {
    "datetime": datetime,
}


def _eval_py_expr(expr: str) -> Any:
    """Safe-ish eval for !py tag values. Only stdlib + builtins."""
    return eval(expr, {"__builtins__": _SAFE_BUILTINS, **_SAFE_MODULES})  # noqa: S307


# ----------------------------------------------------------------------------
# YAML loader với !py tag support
# ----------------------------------------------------------------------------


def _build_yaml_loader():
    """Return PyYAML SafeLoader subclass with !py tag registered."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML required for YAML fixture loading. Install: pip install pyyaml"
        ) from exc

    class _CaseYamlLoader(yaml.SafeLoader):
        pass

    def _py_constructor(loader, node):
        expr = loader.construct_scalar(node)
        return _eval_py_expr(expr)

    _CaseYamlLoader.add_constructor("!py", _py_constructor)
    return _CaseYamlLoader, yaml


# ----------------------------------------------------------------------------
# Loader API
# ----------------------------------------------------------------------------


class FixtureLoader:
    """Load EvalCase/EvalCaseTemplate from JSON or YAML files."""

    @staticmethod
    def load(path: str | Path) -> list[EvalCase]:
        """Auto-detect JSON or YAML by extension. Returns list[EvalCase]."""
        p = Path(path)
        if p.suffix in (".yml", ".yaml"):
            return FixtureLoader._load_yaml(p)
        # Default: JSON
        data = json.loads(p.read_text())
        cases_data: list[dict[str, Any]] = (
            data if isinstance(data, list) else data.get("cases", [data])
        )
        return FixtureLoader.load_json(cases_data)

    @staticmethod
    def load_json(data: list[dict[str, Any]]) -> list[EvalCase]:
        return [
            EvalCase(
                case_id=c.get("case_id", str(i)),
                input=c["input"],
                expected=c.get("expected"),
                metadata=c.get("metadata", {}),
            )
            for i, c in enumerate(data)
        ]

    @staticmethod
    def _load_yaml(path: Path) -> list[EvalCase]:
        """Parse YAML với !py tag support.

        Accepts three shapes:
          - list[dict]              — multiple cases
          - {"cases": [dict, ...]}   — multiple cases wrapped
          - dict với case_id key     — single case (auto-wrapped to list)
        """
        Loader, yaml = _build_yaml_loader()
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
        if isinstance(data, dict) and "cases" in data:
            data = data["cases"]
        elif isinstance(data, dict) and ("case_id" in data or "input" in data):
            # Single case dict → wrap to list
            data = [data]
        if not isinstance(data, list):
            raise ValueError(
                f"{path}: expected list, {{cases: [...]}}, or single case dict, "
                f"got {type(data).__name__}",
            )
        return FixtureLoader.load_json(data)

    # ------------------------------------------------------------------
    # Templates — Q1: multiple templates per suite
    # ------------------------------------------------------------------

    @staticmethod
    def load_template(path: str | Path) -> EvalCaseTemplate:
        """Load single template từ YAML file."""
        p = Path(path)
        Loader, yaml = _build_yaml_loader()
        data = yaml.load(p.read_text(encoding="utf-8"), Loader=Loader)
        if not isinstance(data, dict):
            raise ValueError(f"{p}: expected template dict, got {type(data).__name__}")
        return EvalCaseTemplate(
            template_id=data["template_id"],
            suite_id=data["suite_id"],
            title=data.get("title", data["template_id"]),
            description=data.get("description", ""),
            input_schema=data.get("input_schema", {}),
            expected_schema=data.get("expected_schema", {}),
            examples=data.get("examples", []),
            tags=data.get("tags", []),
        )

    @staticmethod
    def list_templates(suite_dir: str | Path) -> list[EvalCaseTemplate]:
        """Discover all *_template.yml / templates/*.yml in suite_dir.

        Convention: suite directory may contain:
          templates/<template_id>.yml
          *.template.yml
        Both patterns auto-discovered.
        """
        suite_path = Path(suite_dir)
        if not suite_path.exists():
            return []

        candidates: list[Path] = []
        templates_subdir = suite_path / "templates"
        if templates_subdir.is_dir():
            candidates.extend(templates_subdir.glob("*.yml"))
            candidates.extend(templates_subdir.glob("*.yaml"))
        # Also files matching *.template.yml in suite_dir
        candidates.extend(suite_path.glob("*.template.yml"))
        candidates.extend(suite_path.glob("*.template.yaml"))

        result: list[EvalCaseTemplate] = []
        for f in sorted(set(candidates)):
            try:
                result.append(FixtureLoader.load_template(f))
            except (KeyError, ValueError):
                continue
        return result
