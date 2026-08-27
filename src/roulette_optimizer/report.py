from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from roulette_optimizer.analysis import DiceMapResult
from roulette_optimizer.config import SessionConfig
from roulette_optimizer.policy import Recommendation, count_policy_actions
from roulette_optimizer.policy_verifier import VerificationResult
from roulette_optimizer.solver import SolverResult
from roulette_optimizer.state_space import build_state_space
from roulette_optimizer.sweep import SweepResult
from roulette_optimizer.utils import ConfigError
from roulette_optimizer.validation import ValidateResult, max_absolute_difference


def write_csv(
    path: str | Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> Path:
    out = Path(path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(fieldnames))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
    except OSError as exc:
        raise ConfigError(f"Failed to write CSV: {out}: {exc}") from exc
    return out


def format_dice_map_summary(result: DiceMapResult, output_path: Path | str) -> str:
    session = result.session

    def _fmt(v: float | None) -> str:
        return "n/a" if v is None else str(v)

    lines = [
        f"Starting bankroll:      {session.starting_bankroll}",
        f"Target bankroll:        {session.target_bankroll}",
        f"Hard bankroll floor:    {session.floor_bankroll}",
        f"Solver:                 {result.solver}",
        f"Non-terminal states:    {result.state_count}",
        f"DICE-optimal states:    {result.dice_count}",
        f"COLOR-optimal states:   {result.color_count}",
        f"No-action states:       {result.no_action_count}",
        f"Min DICE advantage:     {_fmt(result.min_difference)}",
        f"Max DICE advantage:     {_fmt(result.max_difference)}",
        f"Median DICE advantage:  {_fmt(result.median_difference)}",
        f"Output:                 {output_path}",
    ]
    preview = result.rows
    if preview:
        lines.append("")
        lines.append("Preview (first/last up to 10):")
        show = preview[:10]
        if len(preview) > 20:
            show = preview[:10] + preview[-10:]
        elif len(preview) > 10:
            show = preview
        for r in show:
            lines.append(
                f"  {r.bankroll},{r.dice_stake},{r.dice_q},"
                f"{r.best_color_stake},{r.best_color_q},{r.difference}"
            )
    return "\n".join(lines)


def format_sweep_summary(result: SweepResult, output_path: Path | str) -> str:
    lines = [
        f"Start bankroll:         {result.start}",
        f"Target-profit values:   {len(result.target_profits)}",
        f"Floor-loss values:      {len(result.floor_losses)}",
        f"Total configurations:   {len(result.rows)}",
        f"Successful solves:      {result.successful}",
        f"Failed configurations:  {result.failed}",
        f"Total runtime (s):      {result.total_seconds}",
        f"Output:                 {output_path}",
        "",
        "Compact matrix:",
        f"{'profit':>8}{'loss':>8}{'V(start)':>14}{'loss_dur':>10}",
    ]
    for r in result.rows:
        lines.append(
            f"{r.target_profit:>8}{r.maximum_loss:>8}{r.V_start:>14.6f}"
            f"{r.initial_loss_durability:>10}"
        )
    return "\n".join(lines)


def format_recommendation(rec: Recommendation) -> str:
    session = rec.session
    lines = [
        f"Current bankroll:        {rec.bankroll}",
        f"Target:                  {session.target_bankroll}",
        f"Floor:                   {session.floor_bankroll}",
        f"Target-hit probability:  {rec.target_hit_probability}",
        f"Loss durability:         {rec.consecutive_loss_durability}",
        "",
    ]
    if rec.status == "FLOOR":
        lines.extend(
            [
                "Status:                 FLOOR / FAILURE TERMINAL",
                "Recommended action:     none",
            ]
        )
    elif rec.status == "TARGET":
        lines.extend(
            [
                "Status:                 TARGET / SUCCESS TERMINAL",
                "Recommended action:     none",
            ]
        )
    elif rec.status == "NO_ACTION":
        lines.extend(
            [
                "Status:                 NO_ACTION",
                "Recommended action:     none",
            ]
        )
    else:
        lines.extend(
            [
                "Recommended action:",
                f"Bet type:                {rec.bet_type}",
                f"Stake:                   {rec.stake}",
                f"Win bankroll:            {rec.win_bankroll}",
                f"Loss bankroll:           {rec.lose_bankroll}",
            ]
        )
    return "\n".join(lines)


def format_solve_summary(
    session: SessionConfig,
    result: SolverResult,
    verification: VerificationResult,
) -> str:
    ss = build_state_space(session)
    color, dice, none = count_policy_actions(result, session)
    first = result.policy[session.starting_bankroll]
    action_line = "NO_ACTION"
    if first.action is not None:
        action_line = f"{first.action.bet_type} {first.action.stake}"
    return "\n".join(
        [
            f"Starting bankroll:      {session.starting_bankroll}",
            f"Target bankroll:        {session.target_bankroll}",
            f"Hard bankroll floor:    {session.floor_bankroll}",
            "",
            "Solver:",
            f"Converged:              yes",
            f"Iterations:             {result.iterations}",
            f"Final delta:            {result.final_delta}",
            f"Non-terminal states:    {len(ss.nonterminal)}",
            f"COLOR-optimal states:   {color}",
            f"DICE-optimal states:    {dice}",
            f"No-action states:       {none}",
            "",
            "Verification:",
            f"Policy eval max diff:   {verification.max_value_difference}",
            f"Bellman max gap:        {verification.max_optimality_gap}",
            "",
            "Optimal first action:",
            f"Action:                 {action_line}",
            f"Target-hit probability: {result.values[session.starting_bankroll]}",
        ]
    )


def _pass_fail(ok: bool) -> str:
    return "pass" if ok else "fail"


def format_validate_report(
    session: SessionConfig,
    validate_result: ValidateResult,
) -> str:
    solver = validate_result.solver
    ver = validate_result.verification
    batch = validate_result.batch
    stats = validate_result.stats

    lines = [
        "REFERENCE SOLVER",
        f"Converged:              {'yes' if solver.converged else 'no'}",
        f"Iterations:             {solver.iterations}",
        f"Final delta:            {solver.final_delta}",
        f"V(start):               {solver.values[session.starting_bankroll]}",
        "",
        "POLICY VERIFICATION",
        f"Linear evaluation:      {_pass_fail(ver.policy_evaluation_passed)}",
        f"Max value difference:   {ver.max_value_difference}",
        f"Bellman:                {_pass_fail(ver.bellman_passed)}",
        f"Max optimality gap:     {ver.max_optimality_gap}",
        f"Linear-value Bellman:   {_pass_fail(ver.linear_value_bellman_passed)}",
        f"Linear-value max gap:   {ver.linear_value_bellman_max_gap}",
        f"Legal actions:          {_pass_fail(ver.legal_actions_passed)}",
        "",
    ]

    if batch is not None and stats is not None:
        ci_note = ""
        if stats.se > 0.0:
            inside = stats.ci.lower <= stats.solver_probability <= stats.ci.upper
            ci_note = " (inside CI)" if inside else " (outside CI)"
        lines.extend(
            [
                "MONTE CARLO",
                f"Sessions:               {batch.sessions}",
                f"Seed:                   {validate_result.seed}",
                f"Target hits:            {batch.target_hits}",
                f"Floor hits:             {batch.floor_hits}",
                f"Timeouts:               {batch.timeouts}",
                f"Observed target-hit rate: {stats.p_hat}",
                f"95% CI:                 [{stats.ci.lower}, {stats.ci.upper}]{ci_note}",
                f"Solver probability:     {stats.solver_probability}",
                f"Absolute difference:    {stats.absolute_error}",
                f"Z-score:                {stats.z_score}",
                "",
            ]
        )

    if validate_result.seeds_report:
        max_abs = max_absolute_difference(validate_result)
        seed_count = 1 + len(validate_result.seeds_report)
        lines.append("MULTI-SEED SUMMARY")
        lines.append(f"Seeds:                  {seed_count}")
        lines.append(f"Max absolute difference: {max_abs}")
        lines.append("")

    lines.extend(
        [
            "STATUS",
            validate_result.deterministic_status,
        ]
    )
    return "\n".join(lines)


def format_historical_analysis(analysis, timing=None) -> str:
    t = analysis.total_rolls
    lines = [
        "Historical Roll Analysis",
        "",
        f"Rounds:                 {analysis.round_start} - {analysis.round_end}",
        f"Roll count:             {t}",
    ]
    if timing is not None:
        lines.extend(
            [
                f"Seed date:              {timing.seed_date.isoformat()}",
                f"Timezone:               {timing.timezone_name}",
                f"Avg cycle (est.):       {timing.average_cycle_seconds:.6f}s",
                "Timing status:          ESTIMATED",
            ]
        )
    lines.extend(
        [
            "",
            f"DICE:                   {analysis.dice_count} ({analysis.dice_count / t:.4%})",
            f"ORANGE:                 {analysis.orange_count} ({analysis.orange_count / t:.4%})",
            f"BLACK:                  {analysis.black_count} ({analysis.black_count / t:.4%})",
            "",
            f"Theoretical DICE:       {t / 15:.2f} (1/15)",
            f"Theoretical ORANGE:     {t * 7 / 15:.2f} (7/15)",
            f"Theoretical BLACK:      {t * 7 / 15:.2f} (7/15)",
            "",
            "Longest ORANGE streak:   "
            f"{analysis.longest_orange_streak.length} "
            f"({analysis.longest_orange_streak.start_round}-"
            f"{analysis.longest_orange_streak.end_round})",
            "Longest BLACK streak:    "
            f"{analysis.longest_black_streak.length} "
            f"({analysis.longest_black_streak.start_round}-"
            f"{analysis.longest_black_streak.end_round})",
            "Longest DICE streak:     "
            f"{analysis.longest_dice_streak.length} "
            f"({analysis.longest_dice_streak.start_round}-"
            f"{analysis.longest_dice_streak.end_round})",
            "Longest DICE drought:    "
            f"{analysis.longest_dice_drought.length} "
            f"({analysis.longest_dice_drought.start_round}-"
            f"{analysis.longest_dice_drought.end_round})",
            "Longest ORANGE drought:  "
            f"{analysis.longest_orange_drought.length} "
            f"({analysis.longest_orange_drought.start_round}-"
            f"{analysis.longest_orange_drought.end_round})",
            "Longest BLACK drought:   "
            f"{analysis.longest_black_drought.length} "
            f"({analysis.longest_black_drought.start_round}-"
            f"{analysis.longest_black_drought.end_round})",
            "",
            "Rolling-window extremes:",
        ]
    )
    for we in analysis.window_extremes:
        lines.append(
            f"  {we.window_size}-roll {we.extremum} {we.outcome}: "
            f"count={we.count} rounds={we.start_round}-{we.end_round}"
        )
    return "\n".join(lines)


def format_replay_summary_block(summaries) -> str:
    lines = ["Historical Replay Summary", ""]
    for s in summaries:
        lines.extend(
            [
                f"Scenario:               {s.scenario}",
                f"Color side:             {s.color_side}",
                f"Start mode:             {s.start_mode}",
                f"Starts:                 {s.start_count}",
                f"TARGET / FLOOR / NO_ACTION / EXHAUSTED: "
                f"{s.target_count} / {s.floor_count} / "
                f"{s.no_action_count} / {s.exhausted_count}",
                f"Theoretical V(start):   {s.theoretical_V_start}",
                f"Historical target rate/all:      {s.target_rate_all}",
                f"Historical target rate/resolved: {s.target_rate_resolved}",
                f"Mean rounds (resolved): {s.mean_rounds_resolved}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def format_extreme_replay_report(result) -> str:
    lines = ["Extreme Replay", ""]
    by_sc: dict[tuple[str, str], list] = {}
    for row in result.extreme_rows:
        by_sc.setdefault((row.scenario, row.color_side), []).append(row)
    for (scenario, color), rows in by_sc.items():
        lines.append(f"Scenario: {scenario}")
        lines.append(f"Color side: {color}")
        lines.append("")
        lines.append("Website extremes")
        lines.append("")
        for row in rows:
            if not str(row.extreme_kind).startswith("website"):
                continue
            s = row.session
            lines.extend(
                [
                    row.extreme_label,
                    f"Rounds: {row.extreme_start_round} - {row.extreme_end_round}",
                    f"Replay result: {s.terminal_status}",
                    f"Rolls consumed: {s.rolls_consumed}",
                    f"End bankroll: {s.end_bankroll}",
                    "",
                ]
            )
        lines.append("Policy extremes")
        lines.append("")
        for row in rows:
            if row.extreme_kind != "policy":
                continue
            s = row.session
            lines.extend(
                [
                    f"{row.extreme_label}:",
                    f"  start_round={s.start_round} status={s.terminal_status} "
                    f"rolls={s.rolls_consumed} end={s.end_bankroll} "
                    f"drawdown={s.maximum_drawdown}",
                    "",
                ]
            )
    return "\n".join(lines)
