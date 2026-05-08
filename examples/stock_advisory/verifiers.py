"""
Stock Advisory — Verifiers
============================
Pattern illustrated: three verifier types + VerifierPipeline composition.

LEARNING CASES:
  Case A — SchemaVerifier:
      Validates that trade recommendation output contains required JSON keys.
      Use when: LLM must return structured output (compliance, downstream parsing).

  Case B — GroundTruthVerifier (substring mode):
      Checks that response mentions a specific ticker or required phrase.
      Use when: you have a known fact the response MUST contain (e.g. risk disclosure).

  Case C — GroundTruthVerifier (word_overlap mode):
      Fuzzy match — useful when phrasing varies but key concepts must appear.
      Use when: reference answer isn't verbatim but key terms must be present.

  Case D — VerifierPipeline (ALL_PASS):
      Both schema AND content must pass. Strictest mode.
      Use for: HIGH trust domain output that feeds downstream systems.

  Case E — VerifierPipeline (ANY_PASS):
      At least one verifier must pass. Permissive.
      Use for: exploratory analysis where format OR content sufficiency is enough.

  Case F — VerifierPipeline (THRESHOLD):
      N-of-M verifiers must pass. Configurable strictness.
      Use for: multi-signal consensus (e.g. 2-of-3 verifiers agree).
"""

from __future__ import annotations

from uaaf.cognitive.verifiers import (
    GroundTruthVerifier,
    PipelineMode,
    SchemaVerifier,
    VerifierPipeline,
)


# ── Case A: Schema validation ──────────────────────────────────────────────

def build_trade_schema_verifier() -> SchemaVerifier:
    """
    Pattern: SchemaVerifier — JSON output must contain required keys.

    When the LLM is asked to return a trade recommendation JSON, this verifier
    ensures the output is parseable and contains all required fields before
    the recommendation is passed to downstream compliance systems.
    """
    return SchemaVerifier(
        required_keys=["ticker", "action", "confidence", "risk_level"],
        output_must_be_json=True,
    )


# ── Case B: Ground truth — substring ──────────────────────────────────────

def build_ticker_mention_verifier(ticker: str) -> GroundTruthVerifier:
    """
    Pattern: GroundTruthVerifier (substring) — response must mention ticker.

    When asking about AAPL, the response must reference "AAPL". This catches
    LLM hallucinations where the model answers about a different ticker.
    """
    return GroundTruthVerifier(
        reference=ticker.upper(),
        mode="substring",
    )


def build_risk_disclosure_verifier() -> GroundTruthVerifier:
    """
    Pattern: GroundTruthVerifier (substring) — compliance required phrase.

    HIGH trust domain: all advisory output must contain "risk" (any casing).
    This ensures the LLM never gives a trade recommendation without
    mentioning risk — a compliance requirement.
    """
    return GroundTruthVerifier(
        reference="risk",
        mode="substring",
    )


# ── Case C: Ground truth — word overlap ───────────────────────────────────

def build_bearish_signal_verifier() -> GroundTruthVerifier:
    """
    Pattern: GroundTruthVerifier (word_overlap) — fuzzy concept match.

    When signals are bearish (e.g. XOM death cross), the response should
    discuss bearish/negative concepts. Word overlap at 0.3 threshold
    allows varied phrasing while catching completely off-topic responses.
    """
    # threshold=0.08: XOM (bearish/sell/risk match → ~0.09) passes;
    # NVDA (only "risk" matches → ~0.03) fails; generic (0 match) fails.
    # Word overlap uses bag-of-words with punctuation attached, so threshold
    # must be tuned empirically per reference string.
    return GroundTruthVerifier(
        reference="sell bearish decline downtrend caution risk",
        mode="word_overlap",
        threshold=0.08,
    )


# ── Case D: Pipeline — ALL_PASS (strictest) ───────────────────────────────

def build_strict_trade_pipeline(ticker: str) -> VerifierPipeline:
    """
    Pattern: VerifierPipeline(ALL_PASS) — both schema AND ticker must pass.

    Use for HIGH trust output that feeds order management systems.
    If either verifier fails → entire output is rejected.

    Composition:
      1. SchemaVerifier    → is it valid JSON with required keys?
      2. TickerVerifier    → does it actually discuss the requested ticker?
    """
    return VerifierPipeline(
        verifiers=[
            build_trade_schema_verifier(),
            build_ticker_mention_verifier(ticker),
        ],
        mode=PipelineMode.ALL_PASS,
    )


# ── Case E: Pipeline — ANY_PASS (permissive) ──────────────────────────────

def build_permissive_analysis_pipeline(ticker: str) -> VerifierPipeline:
    """
    Pattern: VerifierPipeline(ANY_PASS) — schema OR content check passes.

    Use for advisory analysis where we want either structured output OR
    the response at least discusses the right stock. Permissive mode for
    exploratory queries where strict JSON is optional.
    """
    return VerifierPipeline(
        verifiers=[
            build_trade_schema_verifier(),
            build_ticker_mention_verifier(ticker),
        ],
        mode=PipelineMode.ANY_PASS,
    )


# ── Case F: Pipeline — THRESHOLD (n-of-m) ─────────────────────────────────

def build_consensus_pipeline(ticker: str) -> VerifierPipeline:
    """
    Pattern: VerifierPipeline(THRESHOLD) — 2-of-3 verifiers must pass.

    Multi-signal consensus check:
      1. Schema verifier     → structured output format
      2. Ticker verifier     → correct stock discussed
      3. Risk disclosure     → compliance phrase present

    threshold_count=2 means at least 2 of 3 must pass.
    Balances compliance with flexibility (e.g. free-text response still passes
    if ticker is mentioned AND risk is disclosed).
    """
    return VerifierPipeline(
        verifiers=[
            build_trade_schema_verifier(),
            build_ticker_mention_verifier(ticker),
            build_risk_disclosure_verifier(),
        ],
        mode=PipelineMode.THRESHOLD,
        threshold_count=2,
    )
