from __future__ import annotations

import time
from dataclasses import dataclass

from roulette_optimizer.config import GameConfig, SessionConfig, validate_session
from roulette_optimizer.play import loaded_policy_from_result
from roulette_optimizer.policy import (
    LoadedPolicy,
    consecutive_loss_durability,
    count_policy_actions,
)
from roulette_optimizer.solver import solve
from roulette_optimizer.state_space import (
    build_state_space,
    check_state_space_size,
    nonterminal_count,
)
from roulette_optimizer.utils import ConfigError


@dataclass(frozen=True)
class SweepRow:
    start: int
    target: int
    floor: int
    target_profit: int
    maximum_loss: int
    state_count: int
    V_start: float
    initial_loss_durability: int
    COLOR_state_count: int
    DICE_state_count: int
    NO_ACTION_state_count: int
    iterations: int
    final_delta: float
    solve_seconds: float
    solver: str
    verification_status: str
    failure_info: str = ""


@dataclass(frozen=True)
class SweepResult:
    start: int
    target_profits: list[int]
    floor_losses: list[int]
    rows: list[SweepRow]
    successful: int
    failed: int
    total_seconds: float


def parse_int_list(raw: str, *, label: str) -> list[int]:
    if raw is None or not str(raw).strip():
        raise ConfigError(f"Empty {label} list")
    parts = [p.strip() for p in str(raw).split(",")]
    if any(p == "" for p in parts):
        raise ConfigError(f"Empty value in {label} list")
    try:
        values = [int(p) for p in parts]
    except ValueError as exc:
        raise ConfigError(f"Invalid integer in {label} list") from exc
    seen: set[int] = set()
    out: list[int] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    if not out:
        raise ConfigError(f"Empty {label} list")
    return out


def build_sweep_configs(
    bankroll: int,
    target_profits: list[int],
    floor_losses: list[int],
    *,
    force: bool = False,
) -> list[tuple[int, int, SessionConfig]]:
    if not target_profits:
        raise ConfigError("Empty target profit list")
    if not floor_losses:
        raise ConfigError("Empty floor loss list")
    configs: list[tuple[int, int, SessionConfig]] = []
    for tp in target_profits:
        if tp <= 0:
            raise ConfigError(f"target_profit must be > 0, got {tp}")
        for fl in floor_losses:
            if fl <= 0:
                raise ConfigError(f"floor_loss must be > 0, got {fl}")
            target = bankroll + tp
            floor = bankroll - fl
            session = SessionConfig(
                starting_bankroll=bankroll,
                target_bankroll=target,
                floor_bankroll=floor,
            )
            try:
                validate_session(session)
                check_state_space_size(nonterminal_count(session), force=force)
            except ConfigError as exc:
                raise ConfigError(
                    f"Invalid config for target_profit={tp}, floor_loss={fl}: {exc}"
                ) from exc
            configs.append((tp, fl, session))
    return configs


def default_sweep_output_path(bankroll: int) -> str:
    return f"outputs/sweep_{bankroll}.csv"


SWEEP_CSV_FIELDS = [
    "start",
    "target",
    "floor",
    "target_profit",
    "maximum_loss",
    "state_count",
    "V_start",
    "initial_loss_durability",
    "COLOR_state_count",
    "DICE_state_count",
    "NO_ACTION_state_count",
    "iterations",
    "final_delta",
    "solve_seconds",
    "solver",
    "verification_status",
]


def run_sweep(
    bankroll: int,
    target_profits: list[int],
    floor_losses: list[int],
    *,
    solver: str = "numpy",
    verify: bool = False,
    force: bool = False,
) -> SweepResult:
    if solver not in ("numpy", "reference", "numba", "policy_iteration"):
        raise ConfigError(f"Unknown solver: {solver!r}")
    from roulette_optimizer.policy_cache import (
        resolve_production_solver,
        solve_and_cache,
    )

    solver_used = resolve_production_solver(solver)
    game = GameConfig()
    pairs = build_sweep_configs(
        bankroll, target_profits, floor_losses, force=force
    )
    rows: list[SweepRow] = []
    successful = 0
    failed = 0
    t0 = time.perf_counter()
    for tp, fl, session in pairs:
        t_solve = time.perf_counter()
        try:
            if verify:
                hit = solve_and_cache(session, solver=solver)
                result = hit.result
                loaded = hit.loaded
                status = "VALID"
                failure = ""
                successful += 1
                label = hit.solver_used
            else:
                result = solve(session, solver=solver_used)
                loaded = loaded_policy_from_result(session, game, result)
                status = "NOT_RUN"
                failure = ""
                successful += 1
                label = solver_used
            elapsed = time.perf_counter() - t_solve
            ss = build_state_space(session)
            color_c, dice_c, none_c = count_policy_actions(result, session)
            loss_durability = consecutive_loss_durability(loaded, bankroll)
            rows.append(
                SweepRow(
                    start=bankroll,
                    target=session.target_bankroll,
                    floor=session.floor_bankroll,
                    target_profit=tp,
                    maximum_loss=fl,
                    state_count=len(ss.nonterminal),
                    V_start=result.values[session.starting_bankroll],
                    initial_loss_durability=loss_durability,
                    COLOR_state_count=color_c,
                    DICE_state_count=dice_c,
                    NO_ACTION_state_count=none_c,
                    iterations=result.iterations,
                    final_delta=result.final_delta,
                    solve_seconds=elapsed,
                    solver=label,
                    verification_status=status,
                    failure_info=failure,
                )
            )
        except Exception as exc:
            elapsed = time.perf_counter() - t_solve
            failed += 1
            rows.append(
                SweepRow(
                    start=bankroll,
                    target=session.target_bankroll,
                    floor=session.floor_bankroll,
                    target_profit=tp,
                    maximum_loss=fl,
                    state_count=0,
                    V_start=float("nan"),
                    initial_loss_durability=0,
                    COLOR_state_count=0,
                    DICE_state_count=0,
                    NO_ACTION_state_count=0,
                    iterations=0,
                    final_delta=float("nan"),
                    solve_seconds=elapsed,
                    solver=solver_used,
                    verification_status="FAILED",
                    failure_info=str(exc),
                )
            )
    rows.sort(key=lambda r: (r.target_profit, r.maximum_loss))
    return SweepResult(
        start=bankroll,
        target_profits=list(target_profits),
        floor_losses=list(floor_losses),
        rows=rows,
        successful=successful,
        failed=failed,
        total_seconds=time.perf_counter() - t0,
    )


def sweep_rows_as_dicts(rows: list[SweepRow]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for r in rows:
        out.append(
            {
                "start": r.start,
                "target": r.target,
                "floor": r.floor,
                "target_profit": r.target_profit,
                "maximum_loss": r.maximum_loss,
                "state_count": r.state_count,
                "V_start": r.V_start,
                "initial_loss_durability": r.initial_loss_durability,
                "COLOR_state_count": r.COLOR_state_count,
                "DICE_state_count": r.DICE_state_count,
                "NO_ACTION_state_count": r.NO_ACTION_state_count,
                "iterations": r.iterations,
                "final_delta": r.final_delta,
                "solve_seconds": r.solve_seconds,
                "solver": r.solver,
                "verification_status": r.verification_status,
            }
        )
    return out
