"""Agent with inline tools — schema auto from docstring + type hints.

Run::

    OPENAI_API_KEY=sk-... python -m examples.factory_quickstart.tool_calling
"""

from __future__ import annotations

import anyio

from ryuu import Agent


def get_weather(city: str) -> dict:
    """Get current weather for a city. Returns temp_c and conditions."""
    # Stub — in production this calls real weather API
    return {"city": city, "temp_c": 22, "conditions": "partly cloudy"}


def search_news(query: str, limit: int = 5) -> dict:
    """Search recent news headlines matching a query."""
    return {
        "query": query,
        "headlines": [f"Headline {i} about {query}" for i in range(limit)],
    }


async def main() -> None:
    agent = Agent(
        model="gpt-4o-mini",
        instructions=(
            "You are a friendly assistant. "
            "Use tools to answer questions about weather or news."
        ),
        tools=[get_weather, search_news],
        max_iterations=3,
    )

    queries = [
        "What's the weather in Tokyo today?",
        "Show me 3 news about AI",
    ]
    for q in queries:
        print(f"\n→ {q}")
        result = await agent.run(q)
        print(result.output)


if __name__ == "__main__":
    anyio.run(main)
