"""Production-grade Agent — all cross-cutting toggles enabled.

Demonstrates:
  - Per-call limits  (max_tokens, temperature)
  - Per-run limit    (max_iterations for ReAct loop)
  - Per-session cap  (budget_usd — raises BudgetExceededError on overrun)
  - Rate limiting    (rate_limit_rps per scope)
  - Audit trail      (JSONL hash chain to ./ryuu_audit.jsonl)
  - Tracing          (OpenTelemetry spans)
  - Verbose console  (stdout debug output, CrewAI-style)
  - Scope kwargs     (user_id, session_id, domain → ContextScope)

Run::

    OPENAI_API_KEY=sk-... python -m examples.factory_quickstart.production
"""

from __future__ import annotations

import anyio

from ryuu import Agent


def lookup_customer(user_id: str) -> dict:
    """Look up customer profile by user_id."""
    return {"user_id": user_id, "plan": "premium", "joined": "2024-03-15"}


def check_order(order_id: str) -> dict:
    """Get order shipping status by order_id."""
    return {"order_id": order_id, "status": "shipped", "eta_days": 2}


async def main() -> None:
    agent = Agent(
        model="gpt-4o-mini",
        instructions=(
            "You are a customer service agent. "
            "Use tools to look up customer + order info. "
            "Be concise — max 100 words per response."
        ),
        tools=[lookup_customer, check_order],

        # Per-call limits
        max_tokens=512,
        temperature=0.2,

        # Per-run limit
        max_iterations=3,

        # Per-session cap (USD primary)
        budget_usd=0.50,

        # Cross-cutting
        rate_limit_rps=10,
        audit=True,
        trace=True,
        verbose=True,         # console output for debugging
    )

    result = await agent.run(
        "Check the status of order ORD-789 for customer u-42",
        user_id="u-42",
        session_id="sess-001",
        domain="support",
    )
    print("\n" + "=" * 60)
    print("FINAL OUTPUT:")
    print(result.output)
    print(f"\nCost: {result.cost.input_tokens} in + {result.cost.output_tokens} out")
    print("Audit log: ./ryuu_audit.jsonl")


if __name__ == "__main__":
    anyio.run(main)
