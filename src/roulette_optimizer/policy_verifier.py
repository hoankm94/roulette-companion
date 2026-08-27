from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from roulette_optimizer.actions import Action
from roulette_optimizer.config import GameConfig, SessionConfig
from roulette_optimizer.game import action_value, next_bankrolls
from roulette_optimizer.solver import SolverResult
from roulette_optimizer.state_space import build_state_space
from roulette_optimizer.utils import VerificationError


@dataclass(frozen=True)
class VerificationResult:
    policy_evaluation_passed: bool
    bellman_passed: bool
    max_value_difference: float
    max_optimality_gap: float
    evaluated_values: dict[int, float]
    linear_value_bellman_passed: bool
    vi_bellman_max_gap: float
    linear_value_bellman_max_gap: float
    legal_actions_passed: bool


def _stake_aligned(stake: int, minimum_bet: int, step: int) -> bool:
    if stake < minimum_bet:
        return False
    return (stake - minimum_bet) % step == 0


def has_any_legal_action(bankroll: int, session: SessionConfig) -> bool:
    risk = bankroll - session.floor_bankroll
    min_bet = session.minimum_bet
    if session.allow_color and min(risk, session.maximum_color_bet) >= min_bet:
        return True
    if session.allow_dice and min(risk, session.maximum_dice_bet) >= min_bet:
        return True
    return False


def is_action_legal(bankroll: int, action: Action | None, session: SessionConfig) -> bool:
    """O(1) legality check for a stored policy action (or None)."""
    if action is None:
        return not has_any_legal_action(bankroll, session)
    risk = bankroll - session.floor_bankroll
    if action.stake > risk:
        return False
    if not _stake_aligned(action.stake, session.minimum_bet, session.bankroll_step):
        return False
    if action.bet_type == "COLOR":
        if not session.allow_color:
            return False
        return action.stake <= session.maximum_color_bet
    if action.bet_type == "DICE":
        if not session.allow_dice:
            return False
        return action.stake <= session.maximum_dice_bet
    return False


def evaluate_policy_dense(
    result: SolverResult,
    session: SessionConfig,
    game: GameConfig | None = None,
) -> dict[int, float]:
    """Legacy dense (I-P)V=b evaluator retained for equivalence tests."""
    game = game or GameConfig()
    ss = build_state_space(session)
    nont = ss.nonterminal
    idx = {b: i for i, b in enumerate(nont)}
    n = len(nont)
    A = np.eye(n, dtype=float)
    bvec = np.zeros(n, dtype=float)

    def terminal_or_var(x: int) -> tuple[float, int | None]:
        if x <= ss.floor:
            return 0.0, None
        if x >= ss.target:
            return 1.0, None
        if x in idx:
            return 0.0, idx[x]
        raise VerificationError(f"Off-grid bankroll {x}")

    for b in nont:
        i = idx[b]
        decision = result.policy[b]
        if decision.action is None:
            continue
        action = decision.action
        win_b, lose_b = next_bankrolls(b, action, game)
        p = (
            game.color_win_probability
            if action.bet_type == "COLOR"
            else game.dice_win_probability
        )
        for prob, nxt in ((p, win_b), (1.0 - p, lose_b)):
            const, j = terminal_or_var(nxt)
            if j is None:
                bvec[i] += prob * const
            else:
                A[i, j] -= prob

    x = np.linalg.solve(A, bvec)
    evaluated = {ss.floor: 0.0, ss.target: 1.0}
    for b, i in idx.items():
        evaluated[b] = float(x[i])
    return evaluated


def evaluate_policy_sparse(
    result: SolverResult,
    session: SessionConfig,
    game: GameConfig | None = None,
    *,
    residual_tol: float | None = None,
) -> dict[int, float]:
    """Sparse fixed-policy evaluation via CSC spsolve."""
    game = game or GameConfig()
    ss = build_state_space(session)
    nont = ss.nonterminal
    idx = {b: i for i, b in enumerate(nont)}
    n = len(nont)
    if n == 0:
        return {ss.floor: 0.0, ss.target: 1.0}

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    bvec = np.zeros(n, dtype=np.float64)

    def add(r: int, c: int, v: float) -> None:
        rows.append(r)
        cols.append(c)
        data.append(v)

    for b in nont:
        i = idx[b]
        add(i, i, 1.0)
        decision = result.policy[b]
        if decision.action is None:
            continue
        action = decision.action
        win_b, lose_b = next_bankrolls(b, action, game)
        p = (
            game.color_win_probability
            if action.bet_type == "COLOR"
            else game.dice_win_probability
        )
        for prob, nxt in ((p, win_b), (1.0 - p, lose_b)):
            if nxt <= ss.floor:
                continue
            if nxt >= ss.target:
                bvec[i] += prob
                continue
            j = idx.get(nxt)
            if j is None:
                raise VerificationError(f"Off-grid bankroll {nxt}")
            add(i, j, -prob)

    A = sparse.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsc()
    try:
        x = spsolve(A, bvec)
    except Exception as exc:  # pragma: no cover - scipy path
        raise VerificationError(f"Sparse policy evaluation failed: {exc}") from exc

    x = np.asarray(x, dtype=np.float64)
    if x.size != n or not np.all(np.isfinite(x)):
        raise VerificationError("Sparse policy evaluation produced non-finite values")
    tol = residual_tol if residual_tol is not None else session.verification_tolerance
    if np.any(x < -tol) or np.any(x > 1.0 + tol):
        raise VerificationError("Sparse policy values outside [0, 1] tolerance")
    residual = float(np.max(np.abs(A @ x - bvec))) if n else 0.0
    if residual > max(tol * 1000.0, 1e-8):
        raise VerificationError(f"Sparse residual too large: {residual}")

    evaluated = {ss.floor: 0.0, ss.target: 1.0}
    for b, i in idx.items():
        evaluated[b] = float(x[i])
    return evaluated


def _bellman_gap(
    result: SolverResult,
    values: dict[int, float],
    session: SessionConfig,
    game: GameConfig,
) -> float:
    from roulette_optimizer.action_bounds import legal_actions_pruned

    ss = build_state_space(session)
    max_gap = 0.0
    for b in ss.nonterminal:
        chosen = result.policy[b].action
        chosen_q = (
            0.0
            if chosen is None
            else action_value(
                b,
                chosen,
                values,
                game,
                target=session.target_bankroll,
                floor=session.floor_bankroll,
            )
        )
        best_q = chosen_q
        for action in legal_actions_pruned(b, session):
            q = action_value(
                b,
                action,
                values,
                game,
                target=session.target_bankroll,
                floor=session.floor_bankroll,
            )
            best_q = max(best_q, q)
        max_gap = max(max_gap, best_q - chosen_q)
    return max_gap


def verify_legal_actions_direct(
    result: SolverResult, session: SessionConfig
) -> bool:
    ss = build_state_space(session)
    for b in ss.nonterminal:
        if not is_action_legal(b, result.policy[b].action, session):
            return False
    return True


def verify_policy(
    result: SolverResult,
    session: SessionConfig,
    game: GameConfig | None = None,
) -> VerificationResult:
    game = game or GameConfig()
    ss = build_state_space(session)
    nont = ss.nonterminal

    evaluated = evaluate_policy_sparse(result, session, game)

    max_diff = 0.0
    for b in nont:
        max_diff = max(max_diff, abs(evaluated[b] - result.values[b]))

    max_gap = _bellman_gap(result, result.values, session, game)
    linear_max_gap = _bellman_gap(result, evaluated, session, game)
    legal_ok = verify_legal_actions_direct(result, session)

    pe_ok = max_diff <= session.verification_tolerance
    bellman_ok = max_gap <= session.optimality_tolerance
    linear_bellman_ok = linear_max_gap <= session.optimality_tolerance
    if not (pe_ok and bellman_ok and linear_bellman_ok and legal_ok):
        raise VerificationError(
            f"Verification failed: max_diff={max_diff}, max_gap={max_gap}, "
            f"linear_max_gap={linear_max_gap}, legal_ok={legal_ok}"
        )
    return VerificationResult(
        pe_ok,
        bellman_ok,
        max_diff,
        max_gap,
        evaluated,
        linear_bellman_ok,
        max_gap,
        linear_max_gap,
        legal_ok,
    )
