"""
Stock Advisory — Tool Handlers
================================
Pattern illustrated: ToolRegistry with domain-specific handlers.

Architecture (same as todo_app):
  YAML (prompts/stock_advisory/v1.yaml)  ← schema the LLM sees
  tools.py                                ← Python callables that do real work
  build_stock_registry()                  ← wires name → handler

HIGH-TRUST NOTE: place_order_dry_run() never executes a real trade.
In production, place_order() would be gated by SandboxManager + AuditLogger
with 7-year compliance retention. This example shows the dry-run pattern.
"""

from __future__ import annotations

import json
from typing import Any

from examples.stock_advisory.models import (
    MARKET_DATA,
    SIGNALS_DATA,
    Portfolio,
    Ticker,
)
from uaaf.execution import ToolRegistry


def build_stock_registry(portfolio: Portfolio) -> ToolRegistry:
    """Wire all tool handlers with access to market data and portfolio state."""
    registry = ToolRegistry()

    # ── get_quote ──────────────────────────────────────────────────────────
    # Pattern: deterministic lookup — no LLM, no network, instant

    async def get_quote(ticker: str) -> dict[str, Any]:
        """Return current price and change for a ticker."""
        t = ticker.upper()
        if t not in MARKET_DATA:
            return {"error": f"Unknown ticker: {t}. Available: {list(MARKET_DATA)}"}
        s = MARKET_DATA[t]
        direction = "▲" if s.change_pct >= 0 else "▼"
        return {
            "ticker": t,
            "company": s.company,
            "sector": s.sector,
            "price": s.price,
            "change_pct": s.change_pct,
            "change_direction": direction,
            "volume": s.volume,
        }

    registry.register("get_quote", get_quote)

    # ── get_signals ────────────────────────────────────────────────────────
    # Pattern: structured signal aggregation — agent uses this to reason

    async def get_signals(ticker: str, min_strength: float = 0.0) -> dict[str, Any]:
        """Return technical + sentiment signals for a ticker."""
        t = ticker.upper()
        if t not in SIGNALS_DATA:
            return {"error": f"No signals for ticker: {t}"}
        all_signals = SIGNALS_DATA[t]
        filtered = [s for s in all_signals if s.strength >= min_strength]

        buy_count  = sum(1 for s in filtered if s.signal_type == "BUY")
        sell_count = sum(1 for s in filtered if s.signal_type == "SELL")
        hold_count = sum(1 for s in filtered if s.signal_type == "HOLD")
        avg_strength = sum(s.strength for s in filtered) / len(filtered) if filtered else 0.0

        consensus: str
        if buy_count > sell_count and buy_count > hold_count:
            consensus = "BUY"
        elif sell_count > buy_count and sell_count > hold_count:
            consensus = "SELL"
        else:
            consensus = "HOLD"

        return {
            "ticker": t,
            "signal_count": len(filtered),
            "consensus": consensus,
            "avg_strength": round(avg_strength, 2),
            "buy": buy_count,
            "sell": sell_count,
            "hold": hold_count,
            "signals": [
                {
                    "type": s.signal_type,
                    "strength": s.strength,
                    "source": s.source,
                    "rationale": s.rationale,
                }
                for s in filtered
            ],
        }

    registry.register("get_signals", get_signals)

    # ── portfolio_summary ──────────────────────────────────────────────────
    # Pattern: domain aggregation — portfolio state → structured context for LLM

    async def portfolio_summary(ticker_filter: str | None = None) -> dict[str, Any]:
        """Return portfolio holdings with P&L analysis."""
        positions = portfolio.positions
        if ticker_filter:
            t = ticker_filter.upper()
            positions = [p for p in positions if p.ticker == t]
            if not positions:
                return {"error": f"No position found for {t}"}

        return {
            "owner_id": portfolio.owner_id,
            "total_value": round(portfolio.total_value, 2),
            "invested": round(portfolio.invested, 2),
            "cash": round(portfolio.cash, 2),
            "cash_pct": round(portfolio.cash / portfolio.total_value * 100, 1),
            "total_pnl": round(portfolio.total_pnl, 2),
            "positions": [
                {
                    "ticker": p.ticker,
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "current_value": round(p.current_value, 2),
                    "pnl": round(p.pnl, 2),
                    "pnl_pct": round(p.pnl_pct, 1),
                    "allocation_pct": round(p.current_value / portfolio.total_value * 100, 1),
                }
                for p in positions
            ],
        }

    registry.register("portfolio_summary", portfolio_summary)

    # ── check_risk ─────────────────────────────────────────────────────────
    # Pattern: risk gate — HIGH trust domain requires explicit risk check before
    # any advisory output. In production this integrates compliance rules.

    async def check_risk(ticker: str, shares: int, action: str) -> dict[str, Any]:
        """Assess risk of a proposed trade (buy/sell) in portfolio context."""
        t = ticker.upper()
        if t not in MARKET_DATA:
            return {"error": f"Unknown ticker: {t}"}

        stock = MARKET_DATA[t]
        trade_value = shares * stock.price
        portfolio_pct = trade_value / portfolio.total_value * 100
        existing = portfolio.get_position(t)
        existing_value = existing.current_value if existing else 0.0
        post_trade_pct = (existing_value + trade_value) / portfolio.total_value * 100 if action.upper() == "BUY" else 0.0

        # Simple rule-based risk tier
        if portfolio_pct > 25:
            risk_level = "CRITICAL"
            warning = f"Trade is {portfolio_pct:.1f}% of portfolio — exceeds 25% concentration limit"
        elif portfolio_pct > 15:
            risk_level = "HIGH"
            warning = f"Trade is {portfolio_pct:.1f}% of portfolio — above 15% threshold"
        elif portfolio_pct > 8:
            risk_level = "MEDIUM"
            warning = f"Trade is {portfolio_pct:.1f}% of portfolio — monitor concentration"
        else:
            risk_level = "LOW"
            warning = ""

        return {
            "ticker": t,
            "action": action.upper(),
            "shares": shares,
            "trade_value": round(trade_value, 2),
            "trade_pct_of_portfolio": round(portfolio_pct, 1),
            "post_trade_pct": round(post_trade_pct, 1),
            "risk_level": risk_level,
            "warning": warning,
            "sufficient_cash": portfolio.cash >= trade_value if action.upper() == "BUY" else True,
        }

    registry.register("check_risk", check_risk)

    # ── place_order_dry_run ────────────────────────────────────────────────
    # Pattern: HIGH TRUST — dry run only. Real execution requires:
    #   SandboxManager + AuditLogger with 7-year retention + human approval gate.
    # This example shows the audit trail pattern without live order routing.

    async def place_order_dry_run(ticker: str, action: str, shares: int) -> dict[str, Any]:
        """Simulate order placement — DRY RUN ONLY, no real trade executed."""
        t = ticker.upper()
        if t not in MARKET_DATA:
            return {"error": f"Unknown ticker: {t}"}
        stock = MARKET_DATA[t]
        return {
            "dry_run": True,
            "status": "SIMULATED",
            "ticker": t,
            "action": action.upper(),
            "shares": shares,
            "price": stock.price,
            "total_value": round(shares * stock.price, 2),
            "compliance_note": (
                "DRY RUN — no real order submitted. "
                "Production: requires AuditLogger 7y retention + SandboxManager + human approval."
            ),
        }

    registry.register("place_order_dry_run", place_order_dry_run)

    return registry
