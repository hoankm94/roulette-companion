from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

SessionSource = Literal["MANUAL", "COMPANION"]


@dataclass
class SavedLiveSession:
    session_id: str
    source: SessionSource
    started_at: str
    ended_at: str
    starting_bankroll: int
    ending_bankroll: int
    target: int
    floor: int
    terminal_status: str
    round_count: int
    initial_loss_durability: int
    policy_identity: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "starting_bankroll": self.starting_bankroll,
            "ending_bankroll": self.ending_bankroll,
            "target": self.target,
            "floor": self.floor,
            "terminal_status": self.terminal_status,
            "round_count": self.round_count,
            "initial_loss_durability": self.initial_loss_durability,
            "policy_identity": self.policy_identity,
            "events": list(self.events),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SavedLiveSession:
        return cls(
            session_id=str(raw["session_id"]),
            source=raw["source"],  # type: ignore[arg-type]
            started_at=str(raw["started_at"]),
            ended_at=str(raw["ended_at"]),
            starting_bankroll=int(raw["starting_bankroll"]),
            ending_bankroll=int(raw["ending_bankroll"]),
            target=int(raw["target"]),
            floor=int(raw["floor"]),
            terminal_status=str(raw["terminal_status"]),
            round_count=int(raw["round_count"]),
            initial_loss_durability=int(raw["initial_loss_durability"]),
            policy_identity=dict(raw["policy_identity"]),
            events=list(raw.get("events", [])),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def terminal_status_for_save(status: str) -> str:
    if status == "QUIT":
        return "USER_STOPPED"
    return status
