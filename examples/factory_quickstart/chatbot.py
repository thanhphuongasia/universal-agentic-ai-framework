"""Minimal chatbot — Factory `Agent()` in ~15 lines.

Run::

    OPENAI_API_KEY=sk-... python -m examples.factory_quickstart.chatbot
"""

from __future__ import annotations

import anyio

from ryuu import Agent


async def main() -> None:
    agent = Agent(
        model="gpt-4o-mini",
        instructions="You are a helpful Python tutor. Keep answers under 80 words.",
    )

    result = await agent.run("What's the difference between a list and a tuple?")
    print(result.output)
    print(f"\n[cost: {result.cost.input_tokens} in + {result.cost.output_tokens} out tokens]")


if __name__ == "__main__":
    anyio.run(main)
