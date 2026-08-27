"""In-memory active live session store (single-user localhost)."""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from roulette_optimizer.play import LiveSession
from roulette_optimizer.policy import LoadedPolicy
from roulette_optimizer.policy_verifier import VerificationResult
from roulette_optimizer.saved_session import SessionSource


@dataclass
class ActiveLiveSessionEntry:
    session_id: str
    session: LiveSession
    loaded: LoadedPolicy
    verification: VerificationResult
    solver: str
    policy_identity: dict[str, Any]
    terminal_status: str | None = None

    @property
    def play(self) -> LiveSession:
        """Backward compatibility alias."""
        return self.session


class ActiveLiveSessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session_locks: dict[str, threading.Lock] = {}
        self._entries: dict[str, ActiveLiveSessionEntry] = {}

    def _session_lock(self, session_id: str) -> threading.Lock:
        with self._lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session_id] = lock
            return lock

    @contextmanager
    def mutate_session(self, session_id: str) -> Iterator[None]:
        """Serialize mutations for one active session."""
        with self._session_lock(session_id):
            yield

    def create(
        self,
        loaded: LoadedPolicy,
        bankroll: int,
        verification: VerificationResult,
        *,
        solver: str,
        policy_identity: dict[str, Any],
        source: SessionSource = "MANUAL",
    ) -> str:
        session_id = uuid.uuid4().hex
        live = LiveSession(loaded, bankroll, source=source, session_id=session_id)
        entry = ActiveLiveSessionEntry(
            session_id=session_id,
            session=live,
            loaded=loaded,
            verification=verification,
            solver=solver,
            policy_identity=policy_identity,
        )
        with self._lock:
            self._entries[session_id] = entry
        return session_id

    def get(self, session_id: str) -> ActiveLiveSessionEntry | None:
        with self._lock:
            return self._entries.get(session_id)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._entries.pop(session_id, None)
            self._session_locks.pop(session_id, None)

    def set_terminal(self, session_id: str, status: str) -> None:
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is not None:
                entry.terminal_status = status


LivePlayStore = ActiveLiveSessionStore
LivePlayStoreEntry = ActiveLiveSessionEntry

play_store = ActiveLiveSessionStore()
