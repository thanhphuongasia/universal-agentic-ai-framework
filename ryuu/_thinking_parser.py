"""Parse `<thinking>...</thinking>` + `<answer>...</answer>` tags from LLM output.

Phase 14.1 helper. Shared between ThinkingStrategy (cognitive layer) and
Factory's thinking_mode wiring (ergonomic layer).
"""

from __future__ import annotations

import re

__all__ = ["parse_thinking_answer", "wrap_thinking_template"]


_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)


def parse_thinking_answer(raw: str) -> tuple[str, str]:
    """Extract (answer, thinking) from LLM output.

    Fallback when tags missing: returns (raw, "") so caller can degrade gracefully.

    >>> parse_thinking_answer("<thinking>step 1</thinking><answer>42</answer>")
    ('42', 'step 1')
    >>> parse_thinking_answer("plain text")
    ('plain text', '')
    """
    thinking_match = _THINKING_RE.search(raw)
    answer_match = _ANSWER_RE.search(raw)
    answer = answer_match.group(1).strip() if answer_match else raw.strip()
    thinking = thinking_match.group(1).strip() if thinking_match else ""
    return answer, thinking


THINKING_TEMPLATE = (
    "\n\nProduce your response in two parts:\n"
    "<thinking>\n"
    "Step through the question carefully. Decompose. Consider the options. "
    "Identify the most likely failure mode of a quick answer. Be honest about uncertainty.\n"
    "</thinking>\n"
    "<answer>\n"
    "The actual answer, concise and direct. No hedging unless uncertainty is genuine.\n"
    "</answer>\n"
    "Always emit BOTH tags. Never omit the thinking block."
)


def wrap_thinking_template(base_system_prompt: str = "") -> str:
    """Augment a base system prompt with the thinking-channel instruction."""
    if not base_system_prompt:
        return THINKING_TEMPLATE.strip()
    return base_system_prompt.rstrip() + THINKING_TEMPLATE
