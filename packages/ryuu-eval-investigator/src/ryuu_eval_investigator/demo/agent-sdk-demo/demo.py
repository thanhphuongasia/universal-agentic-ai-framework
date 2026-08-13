"""Demo: agent SDK reads a route_context.json then verifies it against source code.

Usage:
  python demo.py \\
    --context sample_route_context.json \\
    --repo-path "/absolute/path/to/spring-crud-route-entity-detection"
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
from claude_agent_sdk.types import StreamEvent


def format_tool_input(name: str, input_data: dict) -> str:
    """One-line preview of a tool call's input."""
    if not isinstance(input_data, dict):
        return str(input_data)
    if name == "Grep":
        parts = [f"pattern={input_data.get('pattern', '')!r}"]
        if input_data.get("path"):
            parts.append(f"path={input_data['path']!r}")
        if input_data.get("glob"):
            parts.append(f"glob={input_data['glob']!r}")
        return " ".join(parts)
    if name == "Glob":
        s = f"pattern={input_data.get('pattern', '')!r}"
        if input_data.get("path"):
            s += f" path={input_data['path']!r}"
        return s
    if name == "Read":
        path = input_data.get("file_path", "")
        s = f"file={path!r}"
        if input_data.get("offset") is not None or input_data.get("limit") is not None:
            o = input_data.get("offset") or 0
            l = input_data.get("limit") or 0
            s += f" lines={o}:{o + l}"
        return s
    raw = json.dumps(input_data, separators=(",", ":"))
    return raw if len(raw) <= 120 else raw[:117] + "..."


async def main(context_path: str, repo_path: str) -> None:
    route_context = json.loads(Path(context_path).read_text())

    route_id = route_context.get("route_id", "(unknown route)")

    prompt = f"""
Here is a route_context JSON produced by our ingestion pipeline:

{json.dumps(route_context, indent=2)}

The source code is in the current directory.

Please verify if this route_context is accurate:
1. Identify the HTTP route from the JSON (look for route_id, path, endpoint, or similar fields)
2. Find the matching controller/handler in source (use Grep)
3. Read the controller and trace any call_chain or methods listed
4. Check if the entities and field accesses listed in the JSON match what the source code actually does

Report:
- What is CORRECT in the route_context
- What is MISSING (fields or methods not captured)
- What is WRONG (things in route_context that don't match source)
"""

    print(f"Verifying : {route_id}")
    print(f"Repo      : {repo_path}")
    print("=" * 60)

    # streaming state
    in_tool = False
    tool_calls = 0

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Glob", "Grep"],
            permission_mode="dontAsk",
            cwd=repo_path,
            include_partial_messages=True,  # enable streaming
        ),
    ):
        if isinstance(message, StreamEvent):
            event = message.event
            event_type = event.get("type")

            if event_type == "content_block_start":
                block = event.get("content_block", {})
                if block.get("type") == "tool_use":
                    in_tool = True  # suppress text streaming until tool stops

            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta" and not in_tool:
                    sys.stdout.write(delta.get("text", ""))
                    sys.stdout.flush()

            elif event_type == "content_block_stop":
                in_tool = False

        elif isinstance(message, AssistantMessage):
            # Show tool calls with full input from the complete message
            for block in message.content:
                if hasattr(block, "name") and hasattr(block, "input"):
                    tool_calls += 1
                    preview = format_tool_input(block.name, block.input or {})
                    print(f"\n[{block.name}] {preview}", flush=True)

        elif isinstance(message, ResultMessage):
            print(f"\n{'=' * 60}")
            print(f"Tool calls : {tool_calls}")
            print(f"Turns      : {message.num_turns}")
            print(f"Cost       : ${message.total_cost_usd or 0:.5f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    #  parser.add_argument("--context", default="sample_route_context.json")
    parser.add_argument("--context", default="test_specific_route.json")
    parser.add_argument("--repo-path", required=True)
    args = parser.parse_args()

    asyncio.run(main(args.context, args.repo_path))
