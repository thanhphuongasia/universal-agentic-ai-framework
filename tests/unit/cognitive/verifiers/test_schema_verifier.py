"""Unit tests for SchemaVerifier — P2-T02."""

from __future__ import annotations

import json

import pytest

from ryuu.cognitive.verifiers.schema import SchemaVerifier
from ryuu_workflow.context import ContextScope, ExecutionContext


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


class TestSchemaVerifierJSON:
    @pytest.mark.asyncio
    async def test_pass_all_keys_present(self, ctx):
        v = SchemaVerifier(required_keys=["name", "score"])
        output = json.dumps({"name": "Alice", "score": 42})
        result = await v.verify(output, ctx)
        assert result.passed is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_fail_missing_key(self, ctx):
        v = SchemaVerifier(required_keys=["name", "score"])
        output = json.dumps({"name": "Alice"})
        result = await v.verify(output, ctx)
        assert result.passed is False
        assert result.confidence == 0.0
        assert "score" in result.feedback

    @pytest.mark.asyncio
    async def test_fail_invalid_json(self, ctx):
        v = SchemaVerifier(required_keys=["name"])
        result = await v.verify("not json", ctx)
        assert result.passed is False
        assert result.confidence == 0.0
        assert result.feedback != ""

    @pytest.mark.asyncio
    async def test_empty_required_keys_pass(self, ctx):
        v = SchemaVerifier(required_keys=[])
        result = await v.verify(json.dumps({"x": 1}), ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_verifier_id(self, ctx):
        v = SchemaVerifier(required_keys=[])
        assert v.verifier_id == "schema"


class TestSchemaVerifierNonJSON:
    @pytest.mark.asyncio
    async def test_pass_substrings_present(self, ctx):
        v = SchemaVerifier(required_keys=["hello", "world"], output_must_be_json=False)
        result = await v.verify("say hello to the world", ctx)
        assert result.passed is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_fail_substring_missing(self, ctx):
        v = SchemaVerifier(required_keys=["hello", "missing"], output_must_be_json=False)
        result = await v.verify("say hello", ctx)
        assert result.passed is False
        assert "missing" in result.feedback

    @pytest.mark.asyncio
    async def test_non_json_mode_accepts_any_string(self, ctx):
        v = SchemaVerifier(required_keys=[], output_must_be_json=False)
        result = await v.verify("anything at all", ctx)
        assert result.passed is True
