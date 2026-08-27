"""Write saved live sessions to CSV summary + JSON detail files."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

from roulette_optimizer.saved_session import SavedLiveSession

CSV_FIELDS = (
    "session_id",
    "source",
    "started_at",
    "ended_at",
    "starting_bankroll",
    "ending_bankroll",
    "target",
    "floor",
    "terminal_status",
    "round_count",
    "initial_loss_durability",
    "policy_cache_key_hash",
    "json_file",
)


def default_saved_sessions_dir() -> Path:
    raw = os.environ.get("SAVED_SESSIONS_DIR", "outputs/saved_sessions")
    return Path(raw)


def session_json_path(root: Path, session_id: str) -> Path:
    return root / f"{session_id}.json"


def sessions_csv_path(root: Path) -> Path:
    return root / "sessions.csv"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def write_saved_session(
    session: SavedLiveSession,
    root: Path | None = None,
) -> tuple[Path, Path]:
    """Persist one session; rewrite sessions.csv from all JSON files.

    Returns (csv_path, json_path).
    """
    base = root if root is not None else default_saved_sessions_dir()
    base.mkdir(parents=True, exist_ok=True)
    json_path = session_json_path(base, session.session_id)
    _atomic_write_text(
        json_path,
        json.dumps(session.to_dict(), indent=2, sort_keys=True) + "\n",
    )
    csv_path = sessions_csv_path(base)
    _rewrite_csv(base, csv_path)
    return csv_path, json_path


def delete_saved_session_files(session_id: str, root: Path | None = None) -> None:
    """Remove one session's JSON file and refresh the CSV index."""
    base = root if root is not None else default_saved_sessions_dir()
    json_path = session_json_path(base, session_id)
    json_path.unlink(missing_ok=True)
    csv_path = sessions_csv_path(base)
    if base.is_dir():
        _rewrite_csv(base, csv_path)


def load_all_saved_sessions(root: Path | None = None) -> list[SavedLiveSession]:
    base = root if root is not None else default_saved_sessions_dir()
    if not base.is_dir():
        return []
    out: list[SavedLiveSession] = []
    for path in sorted(base.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        out.append(SavedLiveSession.from_dict(raw))
    return out


def _csv_row(session: SavedLiveSession) -> dict[str, str]:
    identity = session.policy_identity or {}
    return {
        "session_id": session.session_id,
        "source": session.source,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "starting_bankroll": str(session.starting_bankroll),
        "ending_bankroll": str(session.ending_bankroll),
        "target": str(session.target),
        "floor": str(session.floor),
        "terminal_status": session.terminal_status,
        "round_count": str(session.round_count),
        "initial_loss_durability": str(session.initial_loss_durability),
        "policy_cache_key_hash": str(identity.get("cache_key_hash", "")),
        "json_file": f"{session.session_id}.json",
    }


def _rewrite_csv(base: Path, csv_path: Path) -> None:
    sessions = load_all_saved_sessions(base)
    lines: list[str] = []
    with tempfile.SpooledTemporaryFile(
        mode="w+", encoding="utf-8", newline=""
    ) as buffer:
        writer = csv.DictWriter(buffer, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for session in sessions:
            writer.writerow(_csv_row(session))
        buffer.seek(0)
        lines.append(buffer.read())
    _atomic_write_text(csv_path, lines[0])
