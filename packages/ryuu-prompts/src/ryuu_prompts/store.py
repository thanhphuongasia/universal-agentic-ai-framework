"""Prompt lifecycle store — versioning + promotion on top of PromptConfig.

``PromptConfig`` (models.py) covers *what a prompt version is* (content, params,
render). This module adds the generic *lifecycle* layer:

  * ``status`` — draft → staging → archived
  * an **active pointer** per suite (which version is live)
  * ``promote()`` — make a version live, stamping who/when

Maps 1-1 onto the ``prompt_versions`` table + ``suites.active_prompt_version_id``
(docs/eval-prompt-store-schema.sql). Both the eval suite and the production
service resolve their live prompt through one path — no second prompt store.

``'production'`` is deliberately NOT a status value. It is *derived*: the live
version is whichever one the suite's active pointer currently references.

Backends follow the framework's storage pattern (IKVStore → InMemoryKVStore →
PostgresKVStore): depend on ``IPromptStore``, inject a concrete impl.
``InMemoryPromptStore`` ships here for tests + framework default; a
Postgres-backed impl maps the same Protocol onto the SQL tables.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from ryuu_prompts.models import PromptConfig


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class PromptStatus(str, Enum):
    """Lifecycle state of a prompt version. Matches the SQL CHECK constraint.

    Note: there is no ``PRODUCTION`` — live-ness is the active pointer, not a state.
    """

    DRAFT = "draft"
    STAGING = "staging"
    ARCHIVED = "archived"


@dataclass
class PromptVersion:
    """One ``prompt_versions`` row: a PromptConfig plus lifecycle metadata."""

    id: str
    suite_id: str
    version: str                       # e.g. "v1.3"
    config: PromptConfig
    status: PromptStatus = PromptStatus.DRAFT
    promoted_at: float | None = None   # unix epoch; None = never promoted
    promoted_by: str | None = None
    created_at: float = 0.0            # unix epoch; 0 = unknown


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PromptStoreError(Exception):
    """Base class for prompt store errors."""


class PromptVersionNotFoundError(PromptStoreError):
    """Requested (suite_id, version) does not exist."""


# ---------------------------------------------------------------------------
# IPromptStore — persisted versions + lifecycle + active pointer
# ---------------------------------------------------------------------------


@runtime_checkable
class IPromptStore(Protocol):
    """Versioned prompt storage with lifecycle and a per-suite active pointer.

    Async to match the framework's storage backends (the Postgres impl is
    asyncpg-backed). Depend on this Protocol, not a concrete store.
    """

    async def save(self, version: PromptVersion) -> None:
        """Upsert a version (keyed by suite_id + version)."""
        ...

    async def get(self, suite_id: str, version: str) -> PromptVersion | None:
        """Return the version, or None if absent. Never raises on missing."""
        ...

    async def list_versions(self, suite_id: str) -> list[PromptVersion]:
        """All versions for a suite, oldest first (created_at, then version)."""
        ...

    async def set_status(
        self, suite_id: str, version: str, status: PromptStatus
    ) -> PromptVersion:
        """Transition lifecycle state. Raises if the version is absent."""
        ...

    async def promote(self, suite_id: str, version: str, *, by: str) -> PromptVersion:
        """Make *version* the suite's live version; stamp promoted_at/by.

        Raises ``PromptVersionNotFoundError`` if absent, ``PromptStoreError`` if
        the version is archived (promoting a retired version is a footgun).
        """
        ...

    async def get_active(self, suite_id: str) -> PromptVersion | None:
        """Return the suite's currently live version, or None if none promoted."""
        ...


# ---------------------------------------------------------------------------
# InMemoryPromptStore — reference impl (tests + framework default)
# ---------------------------------------------------------------------------


class InMemoryPromptStore:
    """In-memory ``IPromptStore``. Not persistent; for tests and local use."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], PromptVersion] = {}
        self._active: dict[str, str] = {}  # suite_id → active version

    async def save(self, version: PromptVersion) -> None:
        self._versions[(version.suite_id, version.version)] = version

    async def get(self, suite_id: str, version: str) -> PromptVersion | None:
        return self._versions.get((suite_id, version))

    async def list_versions(self, suite_id: str) -> list[PromptVersion]:
        rows = [v for (s, _), v in self._versions.items() if s == suite_id]
        return sorted(rows, key=lambda v: (v.created_at, v.version))

    async def set_status(
        self, suite_id: str, version: str, status: PromptStatus
    ) -> PromptVersion:
        row = self._require(suite_id, version)
        row.status = status
        return row

    async def promote(self, suite_id: str, version: str, *, by: str) -> PromptVersion:
        row = self._require(suite_id, version)
        if row.status == PromptStatus.ARCHIVED:
            raise PromptStoreError(
                f"cannot promote archived version {suite_id}/{version}"
            )
        row.promoted_at = time.time()
        row.promoted_by = by
        self._active[suite_id] = version
        return row

    async def get_active(self, suite_id: str) -> PromptVersion | None:
        active = self._active.get(suite_id)
        return self._versions.get((suite_id, active)) if active else None

    def _require(self, suite_id: str, version: str) -> PromptVersion:
        row = self._versions.get((suite_id, version))
        if row is None:
            raise PromptVersionNotFoundError(f"{suite_id}/{version} not found")
        return row
