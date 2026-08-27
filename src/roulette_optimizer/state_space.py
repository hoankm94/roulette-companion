from __future__ import annotations

from dataclasses import dataclass

from roulette_optimizer.config import SessionConfig
from roulette_optimizer.utils import ConfigError


@dataclass(frozen=True)
class StateSpace:
    floor: int
    target: int
    step: int
    states: list[int]
    nonterminal: list[int]


MAX_NONTERMINAL_STATES = 20_000
WARN_NONTERMINAL_STATES = 5_000


def nonterminal_count(session: SessionConfig) -> int:
    """Count non-terminal bankrolls without allocating the full grid."""
    step = session.bankroll_step
    span_steps = (session.target_bankroll - session.floor_bankroll) // step
    return max(0, span_steps - 1)


def build_state_space(session: SessionConfig) -> StateSpace:
    floor = session.floor_bankroll
    target = session.target_bankroll
    step = session.bankroll_step
    states = list(range(floor, target + 1, step))
    nonterminal = [b for b in states if floor < b < target]
    return StateSpace(floor, target, step, states, nonterminal)


def check_state_space_size(n: int, force: bool = False) -> str | None:
    if n > MAX_NONTERMINAL_STATES and not force:
        raise ConfigError(
            f"State space has {n} non-terminal states "
            f"(max {MAX_NONTERMINAL_STATES} without force). "
            "Narrow the target−floor span (smaller target profits / floor losses, "
            "or a lower bankroll), or pass force / --force to proceed."
        )
    if n > MAX_NONTERMINAL_STATES:
        return None
    if n > WARN_NONTERMINAL_STATES:
        return f"Warning: large state space ({n} states)"
    return None
