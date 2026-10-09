from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from agent_memory_kit import MemoryEngine, Observation, Scope
from agent_memory_kit.adapters import InMemoryStore
from agent_memory_kit.adapters.mongo import MongoStore


@pytest.fixture(params=["memory", "mongo_mock"])
def store(request: pytest.FixtureRequest) -> object:
    if request.param == "memory":
        return InMemoryStore()
    import mongomock

    return MongoStore(mongomock.MongoClient().agent_memory_kit.subjects)


@pytest.fixture
def engine(store: object) -> MemoryEngine:
    return MemoryEngine(store)  # type: ignore[arg-type]


@pytest.fixture
def scope() -> Scope:
    return Scope("team-a", "user-1")


def observation(
    version: int = 1,
    *,
    event_id: str | None = None,
    source: str = "preference",
    content: str = "Short replies",
) -> Observation:
    return Observation(
        event_id or f"event-{version}", source, version, content, (f"source-record:{version}",)
    )


@pytest.fixture
def live_store() -> Iterator[MongoStore]:
    uri = os.environ.get("CONTEXTKIT_TEST_MONGO_URI")
    if not uri:
        pytest.skip("set CONTEXTKIT_TEST_MONGO_URI to an isolated test server")
    from uuid import uuid4

    from pymongo import MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    database = client[f"agent_memory_kit_test_{uuid4().hex}"]
    try:
        client.admin.command("ping")
        yield MongoStore(database.subjects)
    finally:
        client.drop_database(database.name)
        client.close()
