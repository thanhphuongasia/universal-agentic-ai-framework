"""RED tests for ryuu_providers._pricing — T04."""

from __future__ import annotations


def test_pricing_imports() -> None:
    from ryuu_providers._pricing import CONTEXT_WINDOW, PRICING, calculate_usd, reload_pricing  # noqa: F401
    assert callable(calculate_usd)
    assert callable(reload_pricing)
    assert isinstance(PRICING, dict)
    assert isinstance(CONTEXT_WINDOW, dict)


def test_calculate_usd_known_model() -> None:
    from ryuu_providers._pricing import calculate_usd
    usd = calculate_usd("gpt-4o", 1_000_000, 1_000_000)
    assert usd > 0


def test_calculate_usd_unknown_model_returns_zero() -> None:
    from ryuu_providers._pricing import calculate_usd
    assert calculate_usd("nonexistent-model-xyz", 1000, 500) == 0.0


def test_calculate_usd_fake_provider_zero() -> None:
    from ryuu_providers._pricing import calculate_usd
    assert calculate_usd("fake", 10_000, 5_000) == 0.0


def test_context_window_has_known_models() -> None:
    from ryuu_providers._pricing import CONTEXT_WINDOW
    assert "gpt-4o" in CONTEXT_WINDOW
    assert CONTEXT_WINDOW["gpt-4o"] > 0
