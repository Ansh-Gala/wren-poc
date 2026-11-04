"""One chat's working state in this process: its conversation state,
debug log and lock."""

from __future__ import annotations

import threading
import time

from pipeline.context import ConversationState
from pipeline.models import Session

from server.config import STATE_EXPIRY_SECONDS

# --------------------------------------------------------------- sessions --

class Conversation:
    """One thread: its state, its transcript, and a lock.

    The lock matters because a turn takes seconds and mutates the state in
    place. Two overlapping requests on one session would interleave a repair,
    a classification and a state update, and the resulting context would belong
    to neither turn.
    """

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.state = ConversationState()
        self.session = Session(session_id=session_id, turns=[])
        self.lock = threading.Lock()
        self.turn_index = 0
        # Full responses for recent turns, so switching debug on can fill in
        # answers already on screen without re-running anything. Kept here
        # rather than sent and hidden: with debug off the SQL must not reach
        # the browser at all, which is the whole point of the switch. Its own
        # lock: reading or appending it must not wait for a whole turn.
        self.debug_log: list[dict] = []
        self.debug_lock = threading.Lock()
        # When the state was last saved, by the monotonic clock. None until
        # the first turn.
        self.saved_at: float | None = None
        # The chat's PII aliases while it is not saved (SAVE_CHATS=false, or
        # save_chat: false); otherwise they are read from the saved turns.
        self.aliases: list[dict] = []

    def expire_if_idle(self) -> None:
        """Start the working state over when it has sat unused for
        STATE_EXPIRY_SECONDS, as Drupal's expiring key-value store drops it.
        The turns, the turn count and the debug log are kept."""
        if self.saved_at is not None and time.monotonic() - self.saved_at > STATE_EXPIRY_SECONDS:
            self.state = ConversationState()
            self.session = Session(session_id=self.id, turns=[])
            self.saved_at = None

    def reset(self) -> None:
        self.state = ConversationState()
        self.session = Session(session_id=self.id, turns=[])
        self.turn_index = 0
        with self.debug_lock:
            self.debug_log.clear()


# Keyed by user and session: one user's session id never reaches another's
# state, as the saved chat is keyed by both.
SESSIONS: dict[tuple[int, str], Conversation] = {}


SESSIONS_LOCK = threading.Lock()


def conversation_for(session_id: str, user_id: int = 0) -> Conversation:
    with SESSIONS_LOCK:
        key = (user_id, session_id)
        if key not in SESSIONS:
            SESSIONS[key] = Conversation(session_id)
        return SESSIONS[key]
