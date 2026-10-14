"""Parse RAGFlow chunk ``available`` / ``available_int`` fields."""

from __future__ import annotations

from typing import Any


def parse_chunk_available(raw: dict[str, Any]) -> bool:
    """Return whether a chunk is enabled for retrieval (default: True)."""
    if "available" in raw:
        val = raw["available"]
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "yes")
    if "available_int" in raw and raw["available_int"] is not None:
        return int(raw["available_int"]) != 0
    return True


def filter_chunks_for_retrieval(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude chunks with ``available=false`` from Q&A and recall."""
    return [
        ck
        for ck in chunks
        if isinstance(ck, dict) and parse_chunk_available(ck)
    ]
