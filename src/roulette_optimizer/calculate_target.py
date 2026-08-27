"""Setup-only Target search for a requested Reach target probability."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from roulette_optimizer.config import GameConfig, SessionConfig, validate_session
from roulette_optimizer.perf import PerfClock
from roulette_optimizer.policy_cache import PolicyCache, solve_and_cache
from roulette_optimizer.state_space import check_state_space_size, nonterminal_count
from roulette_optimizer.utils import ConfigError

logger = logging.getLogger(__name__)


def _is_state_space_limit(exc: ConfigError) -> bool:
    msg = str(exc)
    return "State space has" in msg and "non-terminal states" in msg


@dataclass(frozen=True)
class CandidateTiming:
    target: int
    cache_status: str
    solve_ms: float
    verify_ms: float
    probability: float


@dataclass(frozen=True)
class CalculateTargetResult:
    target: int
    target_hit_probability: float
    solves: int
    total_ms: float = 0.0
    candidates: tuple[CandidateTiming, ...] = ()


def _session(bankroll: int, target: int, floor: int) -> SessionConfig:
    session = SessionConfig(
        starting_bankroll=bankroll,
        target_bankroll=target,
        floor_bankroll=floor,
    )
    validate_session(session)
    return session


def _default_step() -> int:
    return SessionConfig(
        starting_bankroll=2,
        target_bankroll=3,
        floor_bankroll=1,
    ).bankroll_step


def calculate_target_for_reach(
    starting_bankroll: int,
    floor: int,
    reach_target_probability: float,
    *,
    game: GameConfig | None = None,
    solver: str | None = None,
    force: bool = False,
    cache: PolicyCache | None = None,
) -> CalculateTargetResult:
    """Find the highest Target T with V(B; T, F) >= requested probability.

    Uses only ``solve_and_cache``. Does not create a live session.
    Request-local memo prevents duplicate candidate solves within one search.
    """
    game = game or GameConfig()
    step = _default_step()
    wall = PerfClock()

    if reach_target_probability <= 0 or reach_target_probability > 1:
        raise ConfigError("Reach target % must be greater than 0 and at most 100.")
    if floor >= starting_bankroll:
        raise ConfigError("Hard floor must be below current bankroll.")
    if floor < 0:
        raise ConfigError("Hard floor must be ≥ 0.")
    if starting_bankroll % step != 0 or floor % step != 0:
        raise ConfigError("Bankroll and Hard floor must align to bankroll_step.")

    min_target = starting_bankroll + step
    if min_target % step != 0:
        min_target += step - (min_target % step)

    # Request-local memo: target → (probability, CandidateTiming)
    memo: dict[int, tuple[float, CandidateTiming]] = {}
    candidates: list[CandidateTiming] = []

    def solve_v(target: int) -> float:
        cached = memo.get(target)
        if cached is not None:
            return cached[0]

        session = _session(starting_bankroll, target, floor)
        check_state_space_size(nonterminal_count(session), force=force)
        t0 = PerfClock()
        hit = solve_and_cache(session, game, solver=solver, cache=cache)
        elapsed = t0.ms()
        probability = float(hit.result.values[starting_bankroll])
        timing = CandidateTiming(
            target=target,
            cache_status=hit.cache_status,
            solve_ms=hit.timings.solver_total_ms,
            verify_ms=hit.timings.verification_total_ms,
            probability=probability,
        )
        # Prefer wall elapsed when solver timings are empty (cache hits).
        if timing.solve_ms == 0.0 and timing.verify_ms == 0.0:
            timing = CandidateTiming(
                target=target,
                cache_status=hit.cache_status,
                solve_ms=elapsed,
                verify_ms=0.0,
                probability=probability,
            )
        memo[target] = (probability, timing)
        candidates.append(timing)
        return probability

    try:
        v_min = solve_v(min_target)
    except ConfigError as exc:
        raise ConfigError(str(exc)) from exc

    if v_min < reach_target_probability:
        raise ConfigError(
            "No valid Target: even the minimum Target cannot reach the requested "
            "Reach target %."
        )

    # Expand upper bound until probability drops below P or state-space limit.
    lo = min_target
    v_lo = v_min
    hi: int | None = None
    grow = max(step, (min_target - floor) or step)

    while True:
        candidate = lo + grow
        candidate -= candidate % step
        if candidate <= lo:
            candidate = lo + step
        try:
            v_cand = solve_v(candidate)
        except ConfigError as exc:
            if _is_state_space_limit(exc):
                break
            raise

        if v_cand < reach_target_probability:
            hi = candidate
            break

        lo = candidate
        v_lo = v_cand
        grow = max(step, grow * 2)

    if hi is None:
        total_ms = wall.ms()
        result = CalculateTargetResult(
            target=lo,
            target_hit_probability=v_lo,
            solves=len(candidates),
            total_ms=total_ms,
            candidates=tuple(candidates),
        )
        logger.info(
            "calculate_target bankroll=%s floor=%s P=%.6f target=%s "
            "solves=%s total_ms=%.1f candidates=%s truncated=state_space",
            starting_bankroll,
            floor,
            reach_target_probability,
            lo,
            result.solves,
            total_ms,
            [
                {
                    "target": c.target,
                    "cache": c.cache_status,
                    "solve_ms": round(c.solve_ms, 2),
                    "verify_ms": round(c.verify_ms, 2),
                    "p": round(c.probability, 6),
                }
                for c in candidates
            ],
        )
        return result

    # Binary search grid in [lo, hi): highest T with V >= P.
    best_t = lo
    best_v = v_lo
    low = lo
    high = hi
    assert high is not None
    while high - low > step:
        mid = low + ((high - low) // (2 * step)) * step
        if mid <= low:
            mid = low + step
        if mid >= high:
            break
        v_mid = solve_v(mid)
        if v_mid >= reach_target_probability:
            best_t = mid
            best_v = v_mid
            low = mid
        else:
            high = mid

    total_ms = wall.ms()
    result = CalculateTargetResult(
        target=best_t,
        target_hit_probability=best_v,
        solves=len(candidates),
        total_ms=total_ms,
        candidates=tuple(candidates),
    )
    logger.info(
        "calculate_target bankroll=%s floor=%s P=%.6f target=%s "
        "solves=%s total_ms=%.1f candidates=%s",
        starting_bankroll,
        floor,
        reach_target_probability,
        best_t,
        result.solves,
        total_ms,
        [
            {
                "target": c.target,
                "cache": c.cache_status,
                "solve_ms": round(c.solve_ms, 2),
                "verify_ms": round(c.verify_ms, 2),
                "p": round(c.probability, 6),
            }
            for c in candidates
        ],
    )
    return result
