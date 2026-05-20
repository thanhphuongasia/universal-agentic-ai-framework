"""RequestHandler — single entry point for conversational mode. P7-T09.

Product code calls handle(), NOT agent.execute() directly.

Wire: analyzer → selector → strategy.execute(intent, ctx_routed, pool, verifier)
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from uaaf.cognitive.verifier import IVerifier
from uaaf.execution.pool import AgentPool
from uaaf.intent.analyzer import IIntentAnalyzer
from uaaf.intent.models import CognitiveResult
from uaaf.intent.selector import StrategySelector
from uaaf_workflow.context import ExecutionContext


@dataclass
class RequestHandler:
    """Single entry point for conversational mode.

    Wires: analyzer → selector → strategy.execute(intent, ctx_routed, pool, verifier)
    strategy_id is stamped onto an immutable copy of context before dispatch —
    proves cognitive routing occurred without mutating the caller's context.
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
