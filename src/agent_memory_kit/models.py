"""Domain values and the serialized subject aggregate."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def require_revision(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class Scope:
    tenant: str
    subject: str

    def __post_init__(self) -> None:
        require_text(self.tenant, "tenant")
        require_text(self.subject, "subject")

    @property
    def key(self) -> str:
        return fingerprint([self.tenant, self.subject])


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    FORGOTTEN = "forgotten"


@dataclass(frozen=True)
class Observation:
    event_id: str
    source_key: str
    source_version: int
    content: str
    evidence: tuple[str, ...]
    kind: str = "observation"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        for name in ("event_id", "source_key", "content", "kind"):
            require_text(getattr(self, name), name)
        require_revision(self.source_version, "source_version", 1)
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("evidence must be a nonempty tuple of source references")
        for reference in self.evidence:
            require_text(reference, "evidence reference")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be finite and between 0 and 1")


@dataclass(frozen=True)
class Memory:
    id: str
    source_key: str
    source_version: int
    content: str
    evidence: tuple[str, ...]
    kind: str
    confidence: float
    version: int = 1
    status: MemoryStatus = MemoryStatus.ACTIVE
    user_override: bool = False


@dataclass(frozen=True)
class Operation:
    id: str
    memory_id: str
    action: str
    revision: int
    memory_version: int


@dataclass(frozen=True)
class Receipt:
    digest: str
    memory_id: str
    outcome: str


@dataclass
class SubjectState:
    revision: int = 0
    memories: dict[str, Memory] = field(default_factory=dict)
    receipts: dict[str, Receipt] = field(default_factory=dict)
    operations: list[Operation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SubjectState:
        memories = {}
        for key, value in raw.get("memories", {}).items():
            value = dict(value)
            value["evidence"] = tuple(value["evidence"])
            value["status"] = MemoryStatus(value["status"])
            memories[key] = Memory(**value)
        return cls(
            revision=raw["revision"],
            memories=memories,
            receipts={key: Receipt(**value) for key, value in raw.get("receipts", {}).items()},
            operations=[Operation(**value) for value in raw.get("operations", [])],
        )


@dataclass(frozen=True)
class MutationResult:
    memory: Memory
    outcome: str
    revision: int
    replayed: bool = False


class ContextKitError(Exception):
    """Base exception for state and context failures."""


class RevisionConflict(ContextKitError):
    """A concurrent write or stale memory version prevented this mutation."""


class EventConflict(ContextKitError):
    """An event identity or source version was reused with a different payload."""


class MemoryNotFound(ContextKitError):
    """The memory does not exist in the supplied scope."""


class MemoryInactive(ContextKitError):
    """A forgotten memory cannot be corrected."""
