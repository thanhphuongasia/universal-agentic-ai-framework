"""Tests for ryuu._testing.fakes — T12."""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeKnowledgeBackbone, FakeLLMProvider
from ryuu.providers.llm import CompletionRequest, Message, Response, TokenUsage


def _req() -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content="hi")],
        model="fake",
    )


# ---------------------------------------------------------------------------
# FakeLLMProvider
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fake_llm_returns_default_content() -> None:
    fake = FakeLLMProvider(default_content="hello there")
    resp = await fake.complete(_req())
    assert resp.content == "hello there"
    assert fake.call_count == 1


@pytest.mark.anyio
async def test_fake_llm_pops_queue_in_order() -> None:
    r1 = Response(content="first", model="fake", usage=TokenUsage(1, 1))
    r2 = Response(content="second", model="fake", usage=TokenUsage(1, 1))
    fake = FakeLLMProvider(responses=[r1, r2])
    assert (await fake.complete(_req())).content == "first"
    assert (await fake.complete(_req())).content == "second"
    # After queue exhausted, falls back to default
    assert (await fake.complete(_req())).content == "fake response"


@pytest.mark.anyio
async def test_fake_llm_raises_configured_exception() -> None:
    from ryuu_workflow.errors import RetryableError

    fake = FakeLLMProvider(raise_on_call=RetryableError("forced"))
    with pytest.raises(RetryableError):
        await fake.complete(_req())


@pytest.mark.anyio
async def test_fake_llm_tracks_last_request() -> None:
    fake = FakeLLMProvider()
    req = _req()
    await fake.complete(req)
    assert fake.last_request is req


@pytest.mark.anyio
async def test_fake_llm_reset_clears_state() -> None:
    fake = FakeLLMProvider()
    await fake.complete(_req())
    assert fake.call_count == 1
    fake.reset()
    assert fake.call_count == 0
    assert fake.last_request is None


@pytest.mark.anyio
async def test_fake_llm_embed_returns_vector() -> None:
    fake = FakeLLMProvider()
    emb = await fake.embed("hello")
    assert len(emb.vector) > 0
    assert fake.call_count == 1


def test_fake_llm_estimate_cost_returns_zero() -> None:
    fake = FakeLLMProvider()
    cost = fake.estimate_cost(_req())
    assert cost.usd == 0.0
    assert cost.provider == "fake"


# ---------------------------------------------------------------------------
# FakeKnowledgeBackbone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_backbone_records_writes() -> None:
    backbone = FakeKnowledgeBackbone()
    await backbone.write("hello world", scope_key="dom:u:s")
    assert backbone.write_count == 1
    assert backbone.written[0]["observation"] == "hello world"
    assert backbone.written[0]["scope_key"] == "dom:u:s"


@pytest.mark.asyncio
async def test_fake_backbone_returns_configured_query_result() -> None:
    from ryuu.knowledge.backbone import QueryResult
    qr = QueryResult(results=["node1"], scores=[0.9])
    backbone = FakeKnowledgeBackbone(query_responses=[qr])
    result = await backbone.query("SELECT *", scope_key="s")
    assert result.results == ["node1"]


@pytest.mark.asyncio
async def test_fake_backbone_satisfies_protocol() -> None:
    from ryuu.knowledge.backbone import IKnowledgeBackbone
    backbone = FakeKnowledgeBackbone()
    assert isinstance(backbone, IKnowledgeBackbone)
