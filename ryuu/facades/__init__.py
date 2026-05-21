"""Phase 10.5 + 14.4 — Multi-agent / routing facades.

6 pattern classes wrapping Agent + AgentPool primitives:
  Chain               — sequential output→input (Agent or callable transforms)
  FanOut              — parallel N tasks (3 variants: items / agents / pairs)
  Router              — 1-stage analyzer dispatches to one of N routes
  HierarchicalRouter  — 2-stage: category → specific intent (Phase 14.4)
  Orchestrator        — main agent plans, workers execute, aggregate combines
  Evaluator           — generate → verify → refine if bad → repeat

All implement uniform `.run(input) → output` for composability.

See: docs/guides/quickstart.md §4 (multi-agent patterns).
"""

from __future__ import annotations

from ryuu.facades.chain import Chain
from ryuu.facades.evaluator import Evaluator
from ryuu.facades.fanout import FanOut
from ryuu.facades.hierarchical_router import HierarchicalRouter
from ryuu.facades.orchestrator import Orchestrator
from ryuu.facades.router import Router

__all__ = [
    "Chain",
    "Evaluator",
    "FanOut",
    "HierarchicalRouter",
    "Orchestrator",
    "Router",
]
