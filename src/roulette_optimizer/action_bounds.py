from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from roulette_optimizer.config import SessionConfig


def align_up_to_stake_grid(
    required: int, minimum_bet: int, bankroll_step: int
) -> int:
    """Smallest stake on the grid that is >= required (or minimum_bet)."""
    if required <= minimum_bet:
        return minimum_bet
    delta = required - minimum_bet
    steps = (delta + bankroll_step - 1) // bankroll_step
    return minimum_bet + steps * bankroll_step


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


@dataclass(frozen=True)
class ActionBounds:
    """Per non-terminal normalized state x=1..H-1 arrays (length H-1)."""

    risk: np.ndarray  # int64
    color_legal_max: np.ndarray
    dice_legal_max: np.ndarray
    color_search_max: np.ndarray
    dice_search_max: np.ndarray
    color_action_count: np.ndarray
    dice_action_count: np.ndarray
    color_available: np.ndarray  # bool
    dice_available: np.ndarray  # bool
    H: int
    minimum_bet: int
    bankroll_step: int


def _family_search_max(
    *,
    risk: int,
    configured_max: int,
    minimum_bet: int,
    step: int,
    threshold_raw: int,
) -> tuple[int, int, bool]:
    """Return (legal_max, search_max, available)."""
    legal_max = min(risk, configured_max)
    if legal_max < minimum_bet:
        return 0, 0, False
    first_target = align_up_to_stake_grid(threshold_raw, minimum_bet, step)
    search_max = min(legal_max, first_target)
    # Number of stakes from min_bet to search_max inclusive on grid.
    count = (search_max - minimum_bet) // step + 1
    return legal_max, search_max, count > 0


def precompute_action_bounds(session: SessionConfig) -> ActionBounds:
    """Precompute pruned stake bounds for normalized states x=1..H-1."""
    step = session.bankroll_step
    H = (session.target_bankroll - session.floor_bankroll) // step
    n = max(0, H - 1)
    min_bet = session.minimum_bet

    risk = np.empty(n, dtype=np.int64)
    color_legal_max = np.zeros(n, dtype=np.int64)
    dice_legal_max = np.zeros(n, dtype=np.int64)
    color_search_max = np.zeros(n, dtype=np.int64)
    dice_search_max = np.zeros(n, dtype=np.int64)
    color_action_count = np.zeros(n, dtype=np.int64)
    dice_action_count = np.zeros(n, dtype=np.int64)
    color_available = np.zeros(n, dtype=np.bool_)
    dice_available = np.zeros(n, dtype=np.bool_)

    for i in range(n):
        x = i + 1  # normalized bankroll above floor
        r = x  # risk = B - F = x * step / step when step=1; general: x*step
        # With bankroll_step, absolute risk in money units is x * step.
        r_money = x * step
        risk[i] = r_money

        if session.allow_color:
            # COLOR reaches target when x + s_steps >= H => s_money >= (H-x)*step
            threshold = (H - x) * step
            legal, search, avail = _family_search_max(
                risk=r_money,
                configured_max=session.maximum_color_bet,
                minimum_bet=min_bet,
                step=step,
                threshold_raw=threshold,
            )
            color_legal_max[i] = legal
            color_search_max[i] = search
            color_available[i] = avail
            if avail:
                color_action_count[i] = (search - min_bet) // step + 1
        if session.allow_dice:
            # Dice win step uses GameConfig.dice_net_multiplier (13 in production).
            dice_mult = 13
            need_steps = ceil_div(H - x, dice_mult)
            threshold = need_steps * step
            legal, search, avail = _family_search_max(
                risk=r_money,
                configured_max=session.maximum_dice_bet,
                minimum_bet=min_bet,
                step=step,
                threshold_raw=threshold,
            )
            dice_legal_max[i] = legal
            dice_search_max[i] = search
            dice_available[i] = avail
            if avail:
                dice_action_count[i] = (search - min_bet) // step + 1

    return ActionBounds(
        risk=risk,
        color_legal_max=color_legal_max,
        dice_legal_max=dice_legal_max,
        color_search_max=color_search_max,
        dice_search_max=dice_search_max,
        color_action_count=color_action_count,
        dice_action_count=dice_action_count,
        color_available=color_available,
        dice_available=dice_available,
        H=H,
        minimum_bet=min_bet,
        bankroll_step=step,
    )


def color_search_max_for_state(bankroll: int, session: SessionConfig) -> int:
    """Absolute COLOR search max (money units) at bankroll, with pruning."""
    step = session.bankroll_step
    floor = session.floor_bankroll
    H = (session.target_bankroll - floor) // step
    x = (bankroll - floor) // step
    risk = bankroll - floor
    if not session.allow_color:
        return 0
    legal = min(risk, session.maximum_color_bet)
    if legal < session.minimum_bet:
        return 0
    threshold = (H - x) * step
    first = align_up_to_stake_grid(threshold, session.minimum_bet, step)
    return min(legal, first)


def dice_search_max_for_state(bankroll: int, session: SessionConfig) -> int:
    """Absolute DICE search max (money units) at bankroll, with pruning."""
    step = session.bankroll_step
    floor = session.floor_bankroll
    H = (session.target_bankroll - floor) // step
    x = (bankroll - floor) // step
    risk = bankroll - floor
    if not session.allow_dice:
        return 0
    legal = min(risk, session.maximum_dice_bet)
    if legal < session.minimum_bet:
        return 0
    need_steps = ceil_div(H - x, 13)  # production dice_net_multiplier
    threshold = need_steps * step
    first = align_up_to_stake_grid(threshold, session.minimum_bet, step)
    return min(legal, first)


def legal_actions_pruned(bankroll: int, session: SessionConfig):
    """Legal actions restricted by exact target-saturation pruning."""
    from roulette_optimizer.actions import Action

    out: list[Action] = []
    step = session.bankroll_step
    min_bet = session.minimum_bet
    if session.allow_color:
        cap = color_search_max_for_state(bankroll, session)
        if cap >= min_bet:
            for s in range(min_bet, cap + 1, step):
                out.append(Action("COLOR", s))
    if session.allow_dice:
        cap = dice_search_max_for_state(bankroll, session)
        if cap >= min_bet:
            for s in range(min_bet, cap + 1, step):
                out.append(Action("DICE", s))
    return out
