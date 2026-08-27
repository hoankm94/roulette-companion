"""Serialize domain objects to dollar-facing API payloads."""

from __future__ import annotations

import math
from typing import Any

from roulette_optimizer.config import SessionConfig
from roulette_optimizer.historical import (
    TIMING_STATUS_ESTIMATED,
    DroughtInfo,
    HistoricalRollAnalysis,
    HistoricalTiming,
    StreakInfo,
    WindowExtreme,
    timing_csv_fields_for_range,
)
from roulette_optimizer.play import LiveSession, PlayOutcome
from roulette_optimizer.policy import LoadedPolicy, Recommendation, count_policy_actions
from roulette_optimizer.policy_verifier import VerificationResult
from roulette_optimizer.replay import (
    ExtremeReplayRow,
    ReplaySessionResult,
    ReplaySummary,
    session_as_dict,
    summary_as_dict,
    trace_as_dicts,
)
from roulette_optimizer.solver import SolverResult
from roulette_optimizer.state_space import build_state_space

from api.money import cents_to_dollars
from api.models import (
    CompanionStateResponse,
    CompanionWagerPayload,
    DiceMapRowPayload,
    DroughtPayload,
    ExtremeRowPayload,
    MoneyAmount,
    PolicyDistribution,
    PolicyRow,
    RecommendationPayload,
    ReplayAnalyzeResponse,
    ReplaySessionPayload,
    ReplaySummaryPayload,
    SavedLiveSessionPayload,
    SolverMeta,
    StreakPayload,
    SweepCellPayload,
    VerificationPayload,
    WindowExtremePayload,
)


def money(cents: int | None) -> MoneyAmount | None:
    if cents is None:
        return None
    return MoneyAmount(cents=cents, dollars=float(cents_to_dollars(cents)))


def money_req(cents: int) -> MoneyAmount:
    return MoneyAmount(cents=cents, dollars=float(cents_to_dollars(cents)))


def session_public(session: SessionConfig) -> dict[str, Any]:
    return {
        "starting_bankroll": money_req(session.starting_bankroll).model_dump(),
        "target_bankroll": money_req(session.target_bankroll).model_dump(),
        "floor_bankroll": money_req(session.floor_bankroll).model_dump(),
        "bankroll_step": session.bankroll_step,
        "allow_color": session.allow_color,
        "allow_dice": session.allow_dice,
    }


def verification_payload(
    verification: VerificationResult,
    *,
    status: str = "VALID",
) -> VerificationPayload:
    return VerificationPayload(
        deterministic_status=status,
        policy_evaluation_passed=verification.policy_evaluation_passed,
        bellman_passed=verification.bellman_passed,
        linear_value_bellman_passed=verification.linear_value_bellman_passed,
        legal_actions_passed=verification.legal_actions_passed,
        max_value_difference=verification.max_value_difference,
        max_optimality_gap=verification.max_optimality_gap,
        vi_bellman_max_gap=verification.vi_bellman_max_gap,
        linear_value_bellman_max_gap=verification.linear_value_bellman_max_gap,
    )


def solver_meta(result: SolverResult, solver: str) -> SolverMeta:
    return SolverMeta(
        converged=result.converged,
        iterations=result.iterations,
        final_delta=result.final_delta,
        solver=solver,
    )


def recommendation_payload(rec: Recommendation) -> RecommendationPayload:
    action = None
    if rec.status == "ACTION" and rec.bet_type is not None:
        action = rec.bet_type
    return RecommendationPayload(
        status=rec.status,
        action=action,
        stake=money(rec.stake),
        target_hit_probability=rec.target_hit_probability,
        win_bankroll=money(rec.win_bankroll),
        lose_bankroll=money(rec.lose_bankroll),
        bankroll=money_req(rec.bankroll),
        consecutive_loss_durability=rec.consecutive_loss_durability,
    )


def policy_rows(result: SolverResult, session: SessionConfig) -> list[PolicyRow]:
    rows: list[PolicyRow] = []
    for b in sorted(result.policy):
        d = result.policy[b]
        if b <= session.floor_bankroll:
            action = "STOP"
            stake = None
        elif b >= session.target_bankroll:
            action = "TARGET"
            stake = None
        elif d.action is None:
            action = "NONE"
            stake = None
        else:
            action = d.action.bet_type
            stake = money(d.action.stake)
        rows.append(
            PolicyRow(
                bankroll=money_req(b),
                action=action,
                stake=stake,
                win_bankroll=money(d.win_bankroll),
                lose_bankroll=money(d.lose_bankroll),
                target_hit_probability=float(d.success_probability),
            )
        )
    return rows


def value_series(result: SolverResult, session: SessionConfig) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in sorted(result.values):
        out.append(
            {
                "bankroll": money_req(b).model_dump(),
                "value": float(result.values[b]),
            }
        )
    return out


def distribution(result: SolverResult, session: SessionConfig) -> PolicyDistribution:
    color_c, dice_c, none_c = count_policy_actions(result, session)
    ss = build_state_space(session)
    return PolicyDistribution(
        color_count=color_c,
        dice_count=dice_c,
        no_action_count=none_c,
        state_count=len(ss.nonterminal),
    )


def play_state(
    *,
    session_id: str,
    outcome: PlayOutcome,
    loaded: LoadedPolicy,
    verification: VerificationResult | None = None,
    awaiting_save: bool = False,
) -> dict[str, Any]:
    session = loaded.session
    rec = outcome.recommendation
    durability = None
    if rec is not None:
        durability = rec.consecutive_loss_durability
    else:
        from roulette_optimizer.policy import consecutive_loss_durability

        try:
            durability = consecutive_loss_durability(loaded, outcome.bankroll)
        except Exception:
            durability = 0
    return {
        "session_id": session_id,
        "status": outcome.status,
        "bankroll": money_req(outcome.bankroll).model_dump(),
        "target": money_req(session.target_bankroll).model_dump(),
        "floor": money_req(session.floor_bankroll).model_dump(),
        "target_hit_probability": (
            None if rec is None else rec.target_hit_probability
        ),
        "consecutive_loss_durability": durability,
        "recommendation": None if rec is None else recommendation_payload(rec).model_dump(),
        "rounds_completed": outcome.rounds_completed,
        "message": outcome.message,
        "verification": (
            None if verification is None else verification_payload(verification).model_dump()
        ),
        "awaiting_save": awaiting_save,
    }


def _companion_wager_payload(
    bet_type: str | None,
    stake: int | None,
    color_side: str | None = None,
) -> CompanionWagerPayload | None:
    if bet_type is None or stake is None:
        return None
    side = color_side if color_side in ("ORANGE", "BLACK") else None
    return CompanionWagerPayload(
        bet_type=bet_type,
        stake=money_req(stake),
        color_side=side,
    )


def _desync_reason(session: LiveSession) -> str | None:
    if session.status != "DESYNCED":
        return None
    for event in reversed(session.events):
        kind = event.get("kind")
        if kind in ("policy_grid_miss", "wager_mismatch", "bankroll_mismatch"):
            return kind
    return None


def _companion_context(session: LiveSession) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "recommended_wager": None,
        "observed_wager": None,
        "expected_bankroll": None,
        "observed_bankroll": None,
        "expected_win_bankroll": None,
        "expected_lose_bankroll": None,
        "last_result": None,
        "last_outcome": None,
        "settlement_classification": None,
        "wager_match_status": None,
        "desync_reason": _desync_reason(session),
    }
    pending = session._pending_round
    if pending is not None:
        ctx["recommended_wager"] = _companion_wager_payload(
            pending.get("recommended_bet_type"),
            pending.get("recommended_stake"),
        )
        ctx["observed_wager"] = _companion_wager_payload(
            pending.get("actual_bet_type"),
            pending.get("actual_stake"),
            pending.get("color_side"),
        )
        if pending.get("outcome") is not None:
            ctx["last_outcome"] = pending["outcome"]
        if pending.get("result_outcome") is not None:
            ctx["last_result"] = pending["result_outcome"]
        if pending.get("wager_match_status") is not None:
            ctx["wager_match_status"] = pending["wager_match_status"]
        if pending.get("observed_post_deduction_bankroll") is not None:
            ctx["observed_bankroll"] = money_req(
                pending["observed_post_deduction_bankroll"]
            )
        win_b = pending.get("expected_win_bankroll")
        lose_b = pending.get("expected_lose_bankroll")
        if isinstance(win_b, int):
            ctx["expected_win_bankroll"] = money_req(win_b)
        if isinstance(lose_b, int):
            ctx["expected_lose_bankroll"] = money_req(lose_b)
    if session._expected_bankroll is not None:
        ctx["expected_bankroll"] = money_req(session._expected_bankroll)
    for event in reversed(session.events):
        if event.get("kind") == "companion_round_settled":
            classification = event.get("settlement_classification")
            if classification in ("WIN", "LOSS", "DIVERGENCE"):
                ctx["last_outcome"] = classification
                ctx["settlement_classification"] = classification
            winner_side = event.get("winner_side")
            if winner_side in ("DICE", "ORANGE", "BLACK"):
                ctx["last_result"] = winner_side
            break
        if event.get("kind") == "bankroll_mismatch":
            observed = event.get("observed_bankroll")
            if isinstance(observed, int):
                ctx["observed_bankroll"] = money_req(observed)
            break
    return ctx


def companion_state(
    *,
    session_id: str,
    outcome: PlayOutcome,
    session: LiveSession,
) -> CompanionStateResponse:
    loaded = session.loaded
    rec = outcome.recommendation
    durability = None
    if rec is not None:
        durability = rec.consecutive_loss_durability
    else:
        from roulette_optimizer.policy import consecutive_loss_durability

        try:
            durability = consecutive_loss_durability(loaded, outcome.bankroll)
        except Exception:
            durability = None
    ctx = _companion_context(session)
    return CompanionStateResponse(
        session_id=session_id,
        session_status=session.status,
        status=outcome.status,
        bankroll=money_req(outcome.bankroll),
        target=money_req(loaded.session.target_bankroll),
        floor=money_req(loaded.session.floor_bankroll),
        target_hit_probability=None if rec is None else rec.target_hit_probability,
        consecutive_loss_durability=durability,
        recommendation=None if rec is None else recommendation_payload(rec),
        rounds_completed=outcome.rounds_completed,
        message=outcome.message,
        awaiting_save=False,
        recommended_wager=ctx["recommended_wager"],
        observed_wager=ctx["observed_wager"],
        expected_bankroll=ctx["expected_bankroll"],
        observed_bankroll=ctx["observed_bankroll"],
        expected_win_bankroll=ctx["expected_win_bankroll"],
        expected_lose_bankroll=ctx["expected_lose_bankroll"],
        last_result=ctx["last_result"],
        last_outcome=ctx["last_outcome"],
        settlement_classification=ctx.get("settlement_classification"),
        wager_match_status=ctx.get("wager_match_status"),
        desync_reason=ctx.get("desync_reason"),
    )


def saved_session_payload(session: Any) -> SavedLiveSessionPayload:
    return SavedLiveSessionPayload(
        session_id=session.session_id,
        source=session.source,
        started_at=session.started_at,
        ended_at=session.ended_at,
        starting_bankroll=money_req(session.starting_bankroll),
        ending_bankroll=money_req(session.ending_bankroll),
        target=money_req(session.target),
        floor=money_req(session.floor),
        terminal_status=session.terminal_status,
        round_count=session.round_count,
        initial_loss_durability=session.initial_loss_durability,
        policy_identity=dict(session.policy_identity),
        events=list(session.events),
    )


def _range_timing(
    start_round: int,
    end_round: int,
    timing: HistoricalTiming | None,
) -> dict[str, object]:
    fields = timing_csv_fields_for_range(start_round, end_round, timing)
    if timing is None:
        return {
            "estimated_start_time": None,
            "estimated_end_time": None,
            "estimated_duration_seconds": None,
            "timezone": None,
            "timing_status": None,
        }
    return {
        "estimated_start_time": str(fields["estimated_start_time"]) or None,
        "estimated_end_time": str(fields["estimated_end_time"]) or None,
        "estimated_duration_seconds": float(fields["estimated_duration_seconds"]),  # type: ignore[arg-type]
        "timezone": str(fields["timezone"]) or None,
        "timing_status": str(fields["timing_status"]) or None,
    }


def _streak(s: StreakInfo, timing: HistoricalTiming | None = None) -> StreakPayload:
    return StreakPayload(
        outcome=str(s.outcome),
        length=s.length,
        start_round=s.start_round,
        end_round=s.end_round,
        **_range_timing(s.start_round, s.end_round, timing),  # type: ignore[arg-type]
    )


def _drought(d: DroughtInfo, timing: HistoricalTiming | None = None) -> DroughtPayload:
    return DroughtPayload(
        missing=str(d.missing),
        length=d.length,
        start_round=d.start_round,
        end_round=d.end_round,
        dice_count=d.dice_count,
        orange_count=d.orange_count,
        black_count=d.black_count,
        **_range_timing(d.start_round, d.end_round, timing),  # type: ignore[arg-type]
    )


def _window(w: WindowExtreme, timing: HistoricalTiming | None = None) -> WindowExtremePayload:
    return WindowExtremePayload(
        window_size=w.window_size,
        outcome=str(w.outcome),
        extremum=w.extremum,
        count=w.count,
        start_round=w.start_round,
        end_round=w.end_round,
        **_range_timing(w.start_round, w.end_round, timing),  # type: ignore[arg-type]
    )


def analyze_response(
    analysis: HistoricalRollAnalysis,
    timing: HistoricalTiming | None = None,
) -> ReplayAnalyzeResponse:
    total = analysis.total_rolls
    return ReplayAnalyzeResponse(
        round_start=analysis.round_start,
        round_end=analysis.round_end,
        total_rolls=total,
        dice_count=analysis.dice_count,
        orange_count=analysis.orange_count,
        black_count=analysis.black_count,
        dice_pct=analysis.dice_count / total if total else 0.0,
        orange_pct=analysis.orange_count / total if total else 0.0,
        black_pct=analysis.black_count / total if total else 0.0,
        theoretical_dice_pct=1 / 15,
        theoretical_color_pct=7 / 15,
        longest_orange_streak=_streak(analysis.longest_orange_streak, timing),
        longest_black_streak=_streak(analysis.longest_black_streak, timing),
        longest_same_color_streak=_streak(analysis.longest_same_color_streak, timing),
        longest_dice_streak=_streak(analysis.longest_dice_streak, timing),
        longest_dice_drought=_drought(analysis.longest_dice_drought, timing),
        longest_orange_drought=_drought(analysis.longest_orange_drought, timing),
        longest_black_drought=_drought(analysis.longest_black_drought, timing),
        dice_droughts_ge_35=analysis.dice_droughts_ge_35,
        dice_droughts_ge_45=analysis.dice_droughts_ge_45,
        window_extremes=[_window(w, timing) for w in analysis.window_extremes],
        seed_date=timing.seed_date.isoformat() if timing is not None else None,
        timezone=timing.timezone_name if timing is not None else None,
        average_cycle_seconds=(
            timing.average_cycle_seconds if timing is not None else None
        ),
        timing_status=TIMING_STATUS_ESTIMATED if timing is not None else None,
    )


def _moneyize_session_dict(raw: dict[str, object]) -> ReplaySessionPayload:
    last = raw["last_round"]
    est_start = raw.get("estimated_start_time") or None
    est_last = raw.get("estimated_last_time") or None
    tz = raw.get("timezone") or None
    status = raw.get("timing_status") or None
    return ReplaySessionPayload(
        scenario=str(raw["scenario"]),
        color_side=str(raw["color_side"]),
        start_mode=str(raw["start_mode"]),
        start_round=int(raw["start_round"]),
        last_round=None if last == "" else int(last),  # type: ignore[arg-type]
        rolls_consumed=int(raw["rolls_consumed"]),
        start_bankroll=money_req(int(raw["start_bankroll"])),
        end_bankroll=money_req(int(raw["end_bankroll"])),
        target=money_req(int(raw["target"])),
        floor=money_req(int(raw["floor"])),
        terminal_status=str(raw["terminal_status"]),
        maximum_drawdown=money_req(int(raw["maximum_drawdown"])),
        longest_losing_bet_streak=int(raw["longest_losing_bet_streak"]),
        starting_loss_durability=int(raw.get("starting_loss_durability", 0)),
        minimum_loss_durability=int(raw.get("minimum_loss_durability", 0)),
        ending_loss_durability=int(raw.get("ending_loss_durability", 0)),
        trace=[],
        estimated_start_time=str(est_start) if est_start else None,
        estimated_last_time=str(est_last) if est_last else None,
        timezone=str(tz) if tz else None,
        timing_status=str(status) if status else None,
    )


def replay_session_payload(s: ReplaySessionResult) -> ReplaySessionPayload:
    payload = _moneyize_session_dict(session_as_dict(s))
    if s.trace:
        traces = trace_as_dicts(s.trace)
        for t in traces:
            for key in (
                "bankroll_before",
                "stake",
                "bankroll_after",
                "target",
                "floor",
            ):
                t[key] = money_req(int(t[key])).model_dump()
            t["bet_won"] = bool(t["bet_won"])
        payload.trace = traces
    return payload


def replay_summary_payload(s: ReplaySummary) -> ReplaySummaryPayload:
    raw = summary_as_dict(s)
    seed = raw.get("seed_date") or None
    tz = raw.get("timezone") or None
    cycle = raw.get("average_cycle_seconds")
    status = raw.get("timing_status") or None
    return ReplaySummaryPayload(
        scenario=str(raw["scenario"]),
        color_side=str(raw["color_side"]),
        start_mode=str(raw["start_mode"]),
        start_bankroll=money_req(int(raw["start_bankroll"])),
        target=money_req(int(raw["target"])),
        floor=money_req(int(raw["floor"])),
        start_count=int(raw["start_count"]),
        target_count=int(raw["target_count"]),
        floor_count=int(raw["floor_count"]),
        no_action_count=int(raw["no_action_count"]),
        exhausted_count=int(raw["exhausted_count"]),
        resolved_count=int(raw["resolved_count"]),
        target_rate_all=float(raw["target_rate_all"]),
        target_rate_resolved=float(raw["target_rate_resolved"]),
        theoretical_V_start=float(raw["theoretical_V_start"]),
        mean_rounds_resolved=float(raw["mean_rounds_resolved"]),
        median_rounds_resolved=float(raw["median_rounds_resolved"]),
        largest_drawdown=money_req(int(raw["largest_drawdown"])),
        longest_losing_bet_streak=int(raw["longest_losing_bet_streak"]),
        solver=str(raw["solver"]),
        seed_date=str(seed) if seed else None,
        timezone=str(tz) if tz else None,
        average_cycle_seconds=float(cycle) if cycle not in (None, "") else None,
        timing_status=str(status) if status else None,
    )


def extreme_row_payload(row: ExtremeReplayRow) -> ExtremeRowPayload:
    return ExtremeRowPayload(
        scenario=row.scenario,
        color_side=row.color_side,
        extreme_kind=row.extreme_kind,
        extreme_label=row.extreme_label,
        extreme_start_round=row.extreme_start_round,
        extreme_end_round=row.extreme_end_round,
        session=replay_session_payload(row.session),
        estimated_start_time=row.estimated_start_time,
        estimated_end_time=row.estimated_end_time,
        estimated_duration_seconds=row.estimated_duration_seconds,
        timezone=row.timezone,
        timing_status=row.timing_status,
    )


def dice_map_row(row: Any) -> DiceMapRowPayload:
    return DiceMapRowPayload(
        bankroll=money_req(row.bankroll),
        dice_stake=money_req(row.dice_stake),
        dice_q=row.dice_q,
        best_color_stake=money(row.best_color_stake),
        best_color_q=row.best_color_q,
        difference=row.difference,
    )


def sweep_cell(row: Any) -> SweepCellPayload:
    v = row.V_start
    if isinstance(v, float) and math.isnan(v):
        v = None
    fd = row.final_delta
    if isinstance(fd, float) and math.isnan(fd):
        fd = None
    return SweepCellPayload(
        target_profit=money_req(row.target_profit),
        maximum_loss=money_req(row.maximum_loss),
        target=money_req(row.target),
        floor=money_req(row.floor),
        V_start=v,
        initial_loss_durability=row.initial_loss_durability,
        COLOR_state_count=row.COLOR_state_count,
        DICE_state_count=row.DICE_state_count,
        NO_ACTION_state_count=row.NO_ACTION_state_count,
        iterations=row.iterations,
        final_delta=fd,
        solve_seconds=row.solve_seconds,
        verification_status=row.verification_status,
        failure_info=row.failure_info,
    )
