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
import time
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
    fixtures_dir: Path | None = None,
    last_run_dir: Path | None = None,
    require_auth: Callable[..., Any] | None = None,
    optimizer_callback: Callable[[str, dict], dict] | None = None,
    prompt_resolver: Callable[[str], dict[str, Any] | None] | None = None,
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
        prompt_resolver: ``suite_id -> {path, content, system?, user_template?, output_schema?}``
            (or None when no prompt available). Drives ``GET /suites/{id}/prompt`` so
            external eval frameworks can fetch the prompt being evaluated. Framework
            stays generic — project supplies the lookup mapping its prompts dir.
    """
    import asyncio

    r = APIRouter()
    auth_dep = [Depends(require_auth)] if require_auth else []

    # Active runners keyed by run_id.
    active_runners: dict[str, EvalRunner] = {}
    # SSE event queues keyed by run_id (None sentinel = stream ended).
    _run_queues: dict[str, "asyncio.Queue[dict | None]"] = {}
    # Completed run results keyed by run_id (in-memory, survives until process restart).
    _run_results: dict[str, dict] = {}

    # Where SuiteResult JSON snapshots are written after each run, so the UI
    # can show "Actual (last run)" without re-running.
    _last_run_dir = last_run_dir or (cases_dir.parent / "last_run")

    # ── Suites discovery ───────────────────────────────────────────────

    def _suite_dir(suite_id: str) -> Path:
        return cases_dir / suite_id

    def _list_suite_datasets(suite_id: str) -> list[str]:
        """Datasets = subdirectories under cases_dir/<suite_id>/ (excluding
        the reserved ``templates`` dir). Empty list when no datasets exist —
        cases live flat at the suite root."""
        d = _suite_dir(suite_id)
        if not d.exists():
            return []
        return sorted([
            p.name for p in d.iterdir()
            if p.is_dir() and p.name != "templates"
        ])

    def _count_suite_cases(suite_id: str) -> int:
        d = _suite_dir(suite_id)
        if not d.exists():
            return 0
        # Top-level YAML cases + YAML in dataset subdirs (skip templates/)
        count = sum(1 for _ in d.glob("*.yml"))
        for sub in d.iterdir():
            if sub.is_dir() and sub.name != "templates":
                count += sum(1 for _ in sub.glob("*.yml"))
        return count

    def _read_last_run(suite_id: str) -> dict | None:
        path = _last_run_dir / f"{suite_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_last_run(suite_id: str, suite_result: Any, model: str | None = None) -> None:
        try:
            _last_run_dir.mkdir(parents=True, exist_ok=True)
            payload = _dataclass_dict(suite_result)
            # SuiteResult.{passed_count,total_count,pass_rate} are @property,
            # so asdict() drops them. Inject explicitly so the UI doesn't have
            # to recompute from the cases array.
            payload["passed_count"] = suite_result.passed_count
            payload["total_count"] = suite_result.total_count
            payload["pass_rate"] = suite_result.pass_rate
            payload["finished_at"] = time.time()
            if model:
                payload["model"] = model
            (_last_run_dir / f"{suite_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass  # best-effort — never fail the run for a write error

    @r.get("/suites", dependencies=auth_dep)
    def list_suites() -> list[dict]:
        """List all suite_ids discovered from templates + cases_dir subdirs.

        UI uses this to dynamically render suite cards instead of hardcoding.
        """
        suite_ids: set[str] = set()
        for tpl in template_registry.values():
            if tpl.suite_id:
                suite_ids.add(tpl.suite_id)
        if cases_dir.exists():
            for d in cases_dir.iterdir():
                if d.is_dir():
                    suite_ids.add(d.name)
        result: list[dict] = []
        for sid in sorted(suite_ids):
            tpls = [t for t in template_registry.values() if t.suite_id == sid]
            result.append({
                "suite_id": sid,
                "templates": [_dataclass_dict(t) for t in tpls],
            })
        return result

    @r.get("/suites/{suite_id}", dependencies=auth_dep)
    def get_suite_metadata(suite_id: str) -> dict:
        """Metadata for one suite — title (from first template), case count,
        datasets, last_run summary, model (inferred from last_run)."""
        tpls = [t for t in template_registry.values() if t.suite_id == suite_id]
        last_run = _read_last_run(suite_id)
        model: str | None = (last_run or {}).get("model")
        return {
            "suite_id": suite_id,
            "title": tpls[0].title if tpls else suite_id,
            "templates": [_dataclass_dict(t) for t in tpls],
            "case_count": _count_suite_cases(suite_id),
            "datasets": _list_suite_datasets(suite_id),
            "model": model,
            "last_run": (
                {
                    "run_id": last_run.get("run_id"),
                    "passed_count": last_run.get("passed_count")
                        or sum(1 for c in last_run.get("cases", []) if c.get("passed")),
                    "total_count": last_run.get("total_count")
                        or len(last_run.get("cases", [])),
                    "pass_rate": last_run.get("pass_rate"),
                    "total_cost_usd": last_run.get("total_cost_usd"),
                    "finished_at": last_run.get("finished_at"),
                }
                if last_run else None
            ),
        }

    @r.get("/suites/{suite_id}/datasets", dependencies=auth_dep)
    def list_datasets(suite_id: str) -> list[str]:
        return _list_suite_datasets(suite_id)

    @r.get("/suites/{suite_id}/last_run", dependencies=auth_dep)
    def get_last_run(suite_id: str) -> dict:
        """Full SuiteResult from the most recent run. 404 if never run."""
        data = _read_last_run(suite_id)
        if data is None:
            raise HTTPException(404, f"No prior run for suite_id={suite_id}")
        return data

    @r.get("/suites/{suite_id}/prompt", dependencies=auth_dep)
    def get_suite_prompt(suite_id: str) -> dict:
        """Return the prompt YAML used by this suite — for external eval frameworks
        that want to inspect / diff / optimize without running through us.

        Project must supply ``prompt_resolver`` when building the router; otherwise
        this endpoint returns 501. Resolver returns ``None`` when the suite has no
        prompt registered (404).
        """
        if prompt_resolver is None:
            raise HTTPException(501, "prompt_resolver not configured")
        data = prompt_resolver(suite_id)
        if data is None:
            raise HTTPException(404, f"No prompt registered for suite_id={suite_id}")
        return data

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

    @r.post("/suites/{suite_id}/cases/{case_id}/run", dependencies=auth_dep)
    async def run_persisted_case(
        suite_id: str, case_id: str, payload: dict | None = None,
    ) -> dict:
        """Synchronously run one persisted case by ID — for external eval
        frameworks that want to invoke the project's full pipeline (context
        builder + LLM + scorers) on a single case and get the result back in
        one HTTP call (no streaming).

        Returns the case's ``CaseResult`` as a dict including ``passed``,
        ``scores[]``, ``output``, ``latency_ms``, ``cost_usd``, ``error``.
        Looks up the case in cases_dir + fixtures_dir; 404 if not found.
        """
        _ = payload  # reserved for future overrides (model, dataset, etc.)
        all_cases = _load_all_cases(suite_id)
        match = next(
            (c for c in all_cases if c.get("case_id") == case_id and "error" not in c),
            None,
        )
        if match is None:
            raise HTTPException(404, f"case {case_id!r} not found in suite {suite_id!r}")

        log_path = refine_log_dir / f"{suite_id}.jsonl"
        runner = runner_factory(suite_id, log_path)
        eval_cases = FixtureLoader.load_json([{
            "case_id": case_id,
            "input": match["input"],
            "expected": match.get("expected"),
            "metadata": match.get("metadata", {}),
        }])
        result = await runner.run(eval_cases)
        if not result.cases:
            return {"suite_id": suite_id, "case_id": case_id, "error": "no result"}
        cr = result.cases[0]
        out = _dataclass_dict(cr)
        out["passed"] = cr.passed  # @property dropped by asdict
        out["suite_id"] = suite_id
        return out

    # ── Fixture cases (read-only from fixtures_dir) ────────────────────

    @r.get("/fixtures/{suite_id}", dependencies=auth_dep)
    def list_fixtures(suite_id: str) -> list[dict]:
        """Read-only fixture cases from fixtures_dir/<suite_id>/*.yml."""
        if fixtures_dir is None:
            return []
        suite_path = fixtures_dir / suite_id
        if not suite_path.exists():
            return []
        cases: list[dict] = []
        for f in sorted(suite_path.glob("*.yml")):
            try:
                loaded = FixtureLoader.load(f)
                cases.extend([{
                    "case_id": c.case_id,
                    "input": c.input,
                    "expected": c.expected,
                    "metadata": c.metadata,
                    "_source": "fixture",
                    "_file": f.name,
                } for c in loaded])
            except Exception as exc:  # noqa: BLE001
                cases.append({"case_id": f.stem, "error": str(exc), "_source": "fixture", "_file": f.name})
        return cases

    def _load_all_cases(suite_id: str) -> list[dict]:
        """Combine UI-created cases + fixture cases; UI case wins on duplicate case_id."""
        ui_cases = list_suite_cases(suite_id)
        if fixtures_dir is None:
            return ui_cases
        ui_ids = {c["case_id"] for c in ui_cases if "error" not in c}
        for fc in list_fixtures(suite_id):
            if "error" not in fc and fc["case_id"] not in ui_ids:
                ui_cases.append(fc)
        return ui_cases

    # ── Run (async start + SSE stream) ────────────────────────────────

    def _build_eval_cases(suite_id: str, case_ids: list[str] | None) -> list:
        raw = _load_all_cases(suite_id)
        if case_ids:
            raw = [c for c in raw if c["case_id"] in case_ids]
        return FixtureLoader.load_json([{
            "case_id": c["case_id"],
            "input": c["input"],
            "expected": c.get("expected"),
            "metadata": c.get("metadata", {}),
        } for c in raw if "error" not in c])

    def _to_ui_event(raw: dict, _suite_id: str = "") -> dict | None:
        """Transform backend ProgressEvent dict → frontend StreamEvent dict.

        Backend: {type, payload, case_id}  →  Frontend: {event, ...flat fields}
        Returns None for events the UI doesn't need (llm_attempt, llm_done, etc).
        """
        etype = raw.get("type", "")
        payload: dict = raw.get("payload") or {}
        case_id = raw.get("case_id")
        run_id_val: str = payload.get("run_id", "")

        if etype == "suite_start":
            return {
                "event": "run_start",
                "run_id": run_id_val,
                "total": payload.get("total_cases", 0),
            }
        if etype == "case_start":
            return {"event": "case_start", "case_id": case_id}
        if etype == "case_done":
            scores: list = payload.get("scores") or []
            score_val = scores[0]["score"] if scores else None
            passed = bool(payload.get("passed"))
            return {
                "event": "case_done",
                "case_id": case_id,
                "result": {
                    "case_id": case_id,
                    "suite_id": _suite_id,
                    "pass": passed,
                    "score": score_val,
                    "latency_ms": payload.get("latency_ms"),
                    "cost_usd": payload.get("cost_usd"),
                    "tokens_in": payload.get("tokens_in"),
                    "tokens_out": payload.get("tokens_out"),
                    "error": payload.get("error"),
                },
            }
        if etype == "suite_done":
            cancelled = bool(payload.get("cancelled"))
            if cancelled:
                return {"event": "run_cancel", "run_id": run_id_val}
            total = payload.get("total_count", 0)
            passed_count = payload.get("passed_count", 0)
            return {
                "event": "run_done",
                "run_id": run_id_val,
                "summary": {
                    "run_id": run_id_val,
                    "suite_id": _suite_id,
                    "status": "done",
                    "total_cases": total,
                    "completed_cases": total,
                    "passed_cases": passed_count,
                    "failed_cases": max(0, total - passed_count),
                    "avg_score": payload.get("pass_rate"),
                    "total_cost_usd": payload.get("total_cost_usd"),
                },
            }
        if etype == "error":
            if (payload.get("error_type") or "") == "cancelled":
                return {"event": "run_cancel"}
            return {"event": "error", "error": payload.get("message", "unknown error")}
        # Skip: llm_attempt, llm_done, refine_attempt, refine_done
        return None

    @r.post("/run", dependencies=auth_dep)
    async def start_run(payload: dict) -> dict:
        """Start async run — returns {run_id} immediately.
        Stream progress via GET /run/stream/{run_id}.
        Fetch result via GET /runs/{run_id} after completion.
        """
        suite_id = str(payload.get("suite_id", "")).strip()
        if not suite_id:
            raise HTTPException(400, "suite_id required")

        model = str(payload.get("model", "")).strip()
        case_ids: list[str] | None = payload.get("case_ids") or None
        concurrency = max(1, min(int(payload.get("concurrency", 4)), 16))

        log_path = refine_log_dir / f"{suite_id}.jsonl"
        runner = runner_factory(suite_id, log_path)
        run_id = runner.run_id
        eval_cases = _build_eval_cases(suite_id, case_ids)

        queue: asyncio.Queue = asyncio.Queue()
        _run_queues[run_id] = queue
        active_runners[run_id] = runner

        async def _bg() -> None:
            try:
                async for event in runner.stream(eval_cases, concurrency=concurrency):
                    ui_ev = _to_ui_event(_dataclass_dict(event), suite_id)
                    if ui_ev is not None:
                        await queue.put(ui_ev)
            finally:
                await queue.put(None)  # sentinel — SSE reader exits loop
                active_runners.pop(run_id, None)
                _run_queues.pop(run_id, None)
                if runner.last_suite_result is not None:
                    rd = _dataclass_dict(runner.last_suite_result)
                    rd.update({
                        "passed_count": runner.last_suite_result.passed_count,
                        "total_count": runner.last_suite_result.total_count,
                        "pass_rate": runner.last_suite_result.pass_rate,
                        "finished_at": time.time(),
                        "model": model or None,
                    })
                    _run_results[run_id] = rd
                    _write_last_run(suite_id, runner.last_suite_result, model or None)

        asyncio.create_task(_bg())
        return {"run_id": run_id, "suite_id": suite_id}

    @r.get("/run/stream/{run_id}", dependencies=auth_dep)
    async def stream_run(run_id: str) -> StreamingResponse:
        """SSE stream for a specific run. Connect immediately after POST /run."""

        async def _event_gen():
            queue = _run_queues.get(run_id)
            if queue is None:
                # Run already complete — synthesize a run_done from cached result
                cached = _run_results.get(run_id)
                if cached:
                    summary = {
                        "run_id": run_id,
                        "suite_id": cached.get("suite_id", ""),
                        "status": "done",
                        "total_cases": cached.get("total_count", 0),
                        "completed_cases": cached.get("total_count", 0),
                        "passed_cases": cached.get("passed_count", 0),
                        "failed_cases": max(0, cached.get("total_count", 0) - cached.get("passed_count", 0)),
                        "avg_score": cached.get("pass_rate"),
                        "total_cost_usd": cached.get("total_cost_usd"),
                        "model": cached.get("model"),
                    }
                    yield f"data: {json.dumps({'event': 'run_done', 'summary': summary})}\n\n"
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    yield "data: {}\n\n"  # keepalive ping
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            _event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @r.get("/runs/{run_id}", dependencies=auth_dep)
    def get_run_result(run_id: str) -> dict:
        """Fetch completed run result by run_id, normalized to frontend RunResult shape."""
        raw = _run_results.get(run_id)
        if raw is None:
            raise HTTPException(404, f"Run not found: {run_id}")
        total = raw.get("total_count", 0)
        passed = raw.get("passed_count", 0)
        # Flatten CaseResult: {case: {case_id, input, expected}, scores, ...} → frontend shape
        cases_out = []
        for c in raw.get("cases", []):
            nested = c.get("case") or {}
            scores: list = c.get("scores") or []
            score_val = scores[0]["score"] if scores else None
            all_passed = bool(scores) and all(s.get("passed", False) for s in scores)
            passed_val = all_passed and c.get("error") is None
            cases_out.append({
                "case_id": nested.get("case_id") or c.get("case_id", ""),
                "suite_id": raw.get("suite_id", ""),
                "input": nested.get("input"),
                "expected": nested.get("expected"),
                "actual": c.get("output"),
                "pass": passed_val,
                "status": "pass" if passed_val else "fail",
                "score": score_val,
                "latency_ms": c.get("latency_ms"),
                "cost_usd": c.get("cost_usd"),
                "error": c.get("error"),
                "metadata": nested.get("metadata"),
            })
        return {
            "run_id": run_id,
            "suite_id": raw.get("suite_id", ""),
            "status": "done",
            "model": raw.get("model"),
            "finished_at": raw.get("finished_at"),
            "total_cases": total,
            "completed_cases": total,
            "passed_cases": passed,
            "failed_cases": max(0, total - passed),
            "avg_score": raw.get("pass_rate"),
            "total_cost_usd": raw.get("total_cost_usd"),
            "cases": cases_out,
        }

    @r.post("/run/cancel/{run_id}", dependencies=auth_dep)
    def cancel_run(run_id: str) -> dict:
        runner = active_runners.get(run_id)
        if runner is None:
            raise HTTPException(404, f"No active run with id={run_id}")
        runner.cancel()
        return {"ok": True, "run_id": run_id, "cancelled": True}

    @r.post("/run/single", dependencies=auth_dep)
    async def run_single_case(payload: dict) -> dict:
        """Run one ad-hoc case — editor's '▶ Run this case' button."""
        suite_id = str(payload.get("suite_id", "")).strip()
        if not suite_id:
            raise HTTPException(400, "suite_id required")
        case_id = str(payload.get("case_id", "adhoc")).strip() or "adhoc"
        log_path = refine_log_dir / f"{suite_id}.jsonl"
        runner = runner_factory(suite_id, log_path)
        eval_cases = FixtureLoader.load_json([{
            "case_id": case_id,
            "input": payload.get("input", {}),
            "expected": payload.get("expected"),
            "metadata": payload.get("metadata", {}),
        }])
        result = await runner.run(eval_cases)
        if not result.cases:
            return _dataclass_dict(result)
        case_result = result.cases[0]
        case_dict = _dataclass_dict(case_result)
        case_dict["passed"] = case_result.passed  # @property not included by asdict
        return case_dict

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
            "fixtures_dir": str(fixtures_dir) if fixtures_dir is not None else None,
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
