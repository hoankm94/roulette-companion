"""Exact DICE drought survival analysis over a frozen policy (no re-solve)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roulette_optimizer.policy import LoadedPolicy
from roulette_optimizer.utils import PolicyError

DEFAULT_SURVIVAL_THRESHOLD = 0.95
SAFETY_CAP_ROUNDS = 10_000

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = _PROJECT_ROOT / "outputs" / "reference" / "dice_drought_profile.json"


@dataclass(frozen=True)
class DiceDroughtProfile:
    source: str
    period: str
    median: int
    p90: int
    p95: int
    p99: int


@dataclass(frozen=True)
class DiceDroughtAnalysis:
    dice_drought_durability: int
    survival_threshold: float
    survival_at_p90: float
    survival_at_p95: float
    survival_at_p99: float
    capped: bool = False


def load_dice_drought_profile(path: Path | str | None = None) -> DiceDroughtProfile:
    p = Path(path) if path is not None else DEFAULT_PROFILE_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    return DiceDroughtProfile(
        source=str(raw["source"]),
        period=str(raw["period"]),
        median=int(raw["median"]),
        p90=int(raw["p90"]),
        p95=int(raw["p95"]),
        p99=int(raw["p99"]),
    )


def export_dice_drought_profile(
    *,
    path: Path | str,
    median: float | int | None,
    p90: float | int | None,
    p95: float | int | None,
    p99: float | int | None,
    source: str = "historical replay",
    period: str = "",
) -> None:
    payload = {
        "source": source,
        "period": period,
        "median": 0 if median is None else int(round(float(median))),
        "p90": 0 if p90 is None else int(round(float(p90))),
        "p95": 0 if p95 is None else int(round(float(p95))),
        "p99": 0 if p99 is None else int(round(float(p99))),
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _survival_mass(dist: dict[int, float], floor: int) -> float:
    total = 0.0
    for b, p in dist.items():
        if p <= 0.0:
            continue
        if b > floor:
            total += p
    return total


def no_dice_step(loaded: LoadedPolicy, dist: dict[int, float]) -> dict[int, float]:
    """One conditional no-DICE round forward over a bankroll probability mass."""
    floor = loaded.session.floor_bankroll
    target = loaded.session.target_bankroll
    next_dist: dict[int, float] = {}

    for b, p in dist.items():
        if p <= 0.0:
            continue
        if b <= floor:
            continue
        if b >= target:
            next_dist[b] = next_dist.get(b, 0.0) + p
            continue
        if b not in loaded.policy:
            raise PolicyError(f"Bankroll {b} is not present in this policy state space.")
        decision = loaded.policy[b]
        if decision.action is None:
            next_dist[b] = next_dist.get(b, 0.0) + p
        elif decision.action.bet_type == "DICE":
            lose_b = decision.lose_bankroll
            if lose_b is None:
                raise PolicyError(f"Missing lose successor at bankroll {b}")
            next_dist[lose_b] = next_dist.get(lose_b, 0.0) + p
        elif decision.action.bet_type == "COLOR":
            win_b = decision.win_bankroll
            lose_b = decision.lose_bankroll
            if win_b is None or lose_b is None:
                raise PolicyError(f"Missing successors at bankroll {b}")
            next_dist[win_b] = next_dist.get(win_b, 0.0) + 0.5 * p
            next_dist[lose_b] = next_dist.get(lose_b, 0.0) + 0.5 * p
        else:
            raise PolicyError(f"Unknown bet type at bankroll {b}")

    return next_dist


def survival_at_round(
    loaded: LoadedPolicy,
    starting_bankroll: int,
    rounds: int,
    *,
    initial_dist: dict[int, float] | None = None,
) -> float:
    """S(k, B) — survival probability after k no-DICE rounds from starting bankroll."""
    session = loaded.session
    floor = session.floor_bankroll
    if rounds <= 0:
        return 1.0 if starting_bankroll > floor else 0.0

    dist = (
        initial_dist
        if initial_dist is not None
        else {starting_bankroll: 1.0}
    )
    for _ in range(rounds):
        dist = no_dice_step(loaded, dist)
    return _survival_mass(dist, floor)


def dice_drought_survival_curve(
    loaded: LoadedPolicy,
    starting_bankroll: int,
    *,
    max_rounds: int = SAFETY_CAP_ROUNDS,
) -> list[float]:
    """S(k) for k = 0..max_rounds inclusive, carried forward without recomputation."""
    session = loaded.session
    floor = session.floor_bankroll
    curve: list[float] = []
    dist: dict[int, float] = {starting_bankroll: 1.0}
    for _ in range(max_rounds + 1):
        curve.append(_survival_mass(dist, floor))
        dist = no_dice_step(loaded, dist)
    return curve


def durability_from_curve(
    curve: list[float],
    *,
    threshold: float = DEFAULT_SURVIVAL_THRESHOLD,
) -> tuple[int, bool]:
    """Largest k with S(k) >= threshold; capped=True if threshold never crossed."""
    if not curve:
        return 0, False
    if curve[0] < threshold:
        return 0, False
    for k in range(1, len(curve)):
        if curve[k] < threshold:
            return k - 1, False
    return len(curve) - 1, True


def analyze_dice_drought_durability(
    loaded: LoadedPolicy,
    starting_bankroll: int,
    *,
    profile: DiceDroughtProfile | None = None,
    threshold: float = DEFAULT_SURVIVAL_THRESHOLD,
    max_rounds: int = SAFETY_CAP_ROUNDS,
) -> DiceDroughtAnalysis:
    profile = profile or load_dice_drought_profile()
    curve = dice_drought_survival_curve(loaded, starting_bankroll, max_rounds=max_rounds)
    durability, capped = durability_from_curve(curve, threshold=threshold)
    return DiceDroughtAnalysis(
        dice_drought_durability=durability,
        survival_threshold=threshold,
        survival_at_p90=curve[profile.p90] if profile.p90 < len(curve) else curve[-1],
        survival_at_p95=curve[profile.p95] if profile.p95 < len(curve) else curve[-1],
        survival_at_p99=curve[profile.p99] if profile.p99 < len(curve) else curve[-1],
        capped=capped,
    )


def companion_dice_drought_payload(
    loaded: LoadedPolicy,
    bankroll: int,
    *,
    profile: DiceDroughtProfile | None = None,
) -> dict[str, Any]:
    analysis = analyze_dice_drought_durability(loaded, bankroll, profile=profile)
    profile = profile or load_dice_drought_profile()
    payload: dict[str, Any] = {
        "dice_drought_durability": analysis.dice_drought_durability,
        "dice_drought_survival_threshold": analysis.survival_threshold,
        "dice_drought_survival_at_p90": analysis.survival_at_p90,
        "dice_drought_survival_at_p95": analysis.survival_at_p95,
        "dice_drought_survival_at_p99": analysis.survival_at_p99,
        "historical_dice_drought_median": profile.median,
        "historical_dice_drought_p90": profile.p90,
        "historical_dice_drought_p95": profile.p95,
        "historical_dice_drought_p99": profile.p99,
    }
    if analysis.capped:
        payload["dice_drought_durability_capped"] = True
    return payload
