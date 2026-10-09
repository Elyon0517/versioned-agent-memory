"""Storage and projection contracts; implementations must isolate scopes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from agent_memory_kit.models import Scope, SubjectState, require_revision, require_text


def require_vector(vector: tuple[float, ...]) -> None:
    if not isinstance(vector, tuple) or not vector:
        raise ValueError("vectors must be nonempty tuples")
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("vector values must be finite numbers")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("vector values must be finite numbers")


class SubjectStore(Protocol):
    def load(self, scope: Scope) -> SubjectState: ...

    def compare_and_swap(
        self, scope: Scope, expected_revision: int, state: SubjectState
    ) -> bool:
        """Atomically commit the complete aggregate iff its revision still matches."""
        ...


class SnapshotCache(Protocol):
    def get(self, key: str) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...


@dataclass(frozen=True)
class VectorEntry:
    memory_id: str
    memory_version: int
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        require_text(self.memory_id, "memory_id")
        require_revision(self.memory_version, "memory_version", 1)
        require_vector(self.vector)


@dataclass(frozen=True)
class VectorHit:
    scope: Scope
    memory_id: str
    memory_version: int
    score: float


class VectorIndex(Protocol):
    def replace(self, scope: Scope, revision: int, entries: tuple[VectorEntry, ...]) -> bool:
        """Replace a scoped projection; reject an older revision atomically."""
        ...

    def search(self, scope: Scope, query: tuple[float, ...], limit: int) -> list[VectorHit]: ...


class Embedder(Protocol):
    def embed(self, text: str) -> tuple[float, ...]: ...
