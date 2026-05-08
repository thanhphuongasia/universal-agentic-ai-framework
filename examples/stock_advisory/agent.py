"""
Stock Advisory Agent — extends LLMAgent
==========================================
Pattern illustrated: BaseAgent template method + LLMAgent react_loop.

Compared to TodoAnalysisAgent:
  - Same LLMAgent base → same cross-cutting (trace/rate-limit/audit/cost)
  - Adds: verifier injection per query type
  - Adds: compliance summary in output
  - Uses: ReAct loop (get_quote → get_signals → check_risk → answer)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from examples.stock_advisory.models import Portfolio
from uaaf.execution.agent import AgentResult, Task
from uaaf.execution.llm_agent import LLMAgent
from uaaf.execution.tool_registry import ToolRegistry
from uaaf.intent.models import ModelTier
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.memory.backbone import MemoryBackbone
from uaaf.observability._pricing import calculate_usd
from uaaf.observability.cost import Cost
from uaaf.prompts.registry import PromptRegistry
from uaaf.providers.llm import CompletionRequest, ILLMProvider, TokenUsage
from uaaf.runtime.context import ExecutionContext

_PROMPTS_ROOT = Path(__file__).parent / "prompts"
_registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)

_TIER_TO_MODEL: dict[ModelTier, str] = {
    ModelTier.CHEAP:    "gpt-4o-mini",
    ModelTier.STANDARD: "gpt-4o-mini",
    ModelTier.POWERFUL: "gpt-4o",
}


def build_provider() -> ILLMProvider:
    """Return OpenAIProvider if OPENAI_API_KEY is set, FakeLLMProvider otherwise."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from uaaf.providers.adapters.openai import OpenAIProvider
        print("  🔑 Using OpenAIProvider (OPENAI_API_KEY found)")
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]

    from uaaf._testing.fakes import FakeLLMProvider
    from uaaf.providers.llm import Response

    def _r(t: str) -> Response:
        return Response(content=t, model="fake", usage=TokenUsage(120, 80), finish_reason="stop")

    print("  ⚠️  OPENAI_API_KEY not set — using FakeLLMProvider (demo mode)")
    return FakeLLMProvider(responses=[  # type: ignore[return-value]
        # Case 1 — market snapshot
        _r("AAPL is trading at $185.42 (+1.23%). Signals are bullish: golden cross on MA, "
           "RSI at 42 (not overbought). Risk: MEDIUM — always consider position sizing."),
        # Case 2 — portfolio analysis
        _r("Portfolio total: $108,258. Top holding: AAPL (18.7%, P&L +$2,542). "
           "XOM is the only losing position (-$440, -4.7%). Risk concentration in TECH sector (73%). "
           "Recommend rebalancing into FINANCE or ENERGY to reduce sector risk."),
        # Case 3 — trade advisory JSON (SchemaVerifier target)
        _r(json.dumps({
            "ticker": "NVDA",
            "action": "BUY",
            "confidence": 0.72,
            "rationale": "Strong MACD + AI demand cycle. RSI approaching overbought (74) — size carefully.",
            "risk_level": "HIGH",
            "max_position_pct": 10.0,
        })),
        # Case 4 — compliance report
        _r("COMPLIANCE REPORT — NVDA Advisory\n"
           "SUMMARY: Bullish signals dominate but RSI near overbought at 74.\n"
           "SIGNALS: MACD bullish divergence (0.88 strength), AI sentiment tailwind (0.81).\n"
           "RISK ASSESSMENT: HIGH — trade would be 8.1% of portfolio. risk of concentration.\n"
           "RECOMMENDATION: BUY up to 10% of portfolio. Monitor RSI. Stop-loss at $820.\n"
           "DISCLAIMER: This report is subject to 7-year regulatory retention. Not financial advice."),
        # Case 5 — dry run order
        _r("Order simulated: BUY 10 NVDA @ $875.90 = $8,759.00 (DRY RUN, not executed)."),
        # Extras for multi-round react loops
        _r("Portfolio analysis complete. NVDA position at 16.2% of portfolio — above 15% threshold. "
           "Risk level: HIGH. Recommend trimming to 10%. risk of overconcentration in tech sector."),
    ])


@dataclass
class StockAdvisoryAgent(LLMAgent):
    """
    Stock advisory agent. Extends LLMAgent for react_loop + model selection.

    Key additions vs TodoAnalysisAgent:
      - verifier: IVerifier-compatible object (optional, injected per query)
      - prompt_version: versioned prompt YAML
      - ingest_portfolio(): writes portfolio state to memory for context assembly
    """

    assembler: ContextAssembler = field(
        default_factory=lambda: ContextAssembler(MemoryBackbone())
    )
    prompt_version: str = "v1"

    async def ingest_portfolio(self, portfolio: Portfolio) -> None:
        """Ingest portfolio state into MemoryBackbone for context assembly."""
        scope_key = portfolio.owner_id
        await self.assembler.write(
            observation=portfolio.summary(),
            scope_key=scope_key,
            metadata={"type": "portfolio", "owner": portfolio.owner_id},
        )
        for p in portfolio.positions:
            await self.assembler.write(
                observation=p.summary(),
                scope_key=scope_key,
                metadata={"type": "position", "ticker": p.ticker},
            )

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        query = str(task.payload.get("query", "Analyze my portfolio"))
        prompt_name = str(task.payload.get("prompt", "portfolio_analysis"))
        scope_key = str(task.payload.get("scope_key", context.scope.session_id))
        verifier = task.payload.get("verifier")  # optional IVerifier

        # 1. Model selection via framework
        tier = self.select_model(query)
        model = _TIER_TO_MODEL[tier]
        print(f"  🧠 Model selection: {tier.value} → {model}  ({len(query.split())} words)")

        # 2. Load versioned prompt + assemble context from memory
        cfg = _registry.load("stock_advisory", self.prompt_version)
        assembled = await self.assembler.assemble(
            query=query, scope_key=scope_key, budget_tokens=3000,
        )
        print(f"  📚 Context assembled: {assembled.token_count} tokens from memory")

        # 3. Build CompletionRequest
        base_request = _registry.build_request(
            cfg, prompt_name,
            include_tools=bool(self.tool_registry and self.tool_registry._handlers),
            context=assembled.text,
            query=query,
        )
        request = CompletionRequest(
            messages=base_request.messages,
            model=model,
            temperature=base_request.temperature,
            max_tokens=base_request.max_tokens,
            tools=base_request.tools,
        )

        # 4. ReAct loop — tools called iteratively until LLM has enough info
        response, usage = await self.react_loop(request, max_rounds=4, domain="stock_advisory")

        # 5. Optional: run verifier on the final response
        if verifier is not None:
            vr = await verifier.verify(response, context)
            status = "✅ PASS" if vr.passed else "❌ FAIL"
            print(f"  🔍 Verifier [{getattr(verifier, 'verifier_id', '?')}]: {status}  "
                  f"confidence={vr.confidence:.2f}",
                  end="")
            if not vr.passed and vr.feedback:
                print(f"  → {vr.feedback}", end="")
            print()

        # 6. Token budget display
        summary = self.budget_summary(usage, model)
        print(
            f"\n  📊 Token budget: {summary.input_tokens:,} in + {summary.output_tokens:,} out"
            f" = {summary.total_tokens:,} total  |  window: {summary.window_size // 1_000}K"
            f"  |  {summary.pct_used:.1f}% used"
        )

        usd = calculate_usd(cfg.model, usage.input_tokens, usage.output_tokens)
        return AgentResult(
            task_id=task.task_id,
            output=response,
            cost=Cost(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                usd=usd,
                provider="openai",
                model=model,
            ),
        )
