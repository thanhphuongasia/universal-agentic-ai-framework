"""
Stock Advisory — UAAF Pattern Demo
=====================================
Demonstrates 5 patterns từ uaaf-framework-spec.md, mỗi case độc lập.

Run (fake LLM, không cần API key):
    python -m examples.stock_advisory.main

Run (OpenAI real):
    OPENAI_API_KEY=sk-... python -m examples.stock_advisory.main

Run single case:
    python -m examples.stock_advisory.main --case 1   # Market snapshot
    python -m examples.stock_advisory.main --case 2   # ReAct loop
    python -m examples.stock_advisory.main --case 3   # GroundTruth verifier
    python -m examples.stock_advisory.main --case 4   # VerifierPipeline
    python -m examples.stock_advisory.main --case 5   # Compliance audit trail

PATTERNS ILLUSTRATED:
  Case 1 — DirectQuery + SchemaVerifier:
      Simplest use: 1 LLM call, verify JSON schema of output.
      Key classes: LLMAgent._execute, SchemaVerifier

  Case 2 — ReAct Loop (Thought→Action→Observation):
      Agent calls tools iteratively before answering.
      Key classes: LLMAgent.react_loop, ToolRegistry, PrintCallbacks

  Case 3 — GroundTruth Verifier (3 modes):
      Exact / substring / word_overlap checks on LLM output.
      Key classes: GroundTruthVerifier, standalone verify() call

  Case 4 — VerifierPipeline (ALL_PASS / ANY_PASS / THRESHOLD):
      Chain multiple verifiers with configurable pass logic.
      Key classes: VerifierPipeline, PipelineMode

  Case 5 — Compliance Audit Trail (HIGH trust domain):
      AuditLogger + CostTracker + correlation_id = full observability.
      Key classes: AuditLogger, CostTracker, ExecutionContext
"""

from __future__ import annotations

import argparse
import asyncio
import json

from examples._utils import silent_tracer
from examples.stock_advisory.agent import StockAdvisoryAgent, build_provider
from examples.stock_advisory.models import MARKET_DATA, build_demo_portfolio
from examples.stock_advisory.tools import build_stock_registry
from examples.stock_advisory.verifiers import (
    build_bearish_signal_verifier,
    build_consensus_pipeline,
    build_permissive_analysis_pipeline,
    build_risk_disclosure_verifier,
    build_strict_trade_pipeline,
    build_ticker_mention_verifier,
    build_trade_schema_verifier,
)
from uaaf.execution.agent import Task as AgentTask
from uaaf.execution.llm_agent import PrintCallbacks
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.runtime.context import ContextScope, ExecutionContext

# ── Helpers ────────────────────────────────────────────────────────────────

def sep(title: str = "") -> None:
    w = 68
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * (w - pad - len(title) - 2)}")
    else:
        print(f"\n{'─' * w}")


def build_agent(tool_registry=None) -> StockAdvisoryAgent:
    """Construct a fully wired StockAdvisoryAgent with all cross-cutting."""
    return StockAdvisoryAgent(
        agent_id="stock-advisor",
        llm=build_provider(),
        tool_registry=tool_registry,
        callbacks=PrintCallbacks(),
        cost_tracker=CostTracker(CostPolicy(
            per_user_per_day_usd=2.0,
            per_domain_per_month_usd=50.0,
            global_per_hour_usd=10.0,
        )),
        tracer=silent_tracer(),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy(rps=2.0, burst=20)),
    )


def make_ctx(case_id: str) -> tuple[ContextScope, ExecutionContext]:
    scope = ContextScope(user_id="demo-investor", session_id="stock-session-1", domain="stock_advisory")
    ctx = ExecutionContext(scope=scope, correlation_id=f"stock-{case_id}")
    return scope, ctx


# ── Case 1: Market Snapshot + SchemaVerifier ───────────────────────────────

async def case1_market_snapshot() -> None:
    """
    PATTERN: DirectQuery — 1 LLM call, no tools, verify output schema.

    WHAT TO OBSERVE:
    - Model selection: short query → CHEAP tier
    - No ReAct loop (no tools registered)
    - SchemaVerifier validates JSON keys in response
    - SchemaVerifier in raw mode (output_must_be_json=False) checks substrings
    """
    sep("Case 1 — Direct Query + SchemaVerifier")
    print("""
  Pattern: 1 LLM call → SchemaVerifier → output
  No tools. Agent answers from memory context only.
  Verifier A: JSON schema check (output_must_be_json=True)
  Verifier B: Substring check (output_must_be_json=False)
""")

    portfolio = build_demo_portfolio()
    agent = build_agent(tool_registry=None)  # no tools — direct answer only
    scope, ctx = make_ctx("c1")

    # Ingest market data as memory context
    for ticker, stock in MARKET_DATA.items():
        await agent.assembler.write(
            observation=f"[MARKET] {ticker}: ${stock.price:.2f} ({stock.change_pct:+.2f}%) sector={stock.sector}",
            scope_key=scope.session_id,
            metadata={"type": "market", "ticker": ticker},
        )
    await agent.ingest_portfolio(portfolio)

    query = "Give me a quick market snapshot for AAPL and NVDA with risk context."
    print(f"  Query: {query}\n")

    result = await agent.execute(
        AgentTask(
            task_id="c1-snapshot",
            payload={"query": query, "prompt": "market_snapshot", "scope_key": scope.session_id},
        ),
        ctx,
    )
    print(f"\n  Response:\n{result.output}\n")

    # --- Verifier A: raw substring check ---
    sep("Verifier A — SchemaVerifier (raw substring mode)")
    print("  Checks: does response contain 'AAPL' and 'risk'?\n")
    verifier_a = build_trade_schema_verifier()
    # Override to raw mode for demonstration
    from uaaf.cognitive.verifiers import SchemaVerifier
    verifier_raw = SchemaVerifier(required_keys=["AAPL", "risk"], output_must_be_json=False)
    vr_a = await verifier_raw.verify(result.output, ctx)
    print(f"  {'✅ PASS' if vr_a.passed else '❌ FAIL'}  confidence={vr_a.confidence:.2f}")
    if not vr_a.passed:
        print(f"  Feedback: {vr_a.feedback}")

    # --- Verifier B: JSON schema check ---
    sep("Verifier B — SchemaVerifier (JSON mode)")
    print("  Checks: is output valid JSON with keys [ticker, action, confidence, risk_level]?\n")
    verifier_b = build_trade_schema_verifier()
    vr_b = await verifier_b.verify(result.output, ctx)
    print(f"  {'✅ PASS' if vr_b.passed else '❌ FAIL'}  confidence={vr_b.confidence:.2f}")
    if not vr_b.passed:
        print(f"  Feedback: {vr_b.feedback}")
    print(f"\n  💰 ${result.cost.usd:.6f}")


# ── Case 2: ReAct Loop ─────────────────────────────────────────────────────

async def case2_react_loop() -> None:
    """
    PATTERN: ReAct Loop — Thought→Action→Observation until DONE.

    WHAT TO OBSERVE:
    - PrintCallbacks: 💭 Thought / 🔧 Action / 📋 Observation printed live
    - Agent calls: get_quote → get_signals → portfolio_summary → answer
    - Multiple tool rounds before final response
    - Model: STANDARD tier (medium-length query)
    """
    sep("Case 2 — ReAct Loop (Thought→Action→Observation)")
    print("""
  Pattern: LLMAgent._react_loop() — tools called iteratively
  Tools: get_quote, get_signals, portfolio_summary
  PrintCallbacks shows each Thought/Action/Observation step live.
  Agent stops when it has enough info to answer (or max_rounds exceeded).
""")

    portfolio = build_demo_portfolio()
    tool_registry = build_stock_registry(portfolio)
    agent = build_agent(tool_registry=tool_registry)
    scope, ctx = make_ctx("c2")
    await agent.ingest_portfolio(portfolio)

    query = "Analyze my AAPL position — current price, signals, and portfolio allocation. Is it time to trim?"
    print(f"  Query: {query}\n")

    result = await agent.execute(
        AgentTask(
            task_id="c2-react",
            payload={"query": query, "prompt": "portfolio_analysis", "scope_key": scope.session_id},
        ),
        ctx,
    )
    print(f"\n  Final Response:\n{result.output}")
    print(f"\n  💰 ${result.cost.usd:.6f} | in={result.cost.input_tokens} out={result.cost.output_tokens}")


# ── Case 3: GroundTruth Verifier (3 modes) ────────────────────────────────

async def case3_ground_truth_verifier() -> None:
    """
    PATTERN: GroundTruthVerifier — 3 modes (exact / substring / word_overlap).

    WHAT TO OBSERVE:
    - exact:        strict equality — rarely used for LLM output
    - substring:    reference must appear verbatim — good for ticker, compliance phrase
    - word_overlap: fuzzy match — good for concept coverage (bearish, risk, decline)
    """
    sep("Case 3 — GroundTruthVerifier (3 Modes)")
    print("""
  Pattern: standalone verifier.verify(output, ctx)
  Three modes tested against realistic LLM output samples.
  No agent needed — verifiers are pure functions.
""")

    scope, ctx = make_ctx("c3")

    # Sample outputs to verify (simulating LLM responses)
    response_nvda = (
        "NVDA shows strong bullish signals: MACD divergence (0.88) and AI sentiment tailwind (0.81). "
        "However, RSI at 74 is approaching overbought. HIGH risk — position at 16.2% of portfolio. "
        "Recommend BUY with max 10% allocation. Monitor RSI closely."
    )
    response_xom = (
        "XOM is in a bearish downtrend: death cross formed (50-day below 200-day MA). "
        "Sell signals dominate. Oil demand outlook cautious. Risk of further decline. "
        "SELL recommendation. Caution: energy sector headwinds from EV transition."
    )
    response_generic = (
        "The market looks interesting today. Prices are moving. Some things are going up."
    )

    # --- Mode A: substring ---
    sep("Mode A — Substring (reference must appear verbatim)")
    print("  Use case: LLM must mention specific ticker it was asked about.")
    print("  Verifier: reference='NVDA', mode='substring'\n")

    v_ticker = build_ticker_mention_verifier("NVDA")
    for label, text in [("NVDA response", response_nvda), ("Generic response", response_generic)]:
        vr = await v_ticker.verify(text, ctx)
        icon = "✅" if vr.passed else "❌"
        print(f"  {icon} [{label}]  passed={vr.passed}  confidence={vr.confidence:.2f}")
        if not vr.passed:
            print(f"      Feedback: {vr.feedback}")

    sep("  Compliance phrase check")
    print("  Use case: advisory output must always mention 'risk' (compliance requirement).\n")
    v_risk = build_risk_disclosure_verifier()
    for label, text in [("NVDA response (has risk)", response_nvda), ("Generic (no risk)", response_generic)]:
        vr = await v_risk.verify(text, ctx)
        icon = "✅" if vr.passed else "❌"
        print(f"  {icon} [{label}]  passed={vr.passed}  confidence={vr.confidence:.2f}")

    # --- Mode B: word_overlap ---
    sep("Mode B — Word Overlap (fuzzy concept match)")
    print("  Use case: bearish stock → response should discuss bearish concepts.")
    print("  Verifier: reference='sell bearish decline downtrend caution risk', threshold=0.08\n")

    v_bearish = build_bearish_signal_verifier()
    for label, text in [("XOM bearish response", response_xom), ("NVDA bullish response", response_nvda)]:
        vr = await v_bearish.verify(text, ctx)
        icon = "✅" if vr.passed else "❌"
        print(f"  {icon} [{label}]  passed={vr.passed}  confidence={vr.confidence:.2f}")
        if not vr.passed:
            print(f"      Feedback: {vr.feedback}")

    # --- Mode C: exact ---
    sep("Mode C — Exact (strict equality)")
    print("  Use case: deterministic output (e.g. ticker confirmation).")
    print("  Rarely used for LLM output but available for deterministic agents.\n")

    from uaaf.cognitive.verifiers import GroundTruthVerifier
    v_exact = GroundTruthVerifier(reference="NVDA", mode="exact")
    for label, text in [("Exact 'NVDA'", "NVDA"), ("Full sentence", response_nvda)]:
        vr = await v_exact.verify(text, ctx)
        icon = "✅" if vr.passed else "❌"
        print(f"  {icon} [{label}]  passed={vr.passed}  confidence={vr.confidence:.2f}")


# ── Case 4: VerifierPipeline ───────────────────────────────────────────────

async def case4_verifier_pipeline() -> None:
    """
    PATTERN: VerifierPipeline — 3 modes (ALL_PASS / ANY_PASS / THRESHOLD).

    WHAT TO OBSERVE:
    - ALL_PASS: strictest — both schema AND ticker must pass (HIGH trust)
    - ANY_PASS: permissive — schema OR ticker passing is enough
    - THRESHOLD: n-of-m — 2-of-3 verifiers must pass (consensus)
    """
    sep("Case 4 — VerifierPipeline (ALL_PASS / ANY_PASS / THRESHOLD)")
    print("""
  Pattern: VerifierPipeline chains multiple verifiers.
  Same output → different strictness → different pass/fail outcomes.
  All pipelines are built in verifiers.py — test them here case by case.
""")

    scope, ctx = make_ctx("c4")

    # Three test outputs with different quality levels
    output_perfect = json.dumps({
        "ticker": "NVDA",
        "action": "BUY",
        "confidence": 0.72,
        "rationale": "Strong signals. risk of overbought RSI — size carefully.",
        "risk_level": "HIGH",
        "max_position_pct": 10.0,
    })
    output_json_wrong_ticker = json.dumps({
        "ticker": "AAPL",     # wrong ticker (asked about NVDA)
        "action": "BUY",
        "confidence": 0.72,
        "rationale": "Good signals. risk considered.",
        "risk_level": "MEDIUM",
        "max_position_pct": 8.0,
    })
    output_freetext_good = (
        "NVDA looks bullish. Strong MACD. risk of overbought RSI at 74. "
        "Recommend BUY up to 10% of portfolio. Monitor closely."
    )

    test_cases = [
        ("Perfect JSON — correct ticker + risk disclosure",     output_perfect),
        ("JSON — wrong ticker (AAPL instead of NVDA)",          output_json_wrong_ticker),
        ("Free text — mentions NVDA and risk, not JSON",        output_freetext_good),
    ]

    for pipeline_label, pipeline_factory in [
        ("ALL_PASS  (strictest — schema AND ticker)",  lambda: build_strict_trade_pipeline("NVDA")),
        ("ANY_PASS  (permissive — schema OR ticker)",  lambda: build_permissive_analysis_pipeline("NVDA")),
        ("THRESHOLD (2-of-3 — schema + ticker + risk)",lambda: build_consensus_pipeline("NVDA")),
    ]:
        sep(f"Pipeline: {pipeline_label}")
        pipeline = pipeline_factory()
        for label, output in test_cases:
            vr = await pipeline.verify(output, ctx)
            icon = "✅" if vr.passed else "❌"
            print(f"  {icon} {label}")
            print(f"      passed={vr.passed}  confidence={vr.confidence:.2f}", end="")
            if not vr.passed and vr.feedback:
                print(f"  | {vr.feedback[:80]}", end="")
            print()


# ── Case 5: Compliance Audit Trail ────────────────────────────────────────

async def case5_compliance_audit() -> None:
    """
    PATTERN: AuditLogger + CostTracker + correlation_id = full observability.

    WHAT TO OBSERVE:
    - correlation_id threads through entire execution context
    - AuditLogger.log_start / log_complete / log_error called by BaseAgent.execute()
    - CostTracker enforces per-domain budget
    - place_order_dry_run shows the high-trust gate pattern
    - All of this is AUTOMATIC — no domain code needed, BaseAgent handles it
    """
    sep("Case 5 — Compliance Audit Trail (HIGH Trust Domain)")
    print("""
  Pattern: BaseAgent.execute() wraps _execute() with full observability.
  AuditLogger + CostTracker + correlation_id = automatic.
  Domain code (StockAdvisoryAgent._execute) adds zero observability code.

  This is the KEY advantage of BaseAgent template method:
    - Stock trading audit log (7y retention) → AuditLogger
    - Cost enforcement → CostTracker budget cap
    - Distributed tracing → correlation_id in ExecutionContext
    - All injected at construction, not scattered in domain code
""")

    portfolio = build_demo_portfolio()
    tool_registry = build_stock_registry(portfolio)

    audit = AuditLogger()
    cost_tracker = CostTracker(CostPolicy(
        per_user_per_day_usd=5.0,
        per_domain_per_month_usd=100.0,
        global_per_hour_usd=20.0,
    ))

    agent = StockAdvisoryAgent(
        agent_id="stock-advisor-compliance",
        llm=build_provider(),
        tool_registry=tool_registry,
        callbacks=PrintCallbacks(),
        cost_tracker=cost_tracker,
        tracer=silent_tracer(),
        audit_logger=audit,
        rate_limiter=RateLimiter(RatePolicy(rps=2.0, burst=20)),
    )

    # correlation_id is the trace anchor — appears in every audit log entry
    scope = ContextScope(user_id="investor-007", session_id="compliance-session", domain="stock_advisory")
    ctx = ExecutionContext(scope=scope, correlation_id="TRADE-2026-0508-001")

    print(f"  correlation_id : {ctx.correlation_id}")
    print(f"  user_id        : {scope.user_id}")
    print(f"  domain         : {scope.domain}")
    print(f"  domain budget  : ${cost_tracker.policy.per_domain_per_month_usd:.2f}/month")

    await agent.ingest_portfolio(portfolio)

    # 1. Compliance report query (HIGH trust — uses compliance_report prompt)
    sep("Step 1 — Compliance Report Generation")
    query = "Generate a compliance report for a proposed NVDA BUY recommendation."
    print(f"  Query: {query}\n")

    result = await agent.execute(
        AgentTask(
            task_id="compliance-001",
            payload={"query": query, "prompt": "compliance_report", "scope_key": scope.session_id},
        ),
        ctx,
    )
    print(f"\n  Report:\n{result.output}")
    print(f"\n  💰 Cost: ${result.cost.usd:.6f}  |  model: {result.cost.model}")

    # 2. Verify compliance output with strict pipeline
    sep("Step 2 — Verify Compliance Output (Strict Pipeline)")
    print("  NOTE: compliance_report prompt returns markdown text, NOT JSON.")
    print("  ALL_PASS pipeline uses SchemaVerifier(json=True) → expected FAIL.")
    print("  In production: use SchemaVerifier(json=False) or GroundTruthVerifier for text reports.\n")
    pipeline = build_strict_trade_pipeline("NVDA")
    vr = await pipeline.verify(result.output, ctx)
    icon = "✅" if vr.passed else "❌"
    print(f"  Pipeline [ALL_PASS]: {icon}  confidence={vr.confidence:.2f}")
    if not vr.passed:
        print(f"  Feedback: {vr.feedback}")

    # Bonus: raw substring pipeline actually passes for text report
    text_pipeline = build_permissive_analysis_pipeline("NVDA")
    vr2 = await text_pipeline.verify(result.output, ctx)
    icon2 = "✅" if vr2.passed else "❌"
    print(f"  Pipeline [ANY_PASS]: {icon2}  confidence={vr2.confidence:.2f}  ← passes because NVDA is mentioned")

    # 3. Dry-run order (shows the HIGH-trust gate)
    sep("Step 3 — Order Dry Run (HIGH Trust Gate)")
    print("  Calling place_order_dry_run — no real trade executed.")
    print("  Production would require: SandboxManager + human approval + AuditLogger 7y.\n")

    dry_run_result = await tool_registry.run({
        "id": "order-001",
        "function": {"name": "place_order_dry_run", "arguments": {"ticker": "NVDA", "action": "BUY", "shares": 10}},
    })
    dry_run_data = json.loads(dry_run_result)
    print("  Order result:")
    print(f"    status          : {dry_run_data['status']}")
    print(f"    ticker          : {dry_run_data['ticker']}")
    print(f"    action/shares   : {dry_run_data['action']} {dry_run_data['shares']} shares")
    print(f"    total_value     : ${dry_run_data['total_value']:,.2f}")
    print(f"    compliance_note : {dry_run_data['compliance_note']}")

    # 4. Cost summary
    sep("Step 4 — Cost Summary")
    print(f"  Total cost this session: ${result.cost.usd:.6f}")
    print(f"  Tokens: {result.cost.input_tokens} in + {result.cost.output_tokens} out")
    print(f"  Model: {result.cost.model} (provider: {result.cost.provider})")
    print("\n  All costs tracked automatically by BaseAgent.execute() → CostTracker.record()")
    print("  Audit events logged automatically by BaseAgent.execute() → AuditLogger.log_*")


# ── Main dispatcher ────────────────────────────────────────────────────────

CASES = {
    1: ("Market Snapshot + SchemaVerifier",           case1_market_snapshot),
    2: ("ReAct Loop (Thought→Action→Observation)",     case2_react_loop),
    3: ("GroundTruth Verifier (3 modes)",              case3_ground_truth_verifier),
    4: ("VerifierPipeline (ALL_PASS/ANY_PASS/THRESHOLD)", case4_verifier_pipeline),
    5: ("Compliance Audit Trail (HIGH trust domain)",  case5_compliance_audit),
}


async def main(run_case: int | None = None) -> None:
    sep("UAAF Stock Advisory — Pattern Demo")
    print("""
  Demonstrates UAAF patterns từ uaaf-framework-spec.md:
    Case 1 — DirectQuery + SchemaVerifier
    Case 2 — ReAct Loop (tools: get_quote, get_signals, portfolio_summary)
    Case 3 — GroundTruthVerifier (exact / substring / word_overlap)
    Case 4 — VerifierPipeline (ALL_PASS / ANY_PASS / THRESHOLD)
    Case 5 — Compliance Audit Trail (AuditLogger + CostTracker)
""")

    cases_to_run = [run_case] if run_case is not None else list(CASES)

    for case_num in cases_to_run:
        if case_num not in CASES:
            print(f"  Unknown case: {case_num}. Available: {list(CASES)}")
            continue
        label, fn = CASES[case_num]
        print(f"\n  ▶  Running Case {case_num}: {label}")
        await fn()

    sep("Done")
    print(f"  Ran {len(cases_to_run)} case(s).")
    print("  Source: examples/stock_advisory/")
    print("    models.py   — domain models (Stock, Signal, Portfolio, Position)")
    print("    tools.py    — tool handlers (get_quote, get_signals, portfolio_summary, check_risk, place_order_dry_run)")
    print("    verifiers.py — verifier factories (SchemaVerifier, GroundTruthVerifier, VerifierPipeline)")
    print("    agent.py    — StockAdvisoryAgent (extends LLMAgent)")
    print("    main.py     — this file: 5 self-contained learning cases\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Advisory UAAF Pattern Demo")
    parser.add_argument("--case", type=int, choices=list(CASES), metavar="N",
                        help="Run a single case (1-5). Omit to run all.")
    args = parser.parse_args()
    asyncio.run(main(run_case=args.case))
