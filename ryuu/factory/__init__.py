"""Factory `Agent()` package — lean single-agent + tool-calling facade.

Modular layout (refactored from monolithic 1005-line factory.py):

  agent.py            — Agent dataclass (main public class)
  stream_event.py     — StreamEvent dataclass
  _internal_agent.py  — _FactoryLLMAgent (private — extends LLMAgent)
  RUNNERS/BUILDERS    — methods kept on Agent class for state cohesion

Phase 10 MVP: Mode 1 (`instructions=str`) + Mode A (callable list `tools=[...]`).
Phase 10.1 adds Mode 2: `system=str`, `user_template=str`, `examples=[...]`.
Phase 10.2 adds Mode 3 (file path) + Mode 4 (YAML reference).
Phase 10.3 adds Tool Modes B (ITool) + C (registry) + D (YAML schema pair).
Phase 10.4 adds streaming + multi-provider fallback + budget_tokens.
Phase 10.6 adds token-by-token streaming + failover dispatch.
Phase 14.1 adds thinking_mode (Layer B wire to ThinkingStrategy).
Phase 14.2 adds n_samples / vote (Layer B wire to BestOfNStrategy).
Phase 14.3 adds adaptive_compute (Layer B wire to AdaptiveStrategy).

See: docs/guides/quickstart/01-factory.md
"""

from __future__ import annotations

from ryuu.factory.agent import Agent
from ryuu.factory.stream_event import StreamEvent

__all__ = ["Agent", "StreamEvent"]
