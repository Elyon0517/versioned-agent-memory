"""Thread-safe reference implementations for local applications and tests."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock

from agent_memory_kit.models import Scope, SubjectState


class InMemoryStore:
    def __init__(self) -> None:
        self._states: dict[str, SubjectState] = {}
        self._lock = RLock()

    def load(self, scope: Scope) -> SubjectState:
        with self._lock:
            return deepcopy(self._states.get(scope.key, SubjectState()))

    def compare_and_swap(
        self, scope: Scope, expected_revision: int, state: SubjectState
    ) -> bool:
        if state.revision != expected_revision + 1:
            raise ValueError("new revision must advance exactly once")
        with self._lock:
            current = self._states.get(scope.key, SubjectState())
            if current.revision != expected_revision:
                return False
            self._states[scope.key] = deepcopy(state)
            return True


class InMemoryCache:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = RLock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value
