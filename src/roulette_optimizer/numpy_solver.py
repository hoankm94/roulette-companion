from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from roulette_optimizer.actions import Action
from roulette_optimizer.config import GameConfig, SessionConfig
from roulette_optimizer.game import next_bankrolls
from roulette_optimizer.solver import PolicyDecision, SolverResult, TIE_EPS
from roulette_optimizer.utils import SolverError


@dataclass(frozen=True)
class _StateActions:
    color_stakes: np.ndarray  # int64
    dice_stakes: np.ndarray  # int64


def _bankroll_to_index(bankroll: int, floor: int, step: int) -> int:
    return (bankroll - floor) // step


def _precompute_actions(
    nonterminal: list[int],
    session: SessionConfig,
) -> list[_StateActions]:
    from roulette_optimizer.action_bounds import (
        color_search_max_for_state,
        dice_search_max_for_state,
    )

    step = session.bankroll_step
    min_bet = session.minimum_bet
    out: list[_StateActions] = []
    for b in nonterminal:
        if session.allow_color:
            cap = color_search_max_for_state(b, session)
            if cap >= min_bet:
                color = np.arange(min_bet, cap + 1, step, dtype=np.int64)
            else:
                color = np.empty(0, dtype=np.int64)
        else:
            color = np.empty(0, dtype=np.int64)
        if session.allow_dice:
            cap = dice_search_max_for_state(b, session)
            if cap >= min_bet:
                dice = np.arange(min_bet, cap + 1, step, dtype=np.int64)
            else:
                dice = np.empty(0, dtype=np.int64)
        else:
            dice = np.empty(0, dtype=np.int64)
        out.append(_StateActions(color, dice))
    return out


def _assert_on_grid(bankroll: int, floor: int, step: int, values: np.ndarray) -> None:
    delta = bankroll - floor
    if delta % step != 0:
        raise ValueError(
            f"Off-grid bankroll {bankroll} for floor={floor} step={step}"
        )
    idx = delta // step
    if idx < 0 or idx >= values.shape[0]:
        raise ValueError(f"Off-grid bankroll {bankroll} not in value table")


def _q_values_for_stakes(
    bankroll: int,
    stakes: np.ndarray,
    values: np.ndarray,
    *,
    win_mult: int,
    win_p: float,
    floor: int,
    target: int,
    step: int,
) -> np.ndarray:
    if stakes.size == 0:
        return np.empty(0, dtype=np.float64)
    win_b = bankroll + win_mult * stakes
    lose_b = bankroll - stakes
    win_vals = np.empty(stakes.shape, dtype=np.float64)
    success = win_b >= target
    ruin = win_b <= floor
    mid = ~success & ~ruin
    win_vals[success] = 1.0
    win_vals[ruin] = 0.0
    if np.any(mid):
        for wb in win_b[mid]:
            _assert_on_grid(int(wb), floor, step, values)
        win_vals[mid] = values[(win_b[mid] - floor) // step]
    for lb in lose_b:
        _assert_on_grid(int(lb), floor, step, values)
    lose_vals = values[(lose_b - floor) // step]
    return win_p * win_vals + (1.0 - win_p) * lose_vals


def _select_best(
    color_stakes: np.ndarray,
    color_q: np.ndarray,
    dice_stakes: np.ndarray,
    dice_q: np.ndarray,
) -> tuple[Action | None, float]:
    best_a: Action | None = None
    best_q = 0.0

    def consider(bet_type: str, stakes: np.ndarray, qs: np.ndarray) -> None:
        nonlocal best_a, best_q
        if qs.size == 0:
            return
        max_q = float(np.max(qs))
        tied = qs >= max_q - TIE_EPS
        # Among tied: smallest stake; COLOR considered before DICE via call order
        # when stakes equal across types — handled by sequential consider + rules.
        cand_stakes = stakes[tied]
        cand_qs = qs[tied]
        order = np.argsort(cand_stakes, kind="mergesort")
        for i in order:
            stake = int(cand_stakes[i])
            q = float(cand_qs[i])
            action = Action(bet_type, stake)  # type: ignore[arg-type]
            if best_a is None:
                best_a, best_q = action, q
                continue
            if q > best_q + TIE_EPS:
                best_a, best_q = action, q
            elif abs(q - best_q) <= TIE_EPS:
                if stake < best_a.stake:
                    best_a, best_q = action, q
                elif (
                    stake == best_a.stake
                    and bet_type == "COLOR"
                    and best_a.bet_type == "DICE"
                ):
                    best_a, best_q = action, q

    # COLOR before DICE when scanning; equality ties prefer COLOR via rule above.
    consider("COLOR", color_stakes, color_q)
    consider("DICE", dice_stakes, dice_q)
    if best_a is None:
        return None, 0.0
    return best_a, best_q


def _best_for_state(
    bankroll: int,
    actions: _StateActions,
    values: np.ndarray,
    game: GameConfig,
    session: SessionConfig,
) -> tuple[Action | None, float]:
    floor = session.floor_bankroll
    target = session.target_bankroll
    step = session.bankroll_step
    color_q = _q_values_for_stakes(
        bankroll,
        actions.color_stakes,
        values,
        win_mult=game.color_net_multiplier,
        win_p=game.color_win_probability,
        floor=floor,
        target=target,
        step=step,
    )
    dice_q = _q_values_for_stakes(
        bankroll,
        actions.dice_stakes,
        values,
        win_mult=game.dice_net_multiplier,
        win_p=game.dice_win_probability,
        floor=floor,
        target=target,
        step=step,
    )
    return _select_best(
        actions.color_stakes, color_q, actions.dice_stakes, dice_q
    )


def solve_numpy(
    session: SessionConfig, game: GameConfig | None = None
) -> SolverResult:
    game = game or GameConfig()
    floor = session.floor_bankroll
    target = session.target_bankroll
    step = session.bankroll_step
    n = (target - floor) // step + 1
    nonterminal_bankrolls = list(range(floor + step, target, step))
    precomputed = _precompute_actions(nonterminal_bankrolls, session)

    values = np.zeros(n, dtype=np.float64)
    values[-1] = 1.0  # target

    converged = False
    delta = 0.0
    iterations = 0
    for iterations in range(1, session.solver_max_iterations + 1):
        new_values = values.copy()
        delta = 0.0
        for i, b in enumerate(nonterminal_bankrolls):
            idx = i + 1  # floor at 0, first nonterminal at 1
            _, q = _best_for_state(b, precomputed[i], values, game, session)
            new_values[idx] = q
            delta = max(delta, abs(q - values[idx]))
        values = new_values
        if delta < session.solver_tolerance:
            converged = True
            break
    if not converged:
        raise SolverError(
            f"Value iteration did not converge "
            f"(iterations={iterations}, delta={delta})"
        )

    # Final policy extraction from frozen values.
    value_dict: dict[int, float] = {
        floor + i * step: float(values[i]) for i in range(n)
    }
    policy: dict[int, PolicyDecision] = {}
    for i in range(n):
        b = floor + i * step
        if b <= floor:
            policy[b] = PolicyDecision(b, None, 0.0, None, None)
            continue
        if b >= target:
            policy[b] = PolicyDecision(b, None, 1.0, None, None)
            continue
        nt_i = i - 1
        action, q = _best_for_state(
            b, precomputed[nt_i], values, game, session
        )
        if action is None:
            policy[b] = PolicyDecision(b, None, 0.0, None, None)
            value_dict[b] = 0.0
            values[i] = 0.0
        else:
            win_b, lose_b = next_bankrolls(b, action, game)
            policy[b] = PolicyDecision(b, action, q, win_b, lose_b)
            value_dict[b] = q

    return SolverResult(True, iterations, float(delta), value_dict, policy)


class NumPySolver:
    def solve(
        self, session: SessionConfig, game: GameConfig | None = None
    ) -> SolverResult:
        return solve_numpy(session, game)
