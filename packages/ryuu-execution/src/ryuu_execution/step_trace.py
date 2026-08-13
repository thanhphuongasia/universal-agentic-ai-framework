"""Bedrock-style structured step trace for the ReAct loop.

Every agent run can carry a machine-readable list of STEPS — one per model
invocation / tool invocation / synthesis — each with its own input, output,
duration and token usage. Consumers (UIs, evals, audits) get the same shape
regardless of provider or project, mirroring how Bedrock Agents expose
``trace`` events next to the final completion.

Design constraints:
  - ZERO schema change on ``AgentResult`` — the snapshot rides in
    ``result.metadata["step_trace"]`` (a plain list[dict], json-safe).
  - Text payloads are HEAD-capped so traces stay cheap to persist.
  - The recorder is a dumb accumulator: no locks, one recorder per run
    (same lifecycle as ``callbacks``).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

_HEAD_CAP = 1200


def _head(text: Any, cap: int = _HEAD_CAP) -> str:
    s = str(text or "")
    return s if len(s) <= cap else s[:cap] + f"… [+{len(s) - cap} chars]"


@dataclass
class TraceStep:
    """One step of an agent run — json-safe via ``as_dict``."""

    index: int
    type: str            # "model_invocation" | "tool_invocation" | "synthesis"
    started_at: float    # epoch seconds
    duration_ms: int
    input: dict[str, Any]
    output: dict[str, Any]
    usage: dict[str, int] | None = None   # {"input_tokens", "output_tokens"} for model steps

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "type": self.type,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "input": self.input,
            "output": self.output,
            "usage": self.usage,
        }


@dataclass
class StepTraceRecorder:
    """Accumulates :class:`TraceStep` items during one agent run."""

    steps: list[TraceStep] = field(default_factory=list)

    # -- model (LLM) invocations -------------------------------------------------
    def model_step(
        self,
        *,
        round_no: int,
        request_head: str,
        content: str,
        thinking: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        usage_in: int = 0,
        usage_out: int = 0,
        started_at: float,
        synthesis: bool = False,
    ) -> None:
        calls = [
            {"tool": str((tc.get("function") or {}).get("name") or "?"),
             "args": _head((tc.get("function") or {}).get("arguments"), 300)}
            for tc in (tool_calls or [])
        ]
        self.steps.append(TraceStep(
            index=len(self.steps),
            type="synthesis" if synthesis else "model_invocation",
            started_at=started_at,
            duration_ms=int((time.time() - started_at) * 1000),
            input={"round": round_no, "request_head": _head(request_head)},
            output={
                "content_head": _head(content),
                "thinking_head": _head(thinking, 400),
                "tool_calls": calls,
            },
            usage={"input_tokens": int(usage_in), "output_tokens": int(usage_out)},
        ))

    # -- tool invocations ----------------------------------------------------------
    def tool_step(
        self,
        *,
        tool: str,
        args: Any,
        result: str,
        started_at: float,
    ) -> None:
        self.steps.append(TraceStep(
            index=len(self.steps),
            type="tool_invocation",
            started_at=started_at,
            duration_ms=int((time.time() - started_at) * 1000),
            input={"tool": str(tool), "args": _head(args, 400)},
            output={"result_head": _head(result)},
            usage=None,
        ))

    def snapshot(self) -> list[dict[str, Any]]:
        return [s.as_dict() for s in self.steps]
