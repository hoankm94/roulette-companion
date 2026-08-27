from __future__ import annotations

from collections.abc import Mapping

from roulette_optimizer.actions import Action
from roulette_optimizer.config import GameConfig


def lookup_value(
    bankroll: int,
    values: Mapping[int, float],
    *,
    target: int,
    floor: int,
) -> float:
    if bankroll <= floor:
        return 0.0
    if bankroll >= target:
        return 1.0
    if bankroll not in values:
        raise KeyError(f"Off-grid bankroll {bankroll} not in value table")
    return values[bankroll]


def next_bankrolls(
    bankroll: int, action: Action, game: GameConfig
) -> tuple[int, int]:
    if action.bet_type == "COLOR":
        win = bankroll + game.color_net_multiplier * action.stake
    else:
        win = bankroll + game.dice_net_multiplier * action.stake
    lose = bankroll - action.stake
    return win, lose


def action_value(
    bankroll: int,
    action: Action,
    values: Mapping[int, float],
    game: GameConfig,
    *,
    target: int,
    floor: int,
) -> float:
    win_b, lose_b = next_bankrolls(bankroll, action, game)
    v_win = lookup_value(win_b, values, target=target, floor=floor)
    v_lose = lookup_value(lose_b, values, target=target, floor=floor)
    if action.bet_type == "COLOR":
        p = game.color_win_probability
    else:
        p = game.dice_win_probability
    return p * v_win + (1.0 - p) * v_lose
