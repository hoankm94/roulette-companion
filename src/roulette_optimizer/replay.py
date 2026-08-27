from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Callable, Literal

from roulette_optimizer.config import GameConfig, SessionConfig, validate_session
from roulette_optimizer.historical import (
    HistoricalExtreme,
    HistoricalRoll,
    HistoricalRollAnalysis,
    HistoricalTiming,
    TIMING_STATUS_ESTIMATED,
    analyze_rolls,
    annotate_extreme_timing,
    annotate_extremes_timing,
    estimate_round_timestamp,
    format_estimated_timestamp,
)
from roulette_optimizer.play import loaded_policy_from_result
from roulette_optimizer.policy import (
    LoadedPolicy,
    consecutive_loss_durability,
    recommend_from_policy,
)
from roulette_optimizer.policy_verifier import verify_policy
from roulette_optimizer.solver import SolverResult
from roulette_optimizer.utils import ConfigError, PolicyError

ColorSide = Literal["orange", "black"]
ColorSideSpec = Literal["orange", "black", "alternate_black", "alternate_orange"]
StartMode = Literal["first", "random", "all"]
TerminalStatus = Literal["TARGET", "FLOOR", "NO_ACTION", "EXHAUSTED"]

PRIMARY_WEBSITE_EXTREME_LABELS = frozenset(
    {
        "longest DICE drought",
        "longest ORANGE streak",
        "longest BLACK streak",
        "highest-DICE 50-roll window",
    }
)

PRIMARY_POLICY_EXTREME_LABELS = (
    "worst_starting_round",
    "best_starting_round",
    "fastest_FLOOR",
    "fastest_TARGET",
    "largest_bankroll_drawdown",
    "longest_losing_bet_streak",
    "longest_resolved_session",
)

# Kept in policy_extremes() for CSV/API compatibility; not primary product metrics.
LEGACY_POLICY_EXTREME_LABELS = (
    "shortest_resolved_session",
    "lowest_end_bankroll_EXHAUSTED",
    "highest_end_bankroll_EXHAUSTED",
)

SESSION_CSV_FIELDS = (
    "scenario",
    "color_side",
    "start_mode",
    "start_round",
    "last_round",
    "rolls_consumed",
    "start_bankroll",
    "end_bankroll",
    "target",
    "floor",
    "terminal_status",
    "COLOR_bets",
    "DICE_bets",
    "COLOR_wins",
    "COLOR_losses",
    "DICE_wins",
    "DICE_losses",
    "minimum_bankroll",
    "maximum_bankroll",
    "maximum_drawdown",
    "longest_losing_bet_streak",
    "starting_loss_durability",
    "minimum_loss_durability",
    "ending_loss_durability",
    "estimated_start_time",
    "estimated_last_time",
    "timezone",
    "timing_status",
)

SUMMARY_CSV_FIELDS = (
    "scenario",
    "color_side",
    "start_mode",
    "start_bankroll",
    "target",
    "floor",
    "start_count",
    "target_count",
    "floor_count",
    "no_action_count",
    "exhausted_count",
    "resolved_count",
    "target_rate_all",
    "target_rate_resolved",
    "mean_rounds_resolved",
    "median_rounds_resolved",
    "min_rounds_target",
    "max_rounds_target",
    "min_rounds_floor",
    "max_rounds_floor",
    "min_end_bankroll",
    "max_end_bankroll",
    "largest_drawdown",
    "longest_losing_bet_streak",
    "theoretical_V_start",
    "solver",
    "seed_date",
    "timezone",
    "average_cycle_seconds",
    "timing_status",
)

TRACE_CSV_FIELDS = (
    "scenario",
    "color_side",
    "session_start_round",
    "step",
    "round",
    "roll",
    "roulette_outcome",
    "bankroll_before",
    "bet_type",
    "stake",
    "bet_won",
    "bankroll_after",
    "target",
    "floor",
    "terminal_status",
)

EXTREME_REPLAY_CSV_FIELDS = (
    "scenario",
    "color_side",
    "extreme_kind",
    "extreme_label",
    "extreme_start_round",
    "extreme_end_round",
    "start_round",
    "last_round",
    "rolls_consumed",
    "end_bankroll",
    "terminal_status",
    "minimum_bankroll",
    "maximum_drawdown",
    "longest_losing_bet_streak",
    "estimated_start_time",
    "estimated_end_time",
    "estimated_duration_seconds",
    "timezone",
    "timing_status",
)


@dataclass(frozen=True)
class ReplayScenario:
    name: str
    bankroll: int
    target: int
    floor: int


@dataclass(frozen=True)
class TraceStep:
    scenario: str
    color_side: str
    session_start_round: int
    step: int
    round: int
    roll: int
    roulette_outcome: str
    bankroll_before: int
    bet_type: str
    stake: int
    bet_won: bool
    bankroll_after: int
    target: int
    floor: int
    terminal_status: str


@dataclass
class ReplaySessionResult:
    scenario: str
    color_side: str
    start_mode: str
    start_round: int
    last_round: int | None
    rolls_consumed: int
    start_bankroll: int
    end_bankroll: int
    target: int
    floor: int
    terminal_status: TerminalStatus
    COLOR_bets: int = 0
    DICE_bets: int = 0
    COLOR_wins: int = 0
    COLOR_losses: int = 0
    DICE_wins: int = 0
    DICE_losses: int = 0
    minimum_bankroll: int = 0
    maximum_bankroll: int = 0
    maximum_drawdown: int = 0
    longest_losing_bet_streak: int = 0
    starting_loss_durability: int = 0
    minimum_loss_durability: int = 0
    ending_loss_durability: int = 0
    trace: list[TraceStep] = field(default_factory=list)
    estimated_start_time: str | None = None
    estimated_last_time: str | None = None
    timezone: str | None = None
    timing_status: str | None = None


@dataclass(frozen=True)
class ReplaySummary:
    scenario: str
    color_side: str
    start_mode: str
    start_bankroll: int
    target: int
    floor: int
    start_count: int
    target_count: int
    floor_count: int
    no_action_count: int
    exhausted_count: int
    resolved_count: int
    target_rate_all: float
    target_rate_resolved: float
    mean_rounds_resolved: float
    median_rounds_resolved: float
    min_rounds_target: int | None
    max_rounds_target: int | None
    min_rounds_floor: int | None
    max_rounds_floor: int | None
    min_end_bankroll: int
    max_end_bankroll: int
    largest_drawdown: int
    longest_losing_bet_streak: int
    theoretical_V_start: float
    solver: str
    seed_date: str | None = None
    timezone: str | None = None
    average_cycle_seconds: float | None = None
    timing_status: str | None = None


@dataclass(frozen=True)
class ExtremeReplayRow:
    scenario: str
    color_side: str
    extreme_kind: str
    extreme_label: str
    extreme_start_round: int
    extreme_end_round: int
    session: ReplaySessionResult
    estimated_start_time: str | None = None
    estimated_end_time: str | None = None
    estimated_duration_seconds: float | None = None
    timezone: str | None = None
    timing_status: str | None = None


@dataclass
class SolvedScenario:
    scenario: ReplayScenario
    loaded: LoadedPolicy
    values: dict[int, float]
    solver: str
    solve_calls: int


def bet_won(
    bet_type: str,
    color_side: ColorSide,
    roll: int,
) -> bool:
    if bet_type == "DICE":
        return roll == 0
    if bet_type != "COLOR":
        raise ConfigError(f"Unknown bet type: {bet_type}")
    if color_side == "orange":
        return 1 <= roll <= 7
    if color_side == "black":
        return 8 <= roll <= 14
    raise ConfigError(f"Unknown color side: {color_side}")


def parse_color_sides(
    raw: str,
    *,
    alternate_first: str = "orange",
) -> list[ColorSideSpec]:
    token = raw.strip().lower()
    if token == "orange":
        return ["orange"]
    if token == "black":
        return ["black"]
    if token == "both":
        return ["orange", "black"]
    if token in ("alternate", "alternate_black", "alternate_orange"):
        if token == "alternate":
            first = alternate_first.strip().lower()
        elif token == "alternate_black":
            first = "black"
        else:
            first = "orange"
        if first not in ("black", "orange"):
            raise ConfigError(
                f"Invalid alternate_first {alternate_first!r}; use black or orange"
            )
        return [f"alternate_{first}"]  # type: ignore[list-item]
    raise ConfigError(
        f"Invalid --color-side {raw!r}; use orange, black, both, or alternate"
    )


def color_side_label(spec: ColorSideSpec) -> str:
    return spec.upper()


def is_alternate_color(spec: ColorSideSpec) -> bool:
    return spec.startswith("alternate_")


def alternate_first_side(spec: ColorSideSpec) -> ColorSide:
    if spec == "alternate_black":
        return "black"
    if spec == "alternate_orange":
        return "orange"
    raise ConfigError(f"Not an alternate color spec: {spec}")


def next_alternate_side(side: ColorSide) -> ColorSide:
    return "orange" if side == "black" else "black"


def parse_start_mode(raw: str) -> StartMode:
    token = raw.strip().lower()
    if token in ("first", "random", "all"):
        return token  # type: ignore[return-value]
    raise ConfigError(
        f"Invalid --start-mode {raw!r}; use first, random, or all"
    )


def parse_scenario_file(path: str | Path) -> list[ReplayScenario]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Invalid scenario file: {p}: {exc}") from exc
    if not isinstance(data, dict) or "scenarios" not in data:
        raise ConfigError("Scenario file must contain a 'scenarios' array")
    raw_list = data["scenarios"]
    if not isinstance(raw_list, list) or not raw_list:
        raise ConfigError("Scenario file 'scenarios' must be a non-empty array")
    scenarios: list[ReplayScenario] = []
    names: set[str] = set()
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ConfigError(f"Scenario {i} must be an object")
        try:
            name = str(item["name"])
            bankroll = int(item["bankroll"])
            target = int(item["target"])
            floor = int(item["floor"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"Scenario {i} is invalid: {exc}") from exc
        if name in names:
            raise ConfigError(f"Duplicate scenario name: {name}")
        names.add(name)
        session = SessionConfig(
            starting_bankroll=bankroll,
            target_bankroll=target,
            floor_bankroll=floor,
        )
        validate_session(session)
        scenarios.append(
            ReplayScenario(name=name, bankroll=bankroll, target=target, floor=floor)
        )
    return scenarios


def resolve_scenarios(
    *,
    bankroll: int | None,
    target: int | None,
    floor: int | None,
    scenario_file: str | Path | None,
) -> list[ReplayScenario]:
    if scenario_file is not None:
        if bankroll is not None or target is not None or floor is not None:
            raise ConfigError(
                "Do not combine --scenario-file with --bankroll/--target/--floor"
            )
        return parse_scenario_file(scenario_file)
    if bankroll is None or target is None or floor is None:
        raise ConfigError(
            "Provide --bankroll, --target, and --floor, or use --scenario-file"
        )
    session = SessionConfig(
        starting_bankroll=bankroll,
        target_bankroll=target,
        floor_bankroll=floor,
    )
    validate_session(session)
    return [
        ReplayScenario(
            name=f"{bankroll}_{target}_{floor}",
            bankroll=bankroll,
            target=target,
            floor=floor,
        )
    ]


def select_start_rounds(
    rolls: list[HistoricalRoll],
    *,
    start_mode: StartMode,
    samples: int | None = None,
    sample_seed: int | None = None,
) -> list[int]:
    if not rolls:
        raise ConfigError("Empty historical roll sequence")
    all_starts = [r.round_number for r in rolls]
    if start_mode == "first":
        return [all_starts[0]]
    if start_mode == "all":
        return list(all_starts)
    if start_mode == "random":
        if samples is None:
            raise ConfigError("--samples is required for --start-mode random")
        if samples <= 0:
            raise ConfigError("--samples must be > 0")
        if samples > len(all_starts):
            raise ConfigError(
                f"--samples {samples} exceeds available starts {len(all_starts)}"
            )
        if sample_seed is None:
            raise ConfigError("--sample-seed is required for --start-mode random")
        rng = random.Random(sample_seed)
        return sorted(rng.sample(all_starts, samples))
    raise ConfigError(f"Unknown start mode: {start_mode}")


def solve_scenario(
    scenario: ReplayScenario,
    *,
    solver: str = "numpy",
    solve_fn: Callable[..., SolverResult] | None = None,
) -> SolvedScenario:
    session = SessionConfig(
        starting_bankroll=scenario.bankroll,
        target_bankroll=scenario.target,
        floor_bankroll=scenario.floor,
    )
    validate_session(session)
    game = GameConfig()
    if solve_fn is not None:
        from roulette_optimizer.policy_cache import resolve_production_solver

        solver_used = resolve_production_solver(solver)
        result = solve_fn(session, game, solver=solver_used)
        verify_policy(result, session, game)
        loaded = loaded_policy_from_result(session, game, result)
        return SolvedScenario(
            scenario=scenario,
            loaded=loaded,
            values=result.values,
            solver=solver_used,
            solve_calls=1,
        )

    from roulette_optimizer.policy_cache import solve_and_cache

    hit = solve_and_cache(session, game, solver=solver)
    return SolvedScenario(
        scenario=scenario,
        loaded=hit.loaded,
        values=hit.result.values,
        solver=hit.solver_used,
        solve_calls=hit.solve_calls,
    )


def replay_session(
    *,
    loaded: LoadedPolicy,
    rolls: list[HistoricalRoll],
    start_round: int,
    color_side: ColorSideSpec,
    scenario_name: str,
    start_mode: str,
    collect_trace: bool = False,
) -> ReplaySessionResult:
    by_round = {r.round_number: r for r in rolls}
    if start_round not in by_round:
        raise ConfigError(f"start_round {start_round} not in historical sequence")
    ordered = [r for r in rolls if r.round_number >= start_round]
    session = loaded.session
    bankroll = session.starting_bankroll
    target = session.target_bankroll
    floor = session.floor_bankroll
    dur_table = loaded.loss_durability_table()
    start_dur = consecutive_loss_durability(loaded, bankroll, table=dur_table)

    result = ReplaySessionResult(
        scenario=scenario_name,
        color_side=color_side_label(color_side),
        start_mode=start_mode,
        start_round=start_round,
        last_round=None,
        rolls_consumed=0,
        start_bankroll=bankroll,
        end_bankroll=bankroll,
        target=target,
        floor=floor,
        terminal_status="EXHAUSTED",
        minimum_bankroll=bankroll,
        maximum_bankroll=bankroll,
        starting_loss_durability=start_dur,
        minimum_loss_durability=start_dur,
        ending_loss_durability=start_dur,
    )
    peak = bankroll
    losing_streak = 0
    next_color: ColorSide | None = (
        alternate_first_side(color_side) if is_alternate_color(color_side) else None
    )
    fixed_side: ColorSide | None = None if is_alternate_color(color_side) else color_side  # type: ignore[assignment]

    if bankroll >= target:
        result.terminal_status = "TARGET"
        return result
    if bankroll <= floor:
        result.terminal_status = "FLOOR"
        return result

    for step_i, hist in enumerate(ordered, start=1):
        rec = recommend_from_policy(loaded, bankroll)
        if rec.status == "TARGET":
            result.terminal_status = "TARGET"
            result.end_bankroll = bankroll
            result.ending_loss_durability = consecutive_loss_durability(
                loaded, bankroll, table=dur_table
            )
            return result
        if rec.status == "FLOOR":
            result.terminal_status = "FLOOR"
            result.end_bankroll = bankroll
            result.ending_loss_durability = consecutive_loss_durability(
                loaded, bankroll, table=dur_table
            )
            return result
        if rec.status == "NO_ACTION":
            result.terminal_status = "NO_ACTION"
            result.end_bankroll = bankroll
            result.ending_loss_durability = consecutive_loss_durability(
                loaded, bankroll, table=dur_table
            )
            return result
        assert rec.bet_type is not None and rec.stake is not None
        assert rec.win_bankroll is not None and rec.lose_bankroll is not None

        # Choose COLOR side before inspecting the roll outcome path beyond the roll value
        # already present on hist (no hindsight side selection from future rolls).
        if rec.bet_type == "COLOR":
            if next_color is not None:
                side_for_bet = next_color
                next_color = next_alternate_side(next_color)
            else:
                assert fixed_side is not None
                side_for_bet = fixed_side
        else:
            # DICE: color side is unused for win/loss; do not advance alternation.
            if fixed_side is not None:
                side_for_bet = fixed_side
            else:
                assert next_color is not None
                side_for_bet = next_color

        won = bet_won(rec.bet_type, side_for_bet, hist.roll)
        before = bankroll
        bankroll = rec.win_bankroll if won else rec.lose_bankroll
        result.rolls_consumed += 1
        result.last_round = hist.round_number
        result.end_bankroll = bankroll
        result.minimum_bankroll = min(result.minimum_bankroll, bankroll)
        result.maximum_bankroll = max(result.maximum_bankroll, bankroll)
        peak = max(peak, bankroll)
        result.maximum_drawdown = max(result.maximum_drawdown, peak - bankroll)
        dur_now = consecutive_loss_durability(loaded, bankroll, table=dur_table)
        result.minimum_loss_durability = min(result.minimum_loss_durability, dur_now)
        result.ending_loss_durability = dur_now

        if rec.bet_type == "COLOR":
            result.COLOR_bets += 1
            if won:
                result.COLOR_wins += 1
                losing_streak = 0
            else:
                result.COLOR_losses += 1
                losing_streak += 1
        else:
            result.DICE_bets += 1
            if won:
                result.DICE_wins += 1
                losing_streak = 0
            else:
                result.DICE_losses += 1
                losing_streak += 1
        result.longest_losing_bet_streak = max(
            result.longest_losing_bet_streak, losing_streak
        )

        terminal = ""
        if bankroll >= target:
            terminal = "TARGET"
        elif bankroll <= floor:
            terminal = "FLOOR"

        if collect_trace:
            result.trace.append(
                TraceStep(
                    scenario=scenario_name,
                    color_side=side_for_bet.upper(),
                    session_start_round=start_round,
                    step=step_i,
                    round=hist.round_number,
                    roll=hist.roll,
                    roulette_outcome=hist.outcome,
                    bankroll_before=before,
                    bet_type=rec.bet_type,
                    stake=rec.stake,
                    bet_won=won,
                    bankroll_after=bankroll,
                    target=target,
                    floor=floor,
                    terminal_status=terminal,
                )
            )

        if terminal:
            result.terminal_status = terminal  # type: ignore[assignment]
            return result

    result.terminal_status = "EXHAUSTED"
    return result


def apply_session_timing(
    session: ReplaySessionResult,
    timing: HistoricalTiming | None,
) -> ReplaySessionResult:
    if timing is None:
        return session
    start_dt = estimate_round_timestamp(session.start_round, timing)
    last_round = session.last_round if session.last_round is not None else session.start_round
    last_dt = estimate_round_timestamp(last_round, timing)
    session.estimated_start_time = format_estimated_timestamp(start_dt)
    session.estimated_last_time = format_estimated_timestamp(last_dt)
    session.timezone = timing.timezone_name
    session.timing_status = TIMING_STATUS_ESTIMATED
    return session


def extreme_row_with_timing(
    *,
    scenario: str,
    color_side: str,
    extreme_kind: str,
    extreme_label: str,
    extreme_start_round: int,
    extreme_end_round: int,
    session: ReplaySessionResult,
    timing: HistoricalTiming | None,
) -> ExtremeReplayRow:
    if timing is None:
        return ExtremeReplayRow(
            scenario=scenario,
            color_side=color_side,
            extreme_kind=extreme_kind,
            extreme_label=extreme_label,
            extreme_start_round=extreme_start_round,
            extreme_end_round=extreme_end_round,
            session=session,
        )
    annotated = annotate_extreme_timing(
        HistoricalExtreme(
            kind="timing",
            label=extreme_label,
            start_round=extreme_start_round,
            end_round=extreme_end_round,
            length_or_count=extreme_end_round - extreme_start_round + 1,
        ),
        timing,
    )
    return ExtremeReplayRow(
        scenario=scenario,
        color_side=color_side,
        extreme_kind=extreme_kind,
        extreme_label=extreme_label,
        extreme_start_round=extreme_start_round,
        extreme_end_round=extreme_end_round,
        session=session,
        estimated_start_time=annotated.estimated_start_time,
        estimated_end_time=annotated.estimated_end_time,
        estimated_duration_seconds=annotated.estimated_duration_seconds,
        timezone=annotated.timezone,
        timing_status=annotated.timing_status,
    )


def summarize_sessions(
    sessions: list[ReplaySessionResult],
    *,
    theoretical_V_start: float,
    solver: str,
    start_bankroll: int,
    target: int,
    floor: int,
    timing: HistoricalTiming | None = None,
) -> ReplaySummary:
    if not sessions:
        raise ConfigError("No sessions to summarize")
    scenario = sessions[0].scenario
    color_side = sessions[0].color_side
    start_mode = sessions[0].start_mode
    target_count = sum(1 for s in sessions if s.terminal_status == "TARGET")
    floor_count = sum(1 for s in sessions if s.terminal_status == "FLOOR")
    no_action_count = sum(1 for s in sessions if s.terminal_status == "NO_ACTION")
    exhausted_count = sum(1 for s in sessions if s.terminal_status == "EXHAUSTED")
    resolved = [s for s in sessions if s.terminal_status != "EXHAUSTED"]
    resolved_count = len(resolved)
    n = len(sessions)
    target_rounds = [s.rolls_consumed for s in sessions if s.terminal_status == "TARGET"]
    floor_rounds = [s.rolls_consumed for s in sessions if s.terminal_status == "FLOOR"]
    resolved_rounds = [s.rolls_consumed for s in resolved]
    return ReplaySummary(
        scenario=scenario,
        color_side=color_side,
        start_mode=start_mode,
        start_bankroll=start_bankroll,
        target=target,
        floor=floor,
        start_count=n,
        target_count=target_count,
        floor_count=floor_count,
        no_action_count=no_action_count,
        exhausted_count=exhausted_count,
        resolved_count=resolved_count,
        target_rate_all=target_count / n if n else 0.0,
        target_rate_resolved=target_count / resolved_count if resolved_count else 0.0,
        mean_rounds_resolved=mean(resolved_rounds) if resolved_rounds else 0.0,
        median_rounds_resolved=median(resolved_rounds) if resolved_rounds else 0.0,
        min_rounds_target=min(target_rounds) if target_rounds else None,
        max_rounds_target=max(target_rounds) if target_rounds else None,
        min_rounds_floor=min(floor_rounds) if floor_rounds else None,
        max_rounds_floor=max(floor_rounds) if floor_rounds else None,
        min_end_bankroll=min(s.end_bankroll for s in sessions),
        max_end_bankroll=max(s.end_bankroll for s in sessions),
        largest_drawdown=max(s.maximum_drawdown for s in sessions),
        longest_losing_bet_streak=max(s.longest_losing_bet_streak for s in sessions),
        theoretical_V_start=theoretical_V_start,
        solver=solver,
        seed_date=timing.seed_date.isoformat() if timing is not None else None,
        timezone=timing.timezone_name if timing is not None else None,
        average_cycle_seconds=(
            timing.average_cycle_seconds if timing is not None else None
        ),
        timing_status=TIMING_STATUS_ESTIMATED if timing is not None else None,
    )


def _worst_key(s: ReplaySessionResult) -> tuple:
    # FLOOR preferred as worst; then lower min bankroll; larger drawdown;
    # longer losing streak; fewer rounds to FLOOR; earlier start
    is_floor = 0 if s.terminal_status == "FLOOR" else 1
    rounds_to_floor = s.rolls_consumed if s.terminal_status == "FLOOR" else 10**18
    return (
        is_floor,
        s.minimum_bankroll,
        -s.maximum_drawdown,
        -s.longest_losing_bet_streak,
        rounds_to_floor,
        s.start_round,
    )


def _best_key(s: ReplaySessionResult) -> tuple:
    # TARGET preferred; fewer rounds to TARGET; higher min bankroll;
    # smaller drawdown; earlier start
    is_target = 0 if s.terminal_status == "TARGET" else 1
    rounds_to_target = s.rolls_consumed if s.terminal_status == "TARGET" else 10**18
    return (
        is_target,
        rounds_to_target,
        -s.minimum_bankroll,
        s.maximum_drawdown,
        s.start_round,
    )


def pick_worst_session(sessions: list[ReplaySessionResult]) -> ReplaySessionResult:
    return min(sessions, key=_worst_key)


def pick_best_session(sessions: list[ReplaySessionResult]) -> ReplaySessionResult:
    return min(sessions, key=_best_key)


def policy_extremes(sessions: list[ReplaySessionResult]) -> dict[str, ReplaySessionResult | None]:
    if not sessions:
        return {}
    resolved = [s for s in sessions if s.terminal_status != "EXHAUSTED"]
    floors = [s for s in sessions if s.terminal_status == "FLOOR"]
    targets = [s for s in sessions if s.terminal_status == "TARGET"]
    exhausted = [s for s in sessions if s.terminal_status == "EXHAUSTED"]

    def fastest(group: list[ReplaySessionResult]) -> ReplaySessionResult | None:
        if not group:
            return None
        return min(group, key=lambda s: (s.rolls_consumed, s.start_round))

    def longest_resolved() -> ReplaySessionResult | None:
        if not resolved:
            return None
        return max(resolved, key=lambda s: (s.rolls_consumed, -s.start_round))

    def shortest_resolved() -> ReplaySessionResult | None:
        if not resolved:
            return None
        return min(resolved, key=lambda s: (s.rolls_consumed, s.start_round))

    return {
        "worst_starting_round": pick_worst_session(sessions),
        "best_starting_round": pick_best_session(sessions),
        "fastest_FLOOR": fastest(floors),
        "fastest_TARGET": fastest(targets),
        "largest_bankroll_drawdown": max(
            sessions, key=lambda s: (s.maximum_drawdown, -s.start_round)
        ),
        "longest_losing_bet_streak": max(
            sessions, key=lambda s: (s.longest_losing_bet_streak, -s.start_round)
        ),
        "longest_resolved_session": longest_resolved(),
        "shortest_resolved_session": shortest_resolved(),
        "lowest_end_bankroll_EXHAUSTED": (
            min(exhausted, key=lambda s: (s.end_bankroll, s.start_round))
            if exhausted
            else None
        ),
        "highest_end_bankroll_EXHAUSTED": (
            max(exhausted, key=lambda s: (s.end_bankroll, -s.start_round))
            if exhausted
            else None
        ),
    }


@dataclass
class ReplayRunResult:
    rolls: list[HistoricalRoll]
    analysis: HistoricalRollAnalysis | None
    sessions: list[ReplaySessionResult]
    summaries: list[ReplaySummary]
    extreme_rows: list[ExtremeReplayRow]
    solve_calls: int
    sha_generations: int


def run_historical_replays(
    *,
    rolls: list[HistoricalRoll],
    scenarios: list[ReplayScenario],
    color_sides: list[ColorSideSpec],
    start_mode: StartMode,
    samples: int | None = None,
    sample_seed: int | None = None,
    solver: str = "numpy",
    collect_traces: bool = False,
    solve_fn: Callable[..., SolverResult] | None = None,
    solved: dict[str, SolvedScenario] | None = None,
    timing: HistoricalTiming | None = None,
) -> ReplayRunResult:
    starts = select_start_rounds(
        rolls, start_mode=start_mode, samples=samples, sample_seed=sample_seed
    )
    collect = collect_traces or start_mode == "first"
    sessions: list[ReplaySessionResult] = []
    summaries: list[ReplaySummary] = []
    solve_calls = 0
    cache = dict(solved or {})

    for scenario in scenarios:
        if scenario.name not in cache:
            cache[scenario.name] = solve_scenario(
                scenario, solver=solver, solve_fn=solve_fn
            )
            solve_calls += cache[scenario.name].solve_calls
        solved_sc = cache[scenario.name]
        v_start = solved_sc.values[scenario.bankroll]
        for side in color_sides:
            side_sessions: list[ReplaySessionResult] = []
            for start in starts:
                sess = replay_session(
                    loaded=solved_sc.loaded,
                    rolls=rolls,
                    start_round=start,
                    color_side=side,
                    scenario_name=scenario.name,
                    start_mode=start_mode,
                    collect_trace=collect,
                )
                apply_session_timing(sess, timing)
                side_sessions.append(sess)
            sessions.extend(side_sessions)
            summaries.append(
                summarize_sessions(
                    side_sessions,
                    theoretical_V_start=v_start,
                    solver=solved_sc.solver,
                    start_bankroll=scenario.bankroll,
                    target=scenario.target,
                    floor=scenario.floor,
                    timing=timing,
                )
            )

    return ReplayRunResult(
        rolls=rolls,
        analysis=None,
        sessions=sessions,
        summaries=summaries,
        extreme_rows=[],
        solve_calls=solve_calls,
        sha_generations=len(rolls),
    )


def run_extreme_replays(
    *,
    rolls: list[HistoricalRoll],
    scenarios: list[ReplayScenario],
    color_sides: list[ColorSideSpec],
    solver: str = "numpy",
    solve_fn: Callable[..., SolverResult] | None = None,
    solved: dict[str, SolvedScenario] | None = None,
    timing: HistoricalTiming | None = None,
) -> ReplayRunResult:
    analysis = analyze_rolls(rolls)
    website = [
        e
        for e in annotate_extremes_timing(analysis.website_extremes, timing)
        if e.label in PRIMARY_WEBSITE_EXTREME_LABELS
    ]
    solved_cache: dict[str, SolvedScenario] = dict(solved or {})
    solve_calls = 0
    for scenario in scenarios:
        if scenario.name not in solved_cache:
            solved_cache[scenario.name] = solve_scenario(
                scenario, solver=solver, solve_fn=solve_fn
            )
            solve_calls += solved_cache[scenario.name].solve_calls

    all_run = run_historical_replays(
        rolls=rolls,
        scenarios=scenarios,
        color_sides=color_sides,
        start_mode="all",
        solver=solver,
        collect_traces=False,
        solve_fn=solve_fn,
        solved=solved_cache,
        timing=timing,
    )
    solve_calls += all_run.solve_calls
    extreme_rows: list[ExtremeReplayRow] = []
    sessions_out: list[ReplaySessionResult] = []

    for scenario in scenarios:
        solved_sc = solved_cache[scenario.name]
        for side in color_sides:
            side_label = color_side_label(side)
            side_all = [
                s
                for s in all_run.sessions
                if s.scenario == scenario.name and s.color_side == side_label
            ]
            for ext in website:
                sess = replay_session(
                    loaded=solved_sc.loaded,
                    rolls=rolls,
                    start_round=ext.start_round,
                    color_side=side,
                    scenario_name=scenario.name,
                    start_mode="extreme",
                    collect_trace=True,
                )
                apply_session_timing(sess, timing)
                sessions_out.append(sess)
                extreme_rows.append(
                    extreme_row_with_timing(
                        scenario=scenario.name,
                        color_side=side_label,
                        extreme_kind=f"website:{ext.kind}",
                        extreme_label=ext.label,
                        extreme_start_round=ext.start_round,
                        extreme_end_round=ext.end_round,
                        session=sess,
                        timing=timing,
                    )
                )
            pe = policy_extremes(side_all)
            for label in PRIMARY_POLICY_EXTREME_LABELS:
                sess = pe.get(label)
                if sess is None:
                    continue
                traced = replay_session(
                    loaded=solved_sc.loaded,
                    rolls=rolls,
                    start_round=sess.start_round,
                    color_side=side,
                    scenario_name=scenario.name,
                    start_mode="extreme",
                    collect_trace=True,
                )
                apply_session_timing(traced, timing)
                sessions_out.append(traced)
                extreme_end = sess.last_round or sess.start_round
                extreme_rows.append(
                    extreme_row_with_timing(
                        scenario=scenario.name,
                        color_side=side_label,
                        extreme_kind="policy",
                        extreme_label=label,
                        extreme_start_round=sess.start_round,
                        extreme_end_round=extreme_end,
                        session=traced,
                        timing=timing,
                    )
                )

    return ReplayRunResult(
        rolls=rolls,
        analysis=analysis,
        sessions=sessions_out,
        summaries=all_run.summaries,
        extreme_rows=extreme_rows,
        solve_calls=solve_calls,
        sha_generations=len(rolls),
    )


def session_as_dict(s: ReplaySessionResult) -> dict[str, object]:
    return {
        "scenario": s.scenario,
        "color_side": s.color_side,
        "start_mode": s.start_mode,
        "start_round": s.start_round,
        "last_round": s.last_round if s.last_round is not None else "",
        "rolls_consumed": s.rolls_consumed,
        "start_bankroll": s.start_bankroll,
        "end_bankroll": s.end_bankroll,
        "target": s.target,
        "floor": s.floor,
        "terminal_status": s.terminal_status,
        "COLOR_bets": s.COLOR_bets,
        "DICE_bets": s.DICE_bets,
        "COLOR_wins": s.COLOR_wins,
        "COLOR_losses": s.COLOR_losses,
        "DICE_wins": s.DICE_wins,
        "DICE_losses": s.DICE_losses,
        "minimum_bankroll": s.minimum_bankroll,
        "maximum_bankroll": s.maximum_bankroll,
        "maximum_drawdown": s.maximum_drawdown,
        "longest_losing_bet_streak": s.longest_losing_bet_streak,
        "starting_loss_durability": s.starting_loss_durability,
        "minimum_loss_durability": s.minimum_loss_durability,
        "ending_loss_durability": s.ending_loss_durability,
        "estimated_start_time": s.estimated_start_time or "",
        "estimated_last_time": s.estimated_last_time or "",
        "timezone": s.timezone or "",
        "timing_status": s.timing_status or "",
    }


def summary_as_dict(s: ReplaySummary) -> dict[str, object]:
    return {
        "scenario": s.scenario,
        "color_side": s.color_side,
        "start_mode": s.start_mode,
        "start_bankroll": s.start_bankroll,
        "target": s.target,
        "floor": s.floor,
        "start_count": s.start_count,
        "target_count": s.target_count,
        "floor_count": s.floor_count,
        "no_action_count": s.no_action_count,
        "exhausted_count": s.exhausted_count,
        "resolved_count": s.resolved_count,
        "target_rate_all": s.target_rate_all,
        "target_rate_resolved": s.target_rate_resolved,
        "mean_rounds_resolved": s.mean_rounds_resolved,
        "median_rounds_resolved": s.median_rounds_resolved,
        "min_rounds_target": s.min_rounds_target if s.min_rounds_target is not None else "",
        "max_rounds_target": s.max_rounds_target if s.max_rounds_target is not None else "",
        "min_rounds_floor": s.min_rounds_floor if s.min_rounds_floor is not None else "",
        "max_rounds_floor": s.max_rounds_floor if s.max_rounds_floor is not None else "",
        "min_end_bankroll": s.min_end_bankroll,
        "max_end_bankroll": s.max_end_bankroll,
        "largest_drawdown": s.largest_drawdown,
        "longest_losing_bet_streak": s.longest_losing_bet_streak,
        "theoretical_V_start": s.theoretical_V_start,
        "solver": s.solver,
        "seed_date": s.seed_date or "",
        "timezone": s.timezone or "",
        "average_cycle_seconds": (
            s.average_cycle_seconds if s.average_cycle_seconds is not None else ""
        ),
        "timing_status": s.timing_status or "",
    }


def trace_as_dicts(steps: list[TraceStep]) -> list[dict[str, object]]:
    return [
        {
            "scenario": t.scenario,
            "color_side": t.color_side,
            "session_start_round": t.session_start_round,
            "step": t.step,
            "round": t.round,
            "roll": t.roll,
            "roulette_outcome": t.roulette_outcome,
            "bankroll_before": t.bankroll_before,
            "bet_type": t.bet_type,
            "stake": t.stake,
            "bet_won": t.bet_won,
            "bankroll_after": t.bankroll_after,
            "target": t.target,
            "floor": t.floor,
            "terminal_status": t.terminal_status,
        }
        for t in steps
    ]


def extreme_row_as_dict(row: ExtremeReplayRow) -> dict[str, object]:
    s = row.session
    return {
        "scenario": row.scenario,
        "color_side": row.color_side,
        "extreme_kind": row.extreme_kind,
        "extreme_label": row.extreme_label,
        "extreme_start_round": row.extreme_start_round,
        "extreme_end_round": row.extreme_end_round,
        "start_round": s.start_round,
        "last_round": s.last_round if s.last_round is not None else "",
        "rolls_consumed": s.rolls_consumed,
        "end_bankroll": s.end_bankroll,
        "terminal_status": s.terminal_status,
        "minimum_bankroll": s.minimum_bankroll,
        "maximum_drawdown": s.maximum_drawdown,
        "longest_losing_bet_streak": s.longest_losing_bet_streak,
        "estimated_start_time": row.estimated_start_time or "",
        "estimated_end_time": row.estimated_end_time or "",
        "estimated_duration_seconds": (
            row.estimated_duration_seconds
            if row.estimated_duration_seconds is not None
            else ""
        ),
        "timezone": row.timezone or "",
        "timing_status": row.timing_status or "",
    }


def default_sessions_csv_path(round_start: int, round_end: int) -> str:
    return f"outputs/replay_{round_start}_{round_end}_sessions.csv"


def default_summary_csv_path(round_start: int, round_end: int) -> str:
    return f"outputs/replay_{round_start}_{round_end}_summary.csv"


def default_extreme_replays_csv_path(round_start: int, round_end: int) -> str:
    return f"outputs/replay_{round_start}_{round_end}_extreme_replays.csv"


def default_trace_csv_path(scenario: str, start_round: int, color_side: str) -> str:
    safe = scenario.replace("/", "_").replace(" ", "_")
    return f"outputs/replay_{safe}_{start_round}_{color_side}_trace.csv"
