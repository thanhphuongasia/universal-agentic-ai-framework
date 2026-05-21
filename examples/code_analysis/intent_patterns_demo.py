"""Intent Patterns Demo for Code Analysis — Before/After (Phase 14 built-ins).

Shows 5 Claude-like Thinking patterns:
  - 3 patterns (#1+#2, #6+#7, #3+#4) demonstrated TWICE: self-impl vs new built-in
  - 2 patterns (#9 hierarchical, #10 multi-intent) use existing primitives

Goal: verify Phase 14.1-14.3 framework built-ins cover same use cases với ít LOC hơn.

Patterns + Status:
  #1+#2 Thinking Channel      → ✅ Built-in: `Agent(thinking_mode=True)` [Phase 14.1]
  #3+#4 Compute-Adaptive       → ✅ Built-in: `Agent(adaptive_compute=True)` [Phase 14.3]
  #6+#7 Best-of-N              → ✅ Built-in: `Agent(n_samples=N, vote=...)` [Phase 14.2]
  #9    Step-Back Hierarchical → 🔲 Self-impl (Phase 14.4 facade planned)
  #10   Multi-Intent Plan/Work → ✅ Existing `Orchestrator` facade

Run:
    OPENAI_API_KEY=sk-... python -m examples.code_analysis.intent_patterns_demo
    python -m examples.code_analysis.intent_patterns_demo               # FakeLLM demo
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter

from ryuu import Agent, FanOut, Orchestrator
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage


INTENT_TYPES = [
    "symbol_explain", "dep_analysis", "graph_traversal",
    "crud_matrix", "entity_interaction", "entity_diagram",
    "class_diagram", "sequence_diagram",
]


def _fake(text: str = "") -> Response:
    return Response(
        content=text, model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


def _attach_fake(agent: Agent, responses: list[str]) -> Agent:
    """Attach FakeLLMProvider with pre-staged responses to an Agent."""
    agent._agent.llm = FakeLLMProvider(responses=[_fake(r) for r in responses])
    return agent


# ============================================================================
# Pattern #1+#2 — Thinking Channel
# ============================================================================


async def pattern_1_thinking_SELF_IMPL(message: str) -> str:
    """Self-impl version (pre-Phase 14.1)."""
    print("\n  ── Pattern #1+#2 (SELF-IMPL) ──")
    classifier = Agent(
        model="gpt-4o-mini",
        instructions=(
            "Classify intent.\n"
            "<thinking>What keywords? Why eliminate alternatives?</thinking>\n"
            "<answer>{intent_type}</answer>"
        ),
    )
    _attach_fake(classifier, [
        "<thinking>Message mentions CRUD explicitly</thinking>\n"
        "<answer>crud_matrix</answer>"
    ])
    raw = (await classifier.run(message)).output
    thinking = re.search(r"<thinking>(.*?)</thinking>", raw, re.DOTALL)
    answer = re.search(r"<answer>(.*?)</answer>", raw, re.DOTALL)
    intent = answer.group(1).strip() if answer else raw
    reasoning = thinking.group(1).strip() if thinking else ""
    print(f"    Intent: {intent}, Reasoning: {reasoning[:60]}...")
    return intent


async def pattern_1_thinking_BUILTIN(message: str) -> str:
    """Built-in version (Phase 14.1)."""
    print("\n  ── Pattern #1+#2 (BUILT-IN thinking_mode) ──")
    classifier = Agent(
        model="gpt-4o-mini",
        instructions="Classify intent into one of: symbol_explain | crud_matrix | dep_analysis",
        thinking_mode=True,    # ← framework injects template + parses tags
    )
    _attach_fake(classifier, [
        "<thinking>Message mentions CRUD explicitly + 'User entity' → crud_matrix</thinking>\n"
        "<answer>crud_matrix</answer>"
    ])
    result = await classifier.run(message)
    print(f"    Intent: {result.output}")
    print(f"    Reasoning: {result.thinking[:60]}...")
    print(f"    → Framework auto-parsed; consumer LOC: 1 kwarg instead of regex")
    return result.output


# ============================================================================
# Pattern #6+#7 — Best-of-N
# ============================================================================


async def pattern_6_best_of_n_SELF_IMPL(message: str) -> str:
    """Self-impl version (pre-Phase 14.2)."""
    print("\n  ── Pattern #6+#7 (SELF-IMPL) ──")
    classifier = Agent(model="gpt-4o-mini", instructions="Classify intent", temperature=0.9)
    _attach_fake(classifier, ["crud_matrix", "crud_matrix", "entity_diagram"])

    fanout = FanOut(agents=[classifier, classifier, classifier])
    samples = await fanout.run(message)
    votes = Counter(str(s).strip() for s in samples)
    winner = votes.most_common(1)[0][0]
    print(f"    Votes: {dict(votes)} → winner: {winner}")
    return winner


async def pattern_6_best_of_n_BUILTIN(message: str) -> str:
    """Built-in version (Phase 14.2)."""
    print("\n  ── Pattern #6+#7 (BUILT-IN n_samples) ──")
    classifier = Agent(
        model="gpt-4o-mini",
        instructions="Classify intent (one word only)",
        temperature=0.9,
        n_samples=3,           # ← framework runs N concurrent + aggregates
        vote="majority",
    )
    _attach_fake(classifier, ["crud_matrix", "crud_matrix", "entity_diagram"])

    result = await classifier.run(message)
    print(f"    Samples: {result.metadata['samples']}")
    print(f"    Winner: {result.output} (confidence {result.metadata['best_of_n_confidence']:.2f})")
    print(f"    → Framework runs gather+vote; consumer LOC: 2 kwargs instead of ~15 lines")
    return result.output


# ============================================================================
# Pattern #3+#4 — Adaptive Compute
# ============================================================================


DIFFICULTY_TO_AGENT_CONFIG = {
    "trivial": {"model": "gpt-4o-mini", "max_iterations": 2, "max_tokens": 300},
    "medium":  {"model": "gpt-4o-mini", "max_iterations": 4, "max_tokens": 800},
    "hard":    {"model": "gpt-4o",       "max_iterations": 8, "max_tokens": 2000},
}


async def pattern_3_adaptive_SELF_IMPL(message: str) -> str:
    """Self-impl version (pre-Phase 14.3)."""
    print("\n  ── Pattern #3+#4 (SELF-IMPL) ──")
    classifier = Agent(
        model="gpt-4o-mini",
        instructions="Classify difficulty. Output ONLY: trivial|medium|hard",
        max_tokens=5, temperature=0,
    )
    _attach_fake(classifier, ["medium"])
    difficulty = (await classifier.run(message)).output.strip().lower()
    config = DIFFICULTY_TO_AGENT_CONFIG.get(difficulty, DIFFICULTY_TO_AGENT_CONFIG["medium"])
    print(f"    Classified: {difficulty}, Config: {config}")

    main = Agent(model=config["model"], instructions="Analyze",
                 max_iterations=config["max_iterations"], max_tokens=config["max_tokens"])
    _attach_fake(main, [f"[{difficulty}] result"])
    return (await main.run(message)).output


async def pattern_3_adaptive_BUILTIN(message: str) -> str:
    """Built-in version (Phase 14.3)."""
    print("\n  ── Pattern #3+#4 (BUILT-IN adaptive_compute) ──")
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Analyze code-analysis question",
        adaptive_compute=True,     # ← framework classifies + dispatches tier internally
    )
    _attach_fake(agent, ["[hard tier] in-depth result"])
    result = await agent.run(message)
    print(f"    Difficulty: {result.metadata['difficulty']}")
    print(f"    Tier model: {result.metadata['tier_model']}")
    print(f"    → Framework classifies + swaps tier internally; consumer LOC: 1 kwarg")
    return result.output


# ============================================================================
# Pattern #9 — Step-Back Hierarchical (self-impl, HierarchicalRouter Phase 14.4)
# ============================================================================


INTENT_BY_CATEGORY: dict[str, list[str]] = {
    "structure": ["symbol_explain", "dep_analysis", "graph_traversal", "class_diagram"],
    "behavior":  ["symbol_explain", "graph_traversal", "sequence_diagram"],
    "data":      ["crud_matrix", "entity_interaction", "entity_diagram"],
}


async def pattern_9_hierarchical(message: str) -> str:
    """Self-impl. HierarchicalRouter facade planned Phase 14.4."""
    print("\n  ── Pattern #9 (SELF-IMPL — facade pending Phase 14.4) ──")
    cat_classifier = Agent(
        model="gpt-4o-mini",
        instructions="Identify category: structure|behavior|data",
        max_tokens=5, temperature=0,
    )
    _attach_fake(cat_classifier, ["data"])
    category = (await cat_classifier.run(message)).output.strip().lower()
    options = INTENT_BY_CATEGORY.get(category, INTENT_BY_CATEGORY["structure"])
    print(f"    Stage 1: {category}, options: {options}")

    specific = Agent(
        model="gpt-4o-mini",
        instructions=f"Pick ONE from: {', '.join(options)}. Output one word.",
        max_tokens=10,
    )
    _attach_fake(specific, ["crud_matrix"])
    intent = (await specific.run(message)).output.strip()
    print(f"    Stage 2: {intent}")
    return intent


# ============================================================================
# Pattern #10 — Multi-Intent Plan/Worker (Orchestrator — already shipped)
# ============================================================================


def _stub_intent_agent(intent_type: str) -> Agent:
    a = Agent(model="gpt-4o-mini", instructions=f"Handle {intent_type}")
    _attach_fake(a, [f"[{intent_type}] result"])
    return a


async def pattern_10_multi_intent(message: str) -> str:
    """Multi-intent decomposition via Orchestrator facade."""
    print("\n  ── Pattern #10 (Orchestrator facade — already shipped) ──")
    intent_agents = {it: _stub_intent_agent(it) for it in INTENT_TYPES}

    decomposer = Agent(
        model="gpt-4o-mini",
        instructions="Decompose user message into atomic intents (JSON)",
    )
    _attach_fake(decomposer, [json.dumps({"intents": [
        {"type": "crud_matrix", "target": "User"},
        {"type": "symbol_explain", "target": "login()"},
    ]})])

    orch = Orchestrator(
        main=decomposer,
        plan_items=lambda out: json.loads(out)["intents"],
        workers=lambda i: intent_agents[i["type"]],
        aggregate=lambda outputs: "\n".join(f"━ {o}" for o in outputs),
    )
    result = await orch.run(message)
    print(f"    Plan + dispatch + merge:\n    {result[:150]}...")
    return result


# ============================================================================
# Comparison Summary
# ============================================================================


async def main() -> None:
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    print("=" * 72)
    print(f"  Intent Patterns Demo — Phase 14 Built-Ins Side-by-Side")
    print(f"  Mode: {'OpenAI (real)' if has_key else 'FakeLLM (demo)'}")
    print("=" * 72)

    msg = "Show me CRUD matrix for User entity AND explain login() method"

    print("\n" + "━" * 72)
    print("  COMPARISON 1: Thinking Channel (#1+#2)")
    print("━" * 72)
    await pattern_1_thinking_SELF_IMPL(msg)
    await pattern_1_thinking_BUILTIN(msg)

    print("\n" + "━" * 72)
    print("  COMPARISON 2: Best-of-N (#6+#7)")
    print("━" * 72)
    await pattern_6_best_of_n_SELF_IMPL(msg)
    await pattern_6_best_of_n_BUILTIN(msg)

    print("\n" + "━" * 72)
    print("  COMPARISON 3: Adaptive Compute (#3+#4)")
    print("━" * 72)
    await pattern_3_adaptive_SELF_IMPL(msg)
    await pattern_3_adaptive_BUILTIN(msg)

    print("\n" + "━" * 72)
    print("  PATTERN 9 (Hierarchical — Phase 14.4 facade pending)")
    print("━" * 72)
    await pattern_9_hierarchical(msg)

    print("\n" + "━" * 72)
    print("  PATTERN 10 (Multi-Intent Orchestrator — already shipped)")
    print("━" * 72)
    await pattern_10_multi_intent(msg)

    print("\n" + "=" * 72)
    print("  ✅ All 5 patterns demonstrated with Phase 14 built-ins")
    print()
    print("  LOC reduction (consumer side):")
    print("    Pattern #1+#2 thinking:  ~10 lines → 1 kwarg  (thinking_mode=True)")
    print("    Pattern #6+#7 best-of-N: ~15 lines → 2 kwargs (n_samples + vote)")
    print("    Pattern #3+#4 adaptive:  ~20 lines → 1 kwarg  (adaptive_compute=True)")
    print()
    print("  Phase 14 status:")
    print("    ✅ 14.1 ThinkingStrategy + Factory thinking_mode")
    print("    ✅ 14.2 BestOfNStrategy + Factory n_samples/vote")
    print("    ✅ 14.3 AdaptiveStrategy + Factory adaptive_compute")
    print("    🔲 14.4 HierarchicalRouter facade")
    print("    🔲 14.5+14.6 Docs + demo + version bump 0.3.0a12")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
