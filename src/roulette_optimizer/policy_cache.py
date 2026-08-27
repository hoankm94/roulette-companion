from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roulette_optimizer.actions import Action
from roulette_optimizer.config import GameConfig, SessionConfig, session_to_dict, validate_game, validate_session
from roulette_optimizer.game import next_bankrolls
from roulette_optimizer.perf import PerfClock, PerformanceTimings
from roulette_optimizer.policy import LoadedPolicy
from roulette_optimizer.policy_verifier import verify_policy
from roulette_optimizer.solver import PolicyDecision, SolverResult, TIE_EPS, solve
from roulette_optimizer.utils import PolicyError

MATH_MODEL_VERSION = 1
CACHE_SCHEMA_VERSION = 1
SOLVER_VERSION = "1"

DEFAULT_CACHE_DIR = Path("outputs/policy_cache")
DEFAULT_MEMORY_CAPACITY = 32

# Production cache-miss solver for all product modes.
DEFAULT_PRODUCTION_SOLVER = "numba"


def resolve_production_solver(solver: str | None) -> str:
    """Map legacy/default 'numpy' to the optimized production solver.

    Explicit ``reference`` / ``policy_iteration`` / ``numba`` are preserved.
    """
    if solver is None or solver == "numpy":
        return DEFAULT_PRODUCTION_SOLVER
    return solver


@dataclass(frozen=True)
class CacheLookupResult:
    loaded: LoadedPolicy
    result: SolverResult
    verification: Any
    cache_status: str  # MEMORY_HIT | DISK_HIT | MISS
    solve_calls: int
    timings: PerformanceTimings
    solver_used: str


def build_normalized_cache_key(
    session: SessionConfig,
    game: GameConfig,
    *,
    solver: str,
) -> dict[str, Any]:
    step = session.bankroll_step
    span = (session.target_bankroll - session.floor_bankroll) // step
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "math_model_version": MATH_MODEL_VERSION,
        "target_span_steps": span,
        "bankroll_step": step,
        "minimum_bet": session.minimum_bet,
        "maximum_color_bet": session.maximum_color_bet,
        "maximum_dice_bet": session.maximum_dice_bet,
        "allow_color": session.allow_color,
        "allow_dice": session.allow_dice,
        "color_win_probability": game.color_win_probability,
        "dice_win_probability": game.dice_win_probability,
        "color_net_multiplier": game.color_net_multiplier,
        "dice_net_multiplier": game.dice_net_multiplier,
        "tie_eps": TIE_EPS,
        "solver": solver,
        "solver_version": SOLVER_VERSION,
        "solver_tolerance": session.solver_tolerance,
        "verification_tolerance": session.verification_tolerance,
        "optimality_tolerance": session.optimality_tolerance,
    }


def cache_key_hash(key: dict[str, Any]) -> str:
    blob = json.dumps(key, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _entries_digest(entries: list[dict[str, Any]]) -> str:
    blob = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _verification_to_payload(verification: Any) -> dict[str, Any]:
    return {
        "deterministic_status": "VALID",
        "metrics_available": True,
        "policy_evaluation_passed": verification.policy_evaluation_passed,
        "bellman_passed": verification.bellman_passed,
        "max_value_difference": verification.max_value_difference,
        "max_optimality_gap": verification.max_optimality_gap,
        "linear_value_bellman_passed": verification.linear_value_bellman_passed,
        "vi_bellman_max_gap": verification.vi_bellman_max_gap,
        "linear_value_bellman_max_gap": verification.linear_value_bellman_max_gap,
        "legal_actions_passed": verification.legal_actions_passed,
    }


def _verification_from_payload(
    payload: dict[str, Any],
    result: SolverResult,
) -> Any:
    from roulette_optimizer.policy_verifier import VerificationResult

    ver = payload.get("verification") or {}
    if ver.get("deterministic_status") != "VALID":
        raise PolicyError("Cached policy not VALID")
    if not ver.get("metrics_available"):
        return VerificationResult(
            True,
            True,
            math.nan,
            math.nan,
            dict(result.values),
            True,
            math.nan,
            math.nan,
            True,
        )
    return VerificationResult(
        bool(ver["policy_evaluation_passed"]),
        bool(ver["bellman_passed"]),
        float(ver["max_value_difference"]),
        float(ver["max_optimality_gap"]),
        dict(result.values),
        bool(ver["linear_value_bellman_passed"]),
        float(ver["vi_bellman_max_gap"]),
        float(ver["linear_value_bellman_max_gap"]),
        bool(ver["legal_actions_passed"]),
    )


def _normalize_policy_payload(
    session: SessionConfig,
    result: SolverResult,
) -> dict[str, Any]:
    floor = session.floor_bankroll
    step = session.bankroll_step
    entries: list[dict[str, Any]] = []
    span = (session.target_bankroll - floor) // step
    for b, decision in sorted(result.policy.items()):
        if b <= floor or b >= session.target_bankroll:
            continue
        x = (b - floor) // step
        action = decision.action
        entry: dict[str, Any] = {
            "x": x,
            "value": result.values[b],
            "bet_type": None if action is None else action.bet_type,
            "stake": None if action is None else action.stake,
            "win_x": None
            if decision.win_bankroll is None
            else (decision.win_bankroll - floor) // step,
            "lose_x": None
            if decision.lose_bankroll is None
            else (decision.lose_bankroll - floor) // step,
        }
        entries.append(entry)
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "math_model_version": MATH_MODEL_VERSION,
        "normalized_span": span,
        "floor": floor,
        "step": step,
        "target": session.target_bankroll,
        "session": session_to_dict(session),
        "solver": result.convergence_reason or "",
        "solver_version": SOLVER_VERSION,
        "entries": entries,
        "entries_digest": _entries_digest(entries),
        "iterations": result.iterations,
        "final_delta": result.final_delta,
        "convergence_reason": result.convergence_reason,
    }


def _denormalize_to_session(
    payload: dict[str, Any],
    session: SessionConfig,
    game: GameConfig,
) -> tuple[SolverResult, LoadedPolicy]:
    floor = session.floor_bankroll
    step = session.bankroll_step
    target = session.target_bankroll
    values: dict[int, float] = {}
    policy: dict[int, PolicyDecision] = {}
    for entry in payload["entries"]:
        x = int(entry["x"])
        b = floor + x * step
        if b < floor or b > target:
            # Span mismatch — reject
            raise PolicyError("Cached policy state outside session span")
        v = float(entry["value"])
        values[b] = v
        bet_type = entry["bet_type"]
        stake = entry["stake"]
        if bet_type is None:
            policy[b] = PolicyDecision(b, None, v, None, None)
        else:
            action = Action(bet_type, int(stake))  # type: ignore[arg-type]
            win_b, lose_b = next_bankrolls(b, action, game)
            if lose_b < floor:
                raise PolicyError("Cached transition outside session span")
            if (win_b - floor) % step != 0 or (lose_b - floor) % step != 0:
                raise PolicyError("Cached transition off bankroll grid")
            policy[b] = PolicyDecision(b, action, v, win_b, lose_b)

    # Ensure terminals exist
    values.setdefault(floor, 0.0)
    values.setdefault(target, 1.0)
    policy.setdefault(floor, PolicyDecision(floor, None, 0.0, None, None))
    policy.setdefault(target, PolicyDecision(target, None, 1.0, None, None))

    result = SolverResult(
        True,
        int(payload.get("iterations", 0)),
        float(payload.get("final_delta", 0.0)),
        values,
        policy,
        convergence_reason=payload.get("convergence_reason"),
    )
    loaded = LoadedPolicy(
        session=session,
        game=game,
        converged=True,
        deterministic_status="VALID",
        policy=policy,
    )
    return result, loaded


def _validate_payload(
    payload: dict[str, Any],
    key: dict[str, Any],
    session: SessionConfig,
) -> None:
    if payload.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
        raise PolicyError("Cache schema version mismatch")
    if payload.get("math_model_version") != MATH_MODEL_VERSION:
        raise PolicyError("Math model version mismatch")
    span = key["target_span_steps"]
    if payload.get("normalized_span") != span:
        raise PolicyError("Cache span mismatch")
    if "entries" not in payload:
        raise PolicyError("Malformed cache payload")
    entries = payload["entries"]
    digest = payload.get("entries_digest")
    if digest is None:
        raise PolicyError("Cache payload missing entries_digest")
    if _entries_digest(entries) != digest:
        raise PolicyError("Cache entries digest mismatch")
    expected_x = set(range(1, span))
    seen_x: set[int] = set()
    for entry in entries:
        x = int(entry["x"])
        if x not in expected_x:
            raise PolicyError("Cached policy state outside session span")
        seen_x.add(x)
    if seen_x != expected_x:
        raise PolicyError("Cache entries incomplete")


class PolicyCache:
    def __init__(
        self,
        cache_dir: Path | str | None = None,
        *,
        memory_capacity: int = DEFAULT_MEMORY_CAPACITY,
    ) -> None:
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.memory_capacity = memory_capacity
        self._memory: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def _touch_memory(self, digest: str, payload: dict[str, Any]) -> None:
        if digest in self._memory:
            self._memory.move_to_end(digest)
        self._memory[digest] = payload
        while len(self._memory) > self.memory_capacity:
            self._memory.popitem(last=False)

    def get(self, digest: str) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            if digest in self._memory:
                payload = self._memory[digest]
                self._memory.move_to_end(digest)
                return payload, "MEMORY_HIT"
        path = self.cache_dir / f"{digest}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self._lock:
                self._touch_memory(digest, payload)
            return payload, "DISK_HIT"
        return None, "MISS"

    def put(self, digest: str, payload: dict[str, Any]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{digest}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self._lock:
            self._touch_memory(digest, payload)


_GLOBAL_CACHE: PolicyCache | None = None


def get_policy_cache() -> PolicyCache:
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        _GLOBAL_CACHE = PolicyCache()
    return _GLOBAL_CACHE


def init_policy_cache(cache_dir: Path | str | None = None) -> PolicyCache:
    global _GLOBAL_CACHE
    _GLOBAL_CACHE = PolicyCache(cache_dir=cache_dir)
    return _GLOBAL_CACHE


def solve_and_cache(
    session: SessionConfig,
    game: GameConfig | None = None,
    *,
    solver: str | None = None,
    cache: PolicyCache | None = None,
    use_cache: bool = True,
    timings: PerformanceTimings | None = None,
) -> CacheLookupResult:
    """Shared verified-policy path for all product modes (Live, Replay, etc.).

    Uses the normalized memory/disk cache so any mode that solves a span
    warms the cache for every other mode.
    """
    from roulette_optimizer.play import loaded_policy_from_result

    game = game or GameConfig()
    validate_session(session)
    validate_game(game)
    solver_name = resolve_production_solver(solver)
    timings = timings or PerformanceTimings()
    timings.solver_name = solver_name
    cache = cache or get_policy_cache()

    key = build_normalized_cache_key(session, game, solver=solver_name)
    digest = cache_key_hash(key)

    if use_cache:
        t0 = PerfClock()
        payload, status = cache.get(digest)
        timings.cache_lookup_ms += t0.ms()
        if payload is not None:
            try:
                _validate_payload(payload, key, session)
                result, loaded = _denormalize_to_session(payload, session, game)
                verification = _verification_from_payload(payload, result)
                timings.cache_status = status
                timings.iterations = result.iterations
                timings.convergence_reason = result.convergence_reason or ""
                return CacheLookupResult(
                    loaded,
                    result,
                    verification,
                    status,
                    0,
                    timings,
                    solver_name,
                )
            except PolicyError:
                pass  # fall through to solve

    t_solve = PerfClock()
    result = solve(session, game, solver=solver_name)
    timings.solver_total_ms += t_solve.ms()
    timings.iterations = result.iterations
    timings.convergence_reason = result.convergence_reason or ""

    t_ver = PerfClock()
    verification = verify_policy(result, session, game)
    timings.verification_total_ms += t_ver.ms()

    loaded = loaded_policy_from_result(session, game, result)
    if use_cache:
        payload = _normalize_policy_payload(session, result)
        payload["verification"] = _verification_to_payload(verification)
        payload["cache_key"] = key
        t_w = PerfClock()
        cache.put(digest, payload)
        timings.cache_write_ms += t_w.ms()
    timings.cache_status = "MISS"
    return CacheLookupResult(
        loaded, result, verification, "MISS", 1, timings, solver_name
    )
