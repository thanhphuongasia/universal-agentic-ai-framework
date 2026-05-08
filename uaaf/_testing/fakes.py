"""FakeLLMProvider and FakeKnowledgeBackbone for use in product-side tests.

These fakes are stable public API — product teams should import from ``uaaf._testing``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from uaaf.observability.cost import Cost
from uaaf.providers.llm import (
    CompletionRequest,
    Embedding,
    Response,
    StreamChunk,
    TokenUsage,
)

# ---------------------------------------------------------------------------
# FakeLLMProvider
# ---------------------------------------------------------------------------


class FakeLLMProvider:
    """Deterministic ILLMProvider for tests.

    Usage::

        fake = FakeLLMProvider(responses=[
            Response(content="hello", model="fake", usage=TokenUsage(10, 5)),
        ])
        response = await fake.complete(request)
        assert fake.call_count == 1
    """

    provider_id = "fake"

    def __init__(
        self,
        responses: list[Response] | None = None,
        default_content: str = "fake response",
        raise_on_call: Exception | None = None,
    ) -> None:
        self._queue: deque[Response] = deque(responses or [])
        self._default_content = default_content
        self._raise_on_call = raise_on_call
        self.call_count = 0
        self.last_request: CompletionRequest | None = None

    async def complete(self, request: CompletionRequest) -> Response:
        self.call_count += 1
        self.last_request = request

        if self._raise_on_call is not None:
            raise self._raise_on_call

        if self._queue:
            return self._queue.popleft()

        return Response(
            content=self._default_content,
            model="fake",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            finish_reason="stop",
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        self.call_count += 1
        response = await self.complete(request)
        # Simulate streaming as a single final chunk.
        yield StreamChunk(content=response.content, is_final=True, usage=response.usage)

    async def embed(self, text: str, model: str | None = None) -> Embedding:
        self.call_count += 1
        return Embedding(vector=[0.1] * 8, model="fake-embed")

    def estimate_cost(self, request: CompletionRequest) -> Cost:
        return Cost(input_tokens=10, output_tokens=5, usd=0.0, provider="fake", model="fake")

    def reset(self) -> None:
        """Reset call tracking for reuse across test cases."""
        self.call_count = 0
        self.last_request = None
        self._raise_on_call = None


# ---------------------------------------------------------------------------
# FakeKnowledgeBackbone (stub for Phase 3 tests)
# ---------------------------------------------------------------------------


@dataclass
class FakeKnowledgeBackbone:
    """Deterministic IKnowledgeBackbone for tests — Phase 3 implementation."""

    from uaaf.knowledge.backbone import BackboneType  # noqa: PLC0415

    backbone_type: Any = None  # set in __post_init__
    written: list[dict[str, Any]] = field(default_factory=list)
    query_responses: list[Any] = field(default_factory=list)
    write_count: int = 0

    def __post_init__(self) -> None:
        from uaaf.knowledge.backbone import BackboneType
        if self.backbone_type is None:
            self.backbone_type = BackboneType.MEMORY

    async def write(
        self,
        observation: str,
        scope_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.write_count += 1
        self.written.append({"observation": observation, "scope_key": scope_key, "metadata": metadata})

    async def query(
        self,
        query: str,
        scope_key: str = "",
        top_k: int = 5,
    ) -> Any:
        from uaaf.knowledge.backbone import QueryResult
        if self.query_responses:
            return self.query_responses.pop(0)
        return QueryResult(results=[], scores=[])

    async def assemble_context(
        self,
        query: str,
        scope_key: str = "",
        budget_tokens: int = 2000,
    ) -> Any:
        from uaaf.knowledge.backbone import AssembledContext
        return AssembledContext(text="", token_count=0)


# ---------------------------------------------------------------------------
# Phase 1 fakes — FakeIntentAnalyzer, FakeAgentPool, FakeVerifier
# ---------------------------------------------------------------------------


class FakeIntentAnalyzer:
    """Deterministic IIntentAnalyzer for tests."""

    def __init__(self, default_intent: Any = None) -> None:
        from uaaf.intent.models import DIRECT, ComplexityLevel, StructuredIntent

        self._intent = default_intent or StructuredIntent(
            intent_type="query",
            action="search",
            entities={},
            complexity=ComplexityLevel.LOW,
            confidence=0.9,
            suggested_strategy=DIRECT,
        )
        self.call_count = 0
        self.last_message: str | None = None

    async def analyze(
        self,
        message: str,
        scope_key: str,
        history: list[dict[str, str]] | None = None,
    ) -> Any:
        self.call_count += 1
        self.last_message = message
        return self._intent


class FakeAgentPool:
    """Deterministic IAgentPool: pops responses from a queue."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        from uaaf.execution.agent import AgentResult
        from uaaf.observability.cost import Cost

        self._queue: deque[Any] = deque(
            responses
            or [AgentResult(task_id="fake", output="fake output", cost=Cost.zero())]
        )
        self.dispatch_count = 0
        self.last_dispatched: Any = None

    async def dispatch(self, task: Any) -> Any:
        from uaaf.execution.agent import AgentResult
        from uaaf.observability.cost import Cost

        self.dispatch_count += 1
        self.last_dispatched = task
        if self._queue:
            return self._queue.popleft()
        return AgentResult(task_id=task.task_id, output="default fake", cost=Cost.zero())

    async def fan_out(
        self,
        tasks: list[Any],
        context: Any = None,
        tag_filter: Any = None,
        on_error: str = "fail_fast",
    ) -> list[Any]:
        """Sequential fake fan_out — pops from queue for each task."""
        results = []
        for task in tasks:
            results.append(await self.dispatch(task))
        return results


class FakeVerifier:
    """Deterministic IVerifier: iterates through a pass/fail sequence."""

    verifier_id = "fake"

    def __init__(
        self,
        pass_sequence: list[bool] | None = None,
        confidence_sequence: list[float] | None = None,
        feedback: str = "",
    ) -> None:
        self._passes: deque[bool] = deque(pass_sequence or [True])
        self._confidences: deque[float] = deque(confidence_sequence or [])
        self._feedback = feedback
        self.verify_count = 0

    async def verify(
        self,
        output: str,
        context: Any,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        from uaaf.cognitive.verifier import VerificationResult

        self.verify_count += 1
        passed = self._passes.popleft() if self._passes else True
        confidence = self._confidences.popleft() if self._confidences else (0.9 if passed else 0.3)
        return VerificationResult(passed=passed, confidence=confidence, feedback=self._feedback)
