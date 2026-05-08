"""Tests for uaaf.observability._pricing — YAML loading + calculate_usd."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Default tables (loaded from bundled pricing.yaml)
# ---------------------------------------------------------------------------

def test_pricing_contains_openai_models() -> None:
    from uaaf.observability._pricing import PRICING
    for model in ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]:
        assert model in PRICING, f"{model} missing from PRICING"
        inp, out = PRICING[model]
        assert inp >= 0 and out >= 0


def test_pricing_contains_anthropic_models() -> None:
    from uaaf.observability._pricing import PRICING
    for model in ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]:
        assert model in PRICING, f"{model} missing from PRICING"


def test_context_window_contains_common_models() -> None:
    from uaaf.observability._pricing import CONTEXT_WINDOW
    for model in ["gpt-4o", "gpt-4o-mini", "claude-opus-4-7"]:
        assert model in CONTEXT_WINDOW
        assert CONTEXT_WINDOW[model] > 0


# ---------------------------------------------------------------------------
# calculate_usd — API unchanged
# ---------------------------------------------------------------------------

def test_calculate_usd_known_model() -> None:
    from uaaf.observability._pricing import calculate_usd
    # gpt-4o: $2.50/1M input, $10.00/1M output
    usd = calculate_usd("gpt-4o", 1_000_000, 1_000_000)
    assert abs(usd - 12.50) < 1e-6


def test_calculate_usd_unknown_model_returns_zero() -> None:
    from uaaf.observability._pricing import calculate_usd
    assert calculate_usd("nonexistent-model-xyz", 1000, 500) == 0.0


def test_calculate_usd_fake_provider_zero() -> None:
    from uaaf.observability._pricing import calculate_usd
    assert calculate_usd("fake", 10_000, 5_000) == 0.0


# ---------------------------------------------------------------------------
# Custom YAML via UAAF_PRICING_FILE env var
# ---------------------------------------------------------------------------

def test_reload_pricing_from_custom_yaml(tmp_path: Path) -> None:
    """reload_pricing() picks up a custom YAML file."""
    from uaaf.observability._pricing import reload_pricing

    custom = tmp_path / "custom_pricing.yaml"
    custom.write_text(yaml.dump({
        "pricing": {
            "new-model-x": [99.00, 199.00],
            "fake": [0.0, 0.0],
        },
        "context_window": {
            "new-model-x": 256_000,
        },
    }))

    reload_pricing(path=custom)

    from uaaf.observability import _pricing as p
    assert "new-model-x" in p.PRICING
    assert p.PRICING["new-model-x"] == (99.00, 199.00)
    assert p.CONTEXT_WINDOW["new-model-x"] == 256_000

    # Restore original pricing for other tests
    reload_pricing()


def test_reload_pricing_missing_file_keeps_fallback() -> None:
    """reload_pricing() with a missing path keeps tables unchanged."""
    from uaaf.observability import _pricing as p
    from uaaf.observability._pricing import reload_pricing

    before_keys = set(p.PRICING.keys())
    reload_pricing(path=Path("/nonexistent/path/pricing.yaml"))
    # Tables unchanged — fallback triggered silently
    assert set(p.PRICING.keys()) == before_keys


def test_env_var_overrides_pricing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UAAF_PRICING_FILE env var is read by _resolve_pricing_file()."""
    from uaaf.observability._pricing import _resolve_pricing_file

    custom = tmp_path / "env_pricing.yaml"
    custom.write_text("")
    monkeypatch.setenv("UAAF_PRICING_FILE", str(custom))

    resolved = _resolve_pricing_file()
    assert resolved == custom


def test_default_pricing_file_resolves_to_existing_yaml() -> None:
    """_resolve_pricing_file() finds pricing.yaml at project root or bundled fallback."""
    from uaaf.observability._pricing import _resolve_pricing_file
    path = _resolve_pricing_file()
    assert path.exists(), f"pricing.yaml not found at {path}"
    assert path.name == "pricing.yaml"


def test_project_root_pricing_yaml_takes_precedence_over_bundled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project-root pricing.yaml is preferred over bundled package copy."""
    import uaaf.observability._pricing as mod

    # Patch __file__ so project_root calculation points to tmp_path
    custom = tmp_path / "pricing.yaml"
    custom.write_text(yaml.dump({"pricing": {"custom-model": [1.0, 2.0]}, "context_window": {}}))

    # Simulate: project_root = tmp_path (by putting __file__ 3 levels deep)
    fake_file = tmp_path / "uaaf" / "observability" / "_pricing.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.touch()

    original = mod.__file__
    monkeypatch.setattr(mod, "__file__", str(fake_file))
    try:
        from uaaf.observability._pricing import _resolve_pricing_file
        resolved = _resolve_pricing_file()
        assert resolved == custom
    finally:
        monkeypatch.setattr(mod, "__file__", original)
