from __future__ import annotations

from dataclasses import dataclass

from roulette_optimizer.actions import Action, legal_actions
from roulette_optimizer.config import GameConfig, SessionConfig, validate_game, validate_session
from roulette_optimizer.game import action_value, next_bankrolls
from roulette_optimizer.state_space import build_state_space
from roulette_optimizer.utils import SolverError

TIE_EPS = 1e-12


@dataclass(frozen=True)
class PolicyDecision:
    bankroll: int
    action: Action | None
    success_probability: float
    win_bankroll: int | None
    lose_bankroll: int | None


@dataclass
class SolverResult:
    converged: bool
    iterations: int
    final_delta: float
    values: dict[int, float]
    policy: dict[int, PolicyDecision]
    convergence_reason: str | None = None


def _better(candidate: Action, current: Action | None, q_cand: float, q_cur: float) -> bool:
    if current is None:
        return True
    if q_cand > q_cur + TIE_EPS:
        return True
    if abs(q_cand - q_cur) <= TIE_EPS:
        if candidate.stake < current.stake:
            return True
        if candidate.stake == current.stake and candidate.bet_type == "COLOR" and current.bet_type == "DICE":
            return True
    return False


def _best_action(
    bankroll: int,
    values: dict[int, float],
    session: SessionConfig,
    game: GameConfig,
) -> tuple[Action | None, float]:
    best_a: Action | None = None
    best_q = 0.0
    for action in legal_actions(bankroll, session):
        q = action_value(
            bankroll,
            action,
            values,
            game,
            target=session.target_bankroll,
            floor=session.floor_bankroll,
        )
        if _better(action, best_a, q, best_q):
            best_a, best_q = action, q
    if best_a is None:
        return None, 0.0
    return best_a, best_q


KNOWN_SOLVERS = ("reference", "numpy", "numba", "policy_iteration")


def solve(
    session: SessionConfig,
    game: GameConfig | None = None,
    *,
    solver: str = "numba",
) -> SolverResult:
    validate_session(session)
    game = game or GameConfig()
    validate_game(game)
    if solver == "numpy":
        from roulette_optimizer.numpy_solver import solve_numpy

        return solve_numpy(session, game)
    if solver == "numba":
        from roulette_optimizer.numba_solver import solve_numba

        return solve_numba(session, game)
    if solver == "policy_iteration":
        from roulette_optimizer.policy_iteration_solver import solve_policy_iteration

        return solve_policy_iteration(session, game)
    if solver != "reference":
        raise SolverError(f"Unknown solver: {solver!r}")
    return solve_reference(session, game)


def solve_reference(
    session: SessionConfig, game: GameConfig | None = None
) -> SolverResult:
    """Authoritative exhaustive pure-Python reference solve."""
    game = game or GameConfig()
    ss = build_state_space(session)
    values = {b: 0.0 for b in ss.states}
    values[ss.floor] = 0.0
    values[ss.target] = 1.0

    converged = False
    delta = 0.0
    iterations = 0
    for iterations in range(1, session.solver_max_iterations + 1):
        new_values = dict(values)
        delta = 0.0
        for b in ss.nonterminal:
            _, q = _best_action(b, values, session, game)
            new_values[b] = q
            delta = max(delta, abs(q - values[b]))
        values = new_values
        if delta < session.solver_tolerance:
            converged = True
            break
    if not converged:
        raise SolverError(
            f"Value iteration did not converge "
            f"(iterations={iterations}, delta={delta})"
        )

    policy: dict[int, PolicyDecision] = {}
    for b in ss.states:
        if b <= ss.floor:
            policy[b] = PolicyDecision(b, None, 0.0, None, None)
            continue
        if b >= ss.target:
            policy[b] = PolicyDecision(b, None, 1.0, None, None)
            continue
        action, q = _best_action(b, values, session, game)
        if action is None:
            policy[b] = PolicyDecision(b, None, 0.0, None, None)
            values[b] = 0.0
        else:
            win_b, lose_b = next_bankrolls(b, action, game)
            policy[b] = PolicyDecision(b, action, q, win_b, lose_b)

    return SolverResult(True, iterations, delta, values, policy)


class ReferenceSolver:
    """Thin wrapper around the pure-Python reference solve."""

    def solve(
        self, session: SessionConfig, game: GameConfig | None = None
    ) -> SolverResult:
        return solve_reference(session, game)
