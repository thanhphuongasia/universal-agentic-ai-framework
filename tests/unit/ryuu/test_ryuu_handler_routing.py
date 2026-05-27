"""Unit tests for adaptive model routing in RyuuHandler.

Tests _select_model() directly — no LLM call, no Agent instantiation.
"""

from __future__ import annotations

from examples.ryuu_sensei.apps.ryuu_handler import (
    ALLOWED_MODELS,
    RyuuHandler,
    UserSettings,
    _DEFAULT_TIER_MODELS,
)


def _handler(**kwargs) -> RyuuHandler:
    return RyuuHandler(memory_backbone=None, **kwargs)


def _settings(**kwargs) -> UserSettings:
    return UserSettings(**kwargs)


# ---------------------------------------------------------------------------
# _select_model() — routing off
# ---------------------------------------------------------------------------

def test_adaptive_off_returns_settings_model_for_trivial() -> None:
    h = _handler()
    s = _settings(model="gpt-4o-mini", adaptive_routing=False)
    assert h._select_model("hi", s) == "gpt-4o-mini"


def test_adaptive_off_returns_settings_model_for_hard() -> None:
    h = _handler()
    s = _settings(model="gpt-4o-mini", adaptive_routing=False)
    hard = "analyze the architecture and compare performance trade-offs between systems"
    assert h._select_model(hard, s) == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# _select_model() — routing on (heuristic)
# ---------------------------------------------------------------------------

def test_trivial_query_routes_to_mini() -> None:
    h = _handler(difficulty_fn=lambda _: "trivial")
    s = _settings(adaptive_routing=True)
    assert h._select_model("hi", s) == "gpt-4o-mini"


def test_hard_query_routes_to_full_model() -> None:
    h = _handler(difficulty_fn=lambda _: "hard")
    s = _settings(adaptive_routing=True)
    hard = "analyze the architecture and compare performance trade-offs between the two systems"
    assert h._select_model(hard, s) == "gpt-4o"


# ---------------------------------------------------------------------------
# _select_model() — custom difficulty_fn
# ---------------------------------------------------------------------------

def test_custom_difficulty_fn_is_respected() -> None:
    h = _handler(difficulty_fn=lambda _: "hard")
    s = _settings(adaptive_routing=True)
    # Always "hard" regardless of query text
    assert h._select_model("hi", s) == "gpt-4o"


def test_custom_difficulty_fn_trivial_override() -> None:
    h = _handler(difficulty_fn=lambda _: "trivial")
    s = _settings(adaptive_routing=True)
    hard = "analyze and compare all possible architectural trade-offs in detail"
    assert h._select_model(hard, s) == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# _select_model() — invalid tier model falls back to settings.model
# ---------------------------------------------------------------------------

def test_invalid_tier_model_falls_back_to_settings_model() -> None:
    h = _handler(
        difficulty_fn=lambda _: "hard",
        tier_models={"trivial": "gpt-4o-mini", "medium": "gpt-4o-mini", "hard": "claude-opus-not-allowed"},
    )
    s = _settings(model="gpt-4o-mini", adaptive_routing=True)
    assert h._select_model("any query", s) == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# _select_model() — custom tier_models
# ---------------------------------------------------------------------------

def test_custom_tier_models_applied() -> None:
    h = _handler(
        difficulty_fn=lambda _: "medium",
        tier_models={"trivial": "gpt-4o-mini", "medium": "gpt-4o", "hard": "gpt-4o"},
    )
    s = _settings(adaptive_routing=True)
    assert h._select_model("explain this", s) == "gpt-4o"


# ---------------------------------------------------------------------------
# _DEFAULT_TIER_MODELS sanity
# ---------------------------------------------------------------------------

def test_default_tier_models_are_all_allowed() -> None:
    for model in _DEFAULT_TIER_MODELS.values():
        assert model in ALLOWED_MODELS, f"{model!r} not in ALLOWED_MODELS"
