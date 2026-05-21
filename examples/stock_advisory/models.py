"""
Stock Advisory — Domain Models
================================
Pattern illustrated: dataclass-first domain model, no framework coupling.

All business objects live here. Framework objects (AgentResult, Cost, ...) stay
in the agent layer — models.py knows nothing about RYUU.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Ticker = str
SignalType = Literal["BUY", "SELL", "HOLD"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Sector = Literal["TECH", "FINANCE", "ENERGY", "HEALTH", "CONSUMER"]


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@dataclass
class Stock:
    ticker: Ticker
    company: str
    sector: Sector
    price: float
    change_pct: float    # % change today, e.g. +2.3 or -1.1
    volume: int          # shares traded today


@dataclass
class Signal:
    """A single technical or sentiment signal for a ticker."""
    ticker: Ticker
    signal_type: SignalType
    strength: float      # 0.0 – 1.0
    source: str          # e.g. "RSI", "MACD", "MA_CROSSOVER", "SENTIMENT"
    rationale: str


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

@dataclass
class Position:
    ticker: Ticker
    shares: int
    avg_cost: float          # USD per share, purchase price
    current_price: float     # latest market price

    @property
    def current_value(self) -> float:
        return self.shares * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    @property
    def pnl(self) -> float:
        return self.current_value - self.cost_basis

    @property
    def pnl_pct(self) -> float:
        return (self.current_price / self.avg_cost - 1) * 100

    def summary(self) -> str:
        direction = "+" if self.pnl >= 0 else ""
        return (
            f"[{self.ticker}] {self.shares} shares @ ${self.avg_cost:.2f} → "
            f"${self.current_price:.2f}  |  P&L: {direction}${self.pnl:.2f} ({direction}{self.pnl_pct:.1f}%)"
        )


@dataclass
class Portfolio:
    owner_id: str
    positions: list[Position] = field(default_factory=list)
    cash: float = 0.0

    @property
    def total_value(self) -> float:
        return sum(p.current_value for p in self.positions) + self.cash

    @property
    def invested(self) -> float:
        return sum(p.current_value for p in self.positions)

    @property
    def total_pnl(self) -> float:
        return sum(p.pnl for p in self.positions)

    def get_position(self, ticker: Ticker) -> Position | None:
        return next((p for p in self.positions if p.ticker == ticker), None)

    def summary(self) -> str:
        lines = [f"Portfolio [{self.owner_id}] — Total: ${self.total_value:,.2f}"]
        lines.append(f"  Cash: ${self.cash:,.2f}  |  Invested: ${self.invested:,.2f}")
        lines.append(f"  Total P&L: ${self.total_pnl:+,.2f}")
        for p in self.positions:
            lines.append(f"  {p.summary()}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trade output
# ---------------------------------------------------------------------------

@dataclass
class TradeRecommendation:
    """Structured output from StockAdvisoryAgent — must pass SchemaVerifier."""
    ticker: Ticker
    action: SignalType
    confidence: float        # 0.0 – 1.0
    rationale: str
    risk_level: RiskLevel
    max_position_pct: float  # max % of portfolio to allocate

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "risk_level": self.risk_level,
            "max_position_pct": self.max_position_pct,
        }


# ---------------------------------------------------------------------------
# Static market data (replaces live API for learning purposes)
# ---------------------------------------------------------------------------

MARKET_DATA: dict[Ticker, Stock] = {
    "AAPL": Stock("AAPL", "Apple Inc.",         "TECH",     185.42,  +1.23, 52_000_000),
    "NVDA": Stock("NVDA", "NVIDIA Corp.",        "TECH",     875.90,  +3.71, 38_000_000),
    "MSFT": Stock("MSFT", "Microsoft Corp.",     "TECH",     415.30,  -0.45, 22_000_000),
    "JPM":  Stock("JPM",  "JPMorgan Chase",      "FINANCE",  198.10,  +0.88, 11_000_000),
    "XOM":  Stock("XOM",  "ExxonMobil",          "ENERGY",   112.50,  -1.30,  8_000_000),
}

SIGNALS_DATA: dict[Ticker, list[Signal]] = {
    "AAPL": [
        Signal("AAPL", "BUY",  0.72, "MA_CROSSOVER", "50-day MA crossed above 200-day MA (golden cross)"),
        Signal("AAPL", "BUY",  0.65, "RSI",          "RSI at 42 — not overbought, room to run"),
        Signal("AAPL", "HOLD", 0.55, "SENTIMENT",    "Analyst consensus: 28 Buy, 6 Hold, 2 Sell"),
    ],
    "NVDA": [
        Signal("NVDA", "BUY",  0.88, "MACD",         "Strong MACD bullish divergence on weekly chart"),
        Signal("NVDA", "BUY",  0.81, "SENTIMENT",    "AI demand cycle driving upward revision cycle"),
        Signal("NVDA", "SELL", 0.40, "RSI",          "RSI at 74 — approaching overbought territory"),
    ],
    "MSFT": [
        Signal("MSFT", "HOLD", 0.70, "MA_CROSSOVER", "Price consolidating near 200-day MA support"),
        Signal("MSFT", "BUY",  0.60, "SENTIMENT",    "Azure growth re-acceleration; Copilot uptake"),
    ],
    "JPM": [
        Signal("JPM",  "HOLD", 0.65, "RSI",          "RSI neutral at 52; range-bound near highs"),
        Signal("JPM",  "SELL", 0.45, "MACD",         "MACD histogram turning negative on daily"),
    ],
    "XOM": [
        Signal("XOM",  "SELL", 0.70, "MA_CROSSOVER", "Death cross: 50-day crossed below 200-day"),
        Signal("XOM",  "SELL", 0.60, "SENTIMENT",    "Oil demand outlook cautious; EV transition headwind"),
    ],
}


def build_demo_portfolio() -> Portfolio:
    return Portfolio(
        owner_id="demo-investor",
        cash=25_000.0,
        positions=[
            Position("AAPL", shares=100, avg_cost=160.00, current_price=185.42),
            Position("NVDA", shares=20,  avg_cost=620.00, current_price=875.90),
            Position("MSFT", shares=50,  avg_cost=380.00, current_price=415.30),
            Position("XOM",  shares=80,  avg_cost=118.00, current_price=112.50),
        ],
    )
