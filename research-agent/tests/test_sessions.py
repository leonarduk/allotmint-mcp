"""Unit tests for the in-memory conversation-history store (#548).

`app.sessions` is exercised directly here (not through `run_research`) so the
cap/eviction/unknown-id behavior is checked without needing a scripted model or
fake MCP session.
"""

from __future__ import annotations

from app.sessions import SessionStore


class _FakeMessage:
    """Stand-in for a pydantic_ai `ModelMessage` -- these tests never inspect
    message content, only that the store returns exactly what was saved."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FakeMessage) and self.label == other.label

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"_FakeMessage({self.label!r})"


def test_an_unknown_session_id_returns_an_empty_history():
    store = SessionStore()

    assert store.get("never-seen") == []


def test_save_then_get_round_trips_the_history():
    store = SessionStore()
    messages = [_FakeMessage("q1"), _FakeMessage("a1")]

    store.save("conv-1", messages, max_sessions=10, max_messages_per_session=10)

    assert store.get("conv-1") == messages


def test_get_returns_a_copy_not_the_stored_list():
    # Guards against a caller mutating the list they got back and corrupting
    # what a later turn sees.
    store = SessionStore()
    store.save("conv-1", [_FakeMessage("q1")], max_sessions=10, max_messages_per_session=10)

    fetched = store.get("conv-1")
    fetched.append(_FakeMessage("tampered"))

    assert store.get("conv-1") == [_FakeMessage("q1")]


def test_max_messages_per_session_keeps_only_the_most_recent_tail():
    store = SessionStore()
    messages = [_FakeMessage(f"m{i}") for i in range(10)]

    store.save("conv-1", messages, max_sessions=10, max_messages_per_session=3)

    assert store.get("conv-1") == messages[-3:]


def test_max_sessions_evicts_the_least_recently_used_session():
    store = SessionStore()
    store.save("conv-1", [_FakeMessage("a")], max_sessions=2, max_messages_per_session=10)
    store.save("conv-2", [_FakeMessage("b")], max_sessions=2, max_messages_per_session=10)
    # Touch conv-1 so it is more recently used than conv-2.
    store.get("conv-1")

    # Adding a third session over the cap of 2 must evict the least recently
    # used one -- conv-2, not conv-1, since conv-1 was just touched.
    store.save("conv-3", [_FakeMessage("c")], max_sessions=2, max_messages_per_session=10)

    assert store.get("conv-2") == []
    assert store.get("conv-1") == [_FakeMessage("a")]
    assert store.get("conv-3") == [_FakeMessage("c")]
    assert len(store) == 2


def test_zero_max_sessions_disables_the_cap():
    store = SessionStore()
    for i in range(5):
        store.save(f"conv-{i}", [_FakeMessage("x")], max_sessions=0, max_messages_per_session=10)

    assert len(store) == 5


def test_zero_max_messages_disables_the_per_session_cap():
    store = SessionStore()
    messages = [_FakeMessage(f"m{i}") for i in range(50)]

    store.save("conv-1", messages, max_sessions=10, max_messages_per_session=0)

    assert store.get("conv-1") == messages


def test_save_replaces_rather_than_appends():
    store = SessionStore()
    store.save("conv-1", [_FakeMessage("first")], max_sessions=10, max_messages_per_session=10)

    store.save("conv-1", [_FakeMessage("second")], max_sessions=10, max_messages_per_session=10)

    assert store.get("conv-1") == [_FakeMessage("second")]
