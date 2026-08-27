from __future__ import annotations

import numpy as np
from numba import njit, prange

from roulette_optimizer.action_bounds import precompute_action_bounds
from roulette_optimizer.actions import Action
from roulette_optimizer.config import GameConfig, SessionConfig
from roulette_optimizer.game import action_value, next_bankrolls
from roulette_optimizer.perf import PerfClock, PerformanceTimings
from roulette_optimizer.policy_verifier import (
    evaluate_policy_sparse,
    verify_legal_actions_direct,
)
from roulette_optimizer.solver import PolicyDecision, SolverResult, TIE_EPS
from roulette_optimizer.state_space import build_state_space
from roulette_optimizer.utils import SolverError, VerificationError

BET_NONE = 0
BET_COLOR = 1
BET_DICE = 2

PARALLEL_STATE_THRESHOLD = 800
_POLICY_STABLE_SWEEPS = 2


@njit(cache=True)
def _lookup(values: np.ndarray, idx: int, H: int) -> float:
    if idx <= 0:
        return 0.0
    if idx >= H:
        return 1.0
    return values[idx]


@njit(cache=True)
def _better(
    cand_type: int,
    cand_stake: int,
    cand_q: float,
    cur_type: int,
    cur_stake: int,
    cur_q: float,
) -> bool:
    if cur_type == BET_NONE:
        return True
    if cand_q > cur_q + TIE_EPS:
        return True
    if abs(cand_q - cur_q) <= TIE_EPS:
        if cand_stake < cur_stake:
            return True
        if cand_stake == cur_stake and cand_type == BET_COLOR and cur_type == BET_DICE:
            return True
    return False


@njit(cache=True)
def _bellman_sweep_serial(
    old_values: np.ndarray,
    new_values: np.ndarray,
    best_type: np.ndarray,
    best_stake: np.ndarray,
    color_search_max_steps: np.ndarray,
    dice_search_max_steps: np.ndarray,
    color_available: np.ndarray,
    dice_available: np.ndarray,
    min_steps: int,
    H: int,
    color_p: float,
    dice_p: float,
) -> tuple[float, int, int]:
    n = H - 1
    max_delta = 0.0
    color_evals = 0
    dice_evals = 0
    for i in range(n):
        x = i + 1
        bt = BET_NONE
        bs = 0
        bq = 0.0

        if color_available[i]:
            s_max = color_search_max_steps[i]
            for s in range(min_steps, s_max + 1):
                color_evals += 1
                q = color_p * _lookup(old_values, x + s, H) + (
                    1.0 - color_p
                ) * _lookup(old_values, x - s, H)
                if _better(BET_COLOR, s, q, bt, bs, bq):
                    bt = BET_COLOR
                    bs = s
                    bq = q

        if dice_available[i]:
            s_max = dice_search_max_steps[i]
            for s in range(min_steps, s_max + 1):
                dice_evals += 1
                q = dice_p * _lookup(old_values, x + 13 * s, H) + (
                    1.0 - dice_p
                ) * _lookup(old_values, x - s, H)
                if _better(BET_DICE, s, q, bt, bs, bq):
                    bt = BET_DICE
                    bs = s
                    bq = q

        new_values[x] = bq
        best_type[i] = bt
        best_stake[i] = bs
        d = abs(bq - old_values[x])
        if d > max_delta:
            max_delta = d
    return max_delta, color_evals, dice_evals


@njit(cache=True, parallel=True)
def _bellman_sweep_parallel(
    old_values: np.ndarray,
    new_values: np.ndarray,
    best_type: np.ndarray,
    best_stake: np.ndarray,
    color_search_max_steps: np.ndarray,
    dice_search_max_steps: np.ndarray,
    color_available: np.ndarray,
    dice_available: np.ndarray,
    min_steps: int,
    H: int,
    color_p: float,
    dice_p: float,
) -> tuple[float, int, int]:
    n = H - 1
    deltas = np.zeros(n, dtype=np.float64)
    color_counts = np.zeros(n, dtype=np.int64)
    dice_counts = np.zeros(n, dtype=np.int64)
    for i in prange(n):
        x = i + 1
        bt = BET_NONE
        bs = 0
        bq = 0.0
        ce = 0
        de = 0

        if color_available[i]:
            s_max = color_search_max_steps[i]
            for s in range(min_steps, s_max + 1):
                ce += 1
                q = color_p * _lookup(old_values, x + s, H) + (
                    1.0 - color_p
                ) * _lookup(old_values, x - s, H)
                if _better(BET_COLOR, s, q, bt, bs, bq):
                    bt = BET_COLOR
                    bs = s
                    bq = q

        if dice_available[i]:
            s_max = dice_search_max_steps[i]
            for s in range(min_steps, s_max + 1):
                de += 1
                q = dice_p * _lookup(old_values, x + 13 * s, H) + (
                    1.0 - dice_p
                ) * _lookup(old_values, x - s, H)
                if _better(BET_DICE, s, q, bt, bs, bq):
                    bt = BET_DICE
                    bs = s
                    bq = q

        new_values[x] = bq
        best_type[i] = bt
        best_stake[i] = bs
        deltas[i] = abs(bq - old_values[x])
        color_counts[i] = ce
        dice_counts[i] = de

    max_delta = 0.0
    color_evals = 0
    dice_evals = 0
    for i in range(n):
        if deltas[i] > max_delta:
            max_delta = deltas[i]
        color_evals += int(color_counts[i])
        dice_evals += int(dice_counts[i])
    return max_delta, color_evals, dice_evals


@njit(cache=True)
def _policy_improve_serial(
    values: np.ndarray,
    best_type: np.ndarray,
    best_stake: np.ndarray,
    color_search_max_steps: np.ndarray,
    dice_search_max_steps: np.ndarray,
    color_available: np.ndarray,
    dice_available: np.ndarray,
    min_steps: int,
    H: int,
    color_p: float,
    dice_p: float,
) -> None:
    n = H - 1
    for i in range(n):
        x = i + 1
        bt = BET_NONE
        bs = 0
        bq = 0.0
        if color_available[i]:
            s_max = color_search_max_steps[i]
            for s in range(min_steps, s_max + 1):
                q = color_p * _lookup(values, x + s, H) + (
                    1.0 - color_p
                ) * _lookup(values, x - s, H)
                if _better(BET_COLOR, s, q, bt, bs, bq):
                    bt = BET_COLOR
                    bs = s
                    bq = q
        if dice_available[i]:
            s_max = dice_search_max_steps[i]
            for s in range(min_steps, s_max + 1):
                q = dice_p * _lookup(values, x + 13 * s, H) + (
                    1.0 - dice_p
                ) * _lookup(values, x - s, H)
                if _better(BET_DICE, s, q, bt, bs, bq):
                    bt = BET_DICE
                    bs = s
                    bq = q
        best_type[i] = bt
        best_stake[i] = bs


def _arrays_from_session(session: SessionConfig, game: GameConfig):
    bounds = precompute_action_bounds(session)
    step = session.bankroll_step
    H = bounds.H
    n = max(0, H - 1)
    min_steps = session.minimum_bet // step
    color_search = (bounds.color_search_max // step).astype(np.int64)
    dice_search = (bounds.dice_search_max // step).astype(np.int64)
    color_avail = bounds.color_available.astype(np.bool_)
    dice_avail = bounds.dice_available.astype(np.bool_)
    return (
        H,
        n,
        min_steps,
        color_search,
        dice_search,
        color_avail,
        dice_avail,
        float(game.color_win_probability),
        float(game.dice_win_probability),
        step,
    )


def _policy_from_arrays(
    session: SessionConfig,
    game: GameConfig,
    values: np.ndarray,
    best_type: np.ndarray,
    best_stake: np.ndarray,
) -> tuple[dict[int, float], dict[int, PolicyDecision]]:
    floor = session.floor_bankroll
    target = session.target_bankroll
    step = session.bankroll_step
    H = (target - floor) // step
    value_dict: dict[int, float] = {}
    policy: dict[int, PolicyDecision] = {}
    for x in range(H + 1):
        b = floor + x * step
        if x == 0:
            value_dict[b] = 0.0
            policy[b] = PolicyDecision(b, None, 0.0, None, None)
            continue
        if x == H:
            value_dict[b] = 1.0
            policy[b] = PolicyDecision(b, None, 1.0, None, None)
            continue
        i = x - 1
        bt = int(best_type[i])
        stake_steps = int(best_stake[i])
        v = float(values[x])
        if bt == BET_NONE:
            value_dict[b] = 0.0
            policy[b] = PolicyDecision(b, None, 0.0, None, None)
            continue
        bet_type = "COLOR" if bt == BET_COLOR else "DICE"
        action = Action(bet_type, stake_steps * step)  # type: ignore[arg-type]
        win_b, lose_b = next_bankrolls(b, action, game)
        value_dict[b] = v
        policy[b] = PolicyDecision(b, action, v, win_b, lose_b)
    return value_dict, policy


def _result_from_policy_arrays(
    session: SessionConfig,
    game: GameConfig,
    values: np.ndarray,
    best_type: np.ndarray,
    best_stake: np.ndarray,
    *,
    iterations: int,
    final_delta: float,
    convergence_reason: str,
) -> SolverResult:
    value_dict, policy = _policy_from_arrays(
        session, game, values, best_type, best_stake
    )
    return SolverResult(
        True,
        iterations,
        float(final_delta),
        value_dict,
        policy,
        convergence_reason=convergence_reason,
    )


def _certify_policy(
    session: SessionConfig,
    game: GameConfig,
    best_type: np.ndarray,
    best_stake: np.ndarray,
    H: int,
    min_steps: int,
    color_search: np.ndarray,
    dice_search: np.ndarray,
    color_avail: np.ndarray,
    dice_avail: np.ndarray,
    color_p: float,
    dice_p: float,
) -> tuple[bool, np.ndarray]:
    """Return (ok, Vπ as length H+1 array) if policy is Bellman-optimal w.r.t. Vπ."""
    dummy_values = np.zeros(H + 1, dtype=np.float64)
    dummy_values[H] = 1.0
    # Build SolverResult skeleton for sparse eval using current greedy actions.
    value_dict, policy = _policy_from_arrays(
        session, game, dummy_values, best_type, best_stake
    )
    # Seed values from actions' Q under dummy is wrong; sparse eval ignores values.
    skeleton = SolverResult(True, 0, 0.0, value_dict, policy)
    try:
        evaluated = evaluate_policy_sparse(skeleton, session, game)
    except (VerificationError, Exception):
        return False, dummy_values

    floor = session.floor_bankroll
    step = session.bankroll_step
    v_arr = np.zeros(H + 1, dtype=np.float64)
    v_arr[H] = 1.0
    for x in range(1, H):
        b = floor + x * step
        v_arr[x] = float(evaluated[b])

    improved_type = np.zeros(H - 1, dtype=np.int64)
    improved_stake = np.zeros(H - 1, dtype=np.int64)
    _policy_improve_serial(
        v_arr,
        improved_type,
        improved_stake,
        color_search,
        dice_search,
        color_avail,
        dice_avail,
        min_steps,
        H,
        color_p,
        dice_p,
    )
    if not np.array_equal(improved_type, best_type) or not np.array_equal(
        improved_stake, best_stake
    ):
        return False, v_arr

    # Legality + gap check via domain verifier helpers.
    value_dict, policy = _policy_from_arrays(
        session, game, v_arr, best_type, best_stake
    )
    certified = SolverResult(True, 0, 0.0, value_dict, policy)
    if not verify_legal_actions_direct(certified, session):
        return False, v_arr

    ss = build_state_space(session)
    max_gap = 0.0
    from roulette_optimizer.action_bounds import legal_actions_pruned

    for b in ss.nonterminal:
        chosen = policy[b].action
        chosen_q = (
            0.0
            if chosen is None
            else action_value(
                b,
                chosen,
                evaluated,
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
                evaluated,
                game,
                target=session.target_bankroll,
                floor=session.floor_bankroll,
            )
            best_q = max(best_q, q)
        max_gap = max(max_gap, best_q - chosen_q)
    if max_gap > session.optimality_tolerance:
        return False, v_arr
    return True, v_arr


def warm_up_kernels() -> None:
    """Compile Numba kernels on a tiny problem (API startup)."""
    session = SessionConfig(starting_bankroll=2, target_bankroll=4, floor_bankroll=0)
    game = GameConfig()
    (
        H,
        n,
        min_steps,
        color_search,
        dice_search,
        color_avail,
        dice_avail,
        color_p,
        dice_p,
        _step,
    ) = _arrays_from_session(session, game)
    old_v = np.zeros(H + 1, dtype=np.float64)
    old_v[H] = 1.0
    new_v = old_v.copy()
    best_type = np.zeros(n, dtype=np.int64)
    best_stake = np.zeros(n, dtype=np.int64)
    _bellman_sweep_serial(
        old_v,
        new_v,
        best_type,
        best_stake,
        color_search,
        dice_search,
        color_avail,
        dice_avail,
        min_steps,
        H,
        color_p,
        dice_p,
    )
    _policy_improve_serial(
        new_v,
        best_type,
        best_stake,
        color_search,
        dice_search,
        color_avail,
        dice_avail,
        min_steps,
        H,
        color_p,
        dice_p,
    )
    if n >= 1:
        _bellman_sweep_parallel(
            old_v,
            new_v,
            best_type,
            best_stake,
            color_search,
            dice_search,
            color_avail,
            dice_avail,
            min_steps,
            H,
            color_p,
            dice_p,
        )


def solve_numba(
    session: SessionConfig,
    game: GameConfig | None = None,
    *,
    use_certificate: bool = True,
    force_parallel: bool | None = None,
    timings: PerformanceTimings | None = None,
) -> SolverResult:
    game = game or GameConfig()
    clock = PerfClock()
    (
        H,
        n,
        min_steps,
        color_search,
        dice_search,
        color_avail,
        dice_avail,
        color_p,
        dice_p,
        _step,
    ) = _arrays_from_session(session, game)
    state_ms = clock.restart()

    values = np.zeros(H + 1, dtype=np.float64)
    values[H] = 1.0
    best_type = np.zeros(n, dtype=np.int64)
    best_stake = np.zeros(n, dtype=np.int64)
    prev_type = np.full(n, -1, dtype=np.int64)
    prev_stake = np.full(n, -1, dtype=np.int64)
    unchanged = 0

    use_parallel = (
        force_parallel
        if force_parallel is not None
        else n >= PARALLEL_STATE_THRESHOLD
    )
    sweep = _bellman_sweep_parallel if use_parallel else _bellman_sweep_serial

    converged = False
    delta = 0.0
    iterations = 0
    color_evals_total = 0
    dice_evals_total = 0
    reason = "value_delta"
    bellman_ms = 0.0

    for iterations in range(1, session.solver_max_iterations + 1):
        t0 = PerfClock()
        new_values = values.copy()
        delta, ce, de = sweep(
            values,
            new_values,
            best_type,
            best_stake,
            color_search,
            dice_search,
            color_avail,
            dice_avail,
            min_steps,
            H,
            color_p,
            dice_p,
        )
        values = new_values
        color_evals_total += ce
        dice_evals_total += de
        bellman_ms += t0.ms()

        if use_certificate and n > 0:
            if np.array_equal(best_type, prev_type) and np.array_equal(
                best_stake, prev_stake
            ):
                unchanged += 1
            else:
                unchanged = 0
                prev_type = best_type.copy()
                prev_stake = best_stake.copy()

            if unchanged >= _POLICY_STABLE_SWEEPS:
                ok, v_pi = _certify_policy(
                    session,
                    game,
                    best_type,
                    best_stake,
                    H,
                    min_steps,
                    color_search,
                    dice_search,
                    color_avail,
                    dice_avail,
                    color_p,
                    dice_p,
                )
                if ok:
                    values = v_pi
                    converged = True
                    reason = "policy_certificate"
                    delta = 0.0
                    break

        if delta < session.solver_tolerance:
            converged = True
            reason = "value_delta"
            break

    if not converged:
        raise SolverError(
            f"Value iteration did not converge "
            f"(iterations={iterations}, delta={delta})"
        )

    extract_clock = PerfClock()
    # Final greedy extract from frozen values for value_delta path.
    if reason == "value_delta":
        _policy_improve_serial(
            values,
            best_type,
            best_stake,
            color_search,
            dice_search,
            color_avail,
            dice_avail,
            min_steps,
            H,
            color_p,
            dice_p,
        )
        # NO_ACTION states: force value 0
        for i in range(n):
            if best_type[i] == BET_NONE:
                values[i + 1] = 0.0

    result = _result_from_policy_arrays(
        session,
        game,
        values,
        best_type,
        best_stake,
        iterations=iterations,
        final_delta=delta,
        convergence_reason=reason,
    )
    extract_ms = extract_clock.ms()

    if timings is not None:
        timings.state_space_ms += state_ms
        timings.bellman_iterations_ms += bellman_ms
        timings.policy_extraction_ms += extract_ms
        timings.solver_total_ms += state_ms + bellman_ms + extract_ms
        timings.solver_name = "numba"
        timings.iterations = iterations
        timings.non_terminal_states = n
        timings.candidate_color_evaluations = color_evals_total
        timings.candidate_dice_evaluations = dice_evals_total
        timings.convergence_reason = reason

    return result


class NumbaSolver:
    def solve(
        self, session: SessionConfig, game: GameConfig | None = None
    ) -> SolverResult:
        return solve_numba(session, game)
