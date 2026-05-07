"""LLM pricing table (USD per 1 000 000 tokens).

Values are approximate as of 2026-05-07.  Update when providers change prices.
Overridable via RuntimeConfig.cost_overrides.
"""

from __future__ import annotations

# (input_usd_per_1m, output_usd_per_1m)
PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    # Anthropic
    "claude-opus-4-7": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    # Generic fallback (used by FakeLLMProvider)
    "fake": (0.0, 0.0),
}

_MILLION = 1_000_000


def calculate_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a completion given the model and token counts.

    Falls back to 0.0 for unknown models (logs a warning via the caller).
    """
    if model not in PRICING:
        return 0.0
    input_rate, output_rate = PRICING[model]
    return (input_tokens * input_rate + output_tokens * output_rate) / _MILLION
