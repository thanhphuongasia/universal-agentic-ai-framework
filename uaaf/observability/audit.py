"""Immutable structured audit log with hash-chain integrity.

Design:
- Each event includes a ``chain_hash`` = sha256(previous_chain_hash + payload_json).
- This allows tamper detection: any modification breaks the chain.
- v0 backend: JSONL append-only file + console stderr.
- Phase 5: swap backend via IAuditStore Protocol (S3, Postgres, etc.).
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEvent:
    timestamp_utc: str
    correlation_id: str
    scope_key: str
    agent_id: str
    event_type: str  # "start" | "complete" | "error"
    payload: dict[str, Any]
    payload_hash: str   # sha256(json(payload))
    chain_hash: str     # sha256(previous_chain_hash + payload_hash)

    def as_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass(frozen=True)
class AuditConfig:
    """Configuration for AuditLogger."""

    backend: str = "console"     # "console" | "file"
    file_path: str | None = None  # required when backend="file"
    retention_days: int = 2557   # ~7 years default (Stock compliance)


# ---------------------------------------------------------------------------
# Storage protocol + backends
# ---------------------------------------------------------------------------


@runtime_checkable
class IAuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def last_chain_hash(self) -> str: ...


_GENESIS_HASH = hashlib.sha256(b"uaaf-genesis").hexdigest()


class ConsoleAuditStore:
    """Write events to stderr as JSON lines (no persistence)."""

    def __init__(self) -> None:
        self._last_hash = _GENESIS_HASH

    def append(self, event: AuditEvent) -> None:
        print(event.as_json(), file=sys.stderr)
        self._last_hash = event.chain_hash

    def last_chain_hash(self) -> str:
        return self._last_hash


class FileAuditStore:
    """Append events to a JSONL file."""

    def __init__(self, file_path: str) -> None:
        self._path = file_path
        self._last_hash = _GENESIS_HASH
        # Restore last hash from existing file if present.
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


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


def _make_store(config: AuditConfig) -> IAuditStore:
    if config.backend == "file":
        if not config.file_path:
            raise ValueError("AuditConfig.file_path required when backend='file'")
        return FileAuditStore(config.file_path)
    return ConsoleAuditStore()


def _hash_payload(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload_json.encode()).hexdigest()


def _chain(previous_hash: str, payload_hash: str) -> str:
    return hashlib.sha256((previous_hash + payload_hash).encode()).hexdigest()


class AuditLogger:
    """Append-only structured audit log with hash-chain tamper detection.

    All methods are *synchronous* so they can be called inside async code
    without await — JSONL append is fast enough for Phase 0.
    """

    def __init__(self, config: AuditConfig | None = None) -> None:
        self._config = config or AuditConfig()
        self._store: IAuditStore = _make_store(self._config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_start(self, task_id: str, agent_id: str, scope_key: str, correlation_id: str, payload: dict[str, Any] | None = None) -> None:
        self._write("start", task_id, agent_id, scope_key, correlation_id, payload or {})

    def log_complete(self, task_id: str, agent_id: str, scope_key: str, correlation_id: str, payload: dict[str, Any] | None = None) -> None:
        self._write("complete", task_id, agent_id, scope_key, correlation_id, payload or {})

    def log_error(self, task_id: str, agent_id: str, scope_key: str, correlation_id: str, exc: BaseException) -> None:
        self._write(
            "error",
            task_id,
            agent_id,
            scope_key,
            correlation_id,
            {"error_type": type(exc).__name__, "error_message": str(exc)},
        )

    def last_chain_hash(self) -> str:
        """Return the chain hash of the last event (for integrity verification)."""
        return self._store.last_chain_hash()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(
        self,
        event_type: str,
        task_id: str,
        agent_id: str,
        scope_key: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
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
    """Return True if the hash chain of *events* is intact (no tampering)."""
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
