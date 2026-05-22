"""Immutable structured audit log with hash-chain integrity.

Phase 9.3 adds `QueuedFileAuditStore` — non-blocking write via background
worker. `append()` is `queue.put_nowait()` (no I/O); a background task batches
events + flushes to disk every 100ms or 1000 events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AuditEvent:
    timestamp_utc: str
    correlation_id: str
    scope_key: str
    agent_id: str
    event_type: str
    payload: dict[str, Any]
    payload_hash: str
    chain_hash: str

    def as_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass(frozen=True)
class AuditConfig:
    backend: str = "console"
    file_path: str | None = None
    retention_days: int = 2557


@runtime_checkable
class IAuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def last_chain_hash(self) -> str: ...


_GENESIS_HASH = hashlib.sha256(b"ryuu-genesis").hexdigest()


class ConsoleAuditStore:
    def __init__(self) -> None:
        self._last_hash = _GENESIS_HASH

    def append(self, event: AuditEvent) -> None:
        print(event.as_json(), file=sys.stderr)
        self._last_hash = event.chain_hash

    def last_chain_hash(self) -> str:
        return self._last_hash


class FileAuditStore:
    def __init__(self, file_path: str) -> None:
        self._path = file_path
        self._last_hash = _GENESIS_HASH
        try:
            with open(file_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        evt = json.loads(line)
                        self._last_hash = evt.get("chain_hash", _GENESIS_HASH)
        except FileNotFoundError:
            pass

    def append(self, event: AuditEvent) -> None:
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(event.as_json() + "\n")
        self._last_hash = event.chain_hash

    def last_chain_hash(self) -> str:
        return self._last_hash


class QueuedFileAuditStore:
    """Non-blocking file audit store (Phase 9.3).

    `append()` is fire-and-forget: enqueues event, returns immediately. A
    background worker task batches events from the queue and flushes to disk
    every `flush_interval_ms` OR when batch reaches `max_batch_size`.

    Trade-off vs `FileAuditStore`:
      - ✅ append() is non-blocking (no disk I/O on request path)
      - ⚠️ Events not durably persisted at moment of return — may lose last
        ~100ms of events on hard crash.
      - ⚠️ Requires running event loop (worker lazily spawned on first append).

    For strict compliance audit (financial/medical), use `FileAuditStore`
    (synchronous, durable per-event).
    """

    def __init__(
        self,
        file_path: str,
        flush_interval_ms: int = 100,
        max_batch_size: int = 1000,
    ) -> None:
        self._path = file_path
        self._last_hash = _GENESIS_HASH
        self._flush_interval_s = flush_interval_ms / 1000.0
        self._max_batch_size = max_batch_size
        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._shutdown = False

        # Read existing file for chain-hash resume
        try:
            with open(file_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        evt = json.loads(line)
                        self._last_hash = evt.get("chain_hash", _GENESIS_HASH)
        except FileNotFoundError:
            pass

    def append(self, event: AuditEvent) -> None:
        """Non-blocking: enqueue event + ensure worker running."""
        # Update last_hash synchronously so caller observers see chain progress.
        self._last_hash = event.chain_hash
        self._queue.put_nowait(event)
        self._ensure_worker()

    def last_chain_hash(self) -> str:
        return self._last_hash

    def _ensure_worker(self) -> None:
        """Lazily spawn worker on first append (needs event loop)."""
        if self._worker_task is not None and not self._worker_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop — worker can't start; events stay queued
        self._worker_task = loop.create_task(self._worker())

    async def _worker(self) -> None:
        """Background drain: batch events from queue, flush periodically."""
        while not self._shutdown:
            batch: list[AuditEvent] = []
            try:
                # Wait for at least one event
                first = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval_s
                )
                batch.append(first)
            except asyncio.TimeoutError:
                continue

            # Drain queue up to max_batch_size
            while len(batch) < self._max_batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if batch:
                self._flush_batch(batch)

    def _flush_batch(self, batch: list[AuditEvent]) -> None:
        """Write batch to disk (single open() + concatenated writes)."""
        with open(self._path, "a", encoding="utf-8") as fh:
            for event in batch:
                fh.write(event.as_json() + "\n")

    async def shutdown(self) -> None:
        """Graceful shutdown: drain queue + flush remaining events."""
        self._shutdown = True
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
        # Final drain
        remaining: list[AuditEvent] = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining:
            self._flush_batch(remaining)


def _make_store(config: AuditConfig) -> IAuditStore:
    if config.backend == "file":
        if not config.file_path:
            raise ValueError("AuditConfig.file_path required when backend='file'")
        return FileAuditStore(config.file_path)
    if config.backend == "queued_file":
        if not config.file_path:
            raise ValueError("AuditConfig.file_path required when backend='queued_file'")
        return QueuedFileAuditStore(config.file_path)
    return ConsoleAuditStore()


def _hash_payload(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload_json.encode()).hexdigest()


def _chain(previous_hash: str, payload_hash: str) -> str:
    return hashlib.sha256((previous_hash + payload_hash).encode()).hexdigest()


class AuditLogger:
    """Append-only structured audit log with hash-chain tamper detection."""

    def __init__(self, config: AuditConfig | None = None) -> None:
        self._config = config or AuditConfig()
        self._store: IAuditStore = _make_store(self._config)

    def log_start(self, task_id: str, agent_id: str, scope_key: str, correlation_id: str, payload: dict[str, Any] | None = None) -> None:
        self._write("start", task_id, agent_id, scope_key, correlation_id, payload or {})

    def log_complete(self, task_id: str, agent_id: str, scope_key: str, correlation_id: str, payload: dict[str, Any] | None = None) -> None:
        self._write("complete", task_id, agent_id, scope_key, correlation_id, payload or {})

    def log_error(self, task_id: str, agent_id: str, scope_key: str, correlation_id: str, exc: BaseException) -> None:
        self._write("error", task_id, agent_id, scope_key, correlation_id,
                    {"error_type": type(exc).__name__, "error_message": str(exc)})

    def last_chain_hash(self) -> str:
        return self._store.last_chain_hash()

    def _write(self, event_type: str, task_id: str, agent_id: str, scope_key: str, correlation_id: str, payload: dict[str, Any]) -> None:
        full_payload = {"task_id": task_id, **payload}
        ph = _hash_payload(full_payload)
        ch = _chain(self._store.last_chain_hash(), ph)
        event = AuditEvent(
            timestamp_utc=datetime.now(UTC).isoformat(),
            correlation_id=correlation_id,
            scope_key=scope_key,
            agent_id=agent_id,
            event_type=event_type,
            payload=full_payload,
            payload_hash=ph,
            chain_hash=ch,
        )
        self._store.append(event)


def verify_chain(events: list[AuditEvent]) -> bool:
    """Return True if the hash chain of events is intact."""
    if not events:
        return True
    prev_hash = _GENESIS_HASH
    for event in events:
        expected_ph = _hash_payload(event.payload)
        if expected_ph != event.payload_hash:
            return False
        expected_ch = _chain(prev_hash, event.payload_hash)
        if expected_ch != event.chain_hash:
            return False
        prev_hash = event.chain_hash
    return True
