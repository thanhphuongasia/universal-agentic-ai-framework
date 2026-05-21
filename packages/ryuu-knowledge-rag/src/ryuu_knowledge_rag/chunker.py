"""IChunker Protocol + RecursiveChunker — Phase 11."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Chunk:
    """One chunk produced by a chunker."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IChunker(Protocol):
    """Split a document into Chunks."""

    chunker_id: str

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[Chunk]: ...


@dataclass
class RecursiveChunker:
    """Character-count splitting with overlap. Splits on natural boundaries.

    Strategy:
      1. If text ≤ chunk_size, return single chunk
      2. Else: walk text, prefer split at \\n\\n > \\n > ". " > " "
      3. Each chunk overlaps `overlap` chars with previous (preserves context)

    Defaults tuned for English / code (~1500 chars ≈ 400 tokens at gpt-4o-mini).
    """

    chunker_id: str = "recursive"
    chunk_size: int = 1500
    overlap: int = 200

    # Order matters: try \n\n first, then \n, then ". ", then " "
    _SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ")

    def chunk(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> list[Chunk]:
        if not text:
            return []
        metadata = metadata or {}
        if len(text) <= self.chunk_size:
            return [Chunk(text=text, metadata=metadata)]

        chunks: list[Chunk] = []
        start = 0
        idx = 0
        while start < len(text):
            end = start + self.chunk_size
            if end >= len(text):
                chunks.append(Chunk(
                    text=text[start:],
                    metadata={**metadata, "chunk_index": idx},
                ))
                break

            # Find best split point near end
            split_at = self._find_split(text, start, end)
            chunks.append(Chunk(
                text=text[start:split_at],
                metadata={**metadata, "chunk_index": idx},
            ))
            # Next chunk starts with overlap
            start = max(split_at - self.overlap, start + 1)
            idx += 1
        return chunks

    def _find_split(self, text: str, start: int, ideal_end: int) -> int:
        """Search backwards from ideal_end for the best separator."""
        # Search window: from (ideal_end - overlap*2) to ideal_end
        window_start = max(start + self.chunk_size // 2, ideal_end - self.overlap * 2)
        for sep in self._SEPARATORS:
            pos = text.rfind(sep, window_start, ideal_end)
            if pos != -1:
                return pos + len(sep)
        # Hard cut at ideal_end
        return ideal_end


__all__ = ["Chunk", "IChunker", "RecursiveChunker"]
