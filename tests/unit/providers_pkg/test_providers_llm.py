"""RED tests for ryuu_providers.llm — T02."""

from __future__ import annotations

import pytest


def test_import_illlmprovider() -> None:
    from ryuu_providers.llm import ILLMProvider  # noqa: F401
    assert ILLMProvider is not None


def test_import_completion_request() -> None:
    from ryuu_providers.llm import CompletionRequest, Message
    req = CompletionRequest(
        messages=[Message(role="user", content="hello")],
        model="gpt-4o-mini",
    )
    assert req.model == "gpt-4o-mini"
    assert len(req.messages) == 1


def test_import_response_types() -> None:
    from ryuu_providers.llm import Response, StreamChunk, TokenUsage
    usage = TokenUsage(input_tokens=10, output_tokens=5)
    resp = Response(content="hi", model="gpt-4o-mini", usage=usage)
    assert resp.content == "hi"
    chunk = StreamChunk(content="chunk", is_final=False)
    assert not chunk.is_final


def test_import_embedding() -> None:
    from ryuu_providers.llm import Embedding
    emb = Embedding(vector=[0.1, 0.2], model="text-embedding-3-small")
    assert len(emb.vector) == 2


def test_illlmprovider_is_protocol() -> None:
    from ryuu_providers.llm import ILLMProvider
    # Protocol is runtime_checkable — verify via ANNOTATIONS_ANNOTATIONS or duck check
    assert hasattr(ILLMProvider, "complete")
    assert hasattr(ILLMProvider, "stream")
    assert hasattr(ILLMProvider, "embed")
    assert hasattr(ILLMProvider, "estimate_cost")


def test_circuit_breaker_import() -> None:
    from ryuu_providers.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.is_available()


def test_circuit_breaker_trips_on_failures() -> None:
    from ryuu_providers.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=999.0)
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.is_available()
