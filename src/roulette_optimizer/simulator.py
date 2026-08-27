from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean, median
from typing import Literal, Protocol

from roulette_optimizer.solver import PolicyDecision
from roulette_optimizer.utils import SimulationError

COLOR_WIN_P = 7 / 15
DICE_WIN_P = 1 / 15

TerminationReason = Literal["TARGET", "FLOOR", "MAX_ROUNDS"]


class OutcomeSource(Protocol):
    def color_win(self) -> bool: ...
    def dice_win(self) -> bool: ...


class RandomOutcomeSource:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def color_win(self) -> bool:
        return self._rng.random() < COLOR_WIN_P

    def dice_win(self) -> bool:
        return self._rng.random() < DICE_WIN_P


@dataclass(frozen=True)
class SessionResult:
    success: bool
    final_bankroll: int
    rounds: int
    total_wagered: int
    max_bet: int
    max_drawdown: int
    color_actions: int
    dice_actions: int
    termination_reason: TerminationReason


@dataclass(frozen=True)
class BatchResult:
    sessions: int
    target_hits: int
    floor_hits: int
    timeouts: int
    target_hit_rate: float
    mean_rounds: float
    median_rounds: float
    mean_total_wagered: float
    median_total_wagered: float
    mean_max_bet: float
    maximum_observed_bet: int
    mean_max_drawdown: float
    maximum_drawdown: int
    color_actions: int
    dice_actions: int
    color_action_pct: float
    dice_action_pct: float


def simulate_many(
    *,
    policy: dict[int, PolicyDecision],
    starting_bankroll: int,
    target: int,
    floor: int,
    sessions: int,
    seed: int,
    max_rounds: int,
) -> BatchResult:
    """Run many sessions sharing one ``RandomOutcomeSource(seed)``.

    Outcomes are drawn sequentially across sessions; the same seed reproduces
    identical aggregates only when ``sessions`` (and other parameters) match.
    """
    outcomes = RandomOutcomeSource(seed)
    results = [
        simulate_session(
            policy=policy,
            starting_bankroll=starting_bankroll,
            target=target,
            floor=floor,
            outcomes=outcomes,
            max_rounds=max_rounds,
        )
        for _ in range(sessions)
    ]
    target_hits = sum(1 for r in results if r.termination_reason == "TARGET")
    floor_hits = sum(1 for r in results if r.termination_reason == "FLOOR")
    timeouts = sum(1 for r in results if r.termination_reason == "MAX_ROUNDS")
    color_actions = sum(r.color_actions for r in results)
    dice_actions = sum(r.dice_actions for r in results)
    total_actions = color_actions + dice_actions
    rounds = [r.rounds for r in results]
    wagered = [r.total_wagered for r in results]
    max_bets = [r.max_bet for r in results]
    drawdowns = [r.max_drawdown for r in results]
    return BatchResult(
        sessions=sessions,
        target_hits=target_hits,
        floor_hits=floor_hits,
        timeouts=timeouts,
        target_hit_rate=target_hits / sessions if sessions else 0.0,
        mean_rounds=mean(rounds) if rounds else 0.0,
        median_rounds=median(rounds) if rounds else 0.0,
        mean_total_wagered=mean(wagered) if wagered else 0.0,
        median_total_wagered=median(wagered) if wagered else 0.0,
        mean_max_bet=mean(max_bets) if max_bets else 0.0,
        maximum_observed_bet=max(max_bets) if max_bets else 0,
        mean_max_drawdown=mean(drawdowns) if drawdowns else 0.0,
        maximum_drawdown=max(drawdowns) if drawdowns else 0,
        color_actions=color_actions,
        dice_actions=dice_actions,
        color_action_pct=color_actions / total_actions if total_actions else 0.0,
        dice_action_pct=dice_actions / total_actions if total_actions else 0.0,
    )


def simulate_session(
    *,
    policy: dict[int, PolicyDecision],
    starting_bankroll: int,
    target: int,
    floor: int,
    outcomes: OutcomeSource,
    max_rounds: int,
) -> SessionResult:
    b = starting_bankroll
    peak = b
    total_wagered = 0
    max_bet = 0
    max_drawdown = 0
    color_actions = 0
    dice_actions = 0
    if b >= target:
        return SessionResult(True, b, 0, 0, 0, 0, 0, 0, "TARGET")
    if b <= floor:
        return SessionResult(False, b, 0, 0, 0, 0, 0, 0, "FLOOR")
    for rounds in range(1, max_rounds + 1):
        decision = policy.get(b)
        if decision is None or decision.action is None:
            raise SimulationError(f"INVALID_POLICY at bankroll={b}")
        action = decision.action
        stake = action.stake
        total_wagered += stake
        max_bet = max(max_bet, stake)
        if action.bet_type == "COLOR":
            color_actions += 1
            win = outcomes.color_win()
            b = b + stake if win else b - stake
        else:
            dice_actions += 1
            win = outcomes.dice_win()
            b = b + 13 * stake if win else b - stake
        if b < floor:
            raise SimulationError(f"hard floor breached: bankroll={b} < floor={floor}")
        peak = max(peak, b)
        max_drawdown = max(max_drawdown, peak - b)
        if b >= target:
            return SessionResult(
                True, b, rounds, total_wagered, max_bet, max_drawdown,
                color_actions, dice_actions, "TARGET",
            )
        if b <= floor:
            return SessionResult(
                False, b, rounds, total_wagered, max_bet, max_drawdown,
                color_actions, dice_actions, "FLOOR",
            )
    return SessionResult(
        False, b, max_rounds, total_wagered, max_bet, max_drawdown,
        color_actions, dice_actions, "MAX_ROUNDS",
    )
