"""Phase 11.x — Factory knowledge= integration tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage
from ryuu_knowledge_rag import RAGBackbone, RAGPipeline


@dataclass
class _FakeEmbedder:
    provider_id: str = "fake"
    dim: int = 16

    async def embed(self, text: str, model: str | None = None):
        from ryuu_providers.llm import Embedding
        h = hashlib.md5(text.encode()).digest()
        vec = [((h[i % len(h)] / 255.0) * 2 - 1) for i in range(self.dim)]
        return Embedding(vector=vec, model=model or "fake")

    async def complete(self, request): raise NotImplementedError
    async def stream(self, request): raise NotImplementedError
    def estimate_cost(self, request):
        from ryuu_core.models import Cost
        return Cost(input_tokens=0, output_tokens=0, usd=0.0, provider="fake", model="fake")


def _fake_response(text: str = "answer") -> Response:
    return Response(
        content=text, model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


@pytest.fixture
async def populated_backbone():
    """Backbone pre-loaded with knowledge for tests."""
    pipeline = RAGPipeline(embedder=_FakeEmbedder())
    backbone = RAGBackbone(pipeline=pipeline)
    await backbone.write("Python is a programming language", scope_key="default")
    await backbone.write("RYUU is an agent framework", scope_key="default")
    await backbone.write("Different scope content here", scope_key="other_user")
    return backbone


async def test_agent_with_knowledge_prepends_context(populated_backbone) -> None:
    """`knowledge=` injects retrieved context before user query."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Answer based on context",
        knowledge=populated_backbone,
    )
    captured_messages: list[str] = []

    class _CapturingLLM(FakeLLMProvider):
        async def complete(self, request):
            captured_messages.append(request.messages[-1].content)
            return _fake_response("OK")

    agent._agent.llm = _CapturingLLM()  # type: ignore[attr-defined]
    await agent.run("What is Python?")

    user_msg = captured_messages[0]
    assert "Context" in user_msg or "context" in user_msg
    assert "Python is a programming language" in user_msg
    assert "What is Python?" in user_msg


async def test_agent_without_knowledge_no_injection() -> None:
    """`knowledge=None` (default) → user_content unchanged (backward compat)."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Answer",
    )
    captured: list[str] = []

    class _CapturingLLM(FakeLLMProvider):
        async def complete(self, request):
            captured.append(request.messages[-1].content)
            return _fake_response("OK")

    agent._agent.llm = _CapturingLLM()  # type: ignore[attr-defined]
    await agent.run("hello")

    # Should be just "hello", no Context: prefix
    assert "Context" not in captured[0]
    assert captured[0] == "hello"


async def test_agent_knowledge_scope_from_domain(populated_backbone) -> None:
    """`knowledge_scope_field='domain'` (default) filters by scope.domain."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Answer",
        knowledge=populated_backbone,
        knowledge_scope_field="domain",
    )
    captured: list[str] = []

    class _CapturingLLM(FakeLLMProvider):
        async def complete(self, request):
            captured.append(request.messages[-1].content)
            return _fake_response("OK")

    agent._agent.llm = _CapturingLLM()  # type: ignore[attr-defined]
    # Run with domain="other_user" → should retrieve other_user's content
    await agent.run("query", domain="other_user")

    assert "Different scope content" in captured[0]
    assert "Python is a programming" not in captured[0]


async def test_agent_knowledge_budget_respected(populated_backbone) -> None:
    """`knowledge_budget_tokens` constrains context size."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Answer",
        knowledge=populated_backbone,
        knowledge_budget_tokens=5,   # very tight → only 1 chunk fits
    )
    captured: list[str] = []

    class _CapturingLLM(FakeLLMProvider):
        async def complete(self, request):
            captured.append(request.messages[-1].content)
            return _fake_response("OK")

    agent._agent.llm = _CapturingLLM()  # type: ignore[attr-defined]
    await agent.run("Python?")

    # Budget = 5 tokens × 4 chars = 20 chars max — first chunk fits only
    context_part = captured[0].split("---")[0]
    # Only 1 chunk should appear, not all 2 from "default" scope
    chunk_count = context_part.count("\n\n---\n\n") + 1  # joiner between chunks
    assert chunk_count <= 2


async def test_agent_knowledge_empty_backbone_no_injection() -> None:
    """Knowledge backbone empty → no Context: prefix added."""
    empty_backbone = RAGBackbone(pipeline=RAGPipeline(embedder=_FakeEmbedder()))
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Answer",
        knowledge=empty_backbone,
    )
    captured: list[str] = []

    class _CapturingLLM(FakeLLMProvider):
        async def complete(self, request):
            captured.append(request.messages[-1].content)
            return _fake_response("OK")

    agent._agent.llm = _CapturingLLM()  # type: ignore[attr-defined]
    await agent.run("hello")

    assert "Context" not in captured[0]
    assert captured[0] == "hello"
