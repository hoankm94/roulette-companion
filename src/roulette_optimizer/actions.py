from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from roulette_optimizer.config import SessionConfig

BetType = Literal["COLOR", "DICE"]


@dataclass(frozen=True)
class Action:
    bet_type: BetType
    stake: int


def _stakes(max_stake: int, session: SessionConfig) -> list[int]:
    if max_stake < session.minimum_bet:
        return []
    return list(
        range(session.minimum_bet, max_stake + 1, session.bankroll_step)
    )


def legal_actions(bankroll: int, session: SessionConfig) -> list[Action]:
    risk = bankroll - session.floor_bankroll
    out: list[Action] = []
    if session.allow_color:
        cap = min(risk, session.maximum_color_bet)
        out.extend(Action("COLOR", s) for s in _stakes(cap, session))
    if session.allow_dice:
        cap = min(risk, session.maximum_dice_bet)
        out.extend(Action("DICE", s) for s in _stakes(cap, session))
    return out
