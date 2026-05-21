"""Phase 14.7 — ryuu-reasoning demo.

Shows RuleVerifier (no deps) and Z3Verifier (optional z3-solver dep).

Use case: trading bot validates loan recommendation against compliance rules.

Run:
    python -m examples.reasoning_demo
"""

from __future__ import annotations

import asyncio
import json

from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_reasoning import Rule, RuleVerifier, Z3Verifier


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="trader", session_id="s1", domain="loans"),
        correlation_id="demo",
    )


async def demo_rule_verifier() -> None:
    print("\n" + "=" * 60)
    print("  Demo 1: RuleVerifier (pure Python, no deps)")
    print("=" * 60)

    verifier = RuleVerifier(rules=[
        Rule(
            name="positive_amount",
            expression="amount > 0",
            severity="critical",
            message="Loan amount must be positive",
        ),
        Rule(
            name="ratio_to_income",
            expression="amount <= 0.3 * income",
            severity="critical",
            message="Loan exceeds 30% of income",
        ),
        Rule(
            name="prefer_under_50k",
            expression="amount <= 50000",
            severity="warning",
            message="Prefer loans under $50k",
        ),
    ])

    test_cases = [
        # Pass
        {"amount": 25000, "income": 100000},
        # Critical fail (35% of income)
        {"amount": 35000, "income": 100000},
        # Pass với warning (over 50k)
        {"amount": 60000, "income": 250000},
    ]

    for case in test_cases:
        print(f"\n  Input: {case}")
        result = await verifier.verify(json.dumps(case), _ctx())
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"  {status} (confidence={result.confidence:.2f})")
        if result.feedback:
            print(f"  Feedback: {result.feedback}")


async def demo_z3_verifier() -> None:
    print("\n" + "=" * 60)
    print("  Demo 2: Z3Verifier (SMT-backed, optional z3-solver)")
    print("=" * 60)

    if Z3Verifier is None:
        print("  ⚠️  z3-solver not installed. Install: pip install 'ryuu-reasoning[z3]'")
        return

    try:
        import z3   # noqa: F401
    except ImportError:
        print("  ⚠️  z3-solver not installed. Install: pip install 'ryuu-reasoning[z3]'")
        return

    def loan_constraint(data, z3_):
        """Constraint: amount ≤ 30% income AND amount ≤ $100k."""
        amt = data["amount"]
        inc = data["income"]
        return z3_.And(amt <= 0.3 * inc, amt <= 100000)

    verifier = Z3Verifier(constraint_builder=loan_constraint)

    test_cases = [
        {"amount": 25000, "income": 100000},   # ✓ within 30% + under 100k
        {"amount": 35000, "income": 100000},   # ✗ 35% > 30%
        {"amount": 120000, "income": 1000000}, # ✗ over 100k cap
    ]

    for case in test_cases:
        print(f"\n  Input: {case}")
        result = await verifier.verify(json.dumps(case), _ctx())
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"  {status} — {result.feedback}")


async def main() -> None:
    print("=" * 60)
    print("  Phase 14.7 — ryuu-reasoning Demo")
    print("=" * 60)
    await demo_rule_verifier()
    await demo_z3_verifier()
    print("\n" + "=" * 60)
    print("  ✅ Demo complete")
    print()
    print("  Integration: plug as IVerifier in VerifierPipeline:")
    print("    SchemaVerifier → LLMJudgeVerifier → GroundTruthVerifier → ")
    print("      RuleVerifier (compliance) → Z3Verifier (constraints)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
