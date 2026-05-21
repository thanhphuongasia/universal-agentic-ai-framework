"""Phase 12 + 12.1 — BatchRunner for processing N inputs through an Agent.

Two modes:
  - **gather** (default): concurrent execution via anyio task group + semaphore
    for `max_concurrent`. Works with any provider. No cost savings — same
    per-call cost as `.run()` × N.
  - **openai_batch** (Phase 12.1): true OpenAI Batch API integration —
    50% discount, 24h SLA. Builds JSONL → uploads via Files API → creates batch
    → polls until completed → downloads output → maps back to input order.

Usage::

    from ryuu import Agent
    from ryuu.batch import BatchRunner

    agent = Agent(model="gpt-4o-mini", instructions="Summarize")
    runner = BatchRunner(agent=agent, max_concurrent=10)

    # Plain strings
    results = await runner.run(["Text 1", "Text 2", ...])

    # With custom IDs (returned BatchItem.id preserves input id)
    results = await runner.run([
        {"id": "doc-1", "input": "Text 1"},
        {"id": "doc-2", "input": "Text 2"},
    ])
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import anyio

from ryuu.factory import Agent

__all__ = ["BatchRunner", "BatchItem", "BatchAPIClient", "OpenAIBatchClient"]

_log = logging.getLogger(__name__)


@runtime_checkable
class BatchAPIClient(Protocol):
    """Protocol for OpenAI Batch API operations.

    Tests inject a fake implementation. Production uses `OpenAIBatchClient`.
    """

    async def upload_input_file(self, jsonl_bytes: bytes) -> str:
        """Upload JSONL → return file_id."""
        ...

    async def create_batch(
        self, input_file_id: str, endpoint: str, completion_window: str
    ) -> str:
        """Create batch → return batch_id."""
        ...

    async def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        """Return dict with: id, status, output_file_id, error_file_id."""
        ...

    async def download_file(self, file_id: str) -> str:
        """Download file content as text."""
        ...


class OpenAIBatchClient:
    """Production OpenAIBatch API client using the official openai SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        from openai import AsyncOpenAI   # local import — only when used
        self._client = AsyncOpenAI(api_key=api_key)

    async def upload_input_file(self, jsonl_bytes: bytes) -> str:
        file_obj = await self._client.files.create(
            file=jsonl_bytes, purpose="batch",
        )
        return file_obj.id

    async def create_batch(
        self, input_file_id: str, endpoint: str, completion_window: str
    ) -> str:
        batch = await self._client.batches.create(
            input_file_id=input_file_id,
            endpoint=endpoint,
            completion_window=completion_window,
        )
        return batch.id

    async def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        batch = await self._client.batches.retrieve(batch_id)
        return {
            "id": batch.id,
            "status": batch.status,
            "output_file_id": getattr(batch, "output_file_id", None),
            "error_file_id": getattr(batch, "error_file_id", None),
        }

    async def download_file(self, file_id: str) -> str:
        resp = await self._client.files.content(file_id)
        return resp.text


@dataclass
class BatchItem:
    """Wraps an AgentResult with the original input id + optional error."""

    id: str
    task_id: str = ""
    output: str = ""
    error: Exception | None = None
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchRunner:
    """Process N inputs through an Agent in batch.

    `max_concurrent`: cap on parallel `.run()` calls (gather mode). Default 10.
    `on_error`: 'raise' (halt on first error) or 'collect' (continue, mark item).
    `mode`: 'gather' (default) or 'openai_batch' (50% discount, stub for now).
    """

    agent: Agent
    max_concurrent: int = 10
    on_error: Literal["raise", "collect"] = "raise"
    mode: Literal["gather", "openai_batch"] = "gather"

    # Phase 12.1 — OpenAI Batch API config (only used when mode='openai_batch')
    batch_client: BatchAPIClient | None = None
    poll_interval_s: float = 30.0
    completion_window: str = "24h"
    batch_endpoint: str = "/v1/chat/completions"

    async def run(self, inputs: list[Any]) -> list[Any]:
        """Process inputs. Returns ordered list matching input length.

        Item types in input list:
          - str        → returns AgentResult (or BatchItem if any other item is dict)
          - dict (`{"id": str, "input": str}`) → returns BatchItem with id preserved
        """
        if not inputs:
            return []

        # Normalize inputs to (id, prompt) tuples
        any_dict = any(isinstance(item, dict) for item in inputs)
        normalized: list[tuple[str, str]] = []
        for i, item in enumerate(inputs):
            if isinstance(item, dict):
                normalized.append((str(item.get("id", f"item-{i}")), str(item["input"])))
            else:
                normalized.append((f"item-{i}", str(item)))

        if self.mode == "openai_batch":
            return await self._run_openai_batch(normalized, any_dict)

        results: list[Any] = [None] * len(normalized)
        sem = anyio.Semaphore(self.max_concurrent)

        async def _one(idx: int, item_id: str, prompt: str) -> None:
            async with sem:
                try:
                    r = await self.agent.run(prompt)
                    if any_dict:
                        results[idx] = BatchItem(
                            id=item_id, task_id=r.task_id, output=r.output,
                            cost_usd=r.cost.usd if r.cost else 0.0,
                        )
                    else:
                        results[idx] = r
                except Exception as exc:
                    if self.on_error == "raise":
                        raise
                    results[idx] = BatchItem(id=item_id, error=exc)

        async with anyio.create_task_group() as tg:
            for idx, (item_id, prompt) in enumerate(normalized):
                tg.start_soon(_one, idx, item_id, prompt)

        return results

    # ------------------------------------------------------------------
    # OpenAI Batch API (Phase 12.1)
    # ------------------------------------------------------------------

    async def _run_openai_batch(
        self, normalized: list[tuple[str, str]], any_dict: bool
    ) -> list[Any]:
        """Submit batch → poll → download → parse → map back to input order."""
        client = self.batch_client or OpenAIBatchClient()
        model = self.agent._agent._model_name  # type: ignore[attr-defined]
        system_prompt = self.agent._agent.system_prompt  # type: ignore[attr-defined]

        # 1. Build JSONL — one chat completion request per input
        lines: list[str] = []
        for item_id, prompt in normalized:
            body: dict[str, Any] = {
                "model": model,
                "messages": (
                    ([{"role": "system", "content": system_prompt}] if system_prompt else [])
                    + [{"role": "user", "content": prompt}]
                ),
            }
            if self.agent.max_tokens is not None:
                body["max_tokens"] = self.agent.max_tokens
            body["temperature"] = self.agent.temperature
            lines.append(json.dumps({
                "custom_id": item_id,
                "method": "POST",
                "url": self.batch_endpoint,
                "body": body,
            }))
        jsonl = ("\n".join(lines) + "\n").encode("utf-8")

        # 2. Upload + create batch
        input_file_id = await client.upload_input_file(jsonl)
        batch_id = await client.create_batch(
            input_file_id=input_file_id,
            endpoint=self.batch_endpoint,
            completion_window=self.completion_window,
        )

        # 3. Poll until terminal state
        terminal = {"completed", "failed", "expired", "cancelled"}
        while True:
            status_info = await client.get_batch_status(batch_id)
            status = status_info.get("status", "unknown")
            _log.debug("batch %s status=%s", batch_id, status)
            if status in terminal:
                break
            await anyio.sleep(self.poll_interval_s)

        if status != "completed":
            raise RuntimeError(
                f"OpenAI batch {batch_id} ended with status={status!r}. "
                f"error_file_id={status_info.get('error_file_id')}"
            )

        # 4. Download + parse output JSONL
        output_file_id = status_info.get("output_file_id")
        if not output_file_id:
            raise RuntimeError(f"Batch {batch_id} completed but no output_file_id")
        output_text = await client.download_file(output_file_id)

        # Map custom_id → (content, error)
        outputs_by_id: dict[str, tuple[str, dict | None]] = {}
        for line in output_text.strip().split("\n"):
            if not line:
                continue
            parsed = json.loads(line)
            cid = parsed.get("custom_id", "")
            err = parsed.get("error")
            content = ""
            if not err and parsed.get("response"):
                try:
                    content = parsed["response"]["body"]["choices"][0]["message"]["content"]
                except (KeyError, IndexError):
                    content = ""
            outputs_by_id[cid] = (content, err)

        # 5. Build results in input order
        results: list[Any] = []
        for item_id, _ in normalized:
            content, err = outputs_by_id.get(item_id, ("", {"error": "missing"}))
            if err:
                error_exc = RuntimeError(f"{err.get('code', 'unknown')}: {err.get('message', '')}")
                if self.on_error == "raise":
                    raise error_exc
                results.append(BatchItem(id=item_id, error=error_exc))
            else:
                results.append(BatchItem(id=item_id, output=content))

        # If user passed plain strings (no dicts), the BatchItem wrapper is still
        # returned — `any_dict=False` could imply unwrap, but for openai_batch we
        # always return BatchItem to expose `.id` (custom_id).
        _ = any_dict
        return results
