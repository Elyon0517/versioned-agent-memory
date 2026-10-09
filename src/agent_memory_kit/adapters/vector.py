"""A scoped cosine index with atomic projection replacement."""

from __future__ import annotations

import math
from threading import RLock

from agent_memory_kit.models import Scope, require_revision
from agent_memory_kit.ports import VectorEntry, VectorHit, require_vector


def _unit(vector: tuple[float, ...]) -> tuple[float, ...]:
    peak = max(abs(value) for value in vector)
    if not peak:
        return tuple(0.0 for _ in vector)
    scaled = tuple(value / peak for value in vector)
    norm = math.sqrt(sum(value * value for value in scaled))
    return tuple(value / norm for value in scaled)


class InMemoryVectorIndex:
    def __init__(self) -> None:
        self._projections: dict[str, tuple[int, tuple[VectorEntry, ...]]] = {}
        self._lock = RLock()

    def replace(self, scope: Scope, revision: int, entries: tuple[VectorEntry, ...]) -> bool:
        require_revision(revision, "revision")
        if not isinstance(entries, tuple) or any(
            not isinstance(entry, VectorEntry) for entry in entries
        ):
            raise ValueError("projection entries must be a tuple of VectorEntry values")
        for entry in entries:
            require_vector(entry.vector)
        if len({entry.memory_id for entry in entries}) != len(entries):
            raise ValueError("duplicate memory ID in projection")
        if len({len(entry.vector) for entry in entries}) > 1:
            raise ValueError("projection vectors must have the same dimensions")
        with self._lock:
            previous = self._projections.get(scope.key)
            if previous is not None and previous[0] > revision:
                return False
            if previous is not None and previous[0] == revision and previous[1] != entries:
                raise ValueError("projection revision reused with different entries")
            self._projections[scope.key] = (revision, entries)
            return True

    def search(self, scope: Scope, query: tuple[float, ...], limit: int) -> list[VectorHit]:
        require_vector(query)
        require_revision(limit, "limit", 1)
        with self._lock:
            entries = self._projections.get(scope.key, (0, ()))[1]
        unit_query = _unit(query)
        hits = []
        for entry in entries:
            if len(entry.vector) != len(query):
                raise ValueError("query dimensions do not match projection")
            score = sum(a * b for a, b in zip(unit_query, _unit(entry.vector), strict=True))
            score = min(1.0, max(-1.0, score))
            hits.append(VectorHit(scope, entry.memory_id, entry.memory_version, score))
        return sorted(hits, key=lambda hit: (-hit.score, hit.memory_id))[:limit]
