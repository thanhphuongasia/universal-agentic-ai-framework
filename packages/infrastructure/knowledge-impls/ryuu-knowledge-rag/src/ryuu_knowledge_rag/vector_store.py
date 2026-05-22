"""IVectorStore Protocol + InMemoryVectorStore — Phase 11."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class VectorRecord:
    """One stored vector + metadata."""

    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    """Single search hit with similarity score."""

    record: VectorRecord
    score: float   # 0.0 - 1.0, higher = more similar


@runtime_checkable
class IVectorStore(Protocol):
    """Vector store contract — upsert + cosine search."""

    async def upsert(self, records: list[VectorRecord]) -> None: ...

    async def search(
        self, query_vector: list[float], top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]: ...

    async def delete(self, ids: list[str]) -> None: ...

    async def count(self) -> int: ...


class InMemoryVectorStore:
    """Numpy-backed in-memory vector store. Cosine similarity search.

    Production: swap for Chroma/Qdrant/Pinecone via same IVectorStore protocol.
    """

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}
        self._matrix: np.ndarray | None = None
        self._matrix_ids: list[str] = []
        self._dirty = False

    async def upsert(self, records: list[VectorRecord]) -> None:
        for r in records:
            self._records[r.id] = r
        self._dirty = True

    async def search(
        self, query_vector: list[float], top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if not self._records:
            return []
        self._rebuild_matrix_if_dirty()
        assert self._matrix is not None

        q = np.asarray(query_vector, dtype=np.float32)
        # Cosine = dot(q, v) / (|q| * |v|). Matrix already L2-normalized.
        q_norm = q / (np.linalg.norm(q) + 1e-9)
        scores = self._matrix @ q_norm   # (N,) array

        # Apply metadata filter
        candidate_indices = list(range(len(self._matrix_ids)))
        if filter_metadata:
            candidate_indices = [
                i for i in candidate_indices
                if _matches(self._records[self._matrix_ids[i]].metadata, filter_metadata)
            ]

        if not candidate_indices:
            return []

        # Top-K from candidates
        candidate_scores = scores[candidate_indices]
        top_k = min(top_k, len(candidate_indices))
        # argpartition for partial sort (faster than full sort for top-k)
        if top_k >= len(candidate_indices):
            order = np.argsort(-candidate_scores)
        else:
            partition = np.argpartition(-candidate_scores, top_k)[:top_k]
            order = partition[np.argsort(-candidate_scores[partition])]

        return [
            SearchResult(
                record=self._records[self._matrix_ids[candidate_indices[i]]],
                score=float(candidate_scores[i]),
            )
            for i in order
        ]

    async def delete(self, ids: list[str]) -> None:
        for id_ in ids:
            self._records.pop(id_, None)
        self._dirty = True

    async def count(self) -> int:
        return len(self._records)

    def _rebuild_matrix_if_dirty(self) -> None:
        if not self._dirty:
            return
        if not self._records:
            self._matrix = None
            self._matrix_ids = []
            self._dirty = False
            return
        ids = list(self._records.keys())
        vectors = np.array(
            [self._records[i].vector for i in ids],
            dtype=np.float32,
        )
        # L2-normalize so cosine = dot product
        norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
        self._matrix = vectors / norms
        self._matrix_ids = ids
        self._dirty = False


def _matches(metadata: dict[str, Any], filter_: dict[str, Any]) -> bool:
    return all(metadata.get(k) == v for k, v in filter_.items())


__all__ = ["VectorRecord", "SearchResult", "IVectorStore", "InMemoryVectorStore"]
