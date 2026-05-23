"""Generic FastAPI router for eval framework — Step 4 of impl plan.

Any project mounts this để get full eval UI backend:

    from ryuu_eval.http import build_eval_router
    app.include_router(build_eval_router(
        runner_factory=my_build_runner,
        template_registry={my_template.template_id: my_template},
    ), prefix="/api/eval")

Provides:
  GET    /templates                          list[EvalCaseTemplate]
  GET    /templates/{template_id}            EvalCaseTemplate
  POST   /templates/{template_id}/cases       persist new case (form submit)
  GET    /suites/{suite_id}/cases             list cases for suite
  PUT    /suites/{suite_id}/cases/{case_id}   edit case
  DELETE /suites/{suite_id}/cases/{case_id}   remove case
  POST   /run                                  start blocking run, returns SuiteResult
  GET    /run/stream/{suite_id}                SSE stream of ProgressEvent
  GET    /refine_history/{suite_id}            list refine events
  POST   /optimize/{suite_id}                   trigger PromptOptimizer (manual fire — Q3)
  GET    /status                                running suites + cron status

Cron auto-optimization (Q3 = C) controlled by env ``CRON_OPTIMIZE_ENABLED``.
When unset/false (default): only manual fire via POST /optimize/{suite_id}.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, Depends, HTTPException
    from fastapi.responses import StreamingResponse
except ImportError as exc:
    raise ImportError(
        "FastAPI required for ryuu_eval.http. Install: pip install fastapi"
    ) from exc

from ryuu_eval_core import EvalCase, EvalCaseTemplate, EvalRunner
from ryuu_eval_core.fixture_loader import FixtureLoader


# ----------------------------------------------------------------------------
# Type aliases — caller provides these
# ----------------------------------------------------------------------------

RunnerFactory = Callable[[str, Path], EvalRunner]
"""(suite_id, refine_log_path) → configured EvalRunner.
Project's factory wires its target + scorers + refine_logger."""


def _dataclass_dict(obj: Any) -> Any:
    """Recursive dataclass → dict for JSON serialization."""
    if is_dataclass(obj):
        return {k: _dataclass_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_dataclass_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_dict(v) for k, v in obj.items()}
    return obj


# ----------------------------------------------------------------------------
# Router factory
# ----------------------------------------------------------------------------


def build_eval_router(
    *,
    runner_factory: RunnerFactory,
    template_registry: dict[str, EvalCaseTemplate],
    cases_dir: Path = Path("artifacts/eval/cases"),
    refine_log_dir: Path = Path("artifacts/eval/refine_history"),
    require_auth: Callable[..., Any] | None = None,
    optimizer_callback: Callable[[str, dict], dict] | None = None,
    serve_ui: bool = False,
    ui_prefix: str = "/ui",
) -> APIRouter:
    """Build APIRouter — caller mounts với prefix='/api/eval'.

    Args:
        runner_factory: builds EvalRunner per suite (project supplies target+scorers).
        template_registry: registered templates keyed by template_id.
        cases_dir: where to persist cases (YAML files, per suite subdir).
        refine_log_dir: where RefineLogger writes JSONL (per suite).
        require_auth: optional FastAPI dependency cho auth.
        optimizer_callback: ``(suite_id, params) → result_dict``. If provided,
            POST /optimize triggers it; else returns 501 Not Implemented.
    """
    r = APIRouter()
    auth_dep = [Depends(require_auth)] if require_auth else []

    # ── Templates ──────────────────────────────────────────────────────

    @r.get("/templates", dependencies=auth_dep)
    def list_templates() -> list[dict]:
        """Q1 — multiple templates per suite, all listed for UI gallery."""
        return [_dataclass_dict(t) for t in template_registry.values()]

    @r.get("/templates/{template_id}", dependencies=auth_dep)
    def get_template(template_id: str) -> dict:
        if template_id not in template_registry:
            raise HTTPException(404, f"Template not found: {template_id}")
        return _dataclass_dict(template_registry[template_id])

    @r.post("/templates/{template_id}/cases", dependencies=auth_dep)
    def create_case_from_template(template_id: str, payload: dict) -> dict:
        """Persist new case to <cases_dir>/<suite_id>/<case_id>.yml.

        payload shape: {case_id, input, expected, metadata?}
        """
        if template_id not in template_registry:
            raise HTTPException(404, f"Template not found: {template_id}")
        tpl = template_registry[template_id]
        case_id = str(payload.get("case_id", "")).strip()
        if not case_id:
            raise HTTPException(400, "case_id required")

        suite_dir = cases_dir / tpl.suite_id
        suite_dir.mkdir(parents=True, exist_ok=True)
        out_path = suite_dir / f"{case_id}.yml"

        try:
            import yaml
        except ImportError:
            raise HTTPException(500, "PyYAML required to persist cases")

        yaml_data = {
            "case_id": case_id,
            "input": payload["input"],
            "expected": payload.get("expected"),
            "metadata": {**payload.get("metadata", {}), "template_id": template_id},
        }
        out_path.write_text(
            yaml.safe_dump(yaml_data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return {"case_id": case_id, "path": str(out_path), "ok": True}

    # ── Suite cases ────────────────────────────────────────────────────

    @r.get("/suites/{suite_id}/cases", dependencies=auth_dep)
    def list_suite_cases(suite_id: str) -> list[dict]:
        suite_dir = cases_dir / suite_id
        if not suite_dir.exists():
            return []
        cases = []
        for f in sorted(suite_dir.glob("*.yml")):
            try:
                loaded = FixtureLoader.load(f)
                cases.extend([{
                    "case_id": c.case_id, "input": c.input,
                    "expected": c.expected, "metadata": c.metadata,
                    "_path": str(f),
                } for c in loaded])
            except Exception as exc:  # noqa: BLE001
                cases.append({"case_id": f.stem, "error": str(exc), "_path": str(f)})
        return cases

    @r.put("/suites/{suite_id}/cases/{case_id}", dependencies=auth_dep)
    def update_case(suite_id: str, case_id: str, payload: dict) -> dict:
        suite_dir = cases_dir / suite_id
        out_path = suite_dir / f"{case_id}.yml"
        if not out_path.exists():
            raise HTTPException(404, f"Case not found: {out_path}")
        try:
            import yaml
        except ImportError:
            raise HTTPException(500, "PyYAML required")
        yaml_data = {
            "case_id": case_id,
            "input": payload["input"],
            "expected": payload.get("expected"),
            "metadata": payload.get("metadata", {}),
        }
        out_path.write_text(
            yaml.safe_dump(yaml_data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return {"ok": True, "case_id": case_id}

    @r.delete("/suites/{suite_id}/cases/{case_id}", dependencies=auth_dep)
    def delete_case(suite_id: str, case_id: str) -> dict:
        out_path = cases_dir / suite_id / f"{case_id}.yml"
        if not out_path.exists():
            raise HTTPException(404, f"Case not found: {out_path}")
        out_path.unlink()
        return {"ok": True, "deleted": str(out_path)}

    # ── Run (blocking + streaming) ─────────────────────────────────────

    @r.post("/run", dependencies=auth_dep)
    async def run_suite_blocking(payload: dict) -> dict:
        """Blocking run — returns full SuiteResult."""
        suite_id = payload.get("suite_id", "")
        if not suite_id:
            raise HTTPException(400, "suite_id required")
        log_path = refine_log_dir / f"{suite_id}.jsonl"
        runner = runner_factory(suite_id, log_path)
        cases = list_suite_cases(suite_id)
        eval_cases = FixtureLoader.load_json([{
            "case_id": c["case_id"],
            "input": c["input"],
            "expected": c.get("expected"),
            "metadata": c.get("metadata", {}),
        } for c in cases if "error" not in c])
        result = await runner.run(eval_cases)
        return _dataclass_dict(result)

    @r.get("/run/stream/{suite_id}", dependencies=auth_dep)
    async def stream_suite(suite_id: str) -> StreamingResponse:
        log_path = refine_log_dir / f"{suite_id}.jsonl"
        runner = runner_factory(suite_id, log_path)
        cases = list_suite_cases(suite_id)
        eval_cases = FixtureLoader.load_json([{
            "case_id": c["case_id"],
            "input": c["input"],
            "expected": c.get("expected"),
            "metadata": c.get("metadata", {}),
        } for c in cases if "error" not in c])

        async def _event_gen():
            async for event in runner.stream(eval_cases):
                payload = _dataclass_dict(event)
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            _event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Refine history ─────────────────────────────────────────────────

    @r.get("/refine_history/{suite_id}", dependencies=auth_dep)
    def list_refine_history(suite_id: str, limit: int = 100) -> dict:
        log_path = refine_log_dir / f"{suite_id}.jsonl"
        if not log_path.exists():
            return {"suite_id": suite_id, "events": []}
        try:
            from ryuu.refine_logger import RefineLogger
            events = RefineLogger.load_all(log_path)
            stats = RefineLogger.stats(log_path)
            return {
                "suite_id": suite_id,
                "stats": stats,
                "events": [_dataclass_dict(e) for e in events[-limit:]],
            }
        except ImportError:
            # ryuu (full) not installed — fallback raw JSONL read
            events = []
            for line in log_path.read_text().splitlines():
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return {"suite_id": suite_id, "events": events[-limit:]}

    # ── Optimizer (Q3 = C: manual fire + cron opt-in) ──────────────────

    @r.post("/optimize/{suite_id}", dependencies=auth_dep)
    async def trigger_optimize(suite_id: str, payload: dict) -> dict:
        """Manual fire — UI button. Always allowed regardless of CRON flag."""
        if optimizer_callback is None:
            raise HTTPException(501, "optimizer_callback not configured")
        return await _maybe_await(optimizer_callback, suite_id, payload)

    @r.get("/status", dependencies=auth_dep)
    def status() -> dict:
        return {
            "cron_enabled": _is_cron_enabled(),
            "templates_count": len(template_registry),
            "cases_dir": str(cases_dir),
            "refine_log_dir": str(refine_log_dir),
            "ui_served": serve_ui,
        }

    # ── Static UI (Tier 1) ─────────────────────────────────────────────

    if serve_ui:
        from ryuu_eval.http.ui import mount_ui
        mount_ui(r, prefix=ui_prefix)

    return r


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _is_cron_enabled() -> bool:
    """Q3 — cron auto-optimize opt-in via env."""
    return os.environ.get("CRON_OPTIMIZE_ENABLED", "").lower() in ("1", "true", "yes")


async def _maybe_await(fn: Any, *args, **kwargs) -> Any:
    """Call fn — await if returns coroutine."""
    import inspect
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = ["build_eval_router", "RunnerFactory"]
