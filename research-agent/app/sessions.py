"""In-memory conversation-history store keyed by `session_id`.

Issue #548: `allotmint_research` was single-shot -- every call started a fresh
`agent.run(prompt)` with no memory of anything said before it. This gives a
client (Claude Desktop, the webui, `mcp-client`) an opt-in way to hold a real
back-and-forth conversation by passing the same `session_id` on every `ask`
call; the sidecar threads the stored `pydantic_ai` message history into
`agent.run(prompt, message_history=...)` on each turn.

Deliberately in-memory only, per the issue's decision:

* No new persistence layer, no schema migration -- a session is lost if the
  sidecar process restarts. Callers must not assume durability across a
  restart, which is exactly why an unrecognized `session_id` starts a fresh,
  empty history instead of erroring (see `get`).
* Single sidecar instance only. This does not solve multi-instance /
  horizontally-scaled deployments; there is no shared session store. That is a
  known limitation, not an oversight -- see the `allotmint_research` section
  of the root README.
* Bounded, not unbounded: `max_sessions` caps how many conversations are held
  at once (oldest evicted first, LRU by last-touched time) and
  `max_messages_per_session` caps how much history one conversation can carry
  (oldest messages dropped first). Both mirror the existing
  `Settings.max_tool_calls` / `MAX_TOOL_RESULT_CHARS` cap-not-unbounded-growth
  precedent (#466, #578) applied to the new growth axis a multi-turn session
  introduces.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

log = logging.getLogger(__name__)


class SessionStore:
    """Thread-safe LRU store of conversation history, one entry per session_id."""

    def __init__(self) -> None:
        self._sessions: "OrderedDict[str, tuple[float, list[ModelMessage]]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list["ModelMessage"]:
        """Returns the stored history for `session_id`, or `[]` if unknown.

        An unrecognized or expired session_id (e.g. the sidecar restarted
        mid-conversation) returns an empty history rather than raising, so a
        client doesn't have to special-case "session expired" -- the next
        turn just starts fresh, silently, exactly like a brand-new session.
        """
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return []
            # Touch for LRU: a session that is actively being used should be
            # the last one evicted when the store is over max_sessions.
            self._sessions.move_to_end(session_id)
            return list(entry[1])

    def save(
        self,
        session_id: str,
        messages: list["ModelMessage"],
        max_sessions: int,
        max_messages_per_session: int,
    ) -> None:
        """Stores `messages` as the new history for `session_id`, capped and evicted.

        `messages` should be the full conversation so far (pydantic_ai's
        `result.all_messages()`), not just the latest turn -- this replaces
        whatever was stored before, it does not append.
        """
        if max_messages_per_session > 0 and len(messages) > max_messages_per_session:
            # Drop the oldest messages first. This is a blunt cap -- it can
            # split a request/response pair -- but it exists precisely so a
            # long-running conversation can't grow this process's memory
            # without bound; that trade-off is the one #548 asks for ("even a
            # simple fixed cap is fine for v1, but it must exist").
            messages = messages[-max_messages_per_session:]

        with self._lock:
            self._sessions[session_id] = (time.monotonic(), list(messages))
            self._sessions.move_to_end(session_id)
            while max_sessions > 0 and len(self._sessions) > max_sessions:
                evicted_id, _ = self._sessions.popitem(last=False)
                log.info(
                    "conversation session store over capacity (%d); evicted oldest session %s",
                    max_sessions,
                    evicted_id,
                )

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


# Module-level singleton: one store per sidecar process, matching the issue's
# "in-memory dict, scoped to the running process" decision. `main.py` builds a
# fresh `Settings` on every request (see `load_settings()`), so the store
# itself cannot live on `Settings` -- it is configured with whatever cap
# values the current request's settings carry, each time it is touched.
_store = SessionStore()


def get_history(session_id: str | None) -> list["ModelMessage"]:
    """Looks up stored history for `session_id`; `None` always returns `[]`."""
    if not session_id:
        return []
    return _store.get(session_id)


def save_history(
    session_id: str | None,
    messages: list["ModelMessage"],
    max_sessions: int,
    max_messages_per_session: int,
) -> None:
    """Persists `messages` for `session_id`; a no-op when `session_id` is absent.

    This is how "no session_id supplied at all = today's single-shot
    behavior, unchanged" is enforced: nothing is ever written to the store
    for a request that didn't ask to participate in one.
    """
    if not session_id:
        return
    _store.save(session_id, messages, max_sessions, max_messages_per_session)


def session_count() -> int:
    """Current number of live sessions -- exposed for `/health`."""
    return len(_store)
