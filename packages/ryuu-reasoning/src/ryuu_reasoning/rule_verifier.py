"""RuleVerifier — pure Python rule-based formal verifier. Phase 14.7.

No external deps. Evaluates business rules against LLM output (parsed dict).

Use case: trading bot compliance, prescription rules, simple constraints
that don't need full SMT/Prolog power.

For arithmetic constraints (linear programming, integer optimization) use
Z3Verifier. For multi-step logical rules with backtracking use Prolog
(future Phase 14.7.x).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ryuu_cognitive.verifier import IVerifier, VerificationResult
from ryuu_core.context import ExecutionContext


@dataclass
class Rule:
    """One business rule. Evaluated against parsed dict.

    Two modes:
      - `predicate=Callable[[dict], bool]` — full Python, max flexibility
      - `expression=str` — eval'd against dict as local vars (e.g. "amount <= income * 0.3")

    `name` is shown in feedback when rule fails.
    `severity` "critical" rules fail the verification immediately; "warning"
    rules contribute feedback but don't fail.
    """

    name: str
    predicate: Callable[[dict[str, Any]], bool] | None = None
    expression: str | None = None
    severity: str = "critical"   # "critical" | "warning"
    message: str = ""             # custom feedback when rule fails

    def __post_init__(self) -> None:
        if (self.predicate is None) == (self.expression is None):
            raise ValueError(
                f"Rule {self.name!r}: must specify exactly one of "
                "`predicate=` or `expression=`."
            )

    def evaluate(self, data: dict[str, Any]) -> bool:
        """Returns True if rule passes."""
        if self.predicate is not None:
            return bool(self.predicate(data))
        # Expression mode — restricted eval with data as local vars
        try:
            return bool(eval(self.expression, {"__builtins__": {}}, data))   # noqa: S307
        except (KeyError, NameError, TypeError, ValueError, SyntaxError):
            return False


@dataclass
class RuleVerifier:
    """Evaluates list of Rules against output (parsed as JSON dict).

    If output not valid JSON → fail with parse-error feedback.
    Otherwise evaluate each rule; collect failures.

    `passed = True` iff zero "critical" failures. Warnings included in feedback
    but don't fail.
    """

    verifier_id: str = "rule_verifier"
    rules: list[Rule] = field(default_factory=list)

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        # Parse output as JSON
        try:
            stripped = str(output).strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                if len(lines) > 2:
                    stripped = "\n".join(lines[1:-1])
            data = json.loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            return VerificationResult(
                passed=False,
                confidence=0.0,
                feedback=f"Output not valid JSON: {exc}",
            )

        if not isinstance(data, dict):
            return VerificationResult(
                passed=False,
                confidence=0.0,
                feedback=f"Output must be JSON object (dict), got {type(data).__name__}",
            )

        critical_failures: list[str] = []
        warnings: list[str] = []

        for rule in self.rules:
            if rule.evaluate(data):
                continue
            msg = rule.message or f"Rule {rule.name!r} failed"
            if rule.severity == "critical":
                critical_failures.append(msg)
            else:
                warnings.append(msg)

        passed = len(critical_failures) == 0
        confidence = 1.0 if passed and not warnings else (
            0.5 if passed else max(0.0, 1.0 - 0.2 * len(critical_failures))
        )
        feedback_parts: list[str] = []
        if critical_failures:
            feedback_parts.append("Critical: " + "; ".join(critical_failures))
        if warnings:
            feedback_parts.append("Warnings: " + "; ".join(warnings))
        return VerificationResult(
            passed=passed,
            confidence=confidence,
            feedback="\n".join(feedback_parts),
        )


__all__ = ["Rule", "RuleVerifier"]
