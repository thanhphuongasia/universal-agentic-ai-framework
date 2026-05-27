from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from ryuu_eval_oracle.review_schema import ReviewSchema

# Covariant: appears in return position only
_InputT_co = TypeVar("_InputT_co", covariant=True)
_CandidateT_co = TypeVar("_CandidateT_co", covariant=True)

# Contravariant: appears in parameter position only
_InputT_contra = TypeVar("_InputT_contra", contravariant=True)


@runtime_checkable
class IInputSource(Protocol[_InputT_co]):
    """Fetch raw input for a case by ID — from disk, DB, or HTTP."""

    async def fetch(self, case_id: str) -> _InputT_co: ...


@runtime_checkable
class IProductionTarget(Protocol):
    """Run the production system on raw input and return its raw output.

    Kept intentionally loose (Any → Any) so any adapter can satisfy it
    without coupling to eval domain types.
    """

    async def run(self, input: Any) -> Any: ...


@runtime_checkable
class IOracleStrategy(Protocol[_InputT_contra, _CandidateT_co]):
    """Domain-specific oracle logic: describe UI layout + generate candidate expectation.

    Implement one strategy per domain (CRUD matrix, class diagram, etc.).
    Wiring (input source, production target, persistence) lives in OracleWorkflow.
    """

    def review_schema(self) -> ReviewSchema:
        """Return the UI schema for this domain's review table/graph/tree."""
        ...

    async def generate_candidate(
        self,
        input: _InputT_contra,
        existing_output: Any | None = None,
    ) -> _CandidateT_co:
        """Generate an expected-output candidate.

        Args:
            input: raw input fetched from IInputSource.
            existing_output: output already produced by the production system
                (Case A).  None when no production system exists yet (Case B).
        """
        ...
