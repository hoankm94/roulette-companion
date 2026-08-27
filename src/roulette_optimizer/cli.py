from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from roulette_optimizer.analysis import (
    DICE_MAP_CSV_FIELDS,
    build_dice_map,
    default_dice_map_output_path,
    dice_map_rows_as_dicts,
)
from roulette_optimizer.config import GameConfig, SessionConfig, load_session_config, merge_session
from roulette_optimizer.play import initialize_play_policy, run_play_loop
from roulette_optimizer.policy import (
    export_policy_json,
    format_policy_table,
    load_policy,
    recommend_from_policy,
)
from roulette_optimizer.policy_verifier import VerificationResult, verify_policy
from roulette_optimizer.report import (
    format_dice_map_summary,
    format_extreme_replay_report,
    format_historical_analysis,
    format_recommendation,
    format_replay_summary_block,
    format_solve_summary,
    format_sweep_summary,
    format_validate_report,
    write_csv,
)
from roulette_optimizer.solver import SolverResult, solve as run_solver
from roulette_optimizer.state_space import check_state_space_size
from roulette_optimizer.sweep import (
    SWEEP_CSV_FIELDS,
    default_sweep_output_path,
    parse_int_list,
    run_sweep,
    sweep_rows_as_dicts,
)
from roulette_optimizer.utils import (
    ConfigError,
    PolicyError,
    SimulationError,
    SolverError,
    VerificationError,
)
from roulette_optimizer.validation import (
    default_multiseed_output_path,
    default_validation_output_path,
    run_validate,
    write_multiseed_validation_json,
    write_validation_json,
)

app = typer.Typer(
    help="Dynamic Goal-Directed roulette optimizer",
    invoke_without_command=True,
)
replay_app = typer.Typer(help="Historical CSGOEmpire roulette replay")
app.add_typer(replay_app, name="replay")


def default_policy_output_path(session: SessionConfig) -> Path:
    return Path("outputs") / (
        f"policy_{session.starting_bankroll}_"
        f"{session.target_bankroll}_{session.floor_bankroll}.json"
    )


def prompt_session_bankrolls() -> tuple[int, int, int]:
    bankroll = typer.prompt("Starting bankroll", type=int)
    target = typer.prompt("Target bankroll", type=int)
    floor = typer.prompt("Hard floor", type=int)
    return bankroll, target, floor


def _resolve_session(
    bankroll: int | None,
    target: int | None,
    floor: int | None,
    config: Path | None,
    no_color: bool,
    no_dice: bool,
    solver_tolerance: float | None = None,
    solver_max_iterations: int | None = None,
) -> SessionConfig:
    if config is not None:
        base = load_session_config(config)
    elif bankroll is not None and target is not None and floor is not None:
        base = SessionConfig(
            starting_bankroll=bankroll,
            target_bankroll=target,
            floor_bankroll=floor,
        )
    else:
        raise typer.BadParameter(
            "Provide --bankroll, --target, and --floor, or use --config"
        )

    overrides: dict[str, object] = {}
    if bankroll is not None:
        overrides["starting_bankroll"] = bankroll
    if target is not None:
        overrides["target_bankroll"] = target
    if floor is not None:
        overrides["floor_bankroll"] = floor
    if no_color:
        overrides["allow_color"] = False
    if no_dice:
        overrides["allow_dice"] = False
    if solver_tolerance is not None:
        overrides["solver_tolerance"] = solver_tolerance
    if solver_max_iterations is not None:
        overrides["solver_max_iterations"] = solver_max_iterations

    try:
        return merge_session(base, **overrides)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _run_solve_pipeline(
    session: SessionConfig,
    force: bool,
    solver: str = "numpy",
) -> tuple[SolverResult, VerificationResult]:
    n = (session.target_bankroll - session.floor_bankroll) // session.bankroll_step
    warning = check_state_space_size(n, force=force)
    if warning:
        typer.echo(warning, err=True)
    from roulette_optimizer.policy_cache import solve_and_cache

    hit = solve_and_cache(session, solver=solver)
    return hit.result, hit.verification


def _exit_on_error(exc: Exception) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _parse_seeds(seeds: str) -> list[int]:
    try:
        return [int(x) for x in seeds.split(",") if x.strip()]
    except ValueError as exc:
        raise ConfigError(f"Invalid --seeds value: {seeds!r}") from exc


def _extra_seeds(primary_seed: int, seeds: str | None) -> list[int] | None:
    """Parse --seeds, dropping duplicates of --seed and within the list."""
    if seeds is None:
        return None
    seen: set[int] = set()
    out: list[int] = []
    for s in _parse_seeds(seeds):
        if s == primary_seed or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Maximize P(hit target before hard floor). Does not create positive EV."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(solve)


@app.command()
def solve(
    bankroll: Annotated[int | None, typer.Option("--bankroll")] = None,
    target: Annotated[int | None, typer.Option("--target")] = None,
    floor: Annotated[int | None, typer.Option("--floor")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, readable=True),
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    no_color: Annotated[bool, typer.Option("--no-color")] = False,
    no_dice: Annotated[bool, typer.Option("--no-dice")] = False,
    solver_tolerance: Annotated[float | None, typer.Option("--solver-tolerance")] = None,
    solver_max_iterations: Annotated[
        int | None, typer.Option("--solver-max-iterations")
    ] = None,
    solver: Annotated[str, typer.Option("--solver")] = "numpy",
) -> None:
    """Solve optimal policy; prompts for bankroll/target/floor when omitted."""
    if solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    interactive = config is None and (
        bankroll is None or target is None or floor is None
    )
    if interactive:
        bankroll, target, floor = prompt_session_bankrolls()

    try:
        session = _resolve_session(
            bankroll,
            target,
            floor,
            config,
            no_color,
            no_dice,
            solver_tolerance,
            solver_max_iterations,
        )
        result, verification = _run_solve_pipeline(session, force, solver=solver)
    except (ConfigError, SolverError, VerificationError) as exc:
        _exit_on_error(exc)

    typer.echo(format_solve_summary(session, result, verification))

    if interactive:
        typer.echo("")
        typer.echo(format_policy_table(result, session))
        out = default_policy_output_path(session)
        out.parent.mkdir(parents=True, exist_ok=True)
        export_policy_json(out, session, GameConfig(), result, verification)
        typer.echo(f"Wrote {out}")
    elif output is not None:
        export_policy_json(output, session, GameConfig(), result, verification)


@app.command()
def policy(
    bankroll: Annotated[int | None, typer.Option("--bankroll")] = None,
    target: Annotated[int | None, typer.Option("--target")] = None,
    floor: Annotated[int | None, typer.Option("--floor")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, readable=True),
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    from_bankroll: Annotated[int | None, typer.Option("--from-bankroll")] = None,
    to_bankroll: Annotated[int | None, typer.Option("--to-bankroll")] = None,
    no_color: Annotated[bool, typer.Option("--no-color")] = False,
    no_dice: Annotated[bool, typer.Option("--no-dice")] = False,
    solver_tolerance: Annotated[float | None, typer.Option("--solver-tolerance")] = None,
    solver_max_iterations: Annotated[
        int | None, typer.Option("--solver-max-iterations")
    ] = None,
    solver: Annotated[str, typer.Option("--solver")] = "numpy",
) -> None:
    """Solve optimal policy and print table."""
    if solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    try:
        session = _resolve_session(
            bankroll,
            target,
            floor,
            config,
            no_color,
            no_dice,
            solver_tolerance,
            solver_max_iterations,
        )
        result, _verification = _run_solve_pipeline(session, force, solver=solver)
    except (ConfigError, SolverError, VerificationError) as exc:
        _exit_on_error(exc)
    typer.echo(
        format_policy_table(
            result,
            session,
            from_bankroll=from_bankroll,
            to_bankroll=to_bankroll,
        )
    )


@app.command()
def recommend(
    policy: Annotated[
        Path,
        typer.Option("--policy", exists=False, dir_okay=False),
    ],
    bankroll: Annotated[int, typer.Option("--bankroll")],
) -> None:
    """Recommend stored optimal action for one bankroll from a verified policy file."""
    try:
        loaded = load_policy(policy)
        rec = recommend_from_policy(loaded, bankroll)
    except PolicyError as exc:
        _exit_on_error(exc)
    typer.echo(format_recommendation(rec))


@app.command()
def play(
    bankroll: Annotated[int | None, typer.Option("--bankroll")] = None,
    policy: Annotated[
        Path | None,
        typer.Option("--policy", exists=False, dir_okay=False),
    ] = None,
    target: Annotated[int | None, typer.Option("--target")] = None,
    floor: Annotated[int | None, typer.Option("--floor")] = None,
    solver: Annotated[str | None, typer.Option("--solver")] = None,
) -> None:
    """Manual policy-following play assistant (w/l/q)."""
    if solver is not None and solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    try:
        loaded, _solve_calls = initialize_play_policy(
            policy_path=str(policy) if policy is not None else None,
            bankroll=bankroll,
            target=target,
            floor=floor,
            solver=solver,
        )
        if bankroll is None:
            raise PolicyError("Missing --bankroll")
        run_play_loop(
            loaded,
            bankroll,
            input_fn=lambda _prompt: input(),
            echo_fn=typer.echo,
        )
    except (ConfigError, PolicyError, SolverError, VerificationError) as exc:
        _exit_on_error(exc)


@app.command()
def validate(
    bankroll: Annotated[int | None, typer.Option("--bankroll")] = None,
    target: Annotated[int | None, typer.Option("--target")] = None,
    floor: Annotated[int | None, typer.Option("--floor")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, readable=True),
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    sessions: Annotated[int, typer.Option("--sessions")] = 100_000,
    seed: Annotated[int, typer.Option("--seed")] = 42,
    seeds: Annotated[str | None, typer.Option("--seeds")] = None,
    max_rounds: Annotated[int, typer.Option("--max-rounds")] = 100_000,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    multiseed_output: Annotated[
        Path | None, typer.Option("--multiseed-output")
    ] = None,
    no_color: Annotated[bool, typer.Option("--no-color")] = False,
    no_dice: Annotated[bool, typer.Option("--no-dice")] = False,
    solver: Annotated[str, typer.Option("--solver")] = "numpy",
) -> None:
    """Validate solver via Monte Carlo simulation."""
    if solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    try:
        seed_list = _extra_seeds(seed, seeds)
        session = _resolve_session(
            bankroll,
            target,
            floor,
            config,
            no_color,
            no_dice,
        )
        n = (session.target_bankroll - session.floor_bankroll) // session.bankroll_step
        warning = check_state_space_size(n, force=force)
        if warning:
            typer.echo(warning, err=True)
        result = run_validate(
            session,
            sessions=sessions,
            seed=seed,
            max_rounds=max_rounds,
            seeds=seed_list,
            solver=solver,
        )
    except (ConfigError, SolverError, VerificationError, SimulationError) as exc:
        _exit_on_error(exc)

    typer.echo(format_validate_report(session, result))

    out_path = output if output is not None else default_validation_output_path(
        session, seed
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_validation_json(out_path, session, result)

    if seed_list:
        ms_path = (
            multiseed_output
            if multiseed_output is not None
            else default_multiseed_output_path(session)
        )
        ms_path.parent.mkdir(parents=True, exist_ok=True)
        write_multiseed_validation_json(ms_path, session, result)


@app.command("dice-map")
def dice_map(
    bankroll: Annotated[int | None, typer.Option("--bankroll")] = None,
    target: Annotated[int | None, typer.Option("--target")] = None,
    floor: Annotated[int | None, typer.Option("--floor")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, readable=True),
    ] = None,
    solver: Annotated[str, typer.Option("--solver")] = "numpy",
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    no_color: Annotated[bool, typer.Option("--no-color")] = False,
    no_dice: Annotated[bool, typer.Option("--no-dice")] = False,
) -> None:
    """Diagnostic map of DICE-optimal states vs best COLOR alternative."""
    if solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    try:
        session = _resolve_session(
            bankroll, target, floor, config, no_color, no_dice
        )
        result = build_dice_map(session, solver=solver)
        out = (
            Path(output)
            if output is not None
            else Path(default_dice_map_output_path(session))
        )
        write_csv(out, DICE_MAP_CSV_FIELDS, dice_map_rows_as_dicts(result.rows))
    except (ConfigError, SolverError) as exc:
        _exit_on_error(exc)
    typer.echo(format_dice_map_summary(result, out))


@app.command()
def sweep(
    bankroll: Annotated[int, typer.Option("--bankroll")],
    target_profits: Annotated[str, typer.Option("--target-profits")],
    floor_losses: Annotated[str, typer.Option("--floor-losses")],
    solver: Annotated[str, typer.Option("--solver")] = "numpy",
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    verify: Annotated[bool, typer.Option("--verify")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Solve many target/floor configurations (NumPy by default; no Monte Carlo)."""
    if solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    try:
        tp = parse_int_list(target_profits, label="target-profits")
        fl = parse_int_list(floor_losses, label="floor-losses")
        result = run_sweep(
            bankroll, tp, fl, solver=solver, verify=verify, force=force
        )
        out = Path(output) if output is not None else Path(default_sweep_output_path(bankroll))
        write_csv(out, SWEEP_CSV_FIELDS, sweep_rows_as_dicts(result.rows))
    except (ConfigError, SolverError) as exc:
        _exit_on_error(exc)
    typer.echo(format_sweep_summary(result, out))


def _load_historical_rolls(
    server_seed: str,
    public_seed: str,
    rounds: str,
):
    from roulette_optimizer.historical import generate_rolls, parse_round_range

    if not server_seed:
        raise ConfigError("Missing --server-seed")
    if not public_seed:
        raise ConfigError("Missing --public-seed")
    start, end = parse_round_range(rounds)
    rolls = generate_rolls(server_seed, public_seed, start, end)
    return start, end, rolls


def _optional_replay_timing(
    seed_date: str | None,
    timezone_name: str,
    round_start: int,
    round_end: int,
):
    from roulette_optimizer.historical import build_historical_timing

    if seed_date is None:
        return None
    return build_historical_timing(
        seed_date=seed_date,
        timezone_name=timezone_name,
        round_start=round_start,
        round_end=round_end,
    )


def _write_replay_traces(sessions) -> None:
    from roulette_optimizer.replay import TRACE_CSV_FIELDS, default_trace_csv_path, trace_as_dicts

    written: set[str] = set()
    for sess in sessions:
        if not sess.trace:
            continue
        path = default_trace_csv_path(sess.scenario, sess.start_round, sess.color_side)
        if path in written:
            continue
        write_csv(path, TRACE_CSV_FIELDS, trace_as_dicts(sess.trace))
        written.add(path)
        typer.echo(f"Wrote {path}")


@replay_app.command("analyze")
def replay_analyze(
    server_seed: Annotated[str, typer.Option("--server-seed")],
    public_seed: Annotated[str, typer.Option("--public-seed")],
    rounds: Annotated[str, typer.Option("--rounds")],
    seed_date: Annotated[str | None, typer.Option("--seed-date")] = None,
    timezone_name: Annotated[str, typer.Option("--timezone")] = "UTC",
) -> None:
    """Analyze a revealed historical roulette roll sequence."""
    from roulette_optimizer.historical import (
        ANALYSIS_CSV_FIELDS,
        EXTREMES_CSV_FIELDS,
        ROLL_CSV_FIELDS,
        analysis_as_dicts,
        analyze_rolls,
        annotate_extremes_timing,
        default_analysis_csv_path,
        default_extremes_csv_path,
        default_rolls_csv_path,
        extremes_as_dicts,
        rolls_as_dicts,
    )

    try:
        start, end, rolls = _load_historical_rolls(server_seed, public_seed, rounds)
        timing = _optional_replay_timing(seed_date, timezone_name, start, end)
        analysis = analyze_rolls(rolls)
        website = annotate_extremes_timing(analysis.website_extremes, timing)
    except ConfigError as exc:
        _exit_on_error(exc)

    typer.echo(format_historical_analysis(analysis, timing=timing))

    rolls_path = Path(default_rolls_csv_path(start, end))
    analysis_path = Path(default_analysis_csv_path(start, end))
    extremes_path = Path(default_extremes_csv_path(start, end))
    write_csv(rolls_path, ROLL_CSV_FIELDS, rolls_as_dicts(rolls))
    write_csv(analysis_path, ANALYSIS_CSV_FIELDS, analysis_as_dicts(analysis, timing))
    write_csv(
        extremes_path,
        EXTREMES_CSV_FIELDS,
        extremes_as_dicts(website, timing),
    )
    typer.echo(f"Wrote {rolls_path}")
    typer.echo(f"Wrote {analysis_path}")
    typer.echo(f"Wrote {extremes_path}")


@replay_app.command("run")
def replay_run(
    server_seed: Annotated[str, typer.Option("--server-seed")],
    public_seed: Annotated[str, typer.Option("--public-seed")],
    rounds: Annotated[str, typer.Option("--rounds")],
    bankroll: Annotated[int | None, typer.Option("--bankroll")] = None,
    target: Annotated[int | None, typer.Option("--target")] = None,
    floor: Annotated[int | None, typer.Option("--floor")] = None,
    scenario_file: Annotated[
        Path | None,
        typer.Option("--scenario-file", exists=True, dir_okay=False, readable=True),
    ] = None,
    color_side: Annotated[str, typer.Option("--color-side")] = "alternate",
    alternate_first: Annotated[str, typer.Option("--alternate-first")] = "black",
    start_mode: Annotated[str, typer.Option("--start-mode")] = "first",
    samples: Annotated[int | None, typer.Option("--samples")] = None,
    sample_seed: Annotated[int | None, typer.Option("--sample-seed")] = None,
    solver: Annotated[str, typer.Option("--solver")] = "numpy",
    seed_date: Annotated[str | None, typer.Option("--seed-date")] = None,
    timezone_name: Annotated[str, typer.Option("--timezone")] = "UTC",
) -> None:
    """Replay the verified Dynamic Goal-Directed policy on historical rolls."""
    from roulette_optimizer.historical import ROLL_CSV_FIELDS, default_rolls_csv_path, rolls_as_dicts
    from roulette_optimizer.replay import (
        SESSION_CSV_FIELDS,
        SUMMARY_CSV_FIELDS,
        default_sessions_csv_path,
        default_summary_csv_path,
        parse_color_sides,
        parse_start_mode,
        resolve_scenarios,
        run_historical_replays,
        session_as_dict,
        summary_as_dict,
    )

    if solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    try:
        start, end, rolls = _load_historical_rolls(server_seed, public_seed, rounds)
        timing = _optional_replay_timing(seed_date, timezone_name, start, end)
        scenarios = resolve_scenarios(
            bankroll=bankroll,
            target=target,
            floor=floor,
            scenario_file=scenario_file,
        )
        sides = parse_color_sides(color_side, alternate_first=alternate_first)
        mode = parse_start_mode(start_mode)
        result = run_historical_replays(
            rolls=rolls,
            scenarios=scenarios,
            color_sides=sides,
            start_mode=mode,
            samples=samples,
            sample_seed=sample_seed,
            solver=solver,
            collect_traces=(mode == "first"),
            timing=timing,
        )
    except (ConfigError, PolicyError, SolverError, VerificationError) as exc:
        _exit_on_error(exc)

    typer.echo(format_replay_summary_block(result.summaries))

    rolls_path = Path(default_rolls_csv_path(start, end))
    sessions_path = Path(default_sessions_csv_path(start, end))
    summary_path = Path(default_summary_csv_path(start, end))
    write_csv(rolls_path, ROLL_CSV_FIELDS, rolls_as_dicts(rolls))
    write_csv(sessions_path, SESSION_CSV_FIELDS, [session_as_dict(s) for s in result.sessions])
    write_csv(summary_path, SUMMARY_CSV_FIELDS, [summary_as_dict(s) for s in result.summaries])
    typer.echo(f"Wrote {rolls_path}")
    typer.echo(f"Wrote {sessions_path}")
    typer.echo(f"Wrote {summary_path}")
    if mode == "first":
        _write_replay_traces(result.sessions)


@replay_app.command("extreme")
def replay_extreme(
    server_seed: Annotated[str, typer.Option("--server-seed")],
    public_seed: Annotated[str, typer.Option("--public-seed")],
    rounds: Annotated[str, typer.Option("--rounds")],
    bankroll: Annotated[int | None, typer.Option("--bankroll")] = None,
    target: Annotated[int | None, typer.Option("--target")] = None,
    floor: Annotated[int | None, typer.Option("--floor")] = None,
    scenario_file: Annotated[
        Path | None,
        typer.Option("--scenario-file", exists=True, dir_okay=False, readable=True),
    ] = None,
    color_side: Annotated[str, typer.Option("--color-side")] = "alternate",
    alternate_first: Annotated[str, typer.Option("--alternate-first")] = "black",
    solver: Annotated[str, typer.Option("--solver")] = "numpy",
    seed_date: Annotated[str | None, typer.Option("--seed-date")] = None,
    timezone_name: Annotated[str, typer.Option("--timezone")] = "UTC",
) -> None:
    """Stress-test the policy against website and policy extremes."""
    from roulette_optimizer.historical import ROLL_CSV_FIELDS, default_rolls_csv_path, rolls_as_dicts
    from roulette_optimizer.replay import (
        EXTREME_REPLAY_CSV_FIELDS,
        SESSION_CSV_FIELDS,
        SUMMARY_CSV_FIELDS,
        default_extreme_replays_csv_path,
        default_sessions_csv_path,
        default_summary_csv_path,
        extreme_row_as_dict,
        parse_color_sides,
        resolve_scenarios,
        run_extreme_replays,
        session_as_dict,
        summary_as_dict,
    )

    if solver not in ("reference", "numpy", "numba", "policy_iteration"):
        typer.echo(f"Unknown --solver {solver!r}; use reference, numpy, numba, or policy_iteration", err=True)
        raise typer.Exit(code=1)
    try:
        start, end, rolls = _load_historical_rolls(server_seed, public_seed, rounds)
        timing = _optional_replay_timing(seed_date, timezone_name, start, end)
        scenarios = resolve_scenarios(
            bankroll=bankroll,
            target=target,
            floor=floor,
            scenario_file=scenario_file,
        )
        sides = parse_color_sides(color_side, alternate_first=alternate_first)
        result = run_extreme_replays(
            rolls=rolls,
            scenarios=scenarios,
            color_sides=sides,
            solver=solver,
            timing=timing,
        )
    except (ConfigError, PolicyError, SolverError, VerificationError) as exc:
        _exit_on_error(exc)

    typer.echo(format_extreme_replay_report(result))
    if result.summaries:
        typer.echo(format_replay_summary_block(result.summaries))

    rolls_path = Path(default_rolls_csv_path(start, end))
    sessions_path = Path(default_sessions_csv_path(start, end))
    summary_path = Path(default_summary_csv_path(start, end))
    extreme_path = Path(default_extreme_replays_csv_path(start, end))
    write_csv(rolls_path, ROLL_CSV_FIELDS, rolls_as_dicts(rolls))
    write_csv(sessions_path, SESSION_CSV_FIELDS, [session_as_dict(s) for s in result.sessions])
    write_csv(summary_path, SUMMARY_CSV_FIELDS, [summary_as_dict(s) for s in result.summaries])
    write_csv(
        extreme_path,
        EXTREME_REPLAY_CSV_FIELDS,
        [extreme_row_as_dict(r) for r in result.extreme_rows],
    )
    typer.echo(f"Wrote {rolls_path}")
    typer.echo(f"Wrote {sessions_path}")
    typer.echo(f"Wrote {summary_path}")
    typer.echo(f"Wrote {extreme_path}")
    _write_replay_traces(result.sessions)


if __name__ == "__main__":
    app()
