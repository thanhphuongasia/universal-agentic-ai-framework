"""Unit tests for category-based suite dispatch in eval_suites.runner_factory.

The fix: behavior (target + scorer) is keyed on the suite's CATEGORY
(``template_id``), never its instance name — so a cloned/renamed suite keeps
the right wiring. Dummy API keys let us construct providers without network.
"""
from __future__ import annotations

import pytest

from eval_consumer.crud_matrix_llm.target import CrudMatrixTarget
from eval_suites import _SUITE_BEHAVIOR, runner_factory


@pytest.fixture(autouse=True)
def _dummy_keys(monkeypatch):
    # Providers only check key presence at construction; no network call.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


def _runner(suite_id, template_id=None):
    return runner_factory(
        suite_id, None, model="gpt-4o-mini", system_prompt="x", template_id=template_id
    )


def _scorer_ids(runner):
    return [s.scorer_id for s in runner._scorers]


def test_crud_category_gets_crud_target_and_scorer():
    r = _runner("crud_matrix_llm", template_id="crud_matrix_llm")
    assert isinstance(r._target, CrudMatrixTarget)
    assert _scorer_ids(r) == ["crud-ops-match"]


def test_dispatch_is_name_independent():
    # Different instance name, same category → still CRUD wiring (the bug fix).
    r = _runner("crud_matrix_llm_phuong_suite", template_id="crud_matrix_llm")
    assert isinstance(r._target, CrudMatrixTarget)
    assert _scorer_ids(r) == ["crud-ops-match"]


def test_arbitrary_name_with_crud_category():
    r = _runner("totally_unrelated_name", template_id="crud_matrix_llm")
    assert isinstance(r._target, CrudMatrixTarget)


def test_legacy_fallback_to_suite_id_when_no_template_id():
    # No template_id supplied; suite_id itself IS the category.
    r = _runner("crud_matrix_llm", template_id=None)
    assert isinstance(r._target, CrudMatrixTarget)


def test_generic_suite_does_not_get_crud_wiring():
    r = _runner("translation", template_id=None)
    assert not isinstance(r._target, CrudMatrixTarget)
    assert _scorer_ids(r)[0] in ("semantic-similarity", "exact-match")


def test_unknown_category_falls_back_to_generic():
    r = _runner("some_suite", template_id="no_such_category")
    assert not isinstance(r._target, CrudMatrixTarget)


def test_registry_is_open_closed():
    # Adding a category = one entry here; this asserts the registry exists.
    assert "crud_matrix_llm" in _SUITE_BEHAVIOR
    assert callable(_SUITE_BEHAVIOR["crud_matrix_llm"])


# ---------------------------------------------------------------------------
# OpenAI provider strict-schema compatibility guard
# ---------------------------------------------------------------------------

def test_strict_compatible_rejects_dynamic_key_schema():
    from ryuu_providers_openai.provider import _is_strict_compatible
    dynamic = {"type": "object", "additionalProperties": {"type": "object"}}
    closed = {"type": "object", "properties": {"x": {"type": "string"}},
              "additionalProperties": False}
    assert _is_strict_compatible(dynamic) is False
    assert _is_strict_compatible(closed) is True
    assert _is_strict_compatible(None) is True
