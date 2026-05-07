"""Tests for uaaf.observability.audit — T05."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from uaaf.observability.audit import (
    _GENESIS_HASH,
    AuditConfig,
    AuditEvent,
    AuditLogger,
    verify_chain,
)


def _make_logger(backend: str = "console", file_path: str | None = None) -> AuditLogger:
    return AuditLogger(AuditConfig(backend=backend, file_path=file_path))


# ---------------------------------------------------------------------------
# Event structure
# ---------------------------------------------------------------------------


def test_log_start_creates_event(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_start("t1", "agent1", "dom:u:s", "corr-1")
    out = capsys.readouterr().err
    data = json.loads(out.strip())
    assert data["event_type"] == "start"
    assert data["agent_id"] == "agent1"
    assert data["correlation_id"] == "corr-1"
    assert "payload_hash" in data
    assert "chain_hash" in data
    assert "timestamp_utc" in data


def test_log_complete_event_type(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_complete("t1", "agent1", "dom:u:s", "corr-1")
    out = capsys.readouterr().err
    data = json.loads(out.strip())
    assert data["event_type"] == "complete"


def test_log_error_event_type(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_error("t1", "agent1", "dom:u:s", "corr-1", ValueError("oops"))
    out = capsys.readouterr().err
    data = json.loads(out.strip())
    assert data["event_type"] == "error"
    assert "ValueError" in data["payload"]["error_type"]


# ---------------------------------------------------------------------------
# Hash chain integrity
# ---------------------------------------------------------------------------


def test_hash_chain_first_event_based_on_genesis(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_start("t1", "a", "s", "c")
    out = capsys.readouterr().err
    data = json.loads(out.strip())
    # chain_hash of first event is sha256(genesis + payload_hash)
    import hashlib

    expected_ch = hashlib.sha256((_GENESIS_HASH + data["payload_hash"]).encode()).hexdigest()
    assert data["chain_hash"] == expected_ch


def test_hash_chain_second_event_uses_first_chain_hash(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_start("t1", "a", "s", "c")
    logger.log_complete("t1", "a", "s", "c")
    out = capsys.readouterr().err
    lines = [json.loads(line) for line in out.strip().splitlines() if line]
    first, second = lines
    import hashlib

    expected = hashlib.sha256((first["chain_hash"] + second["payload_hash"]).encode()).hexdigest()
    assert second["chain_hash"] == expected


def test_verify_chain_passes_on_valid_events(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_start("t1", "a", "s", "c")
    logger.log_complete("t1", "a", "s", "c")
    out = capsys.readouterr().err
    events = [AuditEvent(**json.loads(line)) for line in out.strip().splitlines() if line]
    assert verify_chain(events) is True


def test_verify_chain_fails_on_tampered_payload(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_start("t1", "a", "s", "c")
    out = capsys.readouterr().err
    data = json.loads(out.strip())
    # Tamper the payload
    data["payload"]["task_id"] = "tampered"
    tampered = AuditEvent(**data)
    assert verify_chain([tampered]) is False


def test_verify_chain_fails_on_tampered_chain_hash(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_start("t1", "a", "s", "c")
    logger.log_complete("t1", "a", "s", "c")
    out = capsys.readouterr().err
    lines = out.strip().splitlines()
    first_data = json.loads(lines[0])
    second_data = json.loads(lines[1])
    # Tamper first event's chain_hash
    first_data["chain_hash"] = "deadbeef" * 8
    events = [AuditEvent(**first_data), AuditEvent(**second_data)]
    assert verify_chain(events) is False


def test_verify_chain_empty_list_is_valid() -> None:
    assert verify_chain([]) is True


# ---------------------------------------------------------------------------
# File backend
# ---------------------------------------------------------------------------


def test_file_backend_appends_jsonl() -> None:
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        path = tmp.name

    logger = AuditLogger(AuditConfig(backend="file", file_path=path))
    logger.log_start("t1", "a", "s", "c")
    logger.log_complete("t1", "a", "s", "c")

    lines = Path(path).read_text().strip().splitlines()
    assert len(lines) == 2
    events = [AuditEvent(**json.loads(line)) for line in lines]
    assert verify_chain(events) is True


def test_file_backend_resumes_chain_on_restart() -> None:
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        path = tmp.name

    # First logger session
    logger1 = AuditLogger(AuditConfig(backend="file", file_path=path))
    logger1.log_start("t1", "a", "s", "c")
    first_hash = logger1.last_chain_hash()

    # Second logger session (restart)
    logger2 = AuditLogger(AuditConfig(backend="file", file_path=path))
    assert logger2.last_chain_hash() == first_hash

    logger2.log_complete("t1", "a", "s", "c")
    lines = Path(path).read_text().strip().splitlines()
    events = [AuditEvent(**json.loads(line)) for line in lines]
    assert verify_chain(events) is True


def test_scope_isolation_in_events(capsys: pytest.CaptureFixture[str]) -> None:
    logger = _make_logger()
    logger.log_start("t1", "a", "scope1", "c")
    logger.log_start("t2", "b", "scope2", "c")
    out = capsys.readouterr().err
    events = [json.loads(line) for line in out.strip().splitlines() if line]
    assert events[0]["scope_key"] == "scope1"
    assert events[1]["scope_key"] == "scope2"
