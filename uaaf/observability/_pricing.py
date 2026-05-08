"""LLM pricing + context-window config loader.

Data lives in pricing.yaml (co-located with this file).
Override the file path via env var: UAAF_PRICING_FILE=/path/to/pricing.yaml

No redeploy needed to add a new model or update prices — edit the YAML file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_MILLION = 1_000_000
_DEFAULT_CONTEXT_WINDOW = 128_000

# Hardcoded fallback — used only when YAML file is missing or unreadable.
_FALLBACK_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o":                  (2.50, 10.00),
    "gpt-4o-mini":             (0.15,  0.60),
    "gpt-4-turbo":            (10.00, 30.00),
    "gpt-3.5-turbo":           (0.50,  1.50),
    "text-embedding-3-small":  (0.02,  0.00),
    "text-embedding-3-large":  (0.13,  0.00),
    "claude-opus-4-7":        (15.00, 75.00),
    "claude-sonnet-4-6":       (3.00, 15.00),
    "claude-haiku-4-5":        (0.80,  4.00),
    "fake":                    (0.00,  0.00),
}

_FALLBACK_CONTEXT_WINDOW: dict[str, int] = {
    "gpt-4o":          128_000,
    "gpt-4o-mini":     128_000,
    "gpt-4-turbo":     128_000,
    "gpt-3.5-turbo":    16_385,
    "claude-opus-4-7":  200_000,
    "claude-sonnet-4-6":200_000,
    "claude-haiku-4-5": 200_000,
}


def _load_yaml(path: Path) -> Any:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _resolve_pricing_file() -> Path:
    env = os.getenv("UAAF_PRICING_FILE")
    if env:
        return Path(env)
    return Path(__file__).parent / "pricing.yaml"


def _build_tables() -> tuple[dict[str, tuple[float, float]], dict[str, int]]:
    pricing_file = _resolve_pricing_file()
    try:
        data = _load_yaml(pricing_file)
    except FileNotFoundError:
        return _FALLBACK_PRICING, _FALLBACK_CONTEXT_WINDOW
    except Exception:
        return _FALLBACK_PRICING, _FALLBACK_CONTEXT_WINDOW

    raw_pricing = data.get("pricing", {})
    pricing: dict[str, tuple[float, float]] = {
        model: (float(rates[0]), float(rates[1]))
        for model, rates in raw_pricing.items()
    }

    raw_window = data.get("context_window", {})
    context_window: dict[str, int] = {
        model: int(tokens) for model, tokens in raw_window.items()
    }

    return pricing or _FALLBACK_PRICING, context_window or _FALLBACK_CONTEXT_WINDOW


# Module-level tables — populated once at import time.
PRICING, CONTEXT_WINDOW = _build_tables()


def calculate_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a completion given the model and token counts.

    Falls back to 0.0 for unknown models.
    """
    if model not in PRICING:
        return 0.0
    input_rate, output_rate = PRICING[model]
    return (input_tokens * input_rate + output_tokens * output_rate) / _MILLION


def reload_pricing(path: Path | None = None) -> None:
    """Reload PRICING and CONTEXT_WINDOW from disk (e.g. after YAML update).

    Useful in long-running services without full restart.
    Optionally pass a custom *path* to load from.
    """
    global PRICING, CONTEXT_WINDOW  # noqa: PLW0603
    if path:
        try:
            data = _load_yaml(path)
            raw_p = data.get("pricing", {})
            raw_w = data.get("context_window", {})
            PRICING = {m: (float(r[0]), float(r[1])) for m, r in raw_p.items()} or _FALLBACK_PRICING
            CONTEXT_WINDOW = {m: int(t) for m, t in raw_w.items()} or _FALLBACK_CONTEXT_WINDOW
        except Exception:
            pass
    else:
        PRICING, CONTEXT_WINDOW = _build_tables()
