from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roulette_optimizer.run_length_stats import maximal_run_lengths, summarize_run_lengths
from roulette_optimizer.utils import ConfigError

Outcome = Literal["DICE", "ORANGE", "BLACK"]

SECONDS_PER_DAY = 86400.0
TIMING_STATUS_ESTIMATED = "ESTIMATED"

ROLL_CSV_FIELDS = ("round", "hash_prefix", "roll", "outcome")
ANALYSIS_CSV_FIELDS = (
    "metric",
    "value",
    "start_round",
    "end_round",
    "extra",
    "estimated_start_time",
    "estimated_end_time",
    "estimated_duration_seconds",
    "timezone",
    "timing_status",
)
EXTREMES_CSV_FIELDS = (
    "kind",
    "label",
    "window_size",
    "length_or_count",
    "start_round",
    "end_round",
    "dice_count",
    "orange_count",
    "black_count",
    "estimated_start_time",
    "estimated_end_time",
    "estimated_duration_seconds",
    "timezone",
    "timing_status",
)

DEFAULT_WINDOW_SIZES = (25, 50, 100, 250)

_RANGE_SEP = re.compile(r"\s*-\s*")


@dataclass(frozen=True)
class HistoricalSeedSet:
    server_seed: str
    public_seed: str
    round_start: int
    round_end: int


@dataclass(frozen=True)
class HistoricalRoll:
    round_number: int
    hash_prefix: str
    roll: int
    outcome: Outcome


@dataclass(frozen=True)
class StreakInfo:
    outcome: Outcome | str
    length: int
    start_round: int
    end_round: int


@dataclass(frozen=True)
class DroughtInfo:
    missing: Outcome
    length: int
    start_round: int
    end_round: int
    dice_count: int
    orange_count: int
    black_count: int


@dataclass(frozen=True)
class WindowExtreme:
    window_size: int
    outcome: Outcome
    extremum: Literal["highest", "lowest"]
    count: int
    start_round: int
    end_round: int


@dataclass(frozen=True)
class HistoricalExtreme:
    kind: str  # streak | drought | window
    label: str
    start_round: int
    end_round: int
    length_or_count: int
    window_size: int | None = None
    dice_count: int | None = None
    orange_count: int | None = None
    black_count: int | None = None
    estimated_start_time: str | None = None
    estimated_end_time: str | None = None
    estimated_duration_seconds: float | None = None
    timezone: str | None = None
    timing_status: str | None = None


@dataclass(frozen=True)
class HistoricalTiming:
    """Estimated wall-clock mapping for a historical seed-day round range."""

    seed_date: date
    timezone_name: str
    round_start: int
    round_end: int
    average_cycle_seconds: float


@dataclass(frozen=True)
class HistoricalRollAnalysis:
    round_start: int
    round_end: int
    total_rolls: int
    dice_count: int
    orange_count: int
    black_count: int
    longest_orange_streak: StreakInfo
    longest_black_streak: StreakInfo
    longest_same_color_streak: StreakInfo
    longest_dice_streak: StreakInfo
    longest_dice_drought: DroughtInfo
    longest_orange_drought: DroughtInfo
    longest_black_drought: DroughtInfo
    dice_drought_count: int
    dice_drought_mean: float | None
    dice_drought_median: float | None
    dice_drought_max: int
    dice_drought_p90: float | None
    dice_drought_p95: float | None
    dice_drought_p99: float | None
    window_extremes: tuple[WindowExtreme, ...]
    website_extremes: tuple[HistoricalExtreme, ...]


def parse_round_range(raw: str) -> tuple[int, int]:
    text = raw.strip()
    if not text:
        raise ConfigError("Empty --rounds value")
    parts = _RANGE_SEP.split(text)
    if len(parts) != 2:
        raise ConfigError(
            f"Invalid --rounds {raw!r}; expected 'START - END' or 'START-END'"
        )
    start_s, end_s = parts[0].strip(), parts[1].strip()
    if not start_s or not end_s:
        raise ConfigError(
            f"Invalid --rounds {raw!r}; expected 'START - END' or 'START-END'"
        )
    if not start_s.isdigit() or not end_s.isdigit():
        raise ConfigError(
            f"Invalid --rounds {raw!r}; endpoints must be non-negative integers"
        )
    start, end = int(start_s), int(end_s)
    if start < 0:
        raise ConfigError("round start must be >= 0")
    if end < start:
        raise ConfigError("round end must be >= round start")
    return start, end


def validate_seed_input(server_seed: str, public_seed: str) -> None:
    if not server_seed or not server_seed.strip():
        raise ConfigError("Missing --server-seed")
    if not public_seed or not public_seed.strip():
        raise ConfigError("Missing --public-seed")
    # public_seed must remain a string; reject only empty after strip of outer whitespace
    # but preserve internal/leading zeros — do not strip leading zeros.
    if public_seed != public_seed.strip():
        # allow trailing/leading spaces from CLI? strip outer only for validation of emptiness
        pass
    if not server_seed.strip():
        raise ConfigError("Missing --server-seed")


def validate_timezone(name: str) -> ZoneInfo:
    text = (name or "").strip()
    if not text:
        raise ConfigError("Empty timezone; expected an IANA name such as UTC or Asia/Taipei")
    try:
        return ZoneInfo(text)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(
            f"Invalid timezone {name!r}; expected an IANA name such as UTC or Asia/Taipei"
        ) from exc


def parse_seed_date(raw: str) -> date:
    text = (raw or "").strip()
    if not text:
        raise ConfigError("Empty --seed-date; expected YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ConfigError(
            f"Invalid --seed-date {raw!r}; expected ISO date YYYY-MM-DD"
        ) from exc


def estimate_round_cycle_seconds(round_start: int, round_end: int) -> float:
    if round_end < round_start:
        raise ConfigError("round end must be >= round start")
    round_count = round_end - round_start + 1
    if round_count <= 0:
        raise ConfigError("round_count must be > 0")
    return SECONDS_PER_DAY / round_count


def build_historical_timing(
    *,
    seed_date: str | date,
    timezone_name: str,
    round_start: int,
    round_end: int,
) -> HistoricalTiming:
    parsed = seed_date if isinstance(seed_date, date) else parse_seed_date(seed_date)
    tz_name = (timezone_name or "UTC").strip() or "UTC"
    validate_timezone(tz_name)
    if round_end < round_start:
        raise ConfigError("round end must be >= round start")
    return HistoricalTiming(
        seed_date=parsed,
        timezone_name=tz_name,
        round_start=round_start,
        round_end=round_end,
        average_cycle_seconds=estimate_round_cycle_seconds(round_start, round_end),
    )


def estimate_round_timestamp(
    round_number: int,
    timing: HistoricalTiming,
) -> datetime:
    if round_number < timing.round_start or round_number > timing.round_end:
        raise ConfigError(
            f"Round {round_number} outside timing range "
            f"{timing.round_start}..{timing.round_end}"
        )
    utc_midnight = datetime(
        timing.seed_date.year,
        timing.seed_date.month,
        timing.seed_date.day,
        tzinfo=timezone.utc,
    )
    offset = (round_number - timing.round_start) * timing.average_cycle_seconds
    utc_instant = utc_midnight + timedelta(seconds=offset)
    return utc_instant.astimezone(ZoneInfo(timing.timezone_name))


def estimate_round_time_range(
    start_round: int,
    end_round: int,
    timing: HistoricalTiming,
) -> tuple[datetime, datetime, float]:
    if end_round < start_round:
        raise ConfigError("end_round must be >= start_round")
    start_dt = estimate_round_timestamp(start_round, timing)
    end_dt = estimate_round_timestamp(end_round, timing)
    duration = (end_round - start_round) * timing.average_cycle_seconds
    return start_dt, end_dt, duration


def format_estimated_timestamp(dt: datetime) -> str:
    return dt.isoformat()


def empty_timing_csv_fields() -> dict[str, object]:
    return {
        "estimated_start_time": "",
        "estimated_end_time": "",
        "estimated_duration_seconds": "",
        "timezone": "",
        "timing_status": "",
    }


def timing_csv_fields_for_range(
    start_round: int,
    end_round: int,
    timing: HistoricalTiming | None,
) -> dict[str, object]:
    if timing is None:
        return empty_timing_csv_fields()
    start_dt, end_dt, duration = estimate_round_time_range(start_round, end_round, timing)
    return {
        "estimated_start_time": format_estimated_timestamp(start_dt),
        "estimated_end_time": format_estimated_timestamp(end_dt),
        "estimated_duration_seconds": duration,
        "timezone": timing.timezone_name,
        "timing_status": TIMING_STATUS_ESTIMATED,
    }


def annotate_extreme_timing(
    extreme: HistoricalExtreme,
    timing: HistoricalTiming | None,
) -> HistoricalExtreme:
    if timing is None:
        return extreme
    fields = timing_csv_fields_for_range(extreme.start_round, extreme.end_round, timing)
    return replace(
        extreme,
        estimated_start_time=str(fields["estimated_start_time"]),
        estimated_end_time=str(fields["estimated_end_time"]),
        estimated_duration_seconds=float(fields["estimated_duration_seconds"]),  # type: ignore[arg-type]
        timezone=str(fields["timezone"]),
        timing_status=str(fields["timing_status"]),
    )


def annotate_extremes_timing(
    extremes: tuple[HistoricalExtreme, ...] | list[HistoricalExtreme],
    timing: HistoricalTiming | None,
) -> tuple[HistoricalExtreme, ...]:
    return tuple(annotate_extreme_timing(e, timing) for e in extremes)


def classify_roll(roll: int) -> Outcome:
    if roll == 0:
        return "DICE"
    if 1 <= roll <= 7:
        return "ORANGE"
    if 8 <= roll <= 14:
        return "BLACK"
    raise ConfigError(f"Roll out of range: {roll}")


def generate_roll(server_seed: str, public_seed: str, round_number: int) -> HistoricalRoll:
    if round_number < 0:
        raise ConfigError("round_number must be >= 0")
    message = f"{server_seed}-{public_seed}-{round_number}"
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    prefix = digest[:8]
    roll = int(prefix, 16) % 15
    return HistoricalRoll(
        round_number=round_number,
        hash_prefix=prefix,
        roll=roll,
        outcome=classify_roll(roll),
    )


def generate_rolls(
    server_seed: str,
    public_seed: str,
    round_start: int,
    round_end: int,
) -> list[HistoricalRoll]:
    validate_seed_input(server_seed, public_seed)
    if round_end < round_start:
        raise ConfigError("round end must be >= round start")
    return [
        generate_roll(server_seed, public_seed, r)
        for r in range(round_start, round_end + 1)
    ]


def _count_outcomes(rolls: list[HistoricalRoll]) -> tuple[int, int, int]:
    dice = orange = black = 0
    for r in rolls:
        if r.outcome == "DICE":
            dice += 1
        elif r.outcome == "ORANGE":
            orange += 1
        else:
            black += 1
    return dice, orange, black


def _longest_streak(rolls: list[HistoricalRoll], outcome: Outcome) -> StreakInfo:
    best_len = 0
    best_start = rolls[0].round_number if rolls else 0
    best_end = best_start
    cur_len = 0
    cur_start = 0
    for r in rolls:
        if r.outcome == outcome:
            if cur_len == 0:
                cur_start = r.round_number
            cur_len += 1
            if cur_len > best_len:
                best_len = cur_len
                best_start = cur_start
                best_end = r.round_number
            elif cur_len == best_len and cur_start < best_start:
                best_start = cur_start
                best_end = r.round_number
        else:
            cur_len = 0
    if best_len == 0 and rolls:
        return StreakInfo(outcome, 0, rolls[0].round_number, rolls[0].round_number)
    return StreakInfo(outcome, best_len, best_start, best_end)


def _longest_same_color_streak(rolls: list[HistoricalRoll]) -> StreakInfo:
    best_len = 0
    best_start = rolls[0].round_number if rolls else 0
    best_end = best_start
    best_outcome: Outcome | str = "ORANGE"
    cur_len = 0
    cur_start = 0
    cur_outcome: Outcome | None = None
    for r in rolls:
        if r.outcome in ("ORANGE", "BLACK"):
            if cur_outcome == r.outcome:
                cur_len += 1
            else:
                cur_outcome = r.outcome
                cur_start = r.round_number
                cur_len = 1
            if cur_len > best_len or (cur_len == best_len and cur_start < best_start):
                best_len = cur_len
                best_start = cur_start
                best_end = r.round_number
                best_outcome = cur_outcome
        else:
            cur_len = 0
            cur_outcome = None
    if best_len == 0 and rolls:
        return StreakInfo("same-color", 0, rolls[0].round_number, rolls[0].round_number)
    return StreakInfo(best_outcome, best_len, best_start, best_end)


def _longest_drought(rolls: list[HistoricalRoll], missing: Outcome) -> DroughtInfo:
    best_len = 0
    best_start = rolls[0].round_number if rolls else 0
    best_end = best_start
    best_counts = (0, 0, 0)
    cur: list[HistoricalRoll] = []
    for r in rolls:
        if r.outcome != missing:
            cur.append(r)
            length = len(cur)
            if length > best_len or (
                length == best_len and cur and cur[0].round_number < best_start
            ):
                if length > best_len or (cur and cur[0].round_number < best_start):
                    best_len = length
                    best_start = cur[0].round_number
                    best_end = cur[-1].round_number
                    best_counts = _count_outcomes(cur)
        else:
            cur = []
    d, o, b = best_counts
    if best_len == 0 and rolls:
        return DroughtInfo(missing, 0, rolls[0].round_number, rolls[0].round_number, 0, 0, 0)
    return DroughtInfo(missing, best_len, best_start, best_end, d, o, b)


def drought_lengths(rolls: list[HistoricalRoll], missing: Outcome) -> list[int]:
    """Lengths of all maximal continuous sequences with no `missing` outcome."""
    return maximal_run_lengths(rolls, lambda r: r.outcome != missing)


def _window_extremes(
    rolls: list[HistoricalRoll],
    window_sizes: tuple[int, ...] = DEFAULT_WINDOW_SIZES,
) -> list[WindowExtreme]:
    n = len(rolls)
    results: list[WindowExtreme] = []
    for w in window_sizes:
        if w > n or w <= 0:
            continue
        # sliding counts
        dice = orange = black = 0
        for i in range(w):
            o = rolls[i].outcome
            if o == "DICE":
                dice += 1
            elif o == "ORANGE":
                orange += 1
            else:
                black += 1

        best: dict[tuple[Outcome, str], tuple[int, int, int]] = {}
        # (count, start_idx, end_idx) — prefer earliest start on ties

        def consider(outcome: Outcome, extremum: str, count: int, start_i: int) -> None:
            key = (outcome, extremum)
            end_i = start_i + w - 1
            prev = best.get(key)
            if prev is None:
                best[key] = (count, start_i, end_i)
                return
            prev_count, prev_start, _ = prev
            better = False
            if extremum == "highest":
                better = count > prev_count or (count == prev_count and start_i < prev_start)
            else:
                better = count < prev_count or (count == prev_count and start_i < prev_start)
            if better:
                best[key] = (count, start_i, end_i)

        consider("DICE", "highest", dice, 0)
        consider("DICE", "lowest", dice, 0)
        consider("ORANGE", "highest", orange, 0)
        consider("ORANGE", "lowest", orange, 0)
        consider("BLACK", "highest", black, 0)
        consider("BLACK", "lowest", black, 0)

        for start_i in range(1, n - w + 1):
            leaving = rolls[start_i - 1].outcome
            entering = rolls[start_i + w - 1].outcome
            for outcome, delta in ((leaving, -1), (entering, 1)):
                if outcome == "DICE":
                    dice += delta
                elif outcome == "ORANGE":
                    orange += delta
                else:
                    black += delta
            consider("DICE", "highest", dice, start_i)
            consider("DICE", "lowest", dice, start_i)
            consider("ORANGE", "highest", orange, start_i)
            consider("ORANGE", "lowest", orange, start_i)
            consider("BLACK", "highest", black, start_i)
            consider("BLACK", "lowest", black, start_i)

        for (outcome, extremum), (count, start_i, end_i) in sorted(
            best.items(), key=lambda x: (x[0][0], x[0][1])
        ):
            results.append(
                WindowExtreme(
                    window_size=w,
                    outcome=outcome,
                    extremum=extremum,  # type: ignore[arg-type]
                    count=count,
                    start_round=rolls[start_i].round_number,
                    end_round=rolls[end_i].round_number,
                )
            )
    return results


def _website_extremes(
    analysis_parts: dict[str, object],
    window_extremes: list[WindowExtreme],
) -> list[HistoricalExtreme]:
    extremes: list[HistoricalExtreme] = []

    def add_streak(label: str, s: StreakInfo) -> None:
        extremes.append(
            HistoricalExtreme(
                kind="streak",
                label=label,
                start_round=s.start_round,
                end_round=s.end_round,
                length_or_count=s.length,
            )
        )

    def add_drought(label: str, d: DroughtInfo) -> None:
        extremes.append(
            HistoricalExtreme(
                kind="drought",
                label=label,
                start_round=d.start_round,
                end_round=d.end_round,
                length_or_count=d.length,
                dice_count=d.dice_count,
                orange_count=d.orange_count,
                black_count=d.black_count,
            )
        )

    add_drought("longest DICE drought", analysis_parts["longest_dice_drought"])  # type: ignore[arg-type]
    add_streak("longest ORANGE streak", analysis_parts["longest_orange_streak"])  # type: ignore[arg-type]
    add_streak("longest BLACK streak", analysis_parts["longest_black_streak"])  # type: ignore[arg-type]
    # Legacy droughts remain on HistoricalRollAnalysis but are not primary website extremes.

    wanted = {
        (50, "DICE", "highest"): "highest-DICE 50-roll window",
    }
    for we in window_extremes:
        key = (we.window_size, we.outcome, we.extremum)
        if key in wanted:
            extremes.append(
                HistoricalExtreme(
                    kind="window",
                    label=wanted[key],
                    start_round=we.start_round,
                    end_round=we.end_round,
                    length_or_count=we.count,
                    window_size=we.window_size,
                )
            )
    return extremes


def analyze_rolls(rolls: list[HistoricalRoll]) -> HistoricalRollAnalysis:
    if not rolls:
        raise ConfigError("Cannot analyze empty roll sequence")
    dice, orange, black = _count_outcomes(rolls)
    orange_streak = _longest_streak(rolls, "ORANGE")
    black_streak = _longest_streak(rolls, "BLACK")
    dice_streak = _longest_streak(rolls, "DICE")
    same_color = _longest_same_color_streak(rolls)
    dice_drought = _longest_drought(rolls, "DICE")
    orange_drought = _longest_drought(rolls, "ORANGE")
    black_drought = _longest_drought(rolls, "BLACK")
    dice_drought_stats = summarize_run_lengths(drought_lengths(rolls, "DICE"))
    windows = _window_extremes(rolls)
    parts = {
        "longest_orange_streak": orange_streak,
        "longest_black_streak": black_streak,
        "longest_dice_drought": dice_drought,
        "longest_orange_drought": orange_drought,
        "longest_black_drought": black_drought,
    }
    website = _website_extremes(parts, windows)
    return HistoricalRollAnalysis(
        round_start=rolls[0].round_number,
        round_end=rolls[-1].round_number,
        total_rolls=len(rolls),
        dice_count=dice,
        orange_count=orange,
        black_count=black,
        longest_orange_streak=orange_streak,
        longest_black_streak=black_streak,
        longest_same_color_streak=same_color,
        longest_dice_streak=dice_streak,
        longest_dice_drought=dice_drought,
        longest_orange_drought=orange_drought,
        longest_black_drought=black_drought,
        dice_drought_count=dice_drought_stats.count,
        dice_drought_mean=dice_drought_stats.mean,
        dice_drought_median=dice_drought_stats.median,
        dice_drought_max=dice_drought_stats.maximum,
        dice_drought_p90=dice_drought_stats.p90,
        dice_drought_p95=dice_drought_stats.p95,
        dice_drought_p99=dice_drought_stats.p99,
        window_extremes=tuple(windows),
        website_extremes=tuple(website),
    )


def export_companion_dice_drought_reference(
    analysis: HistoricalAnalysis,
    path: str | Path,
    *,
    period: str = "",
) -> None:
    """Write Companion reference profile from historical replay drought stats."""
    from roulette_optimizer.dice_drought import export_dice_drought_profile

    export_dice_drought_profile(
        path=path,
        median=analysis.dice_drought_median,
        p90=analysis.dice_drought_p90,
        p95=analysis.dice_drought_p95,
        p99=analysis.dice_drought_p99,
        period=period or f"round {analysis.round_start} to {analysis.round_end}",
    )


def find_roll_extremes(rolls: list[HistoricalRoll]) -> tuple[HistoricalExtreme, ...]:
    return analyze_rolls(rolls).website_extremes


def rolls_as_dicts(rolls: list[HistoricalRoll]) -> list[dict[str, object]]:
    return [
        {
            "round": r.round_number,
            "hash_prefix": r.hash_prefix,
            "roll": r.roll,
            "outcome": r.outcome,
        }
        for r in rolls
    ]


def analysis_as_dicts(
    analysis: HistoricalRollAnalysis,
    timing: HistoricalTiming | None = None,
) -> list[dict[str, object]]:
    empty = empty_timing_csv_fields()

    def row(
        metric: str,
        value: object,
        start_round: object = "",
        end_round: object = "",
        extra: object = "",
        *,
        with_timing: bool = False,
    ) -> dict[str, object]:
        base: dict[str, object] = {
            "metric": metric,
            "value": value,
            "start_round": start_round,
            "end_round": end_round,
            "extra": extra,
        }
        if with_timing and isinstance(start_round, int) and isinstance(end_round, int):
            base.update(timing_csv_fields_for_range(start_round, end_round, timing))
        else:
            base.update(empty)
        return base

    rows: list[dict[str, object]] = [
        row("total_rolls", analysis.total_rolls, analysis.round_start, analysis.round_end),
        row("dice_count", analysis.dice_count, extra=f"pct={analysis.dice_count / analysis.total_rolls}"),
        row("orange_count", analysis.orange_count, extra=f"pct={analysis.orange_count / analysis.total_rolls}"),
        row("black_count", analysis.black_count, extra=f"pct={analysis.black_count / analysis.total_rolls}"),
        row("dice_theoretical", analysis.total_rolls / 15, extra="1/15"),
        row("orange_theoretical", analysis.total_rolls * 7 / 15, extra="7/15"),
        row("black_theoretical", analysis.total_rolls * 7 / 15, extra="7/15"),
    ]
    for name, streak in (
        ("longest_orange_streak", analysis.longest_orange_streak),
        ("longest_black_streak", analysis.longest_black_streak),
        ("longest_same_color_streak", analysis.longest_same_color_streak),
        ("longest_dice_streak", analysis.longest_dice_streak),
    ):
        rows.append(
            row(
                name,
                streak.length,
                streak.start_round,
                streak.end_round,
                streak.outcome,
                with_timing=True,
            )
        )
    for name, drought in (
        ("longest_dice_drought", analysis.longest_dice_drought),
        ("longest_orange_drought", analysis.longest_orange_drought),
        ("longest_black_drought", analysis.longest_black_drought),
    ):
        rows.append(
            row(
                name,
                drought.length,
                drought.start_round,
                drought.end_round,
                (
                    f"dice={drought.dice_count};orange={drought.orange_count};"
                    f"black={drought.black_count}"
                ),
                with_timing=True,
            )
        )
    for metric, value in (
        ("dice_drought_count", analysis.dice_drought_count),
        ("dice_drought_mean", analysis.dice_drought_mean),
        ("dice_drought_median", analysis.dice_drought_median),
        ("dice_drought_max", analysis.dice_drought_max),
        ("dice_drought_p90", analysis.dice_drought_p90),
        ("dice_drought_p95", analysis.dice_drought_p95),
        ("dice_drought_p99", analysis.dice_drought_p99),
    ):
        rows.append(row(metric, "" if value is None else value))
    return rows


def extremes_as_dicts(
    extremes: tuple[HistoricalExtreme, ...] | list[HistoricalExtreme],
    timing: HistoricalTiming | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for e in extremes:
        annotated = annotate_extreme_timing(e, timing)
        rows.append(
            {
                "kind": annotated.kind,
                "label": annotated.label,
                "window_size": annotated.window_size if annotated.window_size is not None else "",
                "length_or_count": annotated.length_or_count,
                "start_round": annotated.start_round,
                "end_round": annotated.end_round,
                "dice_count": annotated.dice_count if annotated.dice_count is not None else "",
                "orange_count": annotated.orange_count if annotated.orange_count is not None else "",
                "black_count": annotated.black_count if annotated.black_count is not None else "",
                "estimated_start_time": annotated.estimated_start_time or "",
                "estimated_end_time": annotated.estimated_end_time or "",
                "estimated_duration_seconds": (
                    annotated.estimated_duration_seconds
                    if annotated.estimated_duration_seconds is not None
                    else ""
                ),
                "timezone": annotated.timezone or "",
                "timing_status": annotated.timing_status or "",
            }
        )
    return rows


def default_rolls_csv_path(round_start: int, round_end: int) -> str:
    return f"outputs/replay_{round_start}_{round_end}_rolls.csv"


def default_analysis_csv_path(round_start: int, round_end: int) -> str:
    return f"outputs/replay_{round_start}_{round_end}_analysis.csv"


def default_extremes_csv_path(round_start: int, round_end: int) -> str:
    return f"outputs/replay_{round_start}_{round_end}_extremes.csv"
