from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from agent_memory_kit import (
    EventConflict,
    MemoryEngine,
    MemoryInactive,
    MemoryNotFound,
    MemoryStatus,
    Observation,
    RevisionConflict,
    Scope,
)
from agent_memory_kit.adapters import InMemoryStore

from .conftest import observation


def test_replayed_event_does_not_change_revision(engine, scope):
    first = engine.observe(scope, observation())
    repeated = engine.observe(scope, observation())
    assert repeated.replayed
    assert repeated.memory.id == first.memory.id
    assert repeated.revision == first.revision
    assert len(engine.store.load(scope).operations) == 1


def test_reused_event_id_with_changed_payload_fails(engine, scope):
    engine.observe(scope, observation())
    with pytest.raises(EventConflict):
        engine.observe(scope, observation(content="Detailed replies"))
    assert engine.active(scope)[0].content == "Short replies"


def test_new_source_version_replaces_content_and_evidence(engine, scope):
    initial = engine.observe(scope, observation())
    updated = engine.observe(scope, observation(2, content="Detailed replies"))
    assert updated.memory.id == initial.memory.id
    assert updated.memory.version == 2
    assert updated.memory.evidence == ("source-record:2",)
    assert updated.memory.source_version == 2
    assert len(engine.active(scope)) == 1


def test_out_of_order_source_version_cannot_overwrite(engine, scope):
    engine.observe(scope, observation(2, content="Current"))
    late = engine.observe(scope, observation())
    assert late.outcome == "stale_source"
    assert late.memory.content == "Current"
    assert late.memory.evidence == ("source-record:2",)


def test_equal_source_version_requires_equal_payload(engine, scope):
    engine.observe(scope, observation())
    with pytest.raises(EventConflict):
        engine.observe(scope, observation(event_id="alternate", content="Different"))
    result = engine.observe(scope, observation(event_id="delivery-2"))
    assert result.outcome == "unchanged"
    assert result.memory.version == 1


def test_correction_preserves_lineage_and_blocks_future_inference(engine, scope):
    memory = engine.observe(scope, observation()).memory
    corrected = engine.correct(
        scope,
        memory.id,
        "Detailed replies",
        evidence=("user-message:7",),
        expected_version=1,
        operation_id="correct-7",
    )
    assert corrected.memory.evidence == ("source-record:1", "user-message:7")
    assert corrected.memory.user_override
    assert corrected.memory.confidence == memory.confidence
    inferred = engine.observe(scope, observation(3, content="Short replies"))
    assert inferred.outcome == "protected_by_user"
    assert inferred.memory.content == "Detailed replies"
    assert inferred.memory.version == 2


def test_forget_clears_content_and_prevents_resurrection(engine, scope):
    initial = engine.observe(scope, observation()).memory
    forgotten = engine.forget(scope, initial.id, expected_version=1, operation_id="forget-1")
    assert forgotten.memory.status == MemoryStatus.FORGOTTEN
    assert forgotten.memory.content == ""
    assert forgotten.memory.evidence == ()
    assert engine.active(scope) == ()
    late = engine.observe(scope, observation(20, content="Late inference"))
    assert late.outcome == "blocked_by_forget"
    assert engine.active(scope) == ()
    replay = engine.observe(scope, observation())
    assert replay.replayed
    assert replay.memory.status == MemoryStatus.FORGOTTEN


@pytest.mark.parametrize("action", ["correct", "forget"])
def test_user_operations_are_idempotent(engine, scope, action):
    memory = engine.observe(scope, observation()).memory
    args = {"expected_version": 1, "operation_id": "user:op.$1"}
    if action == "correct":
        result = engine.correct(scope, memory.id, "New", evidence=("user:1",), **args)
        replay = engine.correct(scope, memory.id, "New", evidence=("user:1",), **args)
    else:
        result = engine.forget(scope, memory.id, **args)
        replay = engine.forget(scope, memory.id, **args)
    assert replay.replayed
    assert replay.revision == result.revision
    assert len(engine.store.load(scope).operations) == 2


def test_stale_user_edit_is_rejected(engine, scope):
    memory = engine.observe(scope, observation()).memory
    engine.observe(scope, observation(2))
    with pytest.raises(RevisionConflict):
        engine.correct(
            scope,
            memory.id,
            "New",
            evidence=("user:1",),
            expected_version=1,
            operation_id="edit",
        )


def test_forgotten_memory_cannot_be_corrected(engine, scope):
    memory = engine.observe(scope, observation()).memory
    engine.forget(scope, memory.id, expected_version=1, operation_id="forget")
    with pytest.raises(MemoryInactive):
        engine.correct(
            scope,
            memory.id,
            "New",
            evidence=("user:1",),
            expected_version=2,
            operation_id="edit",
        )


@pytest.mark.parametrize("other", [Scope("team-b", "user-1"), Scope("team-a", "user-2")])
def test_memory_control_is_scoped(engine, scope, other):
    memory = engine.observe(scope, observation()).memory
    with pytest.raises(MemoryNotFound):
        engine.forget(other, memory.id, expected_version=1, operation_id="foreign")
    assert len(engine.active(scope)) == 1
    assert engine.active(other) == ()


def test_identical_source_and_event_ids_are_isolated_by_scope(engine, scope):
    first = engine.observe(scope, observation()).memory
    second = engine.observe(Scope("team-b", scope.subject), observation()).memory
    assert first.id != second.id


def test_public_state_load_is_detached(engine, scope):
    engine.observe(scope, observation())
    state = engine.store.load(scope)
    state.memories.clear()
    state.receipts.clear()
    assert len(engine.active(scope)) == 1
    assert engine.observe(scope, observation()).replayed


def test_many_source_versions_converge_to_latest():
    engine = MemoryEngine(InMemoryStore(), max_retries=200)
    scope = Scope("team", "user")
    versions = list(range(1, 61)) + list(range(1, 61))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda version: engine.observe(
                    scope, observation(version, content=str(version))
                ),
                versions,
            )
        )
    (memory,) = engine.active(scope)
    assert memory.source_version == 60
    assert memory.content == "60"
    assert len(engine.store.load(scope).receipts) == 60


def test_stale_compare_and_swap_cannot_overwrite_committed_state(engine, scope):
    stale = engine.store.load(scope)
    engine.observe(scope, observation())
    stale.revision = 1
    assert not engine.store.compare_and_swap(scope, 0, stale)
    assert len(engine.active(scope)) == 1


def test_correct_retries_unrelated_write_without_losing_other_memory():
    class InterleavingStore(InMemoryStore):
        armed = False

        def compare_and_swap(self, scope, expected_revision, state):
            if self.armed:
                self.armed = False
                MemoryEngine(self).observe(scope, observation(event_id="other", source="other"))
            return super().compare_and_swap(scope, expected_revision, state)

    store = InterleavingStore()
    engine = MemoryEngine(store)
    scope = Scope("team", "user")
    memory = engine.observe(scope, observation()).memory
    store.armed = True
    engine.correct(
        scope,
        memory.id,
        "New",
        evidence=("user:1",),
        expected_version=1,
        operation_id="correct",
    )
    assert len(engine.active(scope)) == 2
    assert store.load(scope).revision == 3


def test_correct_cannot_overwrite_concurrent_edit():
    class InterleavingStore(InMemoryStore):
        armed = False

        def compare_and_swap(self, scope, expected_revision, state):
            if self.armed:
                self.armed = False
                MemoryEngine(self).observe(scope, observation(2, content="Concurrent"))
            return super().compare_and_swap(scope, expected_revision, state)

    store = InterleavingStore()
    engine = MemoryEngine(store)
    scope = Scope("team", "user")
    memory = engine.observe(scope, observation()).memory
    store.armed = True
    with pytest.raises(RevisionConflict):
        engine.correct(
            scope,
            memory.id,
            "New",
            evidence=("user:1",),
            expected_version=1,
            operation_id="correct",
        )
    assert engine.active(scope)[0].content == "Concurrent"


def test_retry_exhaustion_exposes_conflict():
    class ContendedStore(InMemoryStore):
        def compare_and_swap(self, scope, expected_revision, state):
            return False

    with pytest.raises(RevisionConflict):
        MemoryEngine(ContendedStore(), max_retries=2).observe(
            Scope("team", "user"), observation()
        )


@pytest.mark.parametrize("version", [0, -1, True, 1.5])
def test_invalid_source_revision_is_rejected(version):
    with pytest.raises(ValueError):
        observation(version)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_invalid_confidence_is_rejected(confidence):
    with pytest.raises(ValueError):
        replace(observation(), confidence=confidence)


def test_missing_evidence_is_rejected():
    with pytest.raises(ValueError):
        Observation("event", "source", 1, "value", ())


def test_unknown_commit_result_can_be_retried_without_duplicate_effect():
    class UncertainStore(InMemoryStore):
        uncertain = True

        def compare_and_swap(self, scope, expected_revision, state):
            result = super().compare_and_swap(scope, expected_revision, state)
            if self.uncertain:
                self.uncertain = False
                raise TimeoutError("reply lost after commit")
            return result

    engine = MemoryEngine(UncertainStore())
    scope = Scope("team", "user")
    with pytest.raises(TimeoutError):
        engine.observe(scope, observation())
    result = engine.observe(scope, observation())
    assert result.replayed and result.revision == 1
    assert len(engine.store.load(scope).operations) == 1


def test_scope_delimiters_cannot_create_namespace_collision():
    assert Scope("a:b", "c").key != Scope("a", "b:c").key
