from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from roulette_optimizer.config import SessionConfig, session_to_dict
from roulette_optimizer.policy_verifier import VerificationResult
from roulette_optimizer.simulator import BatchResult, simulate_many
from roulette_optimizer.solver import SolverResult

Z_95 = 1.96


@dataclass(frozen=True)
class ConfidenceInterval:
    lower: float
    upper: float


@dataclass(frozen=True)
class ValidationStats:
    p_hat: float
    se: float
    ci: ConfidenceInterval
    absolute_error: float
    z_score: float
    solver_probability: float
    sessions: int
    target_hits: int


@dataclass(frozen=True)
class SeedValidationEntry:
    seed: int
    batch: BatchResult
    stats: ValidationStats


@dataclass
class ValidateResult:
    solver: SolverResult
    verification: VerificationResult
    batch: BatchResult | None
    stats: ValidationStats | None
    deterministic_status: Literal["VALID"]
    seeds_report: list[SeedValidationEntry] | None
    seed: int
    max_rounds: int


def compute_validation_stats(
    *,
    target_hits: int,
    sessions: int,
    solver_probability: float,
) -> ValidationStats:
    p_hat = target_hits / sessions
    se = math.sqrt(p_hat * (1.0 - p_hat) / sessions)
    absolute_error = abs(p_hat - solver_probability)

    if se == 0.0:
        z_score = 0.0 if absolute_error == 0.0 else float("inf")
        ci = ConfidenceInterval(lower=p_hat, upper=p_hat)
    else:
        margin = Z_95 * se
        ci = ConfidenceInterval(lower=p_hat - margin, upper=p_hat + margin)
        z_score = (p_hat - solver_probability) / se

    return ValidationStats(
        p_hat=p_hat,
        se=se,
        ci=ci,
        absolute_error=absolute_error,
        z_score=z_score,
        solver_probability=solver_probability,
        sessions=sessions,
        target_hits=target_hits,
    )


def _run_monte_carlo(
    *,
    policy: dict,
    session: SessionConfig,
    sessions: int,
    seed: int,
    max_rounds: int,
    solver_probability: float,
) -> tuple[BatchResult, ValidationStats]:
    batch = simulate_many(
        policy=policy,
        starting_bankroll=session.starting_bankroll,
        target=session.target_bankroll,
        floor=session.floor_bankroll,
        sessions=sessions,
        seed=seed,
        max_rounds=max_rounds,
    )
    stats = compute_validation_stats(
        target_hits=batch.target_hits,
        sessions=sessions,
        solver_probability=solver_probability,
    )
    return batch, stats


def run_validate(
    session: SessionConfig,
    *,
    sessions: int,
    seed: int,
    max_rounds: int,
    seeds: list[int] | None = None,
    solver: str = "numpy",
) -> ValidateResult:
    from roulette_optimizer.policy_cache import solve_and_cache

    hit = solve_and_cache(session, solver=solver)
    solver_result = hit.result
    verification = hit.verification
    solver_probability = solver_result.values[session.starting_bankroll]

    batch, stats = _run_monte_carlo(
        policy=solver_result.policy,
        session=session,
        sessions=sessions,
        seed=seed,
        max_rounds=max_rounds,
        solver_probability=solver_probability,
    )

    seeds_report: list[SeedValidationEntry] | None = None
    if seeds:
        seeds_report = []
        for extra_seed in seeds:
            extra_batch, extra_stats = _run_monte_carlo(
                policy=solver_result.policy,
                session=session,
                sessions=sessions,
                seed=extra_seed,
                max_rounds=max_rounds,
                solver_probability=solver_probability,
            )
            seeds_report.append(
                SeedValidationEntry(
                    seed=extra_seed,
                    batch=extra_batch,
                    stats=extra_stats,
                )
            )

    return ValidateResult(
        solver=solver_result,
        verification=verification,
        batch=batch,
        stats=stats,
        deterministic_status="VALID",
        seeds_report=seeds_report,
        seed=seed,
        max_rounds=max_rounds,
    )


def default_validation_output_path(session: SessionConfig, seed: int) -> Path:
    b, t, f = (
        session.starting_bankroll,
        session.target_bankroll,
        session.floor_bankroll,
    )
    return Path("outputs") / f"validation_{b}_{t}_{f}_seed{seed}.json"


def default_multiseed_output_path(session: SessionConfig) -> Path:
    b, t, f = (
        session.starting_bankroll,
        session.target_bankroll,
        session.floor_bankroll,
    )
    return Path("outputs") / f"validation_{b}_{t}_{f}_multiseed.json"


def _stats_to_dict(stats: ValidationStats) -> dict:
    return {
        "p_hat": stats.p_hat,
        "se": stats.se,
        "ci_lower": stats.ci.lower,
        "ci_upper": stats.ci.upper,
        "absolute_error": stats.absolute_error,
        "z_score": stats.z_score,
        "solver_probability": stats.solver_probability,
        "sessions": stats.sessions,
        "target_hits": stats.target_hits,
    }


def _batch_to_dict(batch: BatchResult) -> dict:
    return asdict(batch)


def _seed_entry_to_dict(entry: SeedValidationEntry) -> dict:
    return {
        "seed": entry.seed,
        "batch": _batch_to_dict(entry.batch),
        "stats": _stats_to_dict(entry.stats),
    }


def _primary_seed_entry(result: ValidateResult) -> SeedValidationEntry | None:
    if result.batch is None or result.stats is None:
        return None
    return SeedValidationEntry(
        seed=result.seed,
        batch=result.batch,
        stats=result.stats,
    )


def _all_seed_entries(result: ValidateResult) -> list[SeedValidationEntry]:
    entries: list[SeedValidationEntry] = []
    primary = _primary_seed_entry(result)
    if primary is not None:
        entries.append(primary)
    if result.seeds_report:
        entries.extend(result.seeds_report)
    return entries


def max_absolute_difference(result: ValidateResult) -> float | None:
    entries = _all_seed_entries(result)
    if not entries:
        return None
    return max(e.stats.absolute_error for e in entries)


def _base_validation_payload(session: SessionConfig, result: ValidateResult) -> dict:
    verification = result.verification
    return {
        "session": session_to_dict(session),
        "deterministic_status": result.deterministic_status,
        "solver": {
            "converged": result.solver.converged,
            "iterations": result.solver.iterations,
            "final_delta": result.solver.final_delta,
            "starting_target_probability": result.solver.values[
                session.starting_bankroll
            ],
        },
        "verification": {
            "policy_evaluation_passed": verification.policy_evaluation_passed,
            "bellman_passed": verification.bellman_passed,
            "max_value_difference": verification.max_value_difference,
            "max_optimality_gap": verification.max_optimality_gap,
            "vi_bellman_max_gap": verification.vi_bellman_max_gap,
            "linear_value_bellman_passed": verification.linear_value_bellman_passed,
            "linear_value_bellman_max_gap": verification.linear_value_bellman_max_gap,
            "legal_actions_passed": verification.legal_actions_passed,
        },
    }


def write_validation_json(
    path: str | Path,
    session: SessionConfig,
    result: ValidateResult,
) -> None:
    payload = _base_validation_payload(session, result)

    if result.batch is not None and result.stats is not None:
        payload["monte_carlo"] = {
            "seed": result.seed,
            "max_rounds": result.max_rounds,
            "batch": _batch_to_dict(result.batch),
            "stats": _stats_to_dict(result.stats),
        }

    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_multiseed_validation_json(
    path: str | Path,
    session: SessionConfig,
    result: ValidateResult,
) -> None:
    payload = _base_validation_payload(session, result)
    entries = _all_seed_entries(result)
    payload["seeds"] = [_seed_entry_to_dict(e) for e in entries]
    max_abs = max_absolute_difference(result)
    if max_abs is not None:
        payload["multiseed_summary"] = {
            "seed_count": len(entries),
            "max_absolute_difference": max_abs,
        }

    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
