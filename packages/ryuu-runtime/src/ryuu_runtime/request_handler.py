"""RequestHandler — single entry point for conversational mode."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from ryuu_cognitive.verifier import IVerifier
from ryuu_core.context import ExecutionContext
from ryuu_core.models import CognitiveResult
from ryuu_execution.pool import AgentPool
from ryuu_runtime.analyzer import IIntentAnalyzer
from ryuu_runtime.selector import StrategySelector


@dataclass
class RequestHandler:
    """Single entry point for conversational mode.

    Wires: analyzer → selector → strategy.execute(intent, ctx_routed, pool, verifier)
    strategy_id is stamped onto an immutable copy of context before dispatch.
    """

    analyzer: IIntentAnalyzer
    selector: StrategySelector
    pool: AgentPool
    verifier: IVerifier

    async def handle(
        self,
        message: str,
        context: ExecutionContext,
    ) -> CognitiveResult:
        intent = await self.analyzer.analyze(message, context.scope.scope_key)
        strategy = self.selector.select(intent, context)
        ctx_routed = dataclasses.replace(context, strategy_id=strategy.strategy_id)
        return await strategy.execute(intent, ctx_routed, self.pool, self.verifier)
