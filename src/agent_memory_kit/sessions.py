"""Thread-safe session history with expiry and revision-checked summaries."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import RLock

from agent_memory_kit.models import EventConflict, RevisionConflict, Scope, require_text


@dataclass(frozen=True)
class Message:
    id: str
    role: str
    content: str

    def __post_init__(self) -> None:
        require_text(self.id, "message id")
        require_text(self.content, "message content")
        if self.role not in {"user", "assistant", "tool"}:
            raise ValueError("role must be user, assistant, or tool")


@dataclass(frozen=True)
class SessionSummary:
    content: str
    through_message_id: str
    revision: int


@dataclass(frozen=True)
class Session:
    revision: int = 0
    messages: tuple[Message, ...] = ()
    summary: SessionSummary | None = None
    expires_at: float | None = None


class SessionMemory:
    """Process-local reference store. TTL is fixed from session creation, not sliding."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._sessions: dict[tuple[str, str], Session] = {}
        self._lock = RLock()

    def _key(self, scope: Scope, session_id: str) -> tuple[str, str]:
        require_text(session_id, "session_id")
        return scope.key, session_id

    def load(self, scope: Scope, session_id: str) -> Session:
        key = self._key(scope, session_id)
        with self._lock:
            state = self._sessions.get(key, Session())
            if state.expires_at is not None and self._clock() >= state.expires_at:
                self._sessions.pop(key, None)
                return Session()
            return state

    def append(
        self, scope: Scope, session_id: str, message: Message, *, ttl: float | None = None
    ) -> Session:
        if not isinstance(message, Message):
            raise ValueError("message must be a Message")
        if ttl is not None and (
            isinstance(ttl, bool)
            or not isinstance(ttl, (int, float))
            or not math.isfinite(ttl)
            or ttl <= 0
        ):
            raise ValueError("ttl must be finite and positive")
        key = self._key(scope, session_id)
        with self._lock:
            state = self.load(scope, session_id)
            for previous in state.messages:
                if previous.id == message.id:
                    if previous != message:
                        raise EventConflict("message ID reused with different content")
                    return state
            expiry = state.expires_at
            if state.revision == 0 and ttl is not None:
                expiry = self._clock() + ttl
            updated = replace(
                state,
                revision=state.revision + 1,
                messages=(*state.messages, message),
                expires_at=expiry,
            )
            self._sessions[key] = updated
            return updated

    def summarize(
        self,
        scope: Scope,
        session_id: str,
        summarizer: Callable[[tuple[Message, ...]], str],
    ) -> Session:
        state = self.load(scope, session_id)
        if not state.messages:
            return state
        content = summarizer(state.messages)
        require_text(content, "summary")
        key = self._key(scope, session_id)
        with self._lock:
            # Identity check also detects deletion, expiry and recreation at the same revision.
            current = self.load(scope, session_id)
            if current is not state:
                raise RevisionConflict("session changed while summary was being generated")
            updated = replace(
                state,
                revision=state.revision + 1,
                summary=SessionSummary(content, state.messages[-1].id, state.revision),
            )
            self._sessions[key] = updated
            return updated

    def clear(self, scope: Scope, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(self._key(scope, session_id), None)
