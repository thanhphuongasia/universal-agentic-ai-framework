from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ryuu_eval_core.models import CaseResult, EvalCase, ScoreResult


@runtime_checkable
class EvalTarget(Protocol):
    async def run(self, case: EvalCase) -> CaseResult: ...


@runtime_checkable
class Scorer(Protocol):
    scorer_id: str

    async def score(self, case: EvalCase, output: str) -> ScoreResult: ...


@runtime_checkable
class ITestCaseStore(Protocol):
    """Persisted eval cases for a suite (e.g. the ``test_cases`` table).

    Maps a stored row ↔ ``EvalCase``. The per-case scoring spec is surfaced as
    ``EvalCase.metadata['scoring']`` so it flows straight into a per-case scorer
    resolver (``metadata_scorer_resolver``). Depend on this Protocol, not the impl.
    """

    async def list_cases(self, suite_id: str) -> list[EvalCase]: ...

    async def get_case(self, suite_id: str, case_id: str) -> EvalCase | None: ...

    async def save_case(
        self,
        suite_id: str,
        case: EvalCase,
        *,
        template_id: str | None = None,
        scoring: dict[str, Any] | None = None,
    ) -> None: ...

    async def delete_case(self, suite_id: str, case_id: str) -> bool: ...


@runtime_checkable
class ISuiteStore(Protocol):
    """Persisted suites (the ``suites`` table). When wired, the eval app is
    DB-only for suites — no file-based discovery. Depend on this Protocol.
    """

    async def list_suites(self) -> list[dict[str, Any]]: ...

    async def get_suite(self, suite_id: str) -> dict[str, Any] | None: ...

    async def create_suite(
        self, suite_id: str, *, title: str = "", domain_id: str | None = None
    ) -> None: ...

    async def delete_suite(self, suite_id: str) -> bool: ...


@runtime_checkable
class IEvalRunStore(Protocol):
    """Persisted eval runs + per-case results (``eval_runs`` + ``eval_results``).

    ``create_run`` opens a run row (status='running'); ``finish_run`` closes it
    with a status + summary; ``save_result`` appends one case result. Reads via
    ``get_run`` / ``list_runs``. Depend on this Protocol, not the impl.
    """

    async def create_run(
        self,
        run_id: str,
        suite_id: str,
        *,
        prompt_version_id: str | None = None,
        triggered_by: str = "",
        trigger_type: str = "manual",
    ) -> None: ...

    async def finish_run(
        self, run_id: str, *, status: str, summary: dict[str, Any]
    ) -> None: ...

    async def save_result(
        self,
        run_id: str,
        result: dict[str, Any],
        *,
        test_case_id: str,
        passed: bool,
        resolved_prompt_version_id: str | None = None,
    ) -> None: ...

    async def get_run(self, run_id: str) -> dict[str, Any] | None: ...

    async def list_runs(self, suite_id: str, limit: int = 20) -> list[dict[str, Any]]: ...
