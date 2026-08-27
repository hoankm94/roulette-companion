from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from roulette_optimizer.actions import Action, legal_actions
from roulette_optimizer.config import GameConfig, SessionConfig, session_to_dict, validate_session
from roulette_optimizer.game import next_bankrolls
from roulette_optimizer.policy_verifier import VerificationResult
from roulette_optimizer.solver import PolicyDecision, SolverResult
from roulette_optimizer.state_space import build_state_space
from roulette_optimizer.utils import PolicyError


def count_policy_actions(result: SolverResult, session: SessionConfig) -> tuple[int, int, int]:
    ss = build_state_space(session)
    color = dice = none = 0
    for b in ss.nonterminal:
        d = result.policy[b]
        if d.action is None:
            none += 1
        elif d.action.bet_type == "COLOR":
            color += 1
        else:
            dice += 1
    return color, dice, none


def export_policy_json(
    path: str | Path,
    session: SessionConfig,
    game: GameConfig,
    result: SolverResult,
    verification: VerificationResult,
) -> None:
    policy_map: dict[str, dict[str, Any]] = {}
    for b, d in result.policy.items():
        policy_map[str(b)] = {
            "bet_type": None if d.action is None else d.action.bet_type,
            "stake": None if d.action is None else d.action.stake,
            "value": result.values[b],
            "win_bankroll": d.win_bankroll,
            "lose_bankroll": d.lose_bankroll,
        }
    payload = {
        "game": {
            "color_win_probability": game.color_win_probability,
            "dice_win_probability": game.dice_win_probability,
            "color_net_multiplier": game.color_net_multiplier,
            "dice_net_multiplier": game.dice_net_multiplier,
        },
        "session": session_to_dict(session),
        "solver": {
            "converged": result.converged,
            "iterations": result.iterations,
            "final_delta": result.final_delta,
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
        "deterministic_status": "VALID",
        "starting_target_probability": result.values[session.starting_bankroll],
        "policy": policy_map,
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def format_policy_table(
    result: SolverResult,
    session: SessionConfig,
    from_bankroll: int | None = None,
    to_bankroll: int | None = None,
) -> str:
    lo = session.floor_bankroll if from_bankroll is None else from_bankroll
    hi = session.target_bankroll if to_bankroll is None else to_bankroll
    lines = [
        f"{'BANKROLL':<10}{'ACTION':<8}{'STAKE':<8}{'WIN_TO':<10}{'LOSS_TO':<10}{'TARGET_PROB'}"
    ]
    for b in sorted(result.policy):
        if b < lo or b > hi:
            continue
        d = result.policy[b]
        if b <= session.floor_bankroll:
            lines.append(f"{b:<10}{'STOP':<8}{'-':<8}{'-':<10}{'-':<10}{0.0:.6f}")
        elif b >= session.target_bankroll:
            lines.append(f"{b:<10}{'TARGET':<8}{'-':<8}{'-':<10}{'-':<10}{1.0:.6f}")
        elif d.action is None:
            lines.append(
                f"{b:<10}{'NONE':<8}{'-':<8}{'-':<10}{'-':<10}{d.success_probability:.6f}"
            )
        else:
            lines.append(
                f"{b:<10}{d.action.bet_type:<8}{d.action.stake:<8}"
                f"{d.win_bankroll:<10}{d.lose_bankroll:<10}{d.success_probability:.6f}"
            )
    return "\n".join(lines)


@dataclass(frozen=True)
class LoadedPolicy:
    session: SessionConfig
    game: GameConfig
    converged: bool
    deterministic_status: str
    policy: dict[int, PolicyDecision]

    def loss_durability_table(self) -> dict[int, int]:
        """Precomputed consecutive-loss durability for every policy bankroll."""
        cached = getattr(self, "_loss_durability_table", None)
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        table = precompute_consecutive_loss_durability(self)
        object.__setattr__(self, "_loss_durability_table", table)
        return table


@dataclass(frozen=True)
class Recommendation:
    bankroll: int
    status: str
    bet_type: str | None
    stake: int | None
    win_bankroll: int | None
    lose_bankroll: int | None
    target_hit_probability: float
    session: SessionConfig
    consecutive_loss_durability: int = 0


_VERIFICATION_BOOLS = (
    "policy_evaluation_passed",
    "bellman_passed",
    "linear_value_bellman_passed",
    "legal_actions_passed",
)


def _require_object(data: Any, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PolicyError(f"Policy has wrong structure: {label} must be an object")
    return data


def _session_from_dict(raw: dict[str, Any]) -> SessionConfig:
    allowed = {f.name for f in fields(SessionConfig)}
    filtered = {k: v for k, v in raw.items() if k in allowed}
    try:
        session = SessionConfig(**filtered)
        validate_session(session)
    except TypeError as exc:
        raise PolicyError(f"Policy session is missing required fields: {exc}") from exc
    except Exception as exc:
        raise PolicyError(f"Policy session is invalid: {exc}") from exc
    return session


def _game_from_dict(raw: dict[str, Any]) -> GameConfig:
    allowed = {f.name for f in fields(GameConfig)}
    filtered = {k: v for k, v in raw.items() if k in allowed}
    try:
        return GameConfig(**filtered)
    except TypeError as exc:
        raise PolicyError(f"Policy game is missing required fields: {exc}") from exc


def _parse_decision(bankroll: int, entry: Any) -> PolicyDecision:
    if not isinstance(entry, dict):
        raise PolicyError(f"Malformed policy decision at bankroll {bankroll}")
    bet_type = entry.get("bet_type")
    stake = entry.get("stake")
    value = entry.get("value")
    win_bankroll = entry.get("win_bankroll")
    lose_bankroll = entry.get("lose_bankroll")
    if not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
        raise PolicyError(
            f"Malformed policy decision at bankroll {bankroll}: "
            "value must be numeric in [0, 1]"
        )
    if bet_type is None and stake is None:
        return PolicyDecision(bankroll, None, float(value), None, None)
    if bet_type in ("COLOR", "DICE") and isinstance(stake, int):
        action = Action(bet_type, stake)
    else:
        raise PolicyError(f"Malformed policy decision at bankroll {bankroll}")
    if not isinstance(win_bankroll, int) or not isinstance(lose_bankroll, int):
        raise PolicyError(f"Malformed policy decision at bankroll {bankroll}")
    return PolicyDecision(bankroll, action, float(value), win_bankroll, lose_bankroll)


def load_policy(path: str | Path) -> LoadedPolicy:
    p = Path(path)
    if not p.exists():
        raise PolicyError(f"Policy file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"Policy file is unreadable: {p}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"Policy file is invalid JSON: {p}") from exc
    data = _require_object(data, "root")

    for key in ("game", "session", "solver", "verification", "policy"):
        if key not in data:
            raise PolicyError(f"Policy is missing required field: {key}")

    session = _session_from_dict(_require_object(data["session"], "session"))
    game = _game_from_dict(_require_object(data["game"], "game"))
    solver = _require_object(data["solver"], "solver")
    verification = _require_object(data["verification"], "verification")
    policy_raw = _require_object(data["policy"], "policy")

    if not solver.get("converged"):
        raise PolicyError("Policy solver did not converge.")

    if data.get("deterministic_status") != "VALID":
        raise PolicyError("Policy is not verified VALID.")

    for flag in _VERIFICATION_BOOLS:
        if verification.get(flag) is not True:
            raise PolicyError("Policy is not verified VALID.")

    policy: dict[int, PolicyDecision] = {}
    for key, entry in policy_raw.items():
        try:
            bankroll = int(key)
        except (TypeError, ValueError) as exc:
            raise PolicyError(f"Malformed policy bankroll key: {key!r}") from exc
        policy[bankroll] = _parse_decision(bankroll, entry)

    return LoadedPolicy(
        session=session,
        game=game,
        converged=bool(solver["converged"]),
        deterministic_status="VALID",
        policy=policy,
    )


def precompute_consecutive_loss_durability(loaded: LoadedPolicy) -> dict[int, int]:
    """Durability[B] = 0 at FLOOR/TARGET/NO_ACTION; else 1 + durability[lose_bankroll].

    Loss transitions strictly decrease bankroll, so ascending bankroll order is safe.
    """
    session = loaded.session
    floor = session.floor_bankroll
    target = session.target_bankroll
    durability: dict[int, int] = {}
    for b in sorted(loaded.policy.keys()):
        if b <= floor or b >= target:
            durability[b] = 0
            continue
        decision = loaded.policy[b]
        if decision.action is None or decision.lose_bankroll is None:
            durability[b] = 0
            continue
        lose_b = decision.lose_bankroll
        durability[b] = 1 + durability.get(lose_b, 0)
    return durability


def consecutive_loss_durability(
    loaded: LoadedPolicy,
    bankroll: int,
    *,
    table: dict[int, int] | None = None,
) -> int:
    """Look up precomputed consecutive-loss durability for a bankroll."""
    t = table if table is not None else loaded.loss_durability_table()
    if bankroll in t:
        return t[bankroll]
    if bankroll <= loaded.session.floor_bankroll or bankroll >= loaded.session.target_bankroll:
        return 0
    raise PolicyError(f"Bankroll {bankroll} is not present in this policy state space.")


def consecutive_loss_durability_traverse(loaded: LoadedPolicy, bankroll: int) -> int:
    """Direct loss-chain traversal (test oracle; not used on hot replay paths)."""
    session = loaded.session
    floor = session.floor_bankroll
    target = session.target_bankroll
    count = 0
    b = bankroll
    seen: set[int] = set()
    while True:
        if b in seen:
            raise PolicyError(f"Loss cycle detected at bankroll {b}")
        seen.add(b)
        if b <= floor or b >= target:
            return count
        if b not in loaded.policy:
            raise PolicyError(f"Bankroll {b} is not present in this policy state space.")
        decision = loaded.policy[b]
        if decision.action is None or decision.lose_bankroll is None:
            return count
        count += 1
        b = decision.lose_bankroll


def recommend_from_policy(loaded: LoadedPolicy, bankroll: int) -> Recommendation:
    session = loaded.session
    game = loaded.game

    if bankroll not in loaded.policy:
        raise PolicyError(f"Bankroll {bankroll} is not present in this policy state space.")

    durability = consecutive_loss_durability(loaded, bankroll)
    decision = loaded.policy[bankroll]
    value = decision.success_probability

    if bankroll <= session.floor_bankroll:
        return Recommendation(
            bankroll=bankroll,
            status="FLOOR",
            bet_type=None,
            stake=None,
            win_bankroll=None,
            lose_bankroll=None,
            target_hit_probability=0.0,
            session=session,
            consecutive_loss_durability=0,
        )

    if bankroll >= session.target_bankroll:
        return Recommendation(
            bankroll=bankroll,
            status="TARGET",
            bet_type=None,
            stake=None,
            win_bankroll=None,
            lose_bankroll=None,
            target_hit_probability=1.0,
            session=session,
            consecutive_loss_durability=0,
        )

    legal = legal_actions(bankroll, session)
    if decision.action is None:
        if legal:
            raise PolicyError(
                f"Policy action at bankroll {bankroll} is illegal under the stored configuration."
            )
        return Recommendation(
            bankroll=bankroll,
            status="NO_ACTION",
            bet_type=None,
            stake=None,
            win_bankroll=None,
            lose_bankroll=None,
            target_hit_probability=value,
            session=session,
            consecutive_loss_durability=0,
        )

    action = decision.action
    if action.bet_type not in ("COLOR", "DICE"):
        raise PolicyError(
            f"Policy action at bankroll {bankroll} is illegal under the stored configuration."
        )
    if action not in legal:
        raise PolicyError(
            f"Policy action at bankroll {bankroll} is illegal under the stored configuration."
        )

    expected_win, expected_lose = next_bankrolls(bankroll, action, game)
    if expected_lose < session.floor_bankroll:
        raise PolicyError(
            f"Policy action at bankroll {bankroll} is illegal under the stored configuration."
        )
    if decision.win_bankroll != expected_win or decision.lose_bankroll != expected_lose:
        raise PolicyError(
            f"Policy transition at bankroll {bankroll} is inconsistent with the game rules."
        )

    return Recommendation(
        bankroll=bankroll,
        status="ACTION",
        bet_type=action.bet_type,
        stake=action.stake,
        win_bankroll=decision.win_bankroll,
        lose_bankroll=decision.lose_bankroll,
        target_hit_probability=float(value),
        session=session,
        consecutive_loss_durability=durability,
    )
