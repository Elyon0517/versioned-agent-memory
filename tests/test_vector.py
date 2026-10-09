import pytest

from agent_memory_kit import Scope
from agent_memory_kit.adapters import InMemoryVectorIndex
from agent_memory_kit.ports import VectorEntry, VectorHit

from .conftest import observation


class DemoEmbedder:
    def embed(self, text):
        return (1.0, 0.0) if "Short" in text else (0.0, 1.0)


def test_stale_index_cannot_recall_forgotten_memory(engine, scope):
    index = InMemoryVectorIndex()
    embedder = DemoEmbedder()
    memory = engine.observe(scope, observation()).memory
    engine.project(scope, index, embedder)
    assert engine.recall(scope, "Short", index=index, embedder=embedder) == (memory,)
    engine.forget(scope, memory.id, expected_version=1, operation_id="forget")
    assert index.search(scope, (1.0, 0.0), 5)
    assert engine.recall(scope, "Short", index=index, embedder=embedder) == ()


def test_stale_index_version_is_rejected_after_correction(engine, scope):
    index = InMemoryVectorIndex()
    embedder = DemoEmbedder()
    memory = engine.observe(scope, observation()).memory
    engine.project(scope, index, embedder)
    corrected = engine.correct(
        scope,
        memory.id,
        "Detailed",
        evidence=("user:2",),
        expected_version=1,
        operation_id="edit",
    ).memory
    assert engine.recall(scope, "Detailed", index=index, embedder=embedder) == ()
    engine.project(scope, index, embedder)
    assert engine.recall(scope, "Detailed", index=index, embedder=embedder) == (corrected,)


def test_projection_rejects_out_of_order_replacement(scope):
    index = InMemoryVectorIndex()
    newer = (VectorEntry("memory", 2, (1.0,)),)
    assert index.replace(scope, 2, newer)
    assert not index.replace(scope, 1, ())
    assert index.search(scope, (1.0,), 1)[0].memory_version == 2
    with pytest.raises(ValueError):
        index.replace(scope, 2, ())


def test_foreign_and_duplicate_hits_are_filtered(engine, scope):
    memory = engine.observe(scope, observation()).memory

    class UntrustedIndex:
        def search(self, scope, query, limit):
            return [
                VectorHit(Scope("foreign", scope.subject), memory.id, 1, 1.0),
                VectorHit(scope, "missing", 1, 1.0),
                VectorHit(scope, memory.id, 1, 1.0),
                VectorHit(scope, memory.id, 1, 1.0),
            ]

    result = engine.recall(scope, "Short", index=UntrustedIndex(), embedder=DemoEmbedder())
    assert result == (memory,)


def test_recall_reads_canonical_state_after_index_query(engine, scope):
    memory = engine.observe(scope, observation()).memory

    class InterleavingIndex:
        def search(self, scope, query, limit):
            engine.forget(scope, memory.id, expected_version=1, operation_id="forget")
            return [VectorHit(scope, memory.id, 1, 1.0)]

    assert (
        engine.recall(scope, "Short", index=InterleavingIndex(), embedder=DemoEmbedder()) == ()
    )


def test_empty_rebuild_removes_projection(engine, scope):
    index = InMemoryVectorIndex()
    embedder = DemoEmbedder()
    memory = engine.observe(scope, observation()).memory
    engine.project(scope, index, embedder)
    engine.forget(scope, memory.id, expected_version=1, operation_id="forget")
    assert engine.project(scope, index, embedder)
    assert index.search(scope, (1.0, 0.0), 5) == []


@pytest.mark.parametrize("vector", [(), (float("nan"),), (float("inf"),)])
def test_invalid_vectors_are_rejected(scope, vector):
    with pytest.raises(ValueError):
        InMemoryVectorIndex().replace(scope, 1, (VectorEntry("m", 1, vector),))


def test_vector_dimensions_are_checked(scope):
    index = InMemoryVectorIndex()
    index.replace(scope, 1, (VectorEntry("m", 1, (1.0, 0.0)),))
    with pytest.raises(ValueError, match="dimensions"):
        index.search(scope, (1.0,), 1)


def test_large_and_zero_vectors_have_finite_scores(scope):
    index = InMemoryVectorIndex()
    index.replace(
        scope,
        1,
        (
            VectorEntry("large", 1, (1e308, 1e308)),
            VectorEntry("zero", 1, (0.0, 0.0)),
        ),
    )
    hits = index.search(scope, (1e308, 1e308), 2)
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == 0.0


def test_cosine_ranking_and_scope_isolation(scope):
    index = InMemoryVectorIndex()
    index.replace(
        scope,
        1,
        (
            VectorEntry("match", 1, (1.0, 0.0)),
            VectorEntry("opposite", 1, (-1.0, 0.0)),
        ),
    )
    assert [hit.memory_id for hit in index.search(scope, (1.0, 0.0), 2)] == [
        "match",
        "opposite",
    ]
    assert index.search(Scope("foreign", scope.subject), (1.0, 0.0), 2) == []


def test_mutable_vector_cannot_bypass_projection_revision():
    vector = [1.0, 0.0]
    with pytest.raises(ValueError, match="tuples"):
        VectorEntry("memory", 1, vector)


def test_mutable_entries_cannot_change_committed_projection(scope):
    index = InMemoryVectorIndex()
    initial = (VectorEntry("current", 1, (1.0, 0.0)),)
    assert index.replace(scope, 1, initial)
    with pytest.raises(ValueError, match="tuple of VectorEntry"):
        index.replace(scope, 2, [VectorEntry("replacement", 1, (0.0, 1.0))])
    hits = index.search(scope, (1.0, 0.0), 5)
    assert [(hit.memory_id, hit.score) for hit in hits] == [("current", 1.0)]


@pytest.mark.parametrize("vector", [(True,), ("1",), (10**1000,)])
def test_invalid_vector_values_raise_validation_error(vector):
    with pytest.raises(ValueError, match="finite numbers"):
        VectorEntry("memory", 1, vector)


@pytest.mark.parametrize("version", [True, 0, -1, 1.5])
def test_vector_entry_versions_are_validated(version):
    with pytest.raises(ValueError, match="memory_version"):
        VectorEntry("memory", version, (1.0,))


def test_empty_vector_memory_id_is_rejected():
    with pytest.raises(ValueError, match="memory_id"):
        VectorEntry("", 1, (1.0,))


def test_mutable_query_vector_is_rejected(scope):
    with pytest.raises(ValueError, match="tuples"):
        InMemoryVectorIndex().search(scope, [1.0], 1)
