from __future__ import annotations

from dataclasses import dataclass

from roulette_optimizer.actions import Action, legal_actions
from roulette_optimizer.config import GameConfig, SessionConfig
from roulette_optimizer.game import action_value
from roulette_optimizer.policy import count_policy_actions
from roulette_optimizer.solver import TIE_EPS, SolverResult, _better
from roulette_optimizer.state_space import build_state_space
from roulette_optimizer.utils import ConfigError


@dataclass(frozen=True)
class DiceMapRow:
    bankroll: int
    dice_stake: int
    dice_q: float
    best_color_stake: int | None
    best_color_q: float | None
    difference: float | None


@dataclass(frozen=True)
class DiceMapResult:
    session: SessionConfig
    solver: str
    state_count: int
    dice_count: int
    color_count: int
    no_action_count: int
    rows: list[DiceMapRow]
    min_difference: float | None
    max_difference: float | None
    median_difference: float | None


def default_dice_map_output_path(session: SessionConfig) -> str:
    return (
        f"outputs/dice_map_{session.starting_bankroll}_"
        f"{session.target_bankroll}_{session.floor_bankroll}.csv"
    )


def _best_color_alternative(
    bankroll: int,
    values: dict[int, float],
    session: SessionConfig,
    game: GameConfig,
) -> tuple[Action | None, float | None]:
    best_a: Action | None = None
    best_q = 0.0
    found = False
    for action in legal_actions(bankroll, session):
        if action.bet_type != "COLOR":
            continue
        q = action_value(
            bankroll,
            action,
            values,
            game,
            target=session.target_bankroll,
            floor=session.floor_bankroll,
        )
        if not found or _better(action, best_a, q, best_q):
            best_a, best_q = action, q
            found = True
    if not found:
        return None, None
    return best_a, best_q


def build_dice_map(
    session: SessionConfig,
    *,
    game: GameConfig | None = None,
    solver: str = "numpy",
    result: SolverResult | None = None,
) -> DiceMapResult:
    if solver not in ("numpy", "reference", "numba", "policy_iteration"):
        raise ConfigError(f"Unknown solver: {solver!r}")
    game = game or GameConfig()
    solver_used = solver
    if result is None:
        from roulette_optimizer.policy_cache import solve_and_cache

        hit = solve_and_cache(session, game, solver=solver)
        result = hit.result
        solver_used = hit.solver_used
    ss = build_state_space(session)
    color_c, dice_c, none_c = count_policy_actions(result, session)
    rows: list[DiceMapRow] = []
    diffs: list[float] = []
    for b in ss.nonterminal:
        decision = result.policy[b]
        if decision.action is None or decision.action.bet_type != "DICE":
            continue
        dice_action = decision.action
        dice_q = action_value(
            b,
            dice_action,
            result.values,
            game,
            target=session.target_bankroll,
            floor=session.floor_bankroll,
        )
        if abs(dice_q - result.values[b]) > session.optimality_tolerance:
            raise ConfigError(
                f"Internal inconsistency at bankroll {b}: "
                f"dice_q={dice_q} vs V={result.values[b]}"
            )
        color_a, color_q = _best_color_alternative(b, result.values, session, game)
        if color_a is None or color_q is None:
            rows.append(
                DiceMapRow(b, dice_action.stake, dice_q, None, None, None)
            )
        else:
            diff = dice_q - color_q
            if diff < -TIE_EPS:
                raise ConfigError(
                    f"Materially negative DICE advantage at bankroll {b}: {diff}"
                )
            diffs.append(diff)
            rows.append(
                DiceMapRow(
                    b,
                    dice_action.stake,
                    dice_q,
                    color_a.stake,
                    color_q,
                    diff,
                )
            )
    rows.sort(key=lambda r: r.bankroll)
    med = None
    if diffs:
        ordered = sorted(diffs)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            med = ordered[mid]
        else:
            med = (ordered[mid - 1] + ordered[mid]) / 2.0
    return DiceMapResult(
        session=session,
        solver=solver_used,
        state_count=len(ss.nonterminal),
        dice_count=dice_c,
        color_count=color_c,
        no_action_count=none_c,
        rows=rows,
        min_difference=min(diffs) if diffs else None,
        max_difference=max(diffs) if diffs else None,
        median_difference=med,
    )


DICE_MAP_CSV_FIELDS = [
    "bankroll",
    "dice_stake",
    "dice_q",
    "best_color_stake",
    "best_color_q",
    "difference",
]


def dice_map_rows_as_dicts(rows: list[DiceMapRow]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for r in rows:
        out.append(
            {
                "bankroll": r.bankroll,
                "dice_stake": r.dice_stake,
                "dice_q": r.dice_q,
                "best_color_stake": "" if r.best_color_stake is None else r.best_color_stake,
                "best_color_q": "" if r.best_color_q is None else r.best_color_q,
                "difference": "" if r.difference is None else r.difference,
            }
        )
    return out
