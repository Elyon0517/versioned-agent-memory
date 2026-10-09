import pytest

from agent_memory_kit import EventConflict, Message, RevisionConflict, Scope, SessionMemory


def test_scope_isolation_and_replay():
    sessions = SessionMemory()
    scope = Scope("tenant", "user")
    message = Message("1", "user", "hello")
    first = sessions.append(scope, "a", message)
    assert sessions.append(scope, "a", message) is first
    for other, session in (
        (Scope("other", "user"), "a"),
        (Scope("tenant", "other"), "a"),
        (scope, "b"),
    ):
        assert sessions.load(other, session).messages == ()
    with pytest.raises(EventConflict):
        sessions.append(scope, "a", Message("1", "user", "different"))


def test_fixed_ttl_and_summary_expiry():
    now = [10.0]
    sessions = SessionMemory(clock=lambda: now[0])
    scope = Scope("t", "u")
    sessions.append(scope, "s", Message("1", "user", "first"), ttl=5)
    now[0] = 14
    state = sessions.append(scope, "s", Message("2", "assistant", "reply"), ttl=100)
    assert state.expires_at == 15
    now[0] = 15
    assert sessions.load(scope, "s").messages == ()
    sessions.append(scope, "s", Message("3", "user", "fresh"), ttl=5)
    assert sessions.load(scope, "s").revision == 1


def test_summary_covers_snapshot_and_preserves_tail():
    sessions = SessionMemory()
    scope = Scope("t", "u")
    sessions.append(scope, "s", Message("1", "user", "first"))
    state = sessions.summarize(scope, "s", lambda messages: messages[0].content)
    assert state.summary.content == "first"
    assert state.summary.through_message_id == "1"
    tail = sessions.append(scope, "s", Message("2", "user", "next"))
    assert tail.summary == state.summary


@pytest.mark.parametrize("mutation", ["append", "clear", "recreate", "expire"])
def test_stale_summary_rejected(mutation):
    now = [0.0]
    sessions = SessionMemory(clock=lambda: now[0])
    scope = Scope("t", "u")
    sessions.append(scope, "s", Message("1", "user", "old"), ttl=10)

    def summarize(messages):
        if mutation == "append":
            sessions.append(scope, "s", Message("2", "user", "new"))
        elif mutation in {"clear", "recreate"}:
            sessions.clear(scope, "s")
            if mutation == "recreate":
                sessions.append(scope, "s", Message("1", "user", "replacement"))
        else:
            now[0] = 10
        return "old summary"

    with pytest.raises(RevisionConflict):
        sessions.summarize(scope, "s", summarize)
    assert sessions.load(scope, "s").summary is None


@pytest.mark.parametrize("ttl", [0, -1, float("nan"), float("inf"), True, "1"])
def test_invalid_ttl(ttl):
    with pytest.raises(ValueError):
        SessionMemory().append(Scope("t", "u"), "s", Message("1", "user", "x"), ttl=ttl)
