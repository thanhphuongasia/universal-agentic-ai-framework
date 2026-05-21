"""Z3Verifier — SMT solver-backed formal verifier. Phase 14.7.

Optional dep: `pip install "ryuu-reasoning[z3]"` to install z3-solver.

Use case: arithmetic constraints (linear programming, integer optimization,
trading bot risk limits, scheduling). For predicate rules without arithmetic
use RuleVerifier (cheaper, no extra dep).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ryuu_cognitive.verifier import IVerifier, VerificationResult
from ryuu_core.context import ExecutionContext

try:
    import z3   # type: ignore[import-untyped]
    _Z3_AVAILABLE = True
except ImportError:
    z3 = None   # type: ignore[assignment]
    _Z3_AVAILABLE = False


@dataclass
class Z3Verifier:
    """SMT-backed verifier. `constraint_builder(data, z3_module) -> z3.BoolRef`.

    User supplies a callable that builds a z3 expression from parsed output.
    Verifier checks if assertion holds (or asserts the negation is unsat).

    Example::

        def loan_constraint(data, z3):
            amount = z3.Real("amount")
            income = z3.Real("income")
            return z3.And(amount <= 0.3 * income, amount <= 100000,
                          amount == data["amount"], income == data["income"])

        verifier = Z3Verifier(constraint_builder=loan_constraint)
        result = await verifier.verify('{"amount": 25000, "income": 100000}', ctx)
        # result.passed = True (25000 <= 0.3 * 100000 = 30000 ✓)
    """

    verifier_id: str = "z3_verifier"
    constraint_builder: Callable[[dict[str, Any], Any], Any] = field(
        default=lambda data, z3: True,
    )

    def __post_init__(self) -> None:
        if not _Z3_AVAILABLE:
            raise ImportError(
                "Z3Verifier requires z3-solver. Install with: "
                'pip install "ryuu-reasoning[z3]"'
            )

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        # Parse JSON output
        try:
            stripped = str(output).strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                if len(lines) > 2:
                    stripped = "\n".join(lines[1:-1])
            data = json.loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            return VerificationResult(
                passed=False, confidence=0.0,
                feedback=f"Output not valid JSON: {exc}",
            )

        # Build constraint + check satisfiability
        try:
            constraint = self.constraint_builder(data, z3)
            solver = z3.Solver()
            solver.add(constraint)
            check = solver.check()
        except Exception as exc:
            return VerificationResult(
                passed=False, confidence=0.0,
                feedback=f"Z3 constraint evaluation error: {exc}",
            )

        if check == z3.sat:
            return VerificationResult(
                passed=True, confidence=1.0,
                feedback="Constraint satisfied",
            )
        if check == z3.unsat:
            return VerificationResult(
                passed=False, confidence=1.0,
                feedback=f"Constraint violated: {data}",
            )
        return VerificationResult(
            passed=False, confidence=0.5,
            feedback=f"Z3 returned unknown: {check}",
        )


__all__ = ["Z3Verifier"]
