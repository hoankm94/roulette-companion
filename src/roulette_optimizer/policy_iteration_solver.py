from __future__ import annotations

import numpy as np

from roulette_optimizer.config import GameConfig, SessionConfig
from roulette_optimizer.numba_solver import (
    BET_NONE,
    _arrays_from_session,
    _bellman_sweep_serial,
    _policy_from_arrays,
    _policy_improve_serial,
)
from roulette_optimizer.perf import PerfClock, PerformanceTimings
from roulette_optimizer.policy_verifier import evaluate_policy_sparse
from roulette_optimizer.solver import SolverResult
from roulette_optimizer.utils import SolverError, VerificationError


def solve_policy_iteration(
    session: SessionConfig,
    game: GameConfig | None = None,
    *,
    warm_start_sweeps: int = 4,
    max_policy_iterations: int = 10_000,
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

    bellman_ms = 0.0
    for _ in range(max(0, warm_start_sweeps)):
        t0 = PerfClock()
        new_values = values.copy()
        _bellman_sweep_serial(
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
        bellman_ms += t0.ms()

    pe_ms = 0.0
    iterations = 0
    for iterations in range(1, max_policy_iterations + 1):
        value_dict, policy = _policy_from_arrays(
            session, game, values, best_type, best_stake
        )
        skeleton = SolverResult(True, iterations, 0.0, value_dict, policy)
        t_pe = PerfClock()
        try:
            evaluated = evaluate_policy_sparse(skeleton, session, game)
        except VerificationError as exc:
            raise SolverError(f"Policy evaluation failed: {exc}") from exc
        pe_ms += t_pe.ms()

        floor = session.floor_bankroll
        step = session.bankroll_step
        for x in range(1, H):
            values[x] = float(evaluated[floor + x * step])
        values[0] = 0.0
        values[H] = 1.0

        old_type = best_type.copy()
        old_stake = best_stake.copy()
        t_imp = PerfClock()
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
        bellman_ms += t_imp.ms()

        if np.array_equal(best_type, old_type) and np.array_equal(
            best_stake, old_stake
        ):
            for i in range(n):
                if best_type[i] == BET_NONE:
                    values[i + 1] = 0.0
            value_dict, policy = _policy_from_arrays(
                session, game, values, best_type, best_stake
            )
            result = SolverResult(
                True,
                iterations,
                0.0,
                value_dict,
                policy,
                convergence_reason="policy_iteration",
            )
            if timings is not None:
                timings.state_space_ms += state_ms
                timings.bellman_iterations_ms += bellman_ms
                timings.policy_evaluation_ms += pe_ms
                timings.solver_total_ms += state_ms + bellman_ms + pe_ms
                timings.solver_name = "policy_iteration"
                timings.iterations = iterations
                timings.non_terminal_states = n
                timings.convergence_reason = "policy_iteration"
            return result

    raise SolverError(
        f"Policy iteration did not stabilize "
        f"(iterations={iterations})"
    )


class PolicyIterationSolver:
    def solve(
        self, session: SessionConfig, game: GameConfig | None = None
    ) -> SolverResult:
        return solve_policy_iteration(session, game)
