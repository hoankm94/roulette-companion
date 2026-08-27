"""Thin FastAPI routes over existing domain callables."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, HTTPException

from roulette_optimizer.analysis import build_dice_map
from roulette_optimizer.historical import (
    analyze_rolls,
    build_historical_timing,
    generate_rolls,
    parse_round_range,
    validate_seed_input,
)
from roulette_optimizer.calculate_target import calculate_target_for_reach
from roulette_optimizer.policy import recommend_from_policy
from roulette_optimizer.policy_cache import solve_and_cache
from roulette_optimizer.replay import (
    ReplayScenario,
    parse_color_sides,
    run_extreme_replays,
    run_historical_replays,
)
from roulette_optimizer.sweep import run_sweep
from roulette_optimizer.utils import ConfigError
from roulette_optimizer.validation import max_absolute_difference, run_validate

from api import serializers as ser
from api.errors import SessionNotFoundError
from api.money import dollars_to_cents
from api.models import (
    CompanionBankrollRequest,
    CompanionCalculateTargetRequest,
    CompanionCalculateTargetResponse,
    CompanionDiagnosticEventRequest,
    CompanionDomWagerRequest,
    CompanionSettleRoundRequest,
    CompanionRegisterResultRequest,
    CompanionRegisterWagerRequest,
    CompanionStartRequest,
    CompanionStateResponse,
    DiceMapRequest,
    DiceMapResponse,
    OptimizeRequest,
    OptimizeResponse,
    PlaySaveResponse,
    PlayStartRequest,
    PlayStateResponse,
    ReplayAnalyzeRequest,
    ReplayAnalyzeResponse,
    ReplayExtremesRequest,
    ReplayExtremesResponse,
    ReplayRunRequest,
    ReplayRunResponse,
    SweepRequest,
    SweepResponse,
    ValidateRequest,
    ValidateResponse,
)
from api.play_store import play_store
from api.saved_sessions import saved_session_repository
from api.session_build import default_game, session_from_money

router = APIRouter(prefix="/api")


def _rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


TERMINAL_PLAY_STATUSES = frozenset(
    {"TARGET", "FLOOR", "NO_ACTION", "QUIT", "USER_STOPPED", "ERROR"}
)

TERMINAL_COMPANION_STATUSES = frozenset(
    {"TARGET", "FLOOR", "NO_ACTION", "QUIT", "USER_STOPPED", "ERROR"}
)


def _policy_identity(session, game, solver: str) -> dict:
    from roulette_optimizer.policy_cache import (
        build_normalized_cache_key,
        cache_key_hash,
        resolve_production_solver,
    )

    solver_name = resolve_production_solver(solver)
    key = build_normalized_cache_key(session, game, solver=solver_name)
    return {"cache_key_hash": cache_key_hash(key), "solver": solver_name}


def _play_awaiting_save(status: str) -> bool:
    return status in TERMINAL_PLAY_STATUSES


def _companion_awaiting_save(status: str) -> bool:
    return status in TERMINAL_COMPANION_STATUSES


def _require_companion_entry(session_id: str):
    entry = play_store.get(session_id)
    if entry is None:
        raise SessionNotFoundError()
    if entry.session.source != "COMPANION":
        raise HTTPException(
            status_code=400,
            detail="Session is not a companion session",
        )
    return entry


@contextmanager
def _companion_mutation(session_id: str) -> Iterator:
    with play_store.mutate_session(session_id):
        yield _require_companion_entry(session_id)


def _companion_response(
    session_id: str,
    entry,
    outcome,
    *,
    awaiting_save: bool | None = None,
) -> CompanionStateResponse:
    awaiting = (
        awaiting_save
        if awaiting_save is not None
        else _companion_awaiting_save(outcome.status)
    )
    payload = ser.companion_state(
        session_id=session_id,
        outcome=outcome,
        session=entry.session,
    )
    payload.awaiting_save = awaiting
    return payload


@router.post("/companion/start", response_model=CompanionStateResponse)
def companion_start(req: CompanionStartRequest) -> CompanionStateResponse:
    session = session_from_money(req)
    game = default_game()
    hit = solve_and_cache(session, game, solver=req.solver)
    policy_identity = _policy_identity(session, game, req.solver)
    session_id = play_store.create(
        hit.loaded,
        session.starting_bankroll,
        hit.verification,
        solver=hit.solver_used,
        policy_identity=policy_identity,
        source="COMPANION",
    )
    entry = play_store.get(session_id)
    assert entry is not None
    outcome = entry.session.begin_round()
    if _companion_awaiting_save(outcome.status):
        play_store.set_terminal(session_id, outcome.status)
    return _companion_response(session_id, entry, outcome)


@router.post(
    "/companion/calculate-target",
    response_model=CompanionCalculateTargetResponse,
)
def companion_calculate_target(
    req: CompanionCalculateTargetRequest,
) -> CompanionCalculateTargetResponse:
    """Setup-only Target search. Does not create an ActiveLiveSession."""
    from api.money import MoneyError

    try:
        bankroll = dollars_to_cents(req.bankroll)
        floor = dollars_to_cents(req.floor)
    except MoneyError as exc:
        raise ConfigError(str(exc)) from exc

    result = calculate_target_for_reach(
        bankroll,
        floor,
        req.reach_target_probability,
        game=default_game(),
        solver=req.solver,
        force=req.force,
    )
    # Timing/candidates already logged by calculate_target_for_reach.
    return CompanionCalculateTargetResponse(
        target=ser.money_req(result.target),
        target_hit_probability=result.target_hit_probability,
        solves=result.solves,
    )


@router.get("/companion/{session_id}", response_model=CompanionStateResponse)
def companion_get(session_id: str) -> CompanionStateResponse:
    entry = _require_companion_entry(session_id)
    if entry.terminal_status is not None:
        from roulette_optimizer.play import PlayOutcome

        outcome = PlayOutcome(
            entry.terminal_status,
            entry.session.bankroll,
            entry.session.rounds_completed,
            None,
        )
        return _companion_response(session_id, entry, outcome, awaiting_save=True)
    if entry.session.status == "WAITING_FOR_WAGER":
        from roulette_optimizer.play import PlayOutcome

        outcome = PlayOutcome(
            "CONTINUE",
            entry.session.bankroll,
            entry.session.rounds_completed,
            entry.session.current_recommendation,
        )
        return _companion_response(session_id, entry, outcome)
    if entry.session.status == "ROUND_PENDING":
        from roulette_optimizer.play import PlayOutcome

        message = None
        pending = entry.session._pending_round
        if pending is not None and pending.get("wager_match_status") == "MISMATCH":
            message = (
                "Wager differs from recommendation. "
                "The strategy will resync when the round finishes."
            )
        outcome = PlayOutcome(
            "CONTINUE",
            entry.session.bankroll,
            entry.session.rounds_completed,
            entry.session.current_recommendation,
            message,
        )
        return _companion_response(session_id, entry, outcome)
    outcome = entry.session._outcome()
    return _companion_response(session_id, entry, outcome)


@router.post(
    "/companion/{session_id}/wager-deduction",
    response_model=CompanionStateResponse,
)  # Legacy: bankroll-deduction wager detection; DOM dom-wager is production path.
def companion_wager_deduction(
    session_id: str,
    req: CompanionBankrollRequest,
) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        observed = dollars_to_cents(req.observed_bankroll)
        outcome = entry.session.register_wager_deduction(observed)
        if _companion_awaiting_save(outcome.status):
            play_store.set_terminal(session_id, outcome.status)
        return _companion_response(session_id, entry, outcome)


@router.post(
    "/companion/{session_id}/dom-wager",
    response_model=CompanionStateResponse,
)
def companion_dom_wager(
    session_id: str,
    req: CompanionDomWagerRequest,
) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        observed = dollars_to_cents(req.observed_bankroll)
        stake = dollars_to_cents(req.stake)
        color_side = req.bet_type if req.bet_type in ("ORANGE", "BLACK") else None
        outcome = entry.session.register_dom_placed_wager(
            req.bet_type,
            stake,
            color_side=color_side,
            observed_bankroll=observed,
        )
        if _companion_awaiting_save(outcome.status):
            play_store.set_terminal(session_id, outcome.status)
        return _companion_response(session_id, entry, outcome)


@router.post(
    "/companion/{session_id}/settle-round",
    response_model=CompanionStateResponse,
)
def companion_settle_round(
    session_id: str,
    req: CompanionSettleRoundRequest,
) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        outcome = entry.session.settle_companion_round(req.winner_side)
        if _companion_awaiting_save(outcome.status):
            play_store.set_terminal(session_id, outcome.status)
        return _companion_response(session_id, entry, outcome)


@router.post(
    "/companion/{session_id}/register-wager",
    response_model=CompanionStateResponse,
)
def companion_register_wager(
    session_id: str,
    req: CompanionRegisterWagerRequest,
) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        stake = dollars_to_cents(req.stake)
        outcome = entry.session.register_observed_wager(
            req.round_id,
            req.bet_type,
            stake,
            color_side=req.color_side,
        )
        if _companion_awaiting_save(outcome.status):
            play_store.set_terminal(session_id, outcome.status)
        return _companion_response(session_id, entry, outcome)


@router.post(
    "/companion/{session_id}/register-result",
    response_model=CompanionStateResponse,
)
def companion_register_result(
    session_id: str,
    req: CompanionRegisterResultRequest,
) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        outcome = entry.session.register_observed_result(req.round_id, req.result)
        return _companion_response(session_id, entry, outcome)


@router.post(
    "/companion/{session_id}/reconcile",
    response_model=CompanionStateResponse,
)
def companion_reconcile(
    session_id: str,
    req: CompanionBankrollRequest,
) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        observed = dollars_to_cents(req.observed_bankroll)
        outcome = entry.session.reconcile_bankroll(observed)
        if _companion_awaiting_save(outcome.status):
            play_store.set_terminal(session_id, outcome.status)
        return _companion_response(session_id, entry, outcome)


@router.post("/companion/{session_id}/resync", response_model=CompanionStateResponse)
def companion_resync(
    session_id: str,
    req: CompanionBankrollRequest,
) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        website = dollars_to_cents(req.observed_bankroll)
        outcome = entry.session.resync_bankroll(website)
        if _companion_awaiting_save(outcome.status):
            play_store.set_terminal(session_id, outcome.status)
        return _companion_response(session_id, entry, outcome)


@router.post("/companion/{session_id}/stop", response_model=CompanionStateResponse)
def companion_stop(session_id: str) -> CompanionStateResponse:
    with _companion_mutation(session_id) as entry:
        outcome = entry.session.stop_session()
        play_store.set_terminal(session_id, outcome.status)
        return _companion_response(session_id, entry, outcome, awaiting_save=True)


@router.post("/companion/{session_id}/diagnostic-event")
def companion_diagnostic_event(
    session_id: str,
    req: CompanionDiagnosticEventRequest,
) -> dict[str, object]:
    """Record BANKROLL_RECONCILED / WARNING on the companion session (plan §30)."""
    with _companion_mutation(session_id) as entry:
        entry.session.record_diagnostic_event(req.kind, detail=req.detail)
        return {"ok": True, "session_id": session_id, "kind": req.kind}


@router.post("/companion/{session_id}/save", response_model=PlaySaveResponse)
def companion_save(session_id: str) -> PlaySaveResponse:
    with _companion_mutation(session_id) as entry:
        if entry.terminal_status is None:
            raise HTTPException(
                status_code=400,
                detail="Session is still active; stop or finish before saving",
            )
        terminal_status = entry.terminal_status or "UNKNOWN"
        saved = entry.session.build_saved_session(
            session_id,
            policy_identity=entry.policy_identity,
            terminal_status=terminal_status,
        )
        _, csv_path, json_path = saved_session_repository.save(saved)
        play_store.delete(session_id)
        return PlaySaveResponse(
            saved=True,
            session_id=session_id,
            csv_path=_rel_path(csv_path),
            json_path=_rel_path(json_path),
        )


@router.post("/companion/{session_id}/discard", response_model=PlaySaveResponse)
def companion_discard(session_id: str) -> PlaySaveResponse:
    with _companion_mutation(session_id) as entry:
        if entry.terminal_status is None:
            raise HTTPException(
                status_code=400,
                detail="Session is still active; stop or finish before discarding",
            )
        play_store.delete(session_id)
        return PlaySaveResponse(saved=False, session_id=session_id)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/optimize", response_model=OptimizeResponse)
def optimize(req: OptimizeRequest) -> OptimizeResponse:
    session = session_from_money(req)
    game = default_game()
    hit = solve_and_cache(session, game, solver=req.solver)
    rec = recommend_from_policy(hit.loaded, session.starting_bankroll)
    return OptimizeResponse(
        recommendation=ser.recommendation_payload(rec),
        session=ser.session_public(session),
        distribution=ser.distribution(hit.result, session),
        policy=ser.policy_rows(hit.result, session),
        values=ser.value_series(hit.result, session),
        verification=ser.verification_payload(hit.verification),
        solver=ser.solver_meta(hit.result, hit.solver_used),
    )


@router.post("/play/start", response_model=PlayStateResponse)
def play_start(req: PlayStartRequest) -> PlayStateResponse:
    session = session_from_money(req)
    game = default_game()
    hit = solve_and_cache(session, game, solver=req.solver)
    policy_identity = _policy_identity(session, game, req.solver)
    session_id = play_store.create(
        hit.loaded,
        session.starting_bankroll,
        hit.verification,
        solver=hit.solver_used,
        policy_identity=policy_identity,
    )
    entry = play_store.get(session_id)
    assert entry is not None
    outcome = entry.session.begin_round()
    if _play_awaiting_save(outcome.status):
        play_store.set_terminal(session_id, outcome.status)
    return PlayStateResponse(
        **ser.play_state(
            session_id=session_id,
            outcome=outcome,
            loaded=hit.loaded,
            verification=hit.verification,
            awaiting_save=_play_awaiting_save(outcome.status),
        )
    )


def _play_action(session_id: str, token: str) -> PlayStateResponse:
    entry = play_store.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Play session not found")
    outcome = entry.session.apply_input(token)
    if _play_awaiting_save(outcome.status):
        play_store.set_terminal(session_id, outcome.status)
    return PlayStateResponse(
        **ser.play_state(
            session_id=session_id,
            outcome=outcome,
            loaded=entry.loaded,
            verification=entry.verification,
            awaiting_save=_play_awaiting_save(outcome.status),
        )
    )


@router.post("/play/{session_id}/win", response_model=PlayStateResponse)
def play_win(session_id: str) -> PlayStateResponse:
    return _play_action(session_id, "w")


@router.post("/play/{session_id}/loss", response_model=PlayStateResponse)
def play_loss(session_id: str) -> PlayStateResponse:
    return _play_action(session_id, "l")


@router.post("/play/{session_id}/end", response_model=PlayStateResponse)
def play_end(session_id: str) -> PlayStateResponse:
    entry = play_store.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Play session not found")
    outcome = entry.session.stop_session(message="Session ended")
    play_store.set_terminal(session_id, outcome.status)
    return PlayStateResponse(
        **ser.play_state(
            session_id=session_id,
            outcome=outcome,
            loaded=entry.loaded,
            verification=entry.verification,
            awaiting_save=True,
        )
    )


def _require_terminal_entry(session_id: str):
    entry = play_store.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Play session not found")
    if entry.terminal_status is None:
        raise HTTPException(
            status_code=400,
            detail="Session is still active; finish or end it before saving",
        )
    return entry


@router.post("/play/{session_id}/save", response_model=PlaySaveResponse)
def play_save(session_id: str) -> PlaySaveResponse:
    entry = _require_terminal_entry(session_id)
    terminal_status = entry.terminal_status or "UNKNOWN"
    saved = entry.session.build_saved_session(
        session_id,
        policy_identity=entry.policy_identity,
        terminal_status=terminal_status,
    )
    _, csv_path, json_path = saved_session_repository.save(saved)
    play_store.delete(session_id)
    return PlaySaveResponse(
        saved=True,
        session_id=session_id,
        csv_path=_rel_path(csv_path),
        json_path=_rel_path(json_path),
    )


@router.post("/play/{session_id}/discard", response_model=PlaySaveResponse)
def play_discard(session_id: str) -> PlaySaveResponse:
    _require_terminal_entry(session_id)
    play_store.delete(session_id)
    return PlaySaveResponse(saved=False, session_id=session_id)


@router.get("/play/{session_id}", response_model=PlayStateResponse)
def play_get(session_id: str) -> PlayStateResponse:
    entry = play_store.get(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Play session not found")
    if entry.terminal_status is not None:
        from roulette_optimizer.play import PlayOutcome

        outcome = PlayOutcome(
            entry.terminal_status,
            entry.session.bankroll,
            entry.session.rounds_completed,
            None,
        )
        awaiting = True
    elif entry.session.status == "WAITING_FOR_WAGER":
        from roulette_optimizer.play import PlayOutcome

        outcome = PlayOutcome(
            "CONTINUE",
            entry.session.bankroll,
            entry.session.rounds_completed,
            entry.session.current_recommendation,
        )
        awaiting = False
    else:
        outcome = entry.session.begin_round()
        if _play_awaiting_save(outcome.status):
            play_store.set_terminal(session_id, outcome.status)
        awaiting = _play_awaiting_save(outcome.status)
    return PlayStateResponse(
        **ser.play_state(
            session_id=session_id,
            outcome=outcome,
            loaded=entry.loaded,
            verification=entry.verification,
            awaiting_save=awaiting,
        )
    )


def _optional_timing(seed_date: str | None, timezone: str, start: int, end: int):
    if not seed_date:
        return None
    return build_historical_timing(
        seed_date=seed_date,
        timezone_name=timezone,
        round_start=start,
        round_end=end,
    )


@router.post("/replay/analyze", response_model=ReplayAnalyzeResponse)
def replay_analyze(req: ReplayAnalyzeRequest) -> ReplayAnalyzeResponse:
    validate_seed_input(req.server_seed, req.public_seed)
    start, end = parse_round_range(req.rounds)
    timing = _optional_timing(req.seed_date, req.timezone, start, end)
    rolls = generate_rolls(req.server_seed, req.public_seed, start, end)
    analysis = analyze_rolls(rolls)
    return ser.analyze_response(analysis, timing)


@router.post("/replay/run", response_model=ReplayRunResponse)
def replay_run(req: ReplayRunRequest) -> ReplayRunResponse:
    validate_seed_input(req.server_seed, req.public_seed)
    start, end = parse_round_range(req.rounds)
    timing = _optional_timing(req.seed_date, req.timezone, start, end)
    rolls = generate_rolls(req.server_seed, req.public_seed, start, end)
    bankroll = dollars_to_cents(req.bankroll)
    target = dollars_to_cents(req.target)
    floor = dollars_to_cents(req.floor)
    scenarios = [
        ReplayScenario(name="primary", bankroll=bankroll, target=target, floor=floor)
    ]
    sides = parse_color_sides(req.color_side, alternate_first=req.alternate_first)
    result = run_historical_replays(
        rolls=rolls,
        scenarios=scenarios,
        color_sides=sides,
        start_mode=req.start_mode,
        samples=req.samples,
        sample_seed=req.sample_seed,
        solver=req.solver,
        collect_traces=req.start_mode == "first",
        timing=timing,
    )
    sessions = [ser.replay_session_payload(s) for s in result.sessions]
    if req.start_mode != "first" and len(sessions) > 200:
        sessions = sessions[:200]
    return ReplayRunResponse(
        summaries=[ser.replay_summary_payload(s) for s in result.summaries],
        sessions=sessions,
        solve_calls=result.solve_calls,
    )


@router.post("/replay/extremes", response_model=ReplayExtremesResponse)
def replay_extremes(req: ReplayExtremesRequest) -> ReplayExtremesResponse:
    validate_seed_input(req.server_seed, req.public_seed)
    start, end = parse_round_range(req.rounds)
    timing = _optional_timing(req.seed_date, req.timezone, start, end)
    rolls = generate_rolls(req.server_seed, req.public_seed, start, end)
    bankroll = dollars_to_cents(req.bankroll)
    target = dollars_to_cents(req.target)
    floor = dollars_to_cents(req.floor)
    scenarios = [
        ReplayScenario(name="primary", bankroll=bankroll, target=target, floor=floor)
    ]
    sides = parse_color_sides(req.color_side, alternate_first=req.alternate_first)
    result = run_extreme_replays(
        rolls=rolls,
        scenarios=scenarios,
        color_sides=sides,
        solver=req.solver,
        timing=timing,
    )
    assert result.analysis is not None
    return ReplayExtremesResponse(
        analysis=ser.analyze_response(result.analysis, timing),
        extreme_rows=[ser.extreme_row_payload(r) for r in result.extreme_rows],
        summaries=[ser.replay_summary_payload(s) for s in result.summaries],
        solve_calls=result.solve_calls,
    )


@router.post("/explore/dice-map", response_model=DiceMapResponse)
def explore_dice_map(req: DiceMapRequest) -> DiceMapResponse:
    session = session_from_money(req)
    result = build_dice_map(session, solver=req.solver)
    return DiceMapResponse(
        state_count=result.state_count,
        dice_count=result.dice_count,
        color_count=result.color_count,
        no_action_count=result.no_action_count,
        min_difference=result.min_difference,
        max_difference=result.max_difference,
        median_difference=result.median_difference,
        rows=[ser.dice_map_row(r) for r in result.rows],
        solver=result.solver,
    )


@router.post("/explore/sweep", response_model=SweepResponse)
def explore_sweep(req: SweepRequest) -> SweepResponse:
    bankroll = dollars_to_cents(req.bankroll)
    target_profits = [dollars_to_cents(x) for x in req.target_profits]
    floor_losses = [dollars_to_cents(x) for x in req.floor_losses]
    result = run_sweep(
        bankroll,
        target_profits,
        floor_losses,
        solver=req.solver,
        verify=req.verify,
        force=req.force,
    )
    return SweepResponse(
        bankroll=ser.money_req(bankroll),
        target_profits=[ser.money_req(x) for x in result.target_profits],
        floor_losses=[ser.money_req(x) for x in result.floor_losses],
        cells=[ser.sweep_cell(r) for r in result.rows],
        successful=result.successful,
        failed=result.failed,
        total_seconds=result.total_seconds,
    )


@router.post("/diagnostics/validate", response_model=ValidateResponse)
def diagnostics_validate(req: ValidateRequest) -> ValidateResponse:
    session = session_from_money(req)
    out = run_validate(
        session,
        sessions=req.sessions,
        seed=req.seed,
        max_rounds=req.max_rounds,
        seeds=req.seeds,
        solver=req.solver,
    )
    mc = None
    if out.batch is not None and out.stats is not None:
        mc = {
            "seed": out.seed,
            "max_rounds": out.max_rounds,
            "sessions": out.batch.sessions,
            "target_hits": out.batch.target_hits,
            "floor_hits": out.batch.floor_hits,
            "timeouts": out.batch.timeouts,
            "target_hit_rate": out.batch.target_hit_rate,
            "p_hat": out.stats.p_hat,
            "se": out.stats.se,
            "ci_lower": out.stats.ci.lower,
            "ci_upper": out.stats.ci.upper,
            "z_score": out.stats.z_score,
            "absolute_error": out.stats.absolute_error,
            "solver_probability": out.stats.solver_probability,
        }
    seeds_out = None
    if out.seeds_report is not None:
        seeds_out = [
            {
                "seed": e.seed,
                "p_hat": e.stats.p_hat,
                "absolute_error": e.stats.absolute_error,
                "z_score": e.stats.z_score,
                "ci_lower": e.stats.ci.lower,
                "ci_upper": e.stats.ci.upper,
            }
            for e in out.seeds_report
        ]
    from roulette_optimizer.policy_cache import resolve_production_solver

    return ValidateResponse(
        deterministic_status=out.deterministic_status,
        verification=ser.verification_payload(out.verification),
        solver=ser.solver_meta(out.solver, resolve_production_solver(req.solver)),
        solver_probability=out.solver.values[session.starting_bankroll],
        monte_carlo=mc,
        seeds=seeds_out,
        max_absolute_difference=max_absolute_difference(out),
    )


@router.post("/diagnostics/verify", response_model=OptimizeResponse)
def diagnostics_verify(req: OptimizeRequest) -> OptimizeResponse:
    """Solve + verify; same payload shape as optimize for the diagnostics panel."""
    return optimize(req)
