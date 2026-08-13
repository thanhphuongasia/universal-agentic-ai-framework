"""Agent SDK backend — uses claude-agent-sdk.

Requires: pip install claude-agent-sdk
Auth: ANTHROPIC_API_KEY env var OR Claude Code subscription (claude login).

Streams output via optional `on_event` callback. Returns final RootCauseReport.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Callable

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        query,
    )
    from claude_agent_sdk.types import StreamEvent
except ImportError as _err:
    raise ImportError(
        "claude-agent-sdk is required for AgentSdkBackend.\n"
        "Install with: pip install claude-agent-sdk"
    ) from _err

from ..core.models import (
    Confidence,
    Evidence,
    Finding,
    InputBundle,
    RootCauseReport,
)

logger = logging.getLogger(__name__)


def _format_tool_input(name: str, input_data: dict[str, Any]) -> str:
    """Render a one-line, human-readable preview of a tool call's input."""
    if not isinstance(input_data, dict):
        return str(input_data)

    if name == "Grep":
        pattern = input_data.get("pattern", "")
        path = input_data.get("path", "")
        glob = input_data.get("glob", "")
        parts = [f"pattern={pattern!r}"]
        if path:
            parts.append(f"path={path!r}")
        if glob:
            parts.append(f"glob={glob!r}")
        return " ".join(parts)

    if name == "Glob":
        pattern = input_data.get("pattern", "")
        path = input_data.get("path", "")
        return f"pattern={pattern!r}" + (f" path={path!r}" if path else "")

    if name == "Read":
        path = input_data.get("file_path", "")
        offset = input_data.get("offset")
        limit = input_data.get("limit")
        parts = [f"file={path!r}"]
        if offset is not None or limit is not None:
            parts.append(f"lines={offset}:{(offset or 0) + (limit or 0)}")
        return " ".join(parts)

    # Fallback: shorten generic dict
    s = json.dumps(input_data, separators=(",", ":"))
    return s if len(s) <= 120 else s[:117] + "..."


def _parse_output(text: str, target_id: str, tool_calls_used: int, cost_usd: float) -> RootCauseReport:
    try:
        clean = text.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.splitlines()[1:])
        if clean.endswith("```"):
            clean = "\n".join(clean.splitlines()[:-1])
        data = json.loads(clean)
        findings = [
            Finding(
                entity=f["entity"],
                field=f["field"],
                issue_type=f["issue_type"],
                confidence=Confidence(f.get("confidence", "low")),
                evidence=Evidence(**f.get("evidence", {})),
                root_cause=f.get("root_cause", ""),
                suggested_fix=f.get("suggested_fix", ""),
            )
            for f in data.get("findings", [])
        ]
        return RootCauseReport(
            target_id=target_id,
            findings=findings,
            summary=data.get("summary", ""),
            tool_calls_used=tool_calls_used,
            cost_usd=cost_usd,
        )
    except Exception as exc:
        logger.warning("Failed to parse output: %s | raw: %.200s", exc, text)
        return RootCauseReport(
            target_id=target_id,
            findings=[],
            summary=f"Parse error: {exc}",
            tool_calls_used=tool_calls_used,
            cost_usd=cost_usd,
        )


class AgentSdkBackend:
    """InvestigatorBackend using claude-agent-sdk."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        allowed_tools: list[str] | None = None,
        max_turns: int = 30,
        stream_to_stdout: bool = False,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.model = model
        self.allowed_tools = allowed_tools or ["Read", "Glob", "Grep"]
        self.max_turns = max_turns
        self.stream_to_stdout = stream_to_stdout
        self.on_event = on_event

    def _build_prompt(self, bundle: InputBundle) -> str:
        return (
            f"Investigate eval discrepancies for: {bundle.target_id}\n\n"
            + json.dumps(
                {
                    "payload": bundle.payload,
                    "diff": bundle.diff,
                    "project_id": bundle.project_id,
                },
                indent=2,
            )
        )

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            self.on_event(event)

    async def investigate(
        self,
        bundle: InputBundle,
        system_prompt: str,
        **kwargs: Any,
    ) -> RootCauseReport:
        tool_calls_used = 0
        in_tool = False
        result_msg: ResultMessage | None = None
        final_text = ""

        async for message in query(
            prompt=self._build_prompt(bundle),
            options=ClaudeAgentOptions(
                allowed_tools=self.allowed_tools,
                permission_mode="dontAsk",
                system_prompt=system_prompt,
                cwd=bundle.repo_path,
                model=self.model,
                max_turns=self.max_turns,
                include_partial_messages=True,
            ),
        ):
            if isinstance(message, StreamEvent):
                event = message.event
                event_type = event.get("type")

                if event_type == "content_block_start":
                    block = event.get("content_block", {})
                    if block.get("type") == "tool_use":
                        in_tool = True   # suppress text streaming until tool stops

                elif event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta" and not in_tool:
                        text = delta.get("text", "")
                        self._emit({"type": "text", "text": text})
                        if self.stream_to_stdout:
                            sys.stdout.write(text)
                            sys.stdout.flush()

                elif event_type == "content_block_stop":
                    in_tool = False

            elif isinstance(message, AssistantMessage):
                # Pull tool calls (with full inputs) from the complete message
                for block in message.content:
                    if hasattr(block, "text") and block.text:
                        final_text = block.text  # last text block wins
                    elif hasattr(block, "name") and hasattr(block, "input"):
                        tool_calls_used += 1
                        tool_name = block.name
                        tool_input = block.input or {}
                        self._emit({
                            "type": "tool_call",
                            "name": tool_name,
                            "input": tool_input,
                        })
                        if self.stream_to_stdout:
                            preview = _format_tool_input(tool_name, tool_input)
                            print(f"\n[{tool_name}] {preview}", flush=True)

            elif isinstance(message, ResultMessage):
                result_msg = message
                break

        cost = (result_msg.total_cost_usd or 0.0) if result_msg else 0.0

        if result_msg and result_msg.is_error:
            return RootCauseReport(
                target_id=bundle.target_id,
                findings=[],
                summary=f"Agent error: {result_msg.result}",
                tool_calls_used=tool_calls_used,
                cost_usd=cost,
            )

        # Prefer ResultMessage.result if available; fall back to last text
        text = (result_msg.result if result_msg and result_msg.result else final_text) or ""
        return _parse_output(text, bundle.target_id, tool_calls_used, cost)
