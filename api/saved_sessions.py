"""Persisted live session history (Manual + Companion) — memory + disk CSV/JSON."""

from __future__ import annotations

import threading
from pathlib import Path

from roulette_optimizer.saved_session import SavedLiveSession
from roulette_optimizer.saved_session_io import (
    default_saved_sessions_dir,
    delete_saved_session_files,
    load_all_saved_sessions,
    write_saved_session,
)


class SavedLiveSessionRepository:
    def __init__(self, root: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._root = root if root is not None else default_saved_sessions_dir()
        self._sessions: dict[str, SavedLiveSession] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        for session in load_all_saved_sessions(self._root):
            self._sessions[session.session_id] = session

    def save(self, session: SavedLiveSession) -> tuple[SavedLiveSession, Path, Path]:
        with self._lock:
            csv_path, json_path = write_saved_session(session, self._root)
            self._sessions[session.session_id] = session
        return session, csv_path, json_path

    def get(self, session_id: str) -> SavedLiveSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list_all(self) -> list[SavedLiveSession]:
        with self._lock:
            return list(self._sessions.values())

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            delete_saved_session_files(session_id, self._root)


saved_session_repository = SavedLiveSessionRepository()
