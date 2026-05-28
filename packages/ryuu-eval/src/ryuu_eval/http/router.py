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

import inspect
import json
import os
import time

import yaml
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

from ryuu_eval_core import EvalCaseTemplate, EvalRunner, ExternalProject
from ryuu_eval_core.fixture_loader import FixtureLoader

# ----------------------------------------------------------------------------
# Type aliases — caller provides these
# ----------------------------------------------------------------------------

RunnerFactory = Callable[[str, Path, "str | None", "str | None"], EvalRunner]
"""(suite_id, refine_log_path, model, system_prompt) → configured EvalRunner.
Project's factory wires its target + scorers + refine_logger.

Backward-compatible: factories that only accept (suite_id, log_path) still
work because the extra args are passed as positional kwargs via try/except
inside the router."""


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
    case_factory_callback: Callable[[str, dict], Any] | None = None,
    external_projects: list[ExternalProject] | None = None,
    serve_ui: bool = False,
    ui_prefix: str = "/ui",
    kv_store: Any | None = None,
    oracle_fixtures_dir: Path | None = None,
    oracle_strategy_factory: Callable[[], Any] | None = None,
    llm_providers: dict[str, Any] | None = None,
    model_catalog: dict[str, dict[str, Any]] | None = None,
) -> APIRouter:
    """Build APIRouter — caller mounts với prefix='/api/eval'.

    Args:
        runner_factory: builds EvalRunner per suite (project supplies target+scorers).
            New signature: (suite_id, log_path, model, system_prompt) → EvalRunner.
            Backward-compatible with old 2-arg (suite_id, log_path) factories.
        template_registry: registered templates keyed by template_id.
        cases_dir: where to persist cases (YAML files, per suite subdir).
        refine_log_dir: where RefineLogger writes JSONL (per suite).
        require_auth: optional FastAPI dependency cho auth.
        optimizer_callback: ``(suite_id, params) → result_dict``. If provided,
            POST /optimize triggers it; else returns 501 Not Implemented.
        case_factory_callback: ``(suite_id, seed) -> dict | list[dict] | None``. Drives
            ``POST /suites/{id}/cases:generate`` so projects can auto-build cases from
            their own data sources (knowledge graph, production traces, etc.) instead
            of hand-writing YAMLs. Return shape: `{case_id, input, expected?, metadata?}`
            or a list for multi-case generation. Framework persists when payload.save=true.
        prompt_resolver: ``suite_id -> {path, content, system?, user_template?, output_schema?}``
            (or None when no prompt available). Drives ``GET /suites/{id}/prompt`` so
            external eval frameworks can fetch the prompt being evaluated. Framework
            stays generic — project supplies the lookup mapping its prompts dir.
        kv_store: optional async KV store (e.g. PostgresKVStore) for persisting run
            and batch results across process restarts. Must expose async get(key) and
            put(key, value) methods.
    """
    import asyncio
    import inspect as _inspect

    r = APIRouter()
    auth_dep = [Depends(require_auth)] if require_auth else []

    # Active runners keyed by run_id.
    active_runners: dict[str, EvalRunner] = {}
    # SSE event queues keyed by run_id (None sentinel = stream ended).
    _run_queues: dict[str, asyncio.Queue[dict | None]] = {}
    # Completed run results keyed by run_id (in-memory, survives until process restart).
    _run_results: dict[str, dict] = {}
    # Batch results keyed by batch_id (in-memory).
    _batch_results: dict[str, dict] = {}

    def _call_runner_factory(
        suite_id: str, log_path: Path, model: str | None, system_prompt: str | None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        budget_cap_usd: float | None = None,
    ) -> EvalRunner:
        """Call runner_factory with backward-compat: try 4+arg, fall back to 2-arg.

        Extra kwargs (max_tokens/temperature/budget_cap_usd) are forwarded only
        when the factory advertises them in its signature — older 4-arg factories
        keep working unchanged.
        """
        try:
            sig = _inspect.signature(runner_factory)
            params = sig.parameters
            n_params = len(params)
        except (ValueError, TypeError):
            params = {}  # type: ignore[assignment]
            n_params = 2
        if n_params >= 4:
            extra_kwargs: dict[str, Any] = {}
            for k, v in (("max_tokens", max_tokens),
                         ("temperature", temperature),
                         ("budget_cap_usd", budget_cap_usd)):
                if v is not None and k in params:
                    extra_kwargs[k] = v
            return runner_factory(suite_id, log_path, model, system_prompt, **extra_kwargs)
        return runner_factory(suite_id, log_path)  # type: ignore[call-arg]

    # Where SuiteResult JSON snapshots are written after each run, so the UI
    # can show "Actual (last run)" without re-running.
    _last_run_dir = last_run_dir or (cases_dir.parent / "last_run")
    _run_history_dir = cases_dir.parent / "run_history"
    _suite_config_dir = cases_dir.parent / "suite_config"

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

    def _read_suite_config(suite_id: str) -> dict:
        path = _suite_config_dir / f"{suite_id}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_suite_config(suite_id: str, data: dict) -> None:
        _suite_config_dir.mkdir(parents=True, exist_ok=True)
        path = _suite_config_dir / f"{suite_id}.json"
        existing = _read_suite_config(suite_id)
        existing.update(data)
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def _read_last_run(suite_id: str) -> dict | None:
        path = _last_run_dir / f"{suite_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_run_history(
        suite_id: str,
        run_id: str,
        suite_result: Any,
        model: str | None,
        batch_id: str | None = None,
    ) -> None:
        """Append one-line summary to artifacts/eval/run_history/{suite_id}.jsonl."""
        try:
            _run_history_dir.mkdir(parents=True, exist_ok=True)
            entry: dict[str, Any] = {
                "run_id": run_id,
                "model": model,
                "finished_at": time.time(),
                "passed_count": suite_result.passed_count,
                "total_count": suite_result.total_count,
                "pass_rate": suite_result.pass_rate,
                "total_cost_usd": suite_result.total_cost_usd,
            }
            if batch_id:
                entry["batch_id"] = batch_id
            with (_run_history_dir / f"{suite_id}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            pass

    def _read_run_history(suite_id: str, limit: int = 20) -> list[dict]:
        path = _run_history_dir / f"{suite_id}.jsonl"
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            entries = []
            for line in lines:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            # Back-fill batch_id for legacy entries: group entries without batch_id
            # that finished within 30s of each other (they were multi-model batches).
            no_batch = [e for e in entries if not e.get("batch_id")]
            no_batch.sort(key=lambda e: e.get("finished_at", 0))
            synthetic_id: str | None = None
            anchor_ts: float = 0.0
            for e in no_batch:
                ts = e.get("finished_at", 0) or 0
                if synthetic_id is None or (ts - anchor_ts) > 30:
                    synthetic_id = f"auto_{e['run_id'][:8]}"
                    anchor_ts = ts
                else:
                    # Extend the window to cover the last entry in this group
                    anchor_ts = ts
                e["batch_id"] = synthetic_id
            # Mark synthetic single-entry batches as solo (no compare button needed)
            from collections import Counter
            batch_counts = Counter(e.get("batch_id") for e in entries if e.get("batch_id"))
            for e in entries:
                bid = e.get("batch_id", "")
                if bid and bid.startswith("auto_") and batch_counts[bid] == 1:
                    del e["batch_id"]
            entries.sort(key=lambda e: e.get("finished_at", 0), reverse=True)
            return entries[:limit]
        except OSError:
            return []

    def _write_last_run(
        suite_id: str,
        suite_result: Any,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
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
            if system_prompt:
                payload["system_prompt"] = system_prompt
            serialized = json.dumps(payload, ensure_ascii=False, default=str)
            # Write "latest run" shortcut (one file per suite)
            (_last_run_dir / f"{suite_id}.json").write_text(serialized, encoding="utf-8")
            # Also write per-run-id file so GET /runs/{id} survives server restarts
            run_id = payload.get("run_id", "")
            if run_id:
                run_results_dir = _last_run_dir / "runs"
                run_results_dir.mkdir(parents=True, exist_ok=True)
                (run_results_dir / f"{run_id}.json").write_text(serialized, encoding="utf-8")
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
        cfg = _read_suite_config(suite_id)
        model: str | None = (last_run or {}).get("model")
        return {
            "suite_id": suite_id,
            "title": tpls[0].title if tpls else suite_id,
            "templates": [_dataclass_dict(t) for t in tpls],
            "case_count": _count_suite_cases(suite_id),
            "datasets": _list_suite_datasets(suite_id),
            "model": model,
            "default_system_prompt": cfg.get("default_system_prompt"),
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
                    "system_prompt": last_run.get("system_prompt"),
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

    @r.get("/suites/{suite_id}/runs", dependencies=auth_dep)
    def list_suite_runs(suite_id: str, limit: int = 20) -> list[dict]:
        """List past runs for a suite, most recent first (max ``limit`` entries)."""
        return _read_run_history(suite_id, limit)

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

    @r.get("/suites/{suite_id}/default-prompt", dependencies=auth_dep)
    def get_default_prompt(suite_id: str) -> dict:
        cfg = _read_suite_config(suite_id)
        return {"default_system_prompt": cfg.get("default_system_prompt")}

    @r.put("/suites/{suite_id}/default-prompt", dependencies=auth_dep)
    def save_default_prompt(suite_id: str, body: dict) -> dict:
        prompt = body.get("default_system_prompt", "")
        _write_suite_config(suite_id, {"default_system_prompt": prompt})
        return {"default_system_prompt": prompt}

    @r.post("/suites", dependencies=auth_dep)
    def create_suite(body: dict) -> dict:
        """Create a new suite directory + optional config."""
        suite_id = str(body.get("suite_id", "")).strip().replace(" ", "_")
        if not suite_id:
            raise HTTPException(400, "suite_id required")
        if not all(c.isalnum() or c in "_-" for c in suite_id):
            raise HTTPException(400, "suite_id may only contain letters, numbers, _ and -")
        suite_dir = _suite_dir(suite_id)
        suite_dir.mkdir(parents=True, exist_ok=True)
        cfg: dict[str, Any] = {}
        for key in ("title", "description", "default_system_prompt"):
            if body.get(key) is not None:
                cfg[key] = body[key]
        if cfg:
            _write_suite_config(suite_id, cfg)
        return {"suite_id": suite_id, **_read_suite_config(suite_id)}

    @r.put("/suites/{suite_id}", dependencies=auth_dep)
    def update_suite_metadata(suite_id: str, body: dict) -> dict:
        """Update suite title / description / default_system_prompt."""
        update: dict[str, Any] = {}
        for key in ("title", "description", "default_system_prompt"):
            if key in body:
                update[key] = body[key]
        if update:
            _write_suite_config(suite_id, update)
        return {"suite_id": suite_id, **_read_suite_config(suite_id)}

    @r.delete("/suites/{suite_id}", dependencies=auth_dep)
    def delete_suite(suite_id: str) -> dict:
        """Delete suite directory and its config file."""
        import shutil
        suite_dir = _suite_dir(suite_id)
        if suite_dir.exists():
            shutil.rmtree(suite_dir)
        cfg_path = _suite_config_dir / f"{suite_id}.json"
        if cfg_path.exists():
            cfg_path.unlink()
        return {"deleted": suite_id}

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

    def _list_cases_dir(suite_id: str) -> list[dict]:
        """Read cases from cases_dir only (no fixtures). Used by _load_all_cases."""
        suite_dir = cases_dir / suite_id
        if not suite_dir.exists():
            return []
        result = []
        for f in sorted(suite_dir.glob("*.yml")):
            try:
                loaded = FixtureLoader.load(f)
                result.extend([{
                    "case_id": c.case_id, "input": c.input,
                    "expected": c.expected, "metadata": c.metadata,
                    "_path": str(f),
                } for c in loaded])
            except Exception as exc:  # noqa: BLE001
                result.append({"case_id": f.stem, "error": str(exc), "_path": str(f)})
        return result

    @r.get("/suites/{suite_id}/cases", dependencies=auth_dep)
    def list_suite_cases(suite_id: str) -> list[dict]:
        """Returns UI-created cases + read-only fixtures merged (fixture loses on duplicate case_id)."""
        return _load_all_cases(suite_id)

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

    @r.post("/suites/{suite_id}/cases:generate", dependencies=auth_dep)
    async def generate_case(suite_id: str, payload: dict) -> dict:
        """Auto-generate a case via the project-supplied ``case_factory_callback``.

        Request body:
            {
              "seed": { ... project-specific seed (route, project_id, etc.) ... },
              "as_case_id": "optional_explicit_id",
              "save": true   // persist as YAML under cases_dir/<suite_id>/
            }

        Response: the generated case dict (or list when callback returns a list),
        same shape as ``GET /suites/{id}/cases`` entries.

        501 if the project hasn't wired ``case_factory_callback``.
        """
        if case_factory_callback is None:
            raise HTTPException(501, "case_factory_callback not configured")
        seed = payload.get("seed") or {}
        if not isinstance(seed, dict):
            raise HTTPException(400, "seed must be an object")
        save = bool(payload.get("save", False))
        as_case_id = str(payload.get("as_case_id") or "").strip() or None

        try:
            result = case_factory_callback(suite_id, {**seed, "_as_case_id": as_case_id})
            if inspect.isawaitable(result):
                result = await result
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"case_factory_callback failed: {exc}") from exc

        if result is None:
            raise HTTPException(404, f"factory returned None for suite_id={suite_id!r}")

        cases_out = result if isinstance(result, list) else [result]
        if not save:
            return {"ok": True, "generated": cases_out, "saved": False}

        try:
            import yaml
        except ImportError:
            raise HTTPException(500, "PyYAML required to persist cases")

        suite_dir = cases_dir / suite_id
        suite_dir.mkdir(parents=True, exist_ok=True)
        written: list[dict] = []
        for c in cases_out:
            cid = str(c.get("case_id") or "").strip()
            if not cid:
                raise HTTPException(400, "generated case missing case_id")
            out_path = suite_dir / f"{cid}.yml"
            yaml_data = {
                "case_id": cid,
                "input": c.get("input"),
                "expected": c.get("expected"),
                "metadata": c.get("metadata") or {},
            }
            out_path.write_text(
                yaml.safe_dump(yaml_data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            written.append({"case_id": cid, "path": str(out_path)})
        return {"ok": True, "generated": cases_out, "saved": True, "written": written}

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
        runner = _call_runner_factory(suite_id, log_path, None, None)
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
        ui_cases = _list_cases_dir(suite_id)
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

    async def _start_single_run(
        suite_id: str,
        model: str | None,
        system_prompt: str | None,
        case_ids: list[str] | None,
        concurrency: int,
        batch_id: str | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        budget_cap_usd: float | None = None,
        mode: str = "parallel",
    ) -> str:
        """Spawn one background run and return its run_id."""
        log_path = refine_log_dir / f"{suite_id}.jsonl"
        try:
            runner = _call_runner_factory(
                suite_id, log_path, model, system_prompt,
                max_tokens=max_tokens, temperature=temperature,
                budget_cap_usd=budget_cap_usd,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        run_id = runner.run_id
        eval_cases = _build_eval_cases(suite_id, case_ids)

        # Snapshot the request params so the UI Log tab can show what was used.
        # started_at recorded here so the Log shows wall-clock duration.
        run_params: dict[str, Any] = {
            "model": model,
            "system_prompt": system_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "budget_cap_usd": budget_cap_usd,
            "concurrency": concurrency,
            "mode": mode,
            "case_ids": case_ids,
            "started_at": time.time(),
        }

        queue: asyncio.Queue = asyncio.Queue()
        _run_queues[run_id] = queue
        active_runners[run_id] = runner

        async def _bg() -> None:
            try:
                # Sequential mode forces concurrency=1 even if user set higher.
                eff_concurrency = 1 if mode == "sequential" else concurrency
                async for event in runner.stream(eval_cases, concurrency=eff_concurrency):
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
                        "params": run_params,
                    })
                    _run_results[run_id] = rd
                    _write_last_run(suite_id, runner.last_suite_result, model or None, system_prompt)
                    _write_run_history(suite_id, run_id, runner.last_suite_result, model or None, batch_id)
                    if kv_store is not None and run_id in _run_results:
                        import json as _json
                        try:
                            await kv_store.put(
                                f"run:{run_id}",
                                _json.dumps(_run_results[run_id], default=str),
                            )
                        except Exception:
                            pass  # best-effort

        asyncio.create_task(_bg())
        return run_id

    @r.post("/run", dependencies=auth_dep)
    async def start_run(payload: dict) -> dict:
        """Start async run — returns {run_id} (or {batch_id, runs}) immediately.

        Single model:  POST {suite_id, model, ...}  → {run_id, suite_id, batch_id: null}
        Multi-model:   POST {suite_id, models: [...]} → {batch_id, suite_id, runs: [{run_id, model}]}
        Stream progress via GET /run/stream/{run_id}.
        Fetch result via GET /runs/{run_id} after completion.

        Optional payload fields (all skipped when absent/None):
          max_tokens   : int ≥ 64 (rejected with 400 if 1–63 — produces garbage)
          temperature  : float in [0, 2]
          budget_cap_usd: float ≥ 0 (advisory only — not yet enforced by runner)
          mode         : "parallel" | "sequential" (default "parallel")
        """
        import uuid as _uuid

        suite_id = str(payload.get("suite_id", "")).strip()
        if not suite_id:
            raise HTTPException(400, "suite_id required")

        system_prompt = str(payload.get("prompt", "")).strip() or None
        case_ids: list[str] | None = payload.get("case_ids") or None
        concurrency = max(1, min(int(payload.get("concurrency", 4)), 16))

        # Optional run params — None means "skip / use provider default"
        def _opt_int(key: str) -> int | None:
            v = payload.get(key)
            if v in (None, "", 0):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        def _opt_float(key: str, *, allow_zero: bool = False) -> float | None:
            v = payload.get(key)
            if v in (None, ""):
                return None
            if v == 0 and not allow_zero:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        max_tokens: int | None = _opt_int("max_tokens")
        if max_tokens is not None and max_tokens < 64:
            raise HTTPException(
                400,
                f"max_tokens={max_tokens} too small — minimum 64. "
                "Smaller values produce truncated/garbage output. "
                "Omit the field to use the provider default.",
            )

        # Temperature=0 is meaningful (deterministic), so allow zero
        temperature: float | None = _opt_float("temperature", allow_zero=True)
        budget_cap_usd: float | None = _opt_float("budget_cap_usd")
        if budget_cap_usd is None:
            # UI uses "budget_usd" key — accept both
            budget_cap_usd = _opt_float("budget_usd")
        mode = str(payload.get("mode", "parallel")).strip().lower() or "parallel"
        if mode not in ("parallel", "sequential"):
            raise HTTPException(400, f"mode must be 'parallel' or 'sequential', got {mode!r}")

        # Resolve model list — support both "model" (single) and "models" (batch)
        models_raw: list[str] = payload.get("models") or []
        model_single: str = str(payload.get("model", "")).strip()
        if not models_raw and model_single:
            models_raw = [model_single]
        if not models_raw:
            raise HTTPException(400, "No model selected — pass model=<id> or models=[<id>,...]")

        if len(models_raw) == 1:
            # Single-model path — backward-compatible response shape
            model = models_raw[0] or None
            run_id = await _start_single_run(
                suite_id, model, system_prompt, case_ids, concurrency,
                max_tokens=max_tokens, temperature=temperature,
                budget_cap_usd=budget_cap_usd, mode=mode,
            )
            return {"run_id": run_id, "suite_id": suite_id, "batch_id": None}

        # Multi-model batch path
        batch_id = _uuid.uuid4().hex
        runs: list[dict] = []
        for m in models_raw:
            rid = await _start_single_run(
                suite_id, m or None, system_prompt, case_ids, concurrency, batch_id,
                max_tokens=max_tokens, temperature=temperature,
                budget_cap_usd=budget_cap_usd, mode=mode,
            )
            runs.append({"run_id": rid, "model": m})

        batch_record: dict = {
            "batch_id": batch_id,
            "suite_id": suite_id,
            "runs": runs,
            "created_at": time.time(),
        }
        _batch_results[batch_id] = batch_record

        if kv_store is not None:
            import json as _json
            try:
                await kv_store.put(
                    f"batch:{batch_id}",
                    _json.dumps(batch_record, default=str),
                )
            except Exception:
                pass  # best-effort

        return {"batch_id": batch_id, "suite_id": suite_id, "runs": runs}

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
                except TimeoutError:
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

    @r.get("/batch/{batch_id}", dependencies=auth_dep)
    async def get_batch_result(batch_id: str) -> dict:
        """Fetch batch record by batch_id: {batch_id, suite_id, runs: [{run_id, model, status}]}."""
        record = _batch_results.get(batch_id)
        if record is None and kv_store is not None:
            import json as _json
            raw_str = await kv_store.get(f"batch:{batch_id}")
            if raw_str:
                record = _json.loads(raw_str)
                _batch_results[batch_id] = record
        if record is None:
            raise HTTPException(404, f"Batch not found: {batch_id}")

        # Enrich each run entry with live status
        enriched_runs = []
        for entry in record.get("runs", []):
            rid = entry.get("run_id", "")
            if rid in active_runners:
                status = "running"
            elif rid in _run_results:
                status = "done"
            else:
                status = "unknown"
            enriched_runs.append({**entry, "status": status})

        return {
            "batch_id": batch_id,
            "suite_id": record.get("suite_id", ""),
            "created_at": record.get("created_at"),
            "runs": enriched_runs,
        }

    @r.get("/runs/{run_id}", dependencies=auth_dep)
    async def get_run_result(run_id: str) -> dict:
        """Fetch completed run result by run_id, normalized to frontend RunResult shape."""
        raw = _run_results.get(run_id)
        if raw is None and kv_store is not None:
            import json as _json
            try:
                raw_str = await kv_store.get(f"run:{run_id}")
                if raw_str:
                    raw = _json.loads(raw_str)
                    _run_results[run_id] = raw
            except Exception:
                pass  # DB unavailable — try file fallback below
        if raw is None:
            # Legacy migration: runs created before DB existed live in files.
            # Read once, then write to DB so the next request hits the DB path.
            import json as _json
            run_file = _last_run_dir / "runs" / f"{run_id}.json"
            if run_file.exists():
                try:
                    raw = _json.loads(run_file.read_text(encoding="utf-8"))
                    _run_results[run_id] = raw
                    if kv_store is not None:
                        try:
                            await kv_store.put(f"run:{run_id}", _json.dumps(raw, default=str))
                        except Exception:
                            pass  # migration is best-effort
                except (OSError, _json.JSONDecodeError):
                    pass
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
                "steps": c.get("steps", []),
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
            "params": raw.get("params"),  # run params snapshot for UI Log tab
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
        runner = _call_runner_factory(suite_id, log_path, None, None)
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

    # ── Projects ────────────────────────────────────────────────────────
    # A "project" groups suites. The built-in "local" project collects all
    # suites registered via template_registry + cases_dir. External projects
    # are remote eval2 deployments — their suite list is fetched on demand
    # and cached to disk so discovery still works when the remote is offline.

    _ext_projects: list[ExternalProject] = list(external_projects or [])
    _project_cache_dir = _last_run_dir / "projects"

    def _project_cache_path(project_id: str) -> Path:
        return _project_cache_dir / f"{project_id}.json"

    def _read_project_cache(project_id: str) -> dict | None:
        p = _project_cache_path(project_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_project_cache(project_id: str, payload: dict) -> None:
        try:
            _project_cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {**payload, "cached_at": time.time()}
            _project_cache_path(project_id).write_text(
                json.dumps(payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass  # best-effort

    @r.get("/projects", dependencies=auth_dep)
    def list_projects() -> list[dict]:
        """List all projects — local (this framework instance) + registered external."""
        local_suite_ids = sorted({
            t.suite_id for t in template_registry.values() if t.suite_id
        })
        if cases_dir.exists():
            for d in cases_dir.iterdir():
                if d.is_dir() and d.name not in local_suite_ids:
                    local_suite_ids.append(d.name)
            local_suite_ids.sort()

        result: list[dict] = [{
            "project_id": "local",
            "title": "Local",
            "description": "Suites defined in this framework instance.",
            "remote": False,
            "suite_count": len(local_suite_ids),
            "suite_ids": local_suite_ids,
        }]
        for ep in _ext_projects:
            cached = _read_project_cache(ep.project_id)
            result.append({
                "project_id": ep.project_id,
                "title": ep.title,
                "description": ep.description,
                "remote": True,
                "base_url": ep.base_url,
                "suite_count": len(cached.get("suites", [])) if cached else None,
                "cached_at": cached.get("cached_at") if cached else None,
            })
        return result

    @r.get("/projects/{project_id}", dependencies=auth_dep)
    async def get_project(project_id: str) -> dict:
        """Project detail + suite list.

        For "local": derives suites from template_registry + cases_dir.
        For external: fetches ``GET {base_url}/suites`` and caches result to disk.
          If the remote is unreachable, returns the last cached snapshot with
          ``"stale": true`` so the UI stays functional when the remote is down.
          Returns 502 only when remote is down AND no cache exists yet.
        """
        if project_id == "local":
            return {
                "project_id": "local",
                "title": "Local",
                "description": "Suites defined in this framework instance.",
                "remote": False,
                "suites": list_suites(),
            }

        ep = next((p for p in _ext_projects if p.project_id == project_id), None)
        if ep is None:
            raise HTTPException(404, f"Project not found: {project_id!r}")

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{ep.base_url}/suites")
                resp.raise_for_status()
                suites = resp.json()
            payload = {
                "project_id": ep.project_id,
                "title": ep.title,
                "description": ep.description,
                "remote": True,
                "base_url": ep.base_url,
                "stale": False,
                "suites": suites,
            }
            _write_project_cache(ep.project_id, payload)
            return payload
        except Exception:  # noqa: BLE001
            cached = _read_project_cache(ep.project_id)
            if cached is None:
                raise HTTPException(
                    502,
                    f"Remote {ep.base_url!r} is unreachable and no local cache exists. "
                    f"Run POST /projects/{ep.project_id}/sync while remote is online to seed the cache.",
                )
            return {**cached, "stale": True}

    @r.get("/projects/{project_id}/suites/{suite_id}", dependencies=auth_dep)
    async def get_project_suite(project_id: str, suite_id: str) -> dict:
        """Suite metadata for one suite within a project.

        For "local": same as GET /suites/{suite_id}.
        For external: fetches from remote; falls back to cached suite list entry.
        """
        if project_id == "local":
            return get_suite_metadata(suite_id)

        ep = next((p for p in _ext_projects if p.project_id == project_id), None)
        if ep is None:
            raise HTTPException(404, f"Project not found: {project_id!r}")

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{ep.base_url}/suites/{suite_id}")
                if resp.status_code == 404:
                    raise HTTPException(404, f"Suite {suite_id!r} not found in project {project_id!r}")
                resp.raise_for_status()
                return resp.json()
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            cached = _read_project_cache(ep.project_id)
            if cached:
                for suite in cached.get("suites", []):
                    if suite.get("suite_id") == suite_id:
                        return {**suite, "stale": True}
            raise HTTPException(
                502,
                f"Remote {ep.base_url!r} is unreachable and suite {suite_id!r} is not in cache. "
                f"Run POST /projects/{ep.project_id}/sync to seed the cache.",
            )

    @r.post("/projects/{project_id}/sync", dependencies=auth_dep)
    async def sync_project(project_id: str, payload: dict | None = None) -> dict:
        """Snapshot an external project's cases into local cases_dir.

        Fetches every suite's cases from the remote and writes each one as a
        YAML file under ``cases_dir/{suite_id}/{case_id}.yml``.  Existing
        UI-created cases are NOT overwritten unless ``overwrite: true`` is in
        the request body.  Synced cases carry ``metadata.source: "remote:{project_id}"``
        so they can be distinguished from locally created ones.

        After a successful sync the project is fully runnable offline: all cases
        are available to the local runner_factory even when the remote is down.

        Returns::

            {project_id, synced_suites, synced_cases, skipped_cases, suite_ids, errors}
        """
        ep = next((p for p in _ext_projects if p.project_id == project_id), None)
        if ep is None:
            raise HTTPException(404, f"Project not found: {project_id!r}")

        overwrite: bool = bool((payload or {}).get("overwrite", False))

        try:
            import yaml
        except ImportError:
            raise HTTPException(500, "PyYAML required for sync (pip install pyyaml)")
        try:
            import httpx
        except ImportError:
            raise HTTPException(500, "httpx required for sync (pip install httpx)")

        synced_suites = 0
        synced_cases = 0
        skipped_cases = 0
        suite_ids_out: list[str] = []
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Fetch + cache suite list
            try:
                r_suites = await client.get(f"{ep.base_url}/suites")
                r_suites.raise_for_status()
                suites = r_suites.json()
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, f"Cannot reach {ep.base_url}/suites: {exc}") from exc

            _write_project_cache(ep.project_id, {
                "project_id": ep.project_id,
                "title": ep.title,
                "description": ep.description,
                "remote": True,
                "base_url": ep.base_url,
                "stale": False,
                "suites": suites,
            })

            # 2. For each suite, fetch cases and persist locally
            for suite in suites:
                sid = suite.get("suite_id", "")
                if not sid:
                    continue
                try:
                    r_cases = await client.get(f"{ep.base_url}/suites/{sid}/cases")
                    r_cases.raise_for_status()
                    remote_cases: list[dict] = r_cases.json()
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{sid}: {exc}")
                    continue

                suite_dir = cases_dir / sid
                suite_dir.mkdir(parents=True, exist_ok=True)

                for case in remote_cases:
                    if "error" in case:
                        continue
                    cid = case.get("case_id", "")
                    if not cid:
                        continue
                    out_path = suite_dir / f"{cid}.yml"
                    if out_path.exists() and not overwrite:
                        skipped_cases += 1
                        continue
                    yaml_data = {
                        "case_id": cid,
                        "input": case.get("input"),
                        "expected": case.get("expected"),
                        "metadata": {
                            **case.get("metadata", {}),
                            "source": f"remote:{project_id}",
                        },
                    }
                    out_path.write_text(
                        yaml.safe_dump(yaml_data, sort_keys=False, allow_unicode=True),
                        encoding="utf-8",
                    )
                    synced_cases += 1

                synced_suites += 1
                suite_ids_out.append(sid)

        return {
            "project_id": project_id,
            "synced_suites": synced_suites,
            "synced_cases": synced_cases,
            "skipped_cases": skipped_cases,
            "suite_ids": suite_ids_out,
            "errors": errors,
        }

    # ── Oracle Review ──────────────────────────────────────────────────
    # Serves fixtures from oracle_fixtures_dir for human review.
    # Each fixture is a JSON file; companion .review.json lists low/medium
    # confidence cells that need action before being used as ground truth.

    _oracle_dir = oracle_fixtures_dir or Path("artifacts/eval/oracle_fixtures/crud_matrix")

    def _list_oracle_fixtures(suite_id: str | None = None) -> list[dict]:
        if not _oracle_dir.exists():
            return []
        result = []
        for p in sorted(_oracle_dir.glob("*.json")):
            if p.name.endswith(".review.json"):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            fixture_suite = data.get("suite_id", "")
            if suite_id:
                if fixture_suite != suite_id:
                    continue
            review_path = _oracle_dir / f"{p.stem}.review.json"
            pending = 0
            if review_path.exists():
                try:
                    rd = json.loads(review_path.read_text(encoding="utf-8"))
                    pending = sum(
                        1 for item in rd.get("needs_review", [])
                        if item.get("action") is None
                    )
                except (OSError, json.JSONDecodeError):
                    pass
            result.append({
                "fixture_id": data.get("fixture_id", p.stem),
                "suite_id": fixture_suite,
                "prompt_version": data.get("prompt_version", ""),
                "oracle_model": data.get("oracle_model", ""),
                "reviewed_by": data.get("reviewed_by", ""),
                "reviewed_at": data.get("reviewed_at", ""),
                "pending_review": pending,
                # Studio fields (empty for pre-studio fixtures)
                "oracle_prompt_version": data.get("oracle_prompt_version", ""),
                "meta_prompt_version": data.get("meta_prompt_version", ""),
            })
        return result

    def _get_cells(expected: dict) -> dict:
        """Return mutable cells dict, handling new {cells:{…}} and old {entity:{…}} formats."""
        if "cells" in expected and isinstance(expected["cells"], dict):
            return expected["cells"]
        return expected

    def _normalize_fixture_for_ui(data: dict) -> dict:
        """Normalize on-disk fixture to a stable shape for the frontend.

        Shape evolution:
          v0  route_context + expected = {entity: {field: cell}}
          v1  input_data    + expected = {cells: {…}, valid_fields: …}
          v2  inputs: [{name, data, expected}, …]   ← studio multi-input

        Response shape always exposes BOTH:
          - top-level input_data + expected      (legacy consumers, inputs[0])
          - inputs: [{name, data, expected}]     (multi-input UI)

        Studio audit fields (oracle_prompt, oracle_prompt_version,
        meta_prompt_version, production_prompt) are surfaced with empty-string
        defaults so existing fixtures stay readable without re-saving.
        """
        # v0 → v1 migration: route_context → input_data
        if "input_data" not in data and "route_context" in data:
            data["input_data"] = data.pop("route_context")

        # v1 expected shape: {cells, valid_fields, framework} → flatten to {entity:{field:cell}}
        expected = data.get("expected", {})
        if "cells" in expected and isinstance(expected["cells"], dict):
            if "meta" not in data:
                data["meta"] = {}
            data["meta"].setdefault("valid_fields", expected.get("valid_fields", {}))
            data["meta"].setdefault("framework", expected.get("framework", ""))
            data["expected"] = expected["cells"]
        elif "meta" not in data:
            data["meta"] = {}

        # v2 — inputs[] array. Three cases:
        #   a) `inputs` already present on disk (v2 fixture) — surface as-is,
        #      also populate top-level input_data/expected from inputs[0] so
        #      legacy code paths still work.
        #   b) Only legacy top-level input_data + expected — synthesize
        #      inputs=[{name: "default", data: input_data, expected}].
        #   c) Both missing — empty inputs[].
        inputs = data.get("inputs")
        if isinstance(inputs, list) and inputs:
            # Normalize each inputs[i].expected to flat shape too
            normalized: list[dict] = []
            for entry in inputs:
                if not isinstance(entry, dict):
                    continue
                exp = entry.get("expected", {})
                if isinstance(exp, dict) and "cells" in exp and isinstance(exp["cells"], dict):
                    exp = exp["cells"]
                normalized.append({
                    "name": str(entry.get("name", "")) or "input",
                    "data": entry.get("data", {}),
                    "expected": exp if isinstance(exp, dict) else {},
                })
            data["inputs"] = normalized
            # Mirror inputs[0] into top-level for legacy consumers
            if normalized:
                data.setdefault("input_data", normalized[0]["data"])
                data.setdefault("expected", normalized[0]["expected"])
        else:
            data["inputs"] = [{
                "name": "default",
                "data": data.get("input_data", {}),
                "expected": data.get("expected", {}),
            }]

        # Studio audit fields — empty string when fixture predates the studio flow
        for fld in (
            "oracle_prompt",
            "oracle_prompt_version",
            "meta_prompt_version",
            "production_prompt",
        ):
            data.setdefault(fld, "")
        return data

    @r.get("/oracle-review/", dependencies=auth_dep)
    def list_oracle_fixtures(suite_id: str | None = None) -> list[dict]:
        """List oracle fixtures. Pass ?suite_id=xxx to filter by suite."""
        return _list_oracle_fixtures(suite_id)

    @r.get("/oracle-review/schema", dependencies=auth_dep)
    def get_oracle_schema() -> dict:
        """Return ReviewSchema describing how the UI should render oracle candidates."""
        if oracle_strategy_factory is None:
            raise HTTPException(501, "No oracle_strategy_factory configured")
        return oracle_strategy_factory().review_schema().to_dict()

    @r.post("/oracle-review/generate", dependencies=auth_dep)
    async def generate_oracle_fixture(payload: dict) -> dict:
        """Create or regenerate an oracle fixture.

        Two modes:
          A) Strategy mode (legacy): omit `expected_override` — endpoint runs
             oracle_strategy_factory() on input_data to compute cells.
             Requires `oracle_strategy_factory` to be configured.

          B) Override mode (studio): pass `expected_override.cells` (and
             optionally `valid_fields`) — endpoint skips the strategy and
             persists the supplied cells directly. This is what Tab 3 of the
             Studio flow uses after /run-with-prompt produces a preview.

        Studio audit fields (all optional, default ""):
          - production_prompt    — input given to /meta-generate
          - oracle_prompt        — prompt produced by /meta-generate, edited
          - oracle_prompt_version — timestamp/hash for audit
          - meta_prompt_version   — version of the system meta-prompt used
        """
        case_id = payload.get("case_id", "").strip()
        if not case_id:
            raise HTTPException(400, "case_id is required")
        if not all(c.isalnum() or c in "_-" for c in case_id):
            raise HTTPException(400, "case_id may only contain letters, numbers, _ and -")
        suite_id_val = str(payload.get("suite_id", "")).strip()

        # v2: caller passes inputs[] array directly — preferred for multi-input
        # fixtures. Each entry: {name, data, expected, valid_fields?}
        inputs_payload = payload.get("inputs")
        is_multi_input = isinstance(inputs_payload, list) and inputs_payload

        if is_multi_input:
            normalized_inputs: list[dict] = []
            for i, entry in enumerate(inputs_payload):
                if not isinstance(entry, dict):
                    raise HTTPException(400, f"inputs[{i}] must be a JSON object")
                name = str(entry.get("name", "")).strip() or f"input_{i+1}"
                data_ = entry.get("data", {})
                if not isinstance(data_, dict):
                    raise HTTPException(400, f"inputs[{i}].data must be a JSON object")
                expected_ = entry.get("expected", {})
                if not isinstance(expected_, dict):
                    expected_ = {}
                normalized_inputs.append({
                    "name": name, "data": data_, "expected": expected_,
                })
            # Mirror inputs[0] into legacy top-level fields
            input_data = normalized_inputs[0]["data"]
            cells = normalized_inputs[0]["expected"]
            valid_fields = {}
            prompt_version_val = str(payload.get("prompt_version", ""))
            oracle_model_val = str(payload.get("oracle_model", ""))
        else:
            normalized_inputs = []
            input_data = payload.get("input_data")
            if not isinstance(input_data, dict):
                raise HTTPException(400, "input_data must be a JSON object (or pass inputs[])")

            # Mode B (override) — caller supplies cells, no strategy invocation
            override = payload.get("expected_override")
            if override is not None:
                if not isinstance(override, dict):
                    raise HTTPException(
                        400, "expected_override must be {cells: {...}, valid_fields?: {...}}",
                    )
                cells = override.get("cells", override)
                valid_fields = override.get("valid_fields", {})
                prompt_version_val = str(payload.get("prompt_version", ""))
                oracle_model_val = str(payload.get("oracle_model", ""))
            else:
                # Mode A (strategy) — original behavior
                if oracle_strategy_factory is None:
                    raise HTTPException(
                        501,
                        "No oracle_strategy_factory configured — pass expected_override "
                        "or inputs[] to skip strategy, or wire the factory at startup",
                    )
                strategy = oracle_strategy_factory()
                candidate = await strategy.generate_candidate(input_data)
                cells = candidate.get("cells", candidate)
                valid_fields = candidate.get("valid_fields", {})
                prompt_version_val = getattr(strategy, "prompt_version", "unknown")
                oracle_model_val = getattr(strategy, "_model", "")

        fixture: dict = {
            "fixture_id": case_id,
            "suite_id": suite_id_val,
            "prompt_version": prompt_version_val,
            "oracle_model": oracle_model_val,
            "reviewed_by": "",
            "reviewed_at": "",
            "review_note": "",
            "input_data": input_data,
            "expected": {"cells": cells, "valid_fields": valid_fields},
            "meta": {"valid_fields": valid_fields},
            # Studio audit fields
            "production_prompt": str(payload.get("production_prompt", "")),
            "oracle_prompt": str(payload.get("oracle_prompt", "")),
            "oracle_prompt_version": str(payload.get("oracle_prompt_version", "")),
            "meta_prompt_version": str(payload.get("meta_prompt_version", "")),
        }
        # v2 — persist inputs[] when caller supplied multi-input shape
        if is_multi_input:
            fixture["inputs"] = normalized_inputs
        _oracle_dir.mkdir(parents=True, exist_ok=True)
        path = _oracle_dir / f"{case_id}.json"
        path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

        # Aggregate review items across all inputs (multi-input case) or
        # just the single inputs[0] / legacy cells.
        review_sources: list[tuple[str, dict]] = []
        if is_multi_input:
            for entry in normalized_inputs:
                review_sources.append((entry["name"], entry["expected"]))
        else:
            review_sources.append(("default", cells))
        needs_review = [
            {
                "input_name": iname,
                "entity": entity,
                "field": field_name,
                "op": cell.get("op", ""),
                "confidence": cell.get("confidence"),
                "oracle_why": cell.get("oracle_why", ""),
                "action": None,
                "corrected_op": None,
            }
            for iname, icells in review_sources
            for entity, fields in icells.items()
            if isinstance(fields, dict)
            for field_name, cell in fields.items()
            if isinstance(cell, dict)
            if cell.get("confidence") in ("low", "medium")
        ]
        review_path = _oracle_dir / f"{case_id}.review.json"
        if needs_review:
            from datetime import datetime as _dt
            review_path.write_text(json.dumps({
                "fixture_id": case_id,
                "generated_at": _dt.now().isoformat(),
                "needs_review": needs_review,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        elif review_path.exists():
            review_path.unlink()

        normalized = _normalize_fixture_for_ui(json.loads(path.read_text(encoding="utf-8")))
        normalized["review_items"] = needs_review
        return normalized

    # ── Oracle Ground Truth Studio — meta-prompt → oracle prompt ───────
    # NOTE: must be registered BEFORE /oracle-review/{fixture_id} so the
    # wildcard path-param does not swallow these literal sub-paths.

    @r.get("/oracle-review/providers", dependencies=auth_dep)
    def list_llm_providers() -> dict:
        """Provider keys + models + default_model registered with build_eval_router.

        Response shape:
            {"providers": [{key, models, default_model}, ...]}

        Frontend uses this for the provider AND model dropdowns — no
        hardcoded model lists in JS/TS.
        """
        keys = sorted((llm_providers or {}).keys())
        catalog = model_catalog or {}
        return {
            "providers": [
                {
                    "key": k,
                    "models": list(catalog.get(k, {}).get("models", []) or []),
                    "default_model": str(catalog.get(k, {}).get("default_model", "")),
                }
                for k in keys
            ],
        }

    @r.post("/oracle-review/meta-generate", dependencies=auth_dep)
    async def meta_generate_oracle_prompt(payload: dict) -> dict:
        """Run the generic meta-prompt over a production prompt → oracle prompt.

        Body:
            production_prompt (str, required): production prompt to wrap
            provider          (str, optional): key from /providers. Required
                                               when 2+ providers registered.
            model             (str, optional): forwarded to the provider
            project_name      (str, optional): UI hint
            domain_hint       (str, optional): UI hint

        Returns:
            {oracle_prompt, meta_prompt_version, provider, model, generated_at}
        """
        if not llm_providers:
            raise HTTPException(
                501,
                "No llm_providers configured — pass {key: ILLMProvider} to "
                "build_eval_router",
            )
        production_prompt = str(payload.get("production_prompt", "")).strip()
        if not production_prompt:
            raise HTTPException(400, "production_prompt is required")

        provider_key = str(payload.get("provider", "")).strip()
        available = sorted(llm_providers.keys())
        if not provider_key:
            if len(llm_providers) == 1:
                provider_key = available[0]
            else:
                raise HTTPException(
                    400,
                    f"provider is required when multiple registered "
                    f"(available: {available})",
                )
        if provider_key not in llm_providers:
            raise HTTPException(
                400,
                f"unknown provider {provider_key!r} (available: {available})",
            )

        from ryuu_eval_oracle.meta_prompt import (
            META_PROMPT_VERSION,
            generate_oracle_prompt,
        )

        try:
            result = await generate_oracle_prompt(
                llm_providers[provider_key],
                production_prompt_text=production_prompt,
                project_name=str(payload.get("project_name", "")),
                domain_hint=str(payload.get("domain_hint", "")),
                output_schema_hint=str(payload.get("output_schema_hint", "")),
                model=(payload.get("model") or None),
            )
        except Exception as exc:  # noqa: BLE001 — surface LLM errors to UI
            raise HTTPException(502, f"meta-prompt failed: {exc}") from exc

        from datetime import datetime as _dt, timezone as _tz
        return {
            "oracle_prompt": result.oracle_prompt,
            "meta_prompt_version": result.meta_prompt_version or META_PROMPT_VERSION,
            "provider": provider_key,
            "model": result.model,
            "generated_at": _dt.now(_tz.utc).isoformat(),
        }

    @r.post("/oracle-review/run-with-prompt", dependencies=auth_dep)
    async def run_with_arbitrary_prompt(payload: dict) -> dict:
        """Run a user-supplied oracle prompt against an input — stateless.

        UI flow: step 2 generates an oracle prompt (YAML), human edits in a
        textarea, then step 3 POSTs it here with the input from step 1.
        Nothing is persisted — caller decides whether to Save (step 5).

        Body:
            oracle_prompt (str, required):  YAML string with `system` and
                                            `user_template` fields. The
                                            template is rendered with
                                            `{{ input_json }}` substitution.
            input_data    (dict, required): becomes input_json in the template.
            provider      (str, optional):  registry key from /providers.
            model         (str, optional):  forwarded to the provider.

        Returns:
            {cells, raw_response, parse_error?, latency_ms, cost_usd,
             input_tokens, output_tokens, provider, model}

        Cells parsing: looks for a JSON object in the LLM reply (strips
        ```json fences). On parse failure returns `cells: {}` plus
        `parse_error` — the UI still gets `raw_response` for human triage.
        """
        if not llm_providers:
            raise HTTPException(501, "No llm_providers configured")
        oracle_prompt = str(payload.get("oracle_prompt", "")).strip()
        if not oracle_prompt:
            raise HTTPException(400, "oracle_prompt is required")
        input_data = payload.get("input_data")
        if not isinstance(input_data, dict):
            raise HTTPException(400, "input_data must be a JSON object")

        # Parse the YAML oracle prompt → extract system + user_template
        try:
            parsed_prompt = yaml.safe_load(oracle_prompt)
            if not isinstance(parsed_prompt, dict):
                raise ValueError("oracle_prompt YAML must be a mapping")
        except yaml.YAMLError as exc:
            raise HTTPException(400, f"oracle_prompt is not valid YAML: {exc}")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        system_text = str(parsed_prompt.get("system", "")).strip()
        user_template = str(parsed_prompt.get("user_template", "")).strip()
        if not system_text or not user_template:
            raise HTTPException(
                400,
                "oracle_prompt must contain both `system` and `user_template`",
            )

        # Pick provider (same routing rules as meta-generate)
        provider_key = str(payload.get("provider", "")).strip()
        available = sorted(llm_providers.keys())
        if not provider_key:
            if len(llm_providers) == 1:
                provider_key = available[0]
            else:
                raise HTTPException(
                    400,
                    f"provider is required when multiple registered "
                    f"(available: {available})",
                )
        if provider_key not in llm_providers:
            raise HTTPException(
                400,
                f"unknown provider {provider_key!r} (available: {available})",
            )

        # Render user template — single Mustache-style substitution
        user_text = user_template.replace(
            "{{ input_json }}",
            json.dumps(input_data, ensure_ascii=False, indent=2),
        )

        from ryuu_providers_core import (
            CompletionRequest as _Req,
            Message as _Msg,
            calculate_usd as _calc_usd,
        )
        import time as _time
        import re as _re

        provider = llm_providers[provider_key]
        chosen_model = str(payload.get("model", "")).strip() or getattr(
            provider, "default_model", "",
        )
        req = _Req(
            messages=[_Msg(role="user", content=user_text)],
            model=chosen_model,
            system=system_text,
            temperature=0.0,
            max_tokens=4096,
        )
        t0 = _time.perf_counter()
        try:
            resp = await provider.complete(req)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"provider call failed: {exc}") from exc
        latency_ms = (_time.perf_counter() - t0) * 1000.0

        raw = (resp.content or "").strip()
        # Strip ```json fences if present
        cleaned = _re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = _re.sub(r"\s*```$", "", cleaned)

        cells: dict[str, Any] = {}
        parse_error: str | None = None
        try:
            parsed = json.loads(cleaned)
            # Accept either {entity: {field: cell}} or {cells: {...}} shapes
            cells = parsed.get("cells", parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError as exc:
            parse_error = f"response is not valid JSON: {exc}"

        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        cost = _calc_usd(resp.model or chosen_model, in_tok, out_tok)

        result = {
            "cells": cells,
            "raw_response": raw,
            "provider": provider_key,
            "model": resp.model or chosen_model,
            "latency_ms": latency_ms,
            "cost_usd": cost,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        }
        if parse_error:
            result["parse_error"] = parse_error
        return result

    @r.get("/oracle-review/{fixture_id}", dependencies=auth_dep)
    def get_oracle_fixture(fixture_id: str) -> dict:
        """Return full fixture JSON including cells + any review items."""
        path = _oracle_dir / f"{fixture_id}.json"
        if not path.exists():
            raise HTTPException(404, f"Oracle fixture not found: {fixture_id!r}")
        data = _normalize_fixture_for_ui(json.loads(path.read_text(encoding="utf-8")))
        review_path = _oracle_dir / f"{fixture_id}.review.json"
        review_items: list[dict] = []
        if review_path.exists():
            try:
                rd = json.loads(review_path.read_text(encoding="utf-8"))
                review_items = rd.get("needs_review", [])
            except (OSError, json.JSONDecodeError):
                pass
        data["review_items"] = review_items
        return data

    @r.post("/oracle-review/{fixture_id}/review", dependencies=auth_dep)
    def update_oracle_review(fixture_id: str, payload: dict) -> dict:
        """Apply cell review actions to the review file.

        payload: {
            "actions": [
                {"entity": "Order", "field": "status", "action": "approve"},
                {"entity": "Order", "field": "total", "action": "fix", "corrected_op": "RU"},
                {"entity": "Order", "field": "id", "action": "remove"}
            ],
            "reviewed_by": "phuong"   (optional)
        }
        """
        fix_path = _oracle_dir / f"{fixture_id}.json"
        review_path = _oracle_dir / f"{fixture_id}.review.json"
        if not fix_path.exists():
            raise HTTPException(404, f"Oracle fixture not found: {fixture_id!r}")

        actions: list[dict] = payload.get("actions", [])
        reviewed_by: str = payload.get("reviewed_by", "")
        action_map = {(a["entity"], a["field"]): a for a in actions}

        fixture_data = json.loads(fix_path.read_text(encoding="utf-8"))
        cells = _get_cells(fixture_data.get("expected", {}))
        for entity, fields in list(cells.items()):
            for field_name in list(fields.keys()):
                act = action_map.get((entity, field_name))
                if act is None:
                    continue
                if act["action"] == "remove":
                    del fields[field_name]
                elif act["action"] == "fix":
                    fields[field_name]["op"] = act.get("corrected_op", fields[field_name]["op"])
                    fields[field_name]["confidence"] = "high"
                elif act["action"] == "approve":
                    fields[field_name]["confidence"] = "high"

        if reviewed_by:
            fixture_data["reviewed_by"] = reviewed_by
        from datetime import date as _date
        fixture_data["reviewed_at"] = _date.today().isoformat()
        fix_path.write_text(json.dumps(fixture_data, ensure_ascii=False, indent=2), encoding="utf-8")

        if review_path.exists():
            rd = json.loads(review_path.read_text(encoding="utf-8"))
            for item in rd.get("needs_review", []):
                act = action_map.get((item["entity"], item["field"]))
                if act:
                    item["action"] = act["action"]
                    if act["action"] == "fix":
                        item["corrected_op"] = act.get("corrected_op")
            review_path.write_text(json.dumps(rd, ensure_ascii=False, indent=2), encoding="utf-8")

        return {"fixture_id": fixture_id, "updated": len(actions)}

    @r.get("/oracle-review/{fixture_id}/export", dependencies=auth_dep)
    def export_oracle_fixture(fixture_id: str) -> dict:
        """Return the approved fixture JSON ready for use as ground truth."""
        path = _oracle_dir / f"{fixture_id}.json"
        if not path.exists():
            raise HTTPException(404, f"Oracle fixture not found: {fixture_id!r}")
        return json.loads(path.read_text(encoding="utf-8"))

    @r.get("/oracle-review/{fixture_id}/prompt", dependencies=auth_dep)
    def get_oracle_prompt(fixture_id: str) -> dict:
        """Return rendered oracle prompt (system + user with route_context injected)."""
        if oracle_strategy_factory is None:
            raise HTTPException(501, "No oracle_strategy_factory configured")
        path = _oracle_dir / f"{fixture_id}.json"
        if not path.exists():
            raise HTTPException(404, f"Oracle fixture not found: {fixture_id!r}")
        data = json.loads(path.read_text(encoding="utf-8"))
        strategy = oracle_strategy_factory()
        if not hasattr(strategy, "render_prompt"):
            raise HTTPException(501, "Strategy does not implement render_prompt")
        return strategy.render_prompt(data.get("input_data", {}))

    @r.post("/oracle-review/{fixture_id}/run", dependencies=auth_dep)
    async def run_oracle_preview(fixture_id: str) -> dict:
        """Re-run oracle on fixture input_data, return preview without saving."""
        if oracle_strategy_factory is None:
            raise HTTPException(501, "No oracle_strategy_factory configured")
        path = _oracle_dir / f"{fixture_id}.json"
        if not path.exists():
            raise HTTPException(404, f"Oracle fixture not found: {fixture_id!r}")
        data = json.loads(path.read_text(encoding="utf-8"))
        strategy = oracle_strategy_factory()
        candidate = await strategy.generate_candidate(data.get("input_data", {}))
        return candidate

    @r.post("/oracle-review/{fixture_id}/promote-to-suite", dependencies=auth_dep)
    def promote_oracle_fixture_to_suite(fixture_id: str, payload: dict) -> dict:
        """Copy a reviewed oracle fixture into a suite's cases dir as a YAML case.

        Step 5 of the Studio flow: once cells are reviewed and approved, the
        fixture becomes a regression case the suite re-runs every time.

        Body:
            target_suite_id (str, required):  destination suite. The YAML lands
                                              at cases_dir/<target_suite_id>/.
            case_id         (str, optional):  override the YAML stem; defaults
                                              to fixture_id.
            overwrite       (bool, optional): replace existing case (default False).

        Returns:
            {written_path, case_id, target_suite_id, cells_count}

        The written YAML keeps `input` (from fixture.input_data), `expected`
        (cells flattened to {entity, column, op} list), and a `metadata` block
        carrying audit pointers (oracle_prompt_version, meta_prompt_version,
        oracle_model, source_fixture). Review-only fields (reviewed_by,
        production_prompt, full oracle_prompt text) are stripped to keep the
        case file lean.
        """
        target_suite = str(payload.get("target_suite_id", "")).strip()
        if not target_suite:
            raise HTTPException(400, "target_suite_id is required")
        if not all(c.isalnum() or c in "_-" for c in target_suite):
            raise HTTPException(
                400, "target_suite_id may only contain letters, numbers, _ and -",
            )

        src_path = _oracle_dir / f"{fixture_id}.json"
        if not src_path.exists():
            raise HTTPException(404, f"Oracle fixture not found: {fixture_id!r}")
        data = _normalize_fixture_for_ui(json.loads(src_path.read_text(encoding="utf-8")))

        case_id = str(payload.get("case_id", "")).strip() or fixture_id
        if not all(c.isalnum() or c in "_-" for c in case_id):
            raise HTTPException(400, "case_id may only contain letters, numbers, _ and -")
        overwrite = bool(payload.get("overwrite", False))

        # Flatten cells {entity:{field:cell}} → list[{entity, column, op}]
        cells_map = data.get("expected") or {}
        cells_list: list[dict] = []
        for entity, fields in cells_map.items():
            if not isinstance(fields, dict):
                continue
            for field_name, cell in fields.items():
                if not isinstance(cell, dict):
                    continue
                op = str(cell.get("op", "")).strip()
                if not op:
                    continue
                cells_list.append({
                    "entity": entity,
                    "column": field_name,
                    "op": op,
                })

        verdict = "populated" if cells_list else "empty"
        promoted = {
            "case_id": case_id,
            "input": data.get("input_data", {}),
            "expected": {
                "verdict": verdict,
                "cells": cells_list,
            },
            "metadata": {
                "source_fixture": fixture_id,
                "oracle_model": data.get("oracle_model", ""),
                "oracle_prompt_version": data.get("oracle_prompt_version", ""),
                "meta_prompt_version": data.get("meta_prompt_version", ""),
                "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

        target_dir = cases_dir / target_suite
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / f"{case_id}.yml"
        if out_path.exists() and not overwrite:
            raise HTTPException(
                409,
                f"case already exists at {out_path} — pass overwrite=true to replace",
            )
        out_path.write_text(
            yaml.safe_dump(promoted, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        return {
            "written_path": str(out_path),
            "case_id": case_id,
            "target_suite_id": target_suite,
            "cells_count": len(cells_list),
        }

    @r.delete("/oracle-review/{fixture_id}", dependencies=auth_dep)
    def delete_oracle_fixture(fixture_id: str) -> dict:
        """Delete a fixture and its companion review file."""
        path = _oracle_dir / f"{fixture_id}.json"
        if not path.exists():
            raise HTTPException(404, f"Oracle fixture not found: {fixture_id!r}")
        path.unlink()
        review_path = _oracle_dir / f"{fixture_id}.review.json"
        if review_path.exists():
            review_path.unlink()
        return {"deleted": fixture_id}

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
