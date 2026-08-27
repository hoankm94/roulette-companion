from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from roulette_optimizer.utils import ConfigError

SUPPORTED_COLOR_MULTIPLIER = 1
SUPPORTED_DICE_MULTIPLIER = 13


@dataclass(frozen=True)
class GameConfig:
    color_win_probability: float = 7 / 15
    dice_win_probability: float = 1 / 15
    color_net_multiplier: int = 1
    dice_net_multiplier: int = 13


@dataclass(frozen=True)
class SessionConfig:
    starting_bankroll: int
    target_bankroll: int
    floor_bankroll: int
    bankroll_step: int = 1
    minimum_bet: int = 1
    maximum_color_bet: int = 250000
    maximum_dice_bet: int = 50000
    allow_color: bool = True
    allow_dice: bool = True
    solver_tolerance: float = 1e-12
    solver_max_iterations: int = 100000
    verification_tolerance: float = 1e-9
    optimality_tolerance: float = 1e-9


def validate_game(game: GameConfig) -> None:
    for name, prob in (
        ("color_win_probability", game.color_win_probability),
        ("dice_win_probability", game.dice_win_probability),
    ):
        if not math.isfinite(prob):
            raise ConfigError(f"{name} must be finite")
        if not 0.0 <= prob <= 1.0:
            raise ConfigError(f"{name} must be between 0 and 1")
    if game.color_net_multiplier != SUPPORTED_COLOR_MULTIPLIER:
        raise ConfigError(
            f"color_net_multiplier must be {SUPPORTED_COLOR_MULTIPLIER} "
            "(production solvers do not support other multipliers)"
        )
    if game.dice_net_multiplier != SUPPORTED_DICE_MULTIPLIER:
        raise ConfigError(
            f"dice_net_multiplier must be {SUPPORTED_DICE_MULTIPLIER} "
            "(production solvers do not support other multipliers)"
        )


def validate_session(session: SessionConfig) -> None:
    s = session
    if not (s.target_bankroll > s.starting_bankroll > s.floor_bankroll >= 0):
        raise ConfigError(
            "Require target_bankroll > starting_bankroll > floor_bankroll >= 0"
        )
    if s.bankroll_step <= 0 or s.minimum_bet <= 0:
        raise ConfigError("bankroll_step and minimum_bet must be > 0")
    if not (s.allow_color or s.allow_dice):
        raise ConfigError("At least one wager type must be enabled")
    for name, value in (
        ("starting_bankroll", s.starting_bankroll),
        ("target_bankroll", s.target_bankroll),
        ("floor_bankroll", s.floor_bankroll),
        ("minimum_bet", s.minimum_bet),
        ("maximum_color_bet", s.maximum_color_bet),
        ("maximum_dice_bet", s.maximum_dice_bet),
    ):
        if value % s.bankroll_step != 0:
            raise ConfigError(f"{name} must be divisible by bankroll_step")


def load_session_config(path: str | Path) -> SessionConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {f.name for f in fields(SessionConfig)}
    filtered = {k: v for k, v in data.items() if k in allowed}
    session = SessionConfig(**filtered)
    validate_session(session)
    return session


def merge_session(base: SessionConfig, **overrides: object) -> SessionConfig:
    clean = {k: v for k, v in overrides.items() if v is not None}
    session = replace(base, **clean)
    validate_session(session)
    return session


def session_to_dict(session: SessionConfig) -> dict:
    return asdict(session)
