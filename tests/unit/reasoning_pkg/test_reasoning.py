"""Phase 14.7 — ryuu-reasoning tests.

12 cases covering RuleVerifier (8) + Z3Verifier (4, skipped if z3 not installed).
"""

from __future__ import annotations

import pytest

from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_reasoning import Rule, RuleVerifier, Z3Verifier


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u", session_id="s", domain="t"),
        correlation_id="c1",
    )


# ---------------------------------------------------------------------------
# Rule basic
# ---------------------------------------------------------------------------


def test_rule_predicate_mode() -> None:
    r = Rule(name="positive", predicate=lambda d: d.get("x", 0) > 0)
    assert r.evaluate({"x": 5}) is True
    assert r.evaluate({"x": -1}) is False


def test_rule_expression_mode() -> None:
    r = Rule(name="bounded", expression="x >= 0 and x <= 100")
    assert r.evaluate({"x": 50}) is True
    assert r.evaluate({"x": 150}) is False


def test_rule_requires_exactly_one_mode() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        Rule(name="bad", predicate=lambda d: True, expression="x > 0")
    with pytest.raises(ValueError, match="exactly one"):
        Rule(name="bad", )


def test_rule_expression_safe_eval_no_builtins() -> None:
    """Eval shouldn't have access to builtins (no `open`, `exec`)."""
    r = Rule(name="evil", expression="__import__('os').system('echo HACK')")
    # Should fail gracefully (NameError caught), not execute
    assert r.evaluate({}) is False


# ---------------------------------------------------------------------------
# RuleVerifier
# ---------------------------------------------------------------------------


async def test_rule_verifier_passes_when_all_rules_pass() -> None:
    verifier = RuleVerifier(rules=[
        Rule(name="positive_amount", expression="amount > 0"),
        Rule(name="bounded_income", expression="income < 1000000"),
    ])
    result = await verifier.verify('{"amount": 100, "income": 50000}', _ctx())
    assert result.passed is True
    assert result.confidence == 1.0


async def test_rule_verifier_fails_on_critical() -> None:
    verifier = RuleVerifier(rules=[
        Rule(name="must_be_negative", expression="x < 0", severity="critical"),
    ])
    result = await verifier.verify('{"x": 5}', _ctx())
    assert result.passed is False
    assert "must_be_negative" in result.feedback.lower() or "Critical" in result.feedback


async def test_rule_verifier_warnings_dont_fail() -> None:
    verifier = RuleVerifier(rules=[
        Rule(name="prefer_small", expression="x < 100", severity="warning"),
    ])
    result = await verifier.verify('{"x": 500}', _ctx())
    assert result.passed is True   # warnings don't fail
    assert "Warning" in result.feedback


async def test_rule_verifier_invalid_json_fails_gracefully() -> None:
    verifier = RuleVerifier(rules=[Rule(name="x", expression="True")])
    result = await verifier.verify("not json", _ctx())
    assert result.passed is False
    assert "not valid JSON" in result.feedback


async def test_rule_verifier_strips_markdown_fences() -> None:
    verifier = RuleVerifier(rules=[Rule(name="ok", expression="amount > 0")])
    fenced = '```json\n{"amount": 100}\n```'
    result = await verifier.verify(fenced, _ctx())
    assert result.passed is True


# ---------------------------------------------------------------------------
# Z3Verifier — skip gracefully if z3-solver not installed
# ---------------------------------------------------------------------------


try:
    import z3 as _z3   # noqa: F401
    z3_available = True
except ImportError:
    z3_available = False

pytestmark_z3 = pytest.mark.skipif(not z3_available, reason="z3-solver not installed")


@pytestmark_z3
async def test_z3_verifier_loan_constraint_passes() -> None:
    """Loan amount <= 30% of income → constraint satisfied."""
    def loan_check(data, z3):
        amount = data["amount"]
        income = data["income"]
        return z3.And(amount <= 0.3 * income, amount <= 100000)

    verifier = Z3Verifier(constraint_builder=loan_check)
    result = await verifier.verify('{"amount": 25000, "income": 100000}', _ctx())
    assert result.passed is True


@pytestmark_z3
async def test_z3_verifier_loan_constraint_violated() -> None:
    """Loan amount > 30% of income → constraint violated."""
    def loan_check(data, z3):
        amount = data["amount"]
        income = data["income"]
        return z3.And(amount <= 0.3 * income, amount <= 100000)

    verifier = Z3Verifier(constraint_builder=loan_check)
    # 50000 > 30000 (30% of 100k) → unsat
    result = await verifier.verify('{"amount": 50000, "income": 100000}', _ctx())
    assert result.passed is False


@pytestmark_z3
async def test_z3_verifier_handles_constraint_builder_error() -> None:
    """If builder raises, return failed result with error feedback."""
    def buggy_builder(data, z3):
        raise KeyError("missing_field")

    verifier = Z3Verifier(constraint_builder=buggy_builder)
    result = await verifier.verify('{"x": 1}', _ctx())
    assert result.passed is False
    assert "error" in result.feedback.lower()


@pytestmark_z3
async def test_z3_verifier_invalid_json_graceful() -> None:
    verifier = Z3Verifier(constraint_builder=lambda d, z3: True)
    result = await verifier.verify("not json", _ctx())
    assert result.passed is False
    assert "not valid JSON" in result.feedback
