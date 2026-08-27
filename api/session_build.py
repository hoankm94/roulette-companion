"""Shared helpers for building SessionConfig from dollar inputs."""

from __future__ import annotations

from roulette_optimizer.config import GameConfig, SessionConfig, validate_session
from roulette_optimizer.state_space import check_state_space_size, nonterminal_count
from roulette_optimizer.utils import ConfigError

from api.money import MoneyError, dollars_to_cents
from api.models import SessionMoneyInput


def session_from_money(req: SessionMoneyInput) -> SessionConfig:
    try:
        bankroll = dollars_to_cents(req.bankroll)
        target = dollars_to_cents(req.target)
        floor = dollars_to_cents(req.floor)
    except MoneyError as exc:
        raise ConfigError(str(exc)) from exc
    session = SessionConfig(
        starting_bankroll=bankroll,
        target_bankroll=target,
        floor_bankroll=floor,
    )
    validate_session(session)
    check_state_space_size(nonterminal_count(session), force=req.force)
    return session


def default_game() -> GameConfig:
    return GameConfig()
