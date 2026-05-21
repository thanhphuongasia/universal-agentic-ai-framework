"""Phase 9.3 — QueuedFileAuditStore tests."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from ryuu_observability.audit import (
    AuditConfig,
    AuditEvent,
    AuditLogger,
    QueuedFileAuditStore,
)


def _make_event(idx: int) -> AuditEvent:
    return AuditEvent(
        timestamp_utc="2026-01-01T00:00:00Z",
        correlation_id=f"c-{idx}",
        scope_key="test",
        agent_id="a-1",
        event_type="start",
        payload={"i": idx},
        payload_hash=f"ph-{idx}",
        chain_hash=f"ch-{idx}",
    )


async def test_queued_append_returns_immediately(tmp_path: Path) -> None:
    """append() is non-blocking — no disk I/O on call path."""
    store = QueuedFileAuditStore(str(tmp_path / "audit.jsonl"))
    # 100 appends should complete instantly
    for i in range(100):
        store.append(_make_event(i))
    # File should be empty or not yet flushed (worker async)
    # last_chain_hash reflects most recent enqueue
    assert store.last_chain_hash() == "ch-99"


async def test_queued_flushes_to_disk_after_interval(tmp_path: Path) -> None:
    """Background worker flushes batch to disk within flush_interval."""
    path = tmp_path / "audit.jsonl"
    store = QueuedFileAuditStore(str(path), flush_interval_ms=50)
    for i in range(5):
        store.append(_make_event(i))
    # Wait for worker to flush
    await anyio.sleep(0.2)
    # File should exist with 5 lines
    assert path.exists()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 5
    assert json.loads(lines[0])["correlation_id"] == "c-0"


async def test_queued_shutdown_drains_remaining(tmp_path: Path) -> None:
    """shutdown() flushes any queued events before returning."""
    path = tmp_path / "audit.jsonl"
    store = QueuedFileAuditStore(str(path), flush_interval_ms=10000)  # long interval

    for i in range(3):
        store.append(_make_event(i))

    await store.shutdown()
    # All 3 events flushed
    assert path.exists()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 3


async def test_audit_logger_via_queued_file_backend(tmp_path: Path) -> None:
    """AuditConfig(backend='queued_file') wires QueuedFileAuditStore."""
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(config=AuditConfig(
        backend="queued_file",
        file_path=str(path),
    ))
    assert isinstance(logger._store, QueuedFileAuditStore)

    logger.log_start(
        task_id="t1", agent_id="a1", scope_key="s1",
        correlation_id="c1", payload={"x": 1},
    )
    # last hash updates immediately
    assert logger.last_chain_hash() != ""


def test_audit_config_queued_file_requires_path() -> None:
    """`backend='queued_file'` without file_path → ValueError."""
    with pytest.raises(ValueError, match="file_path"):
        AuditLogger(config=AuditConfig(backend="queued_file"))
