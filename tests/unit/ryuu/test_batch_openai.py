"""Phase 12.1 — OpenAI Batch API integration tests.

7 cases using FakeBatchAPIClient (no real network).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.batch import BatchItem, BatchRunner


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


# ---------------------------------------------------------------------------
# FakeBatchAPIClient — simulates OpenAI Batch API in-memory
# ---------------------------------------------------------------------------


@dataclass
class FakeFile:
    id: str
    content: str = ""


@dataclass
class FakeBatch:
    id: str
    input_file_id: str
    status: str = "completed"
    output_file_id: str | None = None
    error_file_id: str | None = None


@dataclass
class FakeBatchAPIClient:
    """In-memory simulation of OpenAI client.batches + client.files APIs."""

    files: dict[str, FakeFile] = field(default_factory=dict)
    batches: dict[str, FakeBatch] = field(default_factory=dict)
    next_file_id: int = 1
    next_batch_id: int = 1
    # Test hooks: control status sequence + output content
    statuses_to_return: list[str] = field(default_factory=list)
    output_lines: list[str] = field(default_factory=list)

    async def upload_input_file(self, jsonl_bytes: bytes) -> str:
        fid = f"file-in-{self.next_file_id}"
        self.next_file_id += 1
        self.files[fid] = FakeFile(id=fid, content=jsonl_bytes.decode("utf-8"))
        return fid

    async def create_batch(
        self, input_file_id: str, endpoint: str, completion_window: str
    ) -> str:
        bid = f"batch-{self.next_batch_id}"
        self.next_batch_id += 1
        # Pre-stage output file
        ofid = f"file-out-{self.next_file_id}"
        self.next_file_id += 1
        self.files[ofid] = FakeFile(id=ofid, content="\n".join(self.output_lines))
        self.batches[bid] = FakeBatch(
            id=bid, input_file_id=input_file_id,
            status="in_progress", output_file_id=ofid,
        )
        return bid

    async def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        batch = self.batches[batch_id]
        if self.statuses_to_return:
            batch.status = self.statuses_to_return.pop(0)
        else:
            batch.status = "completed"   # default to immediate completion
        return {
            "id": batch.id,
            "status": batch.status,
            "output_file_id": batch.output_file_id,
            "error_file_id": batch.error_file_id,
        }

    async def download_file(self, file_id: str) -> str:
        return self.files[file_id].content


def _make_agent() -> Agent:
    agent = Agent(model="gpt-4o-mini", instructions="be brief")
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]
    return agent


def _batch_output_line(custom_id: str, content: str) -> str:
    """Format one line of OpenAI batch output JSONL."""
    return json.dumps({
        "id": f"resp-{custom_id}",
        "custom_id": custom_id,
        "response": {
            "status_code": 200,
            "body": {
                "id": f"chatcmpl-{custom_id}",
                "object": "chat.completion",
                "model": "gpt-4o-mini",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        },
        "error": None,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_openai_batch_submits_jsonl_correctly() -> None:
    """JSONL upload contains one request per input with required fields."""
    fake_client = FakeBatchAPIClient(output_lines=[
        _batch_output_line("item-0", "answer-0"),
        _batch_output_line("item-1", "answer-1"),
    ])

    runner = BatchRunner(
        agent=_make_agent(),
        mode="openai_batch",
        batch_client=fake_client,
        poll_interval_s=0.001,
    )
    await runner.run(["question 1", "question 2"])

    # Verify uploaded JSONL has 2 lines, each with custom_id + body
    uploaded_file = next(iter(fake_client.files.values()))
    lines = uploaded_file.content.strip().split("\n")
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert "custom_id" in parsed
    assert "method" in parsed
    assert "url" in parsed
    assert parsed["url"] == "/v1/chat/completions"
    assert "body" in parsed
    assert parsed["body"]["model"] == "gpt-4o-mini"


async def test_openai_batch_returns_results_in_order() -> None:
    """Output mapped back to input order via custom_id."""
    fake_client = FakeBatchAPIClient(output_lines=[
        # Intentionally out-of-order from input
        _batch_output_line("item-1", "answer-B"),
        _batch_output_line("item-0", "answer-A"),
    ])

    runner = BatchRunner(
        agent=_make_agent(),
        mode="openai_batch",
        batch_client=fake_client,
        poll_interval_s=0.001,
    )
    results = await runner.run(["question A", "question B"])
    assert len(results) == 2
    # Results in input order despite output order
    assert isinstance(results[0], BatchItem)
    assert results[0].output == "answer-A"
    assert results[1].output == "answer-B"


async def test_openai_batch_polls_until_completion() -> None:
    """Poll loop continues while status is in_progress, exits on completed."""
    fake_client = FakeBatchAPIClient(
        statuses_to_return=["in_progress", "in_progress", "completed"],
        output_lines=[_batch_output_line("item-0", "done")],
    )

    runner = BatchRunner(
        agent=_make_agent(),
        mode="openai_batch",
        batch_client=fake_client,
        poll_interval_s=0.001,
    )
    results = await runner.run(["q1"])
    assert len(results) == 1
    # All 3 status states consumed during poll
    assert fake_client.statuses_to_return == []


async def test_openai_batch_failed_status_raises() -> None:
    """Batch status='failed' → raises informative exception."""
    fake_client = FakeBatchAPIClient(
        statuses_to_return=["failed"],
        output_lines=[],
    )

    runner = BatchRunner(
        agent=_make_agent(),
        mode="openai_batch",
        batch_client=fake_client,
        poll_interval_s=0.001,
    )
    with pytest.raises(RuntimeError, match="failed"):
        await runner.run(["q1"])


async def test_openai_batch_dict_inputs_preserve_id() -> None:
    """Dict inputs with custom 'id' → BatchItem.id preserved through batch."""
    fake_client = FakeBatchAPIClient(output_lines=[
        _batch_output_line("doc-1", "answer-doc1"),
        _batch_output_line("doc-2", "answer-doc2"),
    ])

    runner = BatchRunner(
        agent=_make_agent(),
        mode="openai_batch",
        batch_client=fake_client,
        poll_interval_s=0.001,
    )
    results = await runner.run([
        {"id": "doc-1", "input": "q1"},
        {"id": "doc-2", "input": "q2"},
    ])
    assert results[0].id == "doc-1"
    assert results[0].output == "answer-doc1"
    assert results[1].id == "doc-2"


async def test_openai_batch_line_error_creates_error_item() -> None:
    """A batch output line with error field → BatchItem.error populated."""
    fake_client = FakeBatchAPIClient(output_lines=[
        json.dumps({
            "id": "resp-1",
            "custom_id": "item-0",
            "response": None,
            "error": {"code": "rate_limit_exceeded", "message": "too many"},
        }),
    ])

    runner = BatchRunner(
        agent=_make_agent(),
        mode="openai_batch",
        batch_client=fake_client,
        poll_interval_s=0.001,
        on_error="collect",
    )
    results = await runner.run(["q1"])
    assert results[0].error is not None
    assert "rate_limit_exceeded" in str(results[0].error)


async def test_openai_batch_empty_input_returns_empty() -> None:
    """Empty input list → no API calls, empty result."""
    fake_client = FakeBatchAPIClient()
    runner = BatchRunner(
        agent=_make_agent(),
        mode="openai_batch",
        batch_client=fake_client,
        poll_interval_s=0.001,
    )
    results = await runner.run([])
    assert results == []
    assert fake_client.files == {}
    assert fake_client.batches == {}
