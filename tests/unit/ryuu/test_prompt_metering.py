"""Unit tests for ryuu_cognitive.context.prompt_metering.

Verifies the chars/4 token estimator and breakdown builder used by handlers
to trace where input tokens come from (/last and similar commands).
"""

from __future__ import annotations

from ryuu_cognitive.context import build_prompt_breakdown, est_tokens


def test_est_tokens_empty_returns_zero():
    assert est_tokens("") == 0


def test_est_tokens_none_returns_zero():
    # est_tokens treats falsy input as 0
    assert est_tokens(None) == 0  # type: ignore[arg-type]


def test_est_tokens_short_text_floors_to_one():
    # "hi" = 2 chars → 2//4 = 0, but est_tokens returns max(1, ...)
    assert est_tokens("hi") == 1


def test_est_tokens_chars_div_four():
    # 80 chars → 20 tokens
    text = "a" * 80
    assert est_tokens(text) == 20


def test_build_breakdown_has_total_est():
    bd = build_prompt_breakdown({"system": "abcd", "user": "efgh"})
    assert bd["system"] == 1
    assert bd["user"] == 1
    assert bd["total_est"] == 2


def test_build_breakdown_empty_blocks():
    bd = build_prompt_breakdown({"system": "", "memory": ""})
    assert bd["system"] == 0
    assert bd["memory"] == 0
    assert bd["total_est"] == 0


def test_build_breakdown_preserves_key_order():
    blocks = {"system": "x" * 100, "memory": "y" * 50, "history": "z" * 200}
    bd = build_prompt_breakdown(blocks)
    keys = [k for k in bd if k != "total_est"]
    assert keys == ["system", "memory", "history"]


def test_build_breakdown_total_matches_sum():
    bd = build_prompt_breakdown({
        "system":  "a" * 400,   # 100
        "memory":  "b" * 200,   # 50
        "history": "c" * 800,   # 200
    })
    assert bd["total_est"] == bd["system"] + bd["memory"] + bd["history"]
