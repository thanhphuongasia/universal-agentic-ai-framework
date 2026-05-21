"""StreamEvent — event yielded by `Agent.stream()`. Phase 10.4."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class StreamEvent:
    """Event yielded by `Agent.stream()`. Phase 10.4.

    Types:
      token        — token-by-token LLM output (Phase 10.6 enables tokens for no-tool path)
      thought      — ReAct reasoning text between tool calls
      tool_call    — before tool invocation (tool_name + args)
      tool_result  — after tool returns (tool_name + result)
      error        — exception in lifecycle
      final        — done, has final answer text
    """

    type: Literal["token", "thought", "tool_call", "tool_result", "error", "final"]
    text: str = ""
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Exception | None = None


# `.run(**kwargs)` reserves these keys for ContextScope; remaining kwargs are
# treated as template variables for `user_template` substitution.
RESERVED_SCOPE_KEYS: frozenset[str] = frozenset(
    {"user_id", "session_id", "domain", "correlation_id"}
)
