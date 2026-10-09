"""Versioned memory mutations and canonical validation of derived retrieval."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from agent_memory_kit.models import (
    EventConflict,
    Memory,
    MemoryInactive,
    MemoryNotFound,
    MemoryStatus,
    MutationResult,
    Observation,
    Operation,
    Receipt,
    RevisionConflict,
    Scope,
    SubjectState,
    fingerprint,
    require_revision,
    require_text,
)
from agent_memory_kit.ports import Embedder, SubjectStore, VectorEntry, VectorIndex


class MemoryEngine:
    def __init__(self, store: SubjectStore, *, max_retries: int = 16) -> None:
        require_revision(max_retries, "max_retries", 1)
        self.store = store
        self.max_retries = max_retries

    @staticmethod
    def memory_id(scope: Scope, source_key: str) -> str:
        require_text(source_key, "source_key")
        return str(uuid5(NAMESPACE_URL, fingerprint([scope.key, source_key])))

    @staticmethod
    def _replay(state: SubjectState, event_id: str, digest: str) -> MutationResult | None:
        receipt = state.receipts.get(fingerprint(event_id))
        if receipt is None:
            return None
        if receipt.digest != digest:
            raise EventConflict("event ID reused with a different payload")
        return MutationResult(
            state.memories[receipt.memory_id], receipt.outcome, state.revision, replayed=True
        )

    def _commit(
        self,
        scope: Scope,
        state: SubjectState,
        memory: Memory,
        *,
        event_id: str,
        digest: str,
        outcome: str,
    ) -> MutationResult | None:
        expected = state.revision
        state.revision += 1
        state.memories[memory.id] = memory
        state.receipts[fingerprint(event_id)] = Receipt(digest, memory.id, outcome)
        state.operations.append(
            Operation(event_id, memory.id, outcome, state.revision, memory.version)
        )
        if self.store.compare_and_swap(scope, expected, state):
            return MutationResult(memory, outcome, state.revision)
        return None

    def observe(self, scope: Scope, observation: Observation) -> MutationResult:
        digest = fingerprint({"action": "observe", **asdict(observation)})
        memory_id = self.memory_id(scope, observation.source_key)
        for _ in range(self.max_retries):
            state = self.store.load(scope)
            replay = self._replay(state, observation.event_id, digest)
            if replay is not None:
                return replay
            current = state.memories.get(memory_id)
            if current is None:
                memory = Memory(
                    id=memory_id,
                    source_key=observation.source_key,
                    source_version=observation.source_version,
                    content=observation.content,
                    evidence=observation.evidence,
                    kind=observation.kind,
                    confidence=observation.confidence,
                )
                outcome = "created"
            elif current.status == MemoryStatus.FORGOTTEN:
                memory, outcome = current, "blocked_by_forget"
            elif current.user_override:
                memory, outcome = current, "protected_by_user"
            elif observation.source_version < current.source_version:
                memory, outcome = current, "stale_source"
            elif observation.source_version == current.source_version:
                if (
                    current.content != observation.content
                    or current.evidence != observation.evidence
                    or current.kind != observation.kind
                    or current.confidence != observation.confidence
                ):
                    raise EventConflict("source version reused with a different payload")
                memory, outcome = current, "unchanged"
            else:
                memory = replace(
                    current,
                    source_version=observation.source_version,
                    content=observation.content,
                    evidence=observation.evidence,
                    kind=observation.kind,
                    confidence=observation.confidence,
                    version=current.version + 1,
                )
                outcome = "updated"
            result = self._commit(
                scope,
                state,
                memory,
                event_id=observation.event_id,
                digest=digest,
                outcome=outcome,
            )
            if result is not None:
                return result
        raise RevisionConflict("subject was modified repeatedly; retry the event")

    def correct(
        self,
        scope: Scope,
        memory_id: str,
        content: str,
        *,
        evidence: tuple[str, ...],
        expected_version: int,
        operation_id: str,
    ) -> MutationResult:
        require_text(content, "content")
        if not isinstance(evidence, tuple) or not evidence:
            raise ValueError("correction requires a nonempty evidence tuple")
        for reference in evidence:
            require_text(reference, "evidence reference")
        return self._control(
            scope, memory_id, "correct", expected_version, operation_id, content, evidence
        )

    def forget(
        self,
        scope: Scope,
        memory_id: str,
        *,
        expected_version: int,
        operation_id: str,
    ) -> MutationResult:
        return self._control(scope, memory_id, "forget", expected_version, operation_id)

    def _control(
        self,
        scope: Scope,
        memory_id: str,
        action: Literal["correct", "forget"],
        expected_version: int,
        operation_id: str,
        content: str = "",
        evidence: tuple[str, ...] = (),
    ) -> MutationResult:
        require_text(memory_id, "memory_id")
        require_text(operation_id, "operation_id")
        require_revision(expected_version, "expected_version", 1)
        digest = fingerprint([action, memory_id, expected_version, content, evidence])
        for _ in range(self.max_retries):
            state = self.store.load(scope)
            replay = self._replay(state, operation_id, digest)
            if replay is not None:
                return replay
            current = state.memories.get(memory_id)
            if current is None:
                raise MemoryNotFound(memory_id)
            if current.version != expected_version:
                raise RevisionConflict("memory version changed; reload before editing")
            if current.status != MemoryStatus.ACTIVE:
                raise MemoryInactive(memory_id)
            if action == "correct":
                memory = replace(
                    current,
                    content=content,
                    evidence=tuple(dict.fromkeys((*current.evidence, *evidence))),
                    user_override=True,
                    version=current.version + 1,
                )
            else:
                memory = replace(
                    current,
                    content="",
                    evidence=(),
                    status=MemoryStatus.FORGOTTEN,
                    version=current.version + 1,
                )
            result = self._commit(
                scope, state, memory, event_id=operation_id, digest=digest, outcome=action
            )
            if result is not None:
                return result
        raise RevisionConflict("subject was modified repeatedly; retry the operation")

    def active(self, scope: Scope) -> tuple[Memory, ...]:
        return tuple(
            sorted(
                (
                    m
                    for m in self.store.load(scope).memories.values()
                    if m.status == MemoryStatus.ACTIVE
                ),
                key=lambda memory: memory.id,
            )
        )

    def project(self, scope: Scope, index: VectorIndex, embedder: Embedder) -> bool:
        state = self.store.load(scope)
        entries = tuple(
            VectorEntry(memory.id, memory.version, embedder.embed(memory.content))
            for memory in sorted(state.memories.values(), key=lambda memory: memory.id)
            if memory.status == MemoryStatus.ACTIVE
        )
        return index.replace(scope, state.revision, entries)

    def recall(
        self,
        scope: Scope,
        query: str,
        *,
        index: VectorIndex,
        embedder: Embedder,
        limit: int = 5,
        candidate_limit: int = 50,
    ) -> tuple[Memory, ...]:
        require_text(query, "query")
        require_revision(limit, "limit", 1)
        require_revision(candidate_limit, "candidate_limit", limit)
        hits = index.search(scope, embedder.embed(query), candidate_limit)
        state = self.store.load(scope)
        recalled: dict[str, Memory] = {}
        for hit in hits:
            if hit.scope != scope:
                continue
            memory = state.memories.get(hit.memory_id)
            if (
                memory is not None
                and memory.status == MemoryStatus.ACTIVE
                and memory.version == hit.memory_version
            ):
                recalled[memory.id] = memory
            if len(recalled) == limit:
                break
        return tuple(recalled.values())
