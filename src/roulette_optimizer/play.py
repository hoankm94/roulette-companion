from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from roulette_optimizer.actions import Action
from roulette_optimizer.config import GameConfig, SessionConfig, validate_session
from roulette_optimizer.game import next_bankrolls
from roulette_optimizer.policy import (
    LoadedPolicy,
    Recommendation,
    consecutive_loss_durability,
    recommend_from_policy,
)
from roulette_optimizer.saved_session import (
    SavedLiveSession,
    SessionSource,
    terminal_status_for_save,
    utc_now_iso,
)
from roulette_optimizer.policy_verifier import verify_policy
from roulette_optimizer.solver import SolverResult, solve
from roulette_optimizer.utils import ConfigError, PolicyError

ManualOutcome = Literal["WIN", "LOSS"]
ResultOutcome = Literal["DICE", "ORANGE", "BLACK"]
LiveSessionStatus = Literal[
    "PREPARING",
    "READY",
    "WAITING_FOR_WAGER",
    "ROUND_PENDING",
    "WAITING_FOR_RESULT",
    "RECONCILING",
    "DESYNCED",
    "TARGET",
    "FLOOR",
    "NO_ACTION",
    "USER_STOPPED",
    "ERROR",
]

TERMINAL_STATUSES = frozenset(
    {"TARGET", "FLOOR", "NO_ACTION", "USER_STOPPED", "ERROR"}
)
COLOR_EXECUTION_SIDES = frozenset({"ORANGE", "BLACK"})


@dataclass
class PlayOutcome:
    status: str  # CONTINUE | TARGET | FLOOR | NO_ACTION | QUIT | ERROR | companion statuses
    bankroll: int
    rounds_completed: int
    recommendation: Recommendation | None = None
    message: str | None = None


@dataclass
class LiveSessionError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def loaded_policy_from_result(
    session: SessionConfig,
    game: GameConfig,
    result: SolverResult,
) -> LoadedPolicy:
    return LoadedPolicy(
        session=session,
        game=game,
        converged=result.converged,
        deterministic_status="VALID",
        policy=result.policy,
    )


def initialize_play_policy(
    *,
    policy_path: str | None = None,
    bankroll: int | None = None,
    target: int | None = None,
    floor: int | None = None,
    solver: str | None = None,
    solve_fn: Callable[..., SolverResult] | None = None,
    use_cache: bool = True,
):
    """Load or solve-once a verified policy.

    Returns (loaded, solve_call_count) or with cache:
    (loaded, solve_call_count, cache_status, timings) when use_cache and no policy file.
    For backward compatibility the 2-tuple form is preserved when solve_fn is injected
    or use_cache is False.
    """
    if policy_path is not None:
        if target is not None or floor is not None or solver is not None:
            raise PolicyError(
                "Do not combine --policy with --target, --floor, or --solver"
            )
        if bankroll is None:
            raise PolicyError("Missing --bankroll")
        from roulette_optimizer.policy import load_policy

        return load_policy(policy_path), 0

    if bankroll is None or target is None or floor is None:
        raise PolicyError(
            "Solve mode requires --bankroll, --target, and --floor "
            "(or provide --policy)"
        )
    session = SessionConfig(
        starting_bankroll=bankroll,
        target_bankroll=target,
        floor_bankroll=floor,
    )
    try:
        validate_session(session)
    except ConfigError as exc:
        raise PolicyError(str(exc)) from exc
    game = GameConfig()
    from roulette_optimizer.policy_cache import resolve_production_solver, solve_and_cache

    solver_name = resolve_production_solver(solver)

    if solve_fn is not None or not use_cache:
        fn = solve_fn or solve
        result = fn(session, game, solver=solver_name)
        verify_policy(result, session, game)
        return loaded_policy_from_result(session, game, result), 1

    hit = solve_and_cache(session, game, solver=solver_name)
    return hit.loaded, hit.solve_calls


def normalize_play_input(raw: str) -> str | None:
    token = raw.strip().lower()
    if token in ("w", "l", "q"):
        return token
    return None


def format_play_prompt(rec: Recommendation, round_number: int) -> str:
    session = rec.session
    return "\n".join(
        [
            "Dynamic Goal-Directed Play",
            "",
            f"Round:              {round_number}",
            f"Current bankroll:   {rec.bankroll}",
            f"Target:             {session.target_bankroll}",
            f"Floor:               {session.floor_bankroll}",
            f"Target probability: {rec.target_hit_probability}",
            f"Loss durability:    {rec.consecutive_loss_durability}",
            "",
            "Recommended:",
            f"{rec.bet_type} {rec.stake}",
            "",
            f"If win:             {rec.win_bankroll}",
            f"If loss:             {rec.lose_bankroll}",
            "",
            "Result [w/l/q]:",
        ]
    )


def format_play_terminal(status: str, bankroll: int, rounds_completed: int) -> str:
    labels = {
        "TARGET": "TARGET REACHED",
        "FLOOR": "FLOOR REACHED",
        "NO_ACTION": "NO ACTION AVAILABLE",
        "QUIT": "SESSION QUIT",
        "USER_STOPPED": "SESSION QUIT",
    }
    title = labels.get(status, status)
    return "\n".join(
        [
            title,
            f"Current bankroll:   {bankroll}",
            f"Completed rounds:   {rounds_completed}",
        ]
    )


@dataclass
class PlayRoundRecord:
    round_number: int
    bankroll_before: int
    bet_type: str | None
    stake: int | None
    outcome: str
    bankroll_after: int
    website_round_id: str | None = None
    recommended_bet_type: str | None = None
    recommended_stake: int | None = None
    color_side: str | None = None
    result_outcome: str | None = None
    expected_bankroll_after: int | None = None


def _normalize_wager_type(
    bet_type: str, color_side: str | None = None
) -> tuple[str, str | None]:
    if bet_type in COLOR_EXECUTION_SIDES:
        return "COLOR", bet_type
    return bet_type, color_side


def _wagers_match(
    recommended: Recommendation,
    actual_bet_type: str,
    actual_stake: int,
    color_side: str | None,
) -> bool:
    norm_type, norm_side = _normalize_wager_type(actual_bet_type, color_side)
    if recommended.bet_type != norm_type or recommended.stake != actual_stake:
        return False
    if norm_type == "COLOR" and recommended.bet_type == "COLOR":
        return True
    return True


def _resolve_outcome(
    bet_type: str,
    color_side: str | None,
    result: ResultOutcome,
) -> ManualOutcome:
    if bet_type == "DICE":
        return "WIN" if result == "DICE" else "LOSS"
    side = color_side
    if bet_type in COLOR_EXECUTION_SIDES:
        side = bet_type
    if side is None:
        raise LiveSessionError("missing_color_side", "COLOR wager requires a side")
    return "WIN" if result == side else "LOSS"


class LiveSession:
    """Shared live session engine for Manual Live Play and Edge Companion."""

    def __init__(
        self,
        loaded: LoadedPolicy,
        bankroll: int,
        *,
        source: SessionSource = "MANUAL",
        session_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.loaded = loaded
        self.bankroll = bankroll
        self.source = source
        self.status: LiveSessionStatus = "READY"
        self.current_recommendation: Recommendation | None = None
        self.rounds_completed = 0
        self.started_at = utc_now_iso()
        self.ended_at: str | None = None
        self.round_history: list[PlayRoundRecord] = []
        self.events: list[dict[str, Any]] = [
            {
                "kind": "session_start",
                "at": self.started_at,
                "bankroll": bankroll,
                "target": loaded.session.target_bankroll,
                "floor": loaded.session.floor_bankroll,
                "source": source,
            },
            {
                "kind": "policy_loaded",
                "at": self.started_at,
            },
        ]
        self.initial_loss_durability = consecutive_loss_durability(loaded, bankroll)
        self._active_round_id: str | None = None
        self._wager_round_ids: set[str] = set()
        self._result_round_ids: set[str] = set()
        self._pending_round: dict[str, Any] | None = None
        self._expected_bankroll: int | None = None

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES or self.ended_at is not None

    def _api_status(self) -> str:
        if self.status in ("WAITING_FOR_WAGER", "ROUND_PENDING"):
            return "CONTINUE"
        if self.status == "USER_STOPPED":
            return "QUIT"
        return self.status

    def _outcome(
        self,
        recommendation: Recommendation | None = None,
        message: str | None = None,
    ) -> PlayOutcome:
        api_status = self._api_status()
        rec = recommendation
        if rec is None and api_status == "CONTINUE":
            rec = self.current_recommendation
        return PlayOutcome(
            api_status,
            self.bankroll,
            self.rounds_completed,
            rec,
            message,
        )

    def _append_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def _mark_terminal(self, status: LiveSessionStatus) -> None:
        self.status = status
        if self.ended_at is None:
            self.ended_at = utc_now_iso()
            self._append_event(
                {
                    "kind": "terminal",
                    "at": self.ended_at,
                    "status": terminal_status_for_save(status),
                    "bankroll": self.bankroll,
                    "rounds_completed": self.rounds_completed,
                }
            )
        self.current_recommendation = None
        self._clear_active_round()

    def _clear_active_round(self) -> None:
        self._active_round_id = None
        self._pending_round = None
        self._expected_bankroll = None

    def _terminal_from_bankroll(self) -> PlayOutcome | None:
        session = self.loaded.session
        if self.bankroll >= session.target_bankroll:
            self._mark_terminal("TARGET")
            return self._outcome()
        if self.bankroll <= session.floor_bankroll:
            self._mark_terminal("FLOOR")
            return self._outcome()
        return None

    def _terminal_from_recommendation(self, rec: Recommendation) -> PlayOutcome | None:
        if rec.status == "TARGET":
            self._mark_terminal("TARGET")
            return self._outcome(rec)
        if rec.status == "FLOOR":
            self._mark_terminal("FLOOR")
            return self._outcome(rec)
        if rec.status == "NO_ACTION":
            self._mark_terminal("NO_ACTION")
            return self._outcome(rec)
        return None

    def _validate_recommendation(self, rec: Recommendation) -> None:
        session = self.loaded.session
        if rec.win_bankroll is None or rec.lose_bankroll is None:
            raise PolicyError("Recommendation missing transitions")
        if rec.lose_bankroll < session.floor_bankroll:
            raise PolicyError(
                f"Corrupt transition below floor at bankroll {self.bankroll}"
            )

    def get_recommendation(self) -> PlayOutcome:
        if self.is_terminal():
            return self._outcome()
        terminal = self._terminal_from_bankroll()
        if terminal is not None:
            return terminal
        rec = recommend_from_policy(self.loaded, self.bankroll)
        terminal = self._terminal_from_recommendation(rec)
        if terminal is not None:
            return terminal
        self._validate_recommendation(rec)
        self.current_recommendation = rec
        self.status = "WAITING_FOR_WAGER"
        self._append_event(
            {
                "kind": "recommendation",
                "at": utc_now_iso(),
                "bankroll": self.bankroll,
                "bet_type": rec.bet_type,
                "stake": rec.stake,
                "win_bankroll": rec.win_bankroll,
                "lose_bankroll": rec.lose_bankroll,
            }
        )
        return self._outcome(rec)

    def begin_round(self) -> PlayOutcome:
        return self.get_recommendation()

    def apply_manual_outcome(self, outcome: ManualOutcome) -> PlayOutcome:
        if self.source != "MANUAL":
            raise LiveSessionError(
                "manual_only", "Manual outcomes are only valid for MANUAL sessions"
            )
        if self.status != "WAITING_FOR_WAGER":
            raise LiveSessionError(
                "invalid_state",
                f"Cannot apply manual outcome while status is {self.status}",
            )
        pending = self.current_recommendation
        if pending is None:
            raise PolicyError("No pending recommendation")
        bankroll_before = self.bankroll
        if outcome == "WIN":
            assert pending.win_bankroll is not None
            self.bankroll = pending.win_bankroll
            outcome_label = "WIN"
        else:
            assert pending.lose_bankroll is not None
            self.bankroll = pending.lose_bankroll
            outcome_label = "LOSS"
        self.rounds_completed += 1
        record = PlayRoundRecord(
            round_number=self.rounds_completed,
            bankroll_before=bankroll_before,
            bet_type=pending.bet_type,
            stake=pending.stake,
            outcome=outcome_label,
            bankroll_after=self.bankroll,
            recommended_bet_type=pending.bet_type,
            recommended_stake=pending.stake,
        )
        self.round_history.append(record)
        self._append_event(
            {
                "kind": "manual_outcome",
                "at": utc_now_iso(),
                "round": record.round_number,
                "bankroll_before": record.bankroll_before,
                "bet_type": record.bet_type,
                "stake": record.stake,
                "outcome": record.outcome,
                "bankroll_after": record.bankroll_after,
            }
        )
        self.current_recommendation = None
        return self.get_recommendation()

    def apply_input(self, raw: str) -> PlayOutcome:
        token = normalize_play_input(raw)
        if token is None:
            return self._outcome(message="Invalid input. Enter w, l, or q.")
        if token == "q":
            return self.stop_session()
        if token == "w":
            return self.apply_manual_outcome("WIN")
        return self.apply_manual_outcome("LOSS")

    def register_wager_deduction(self, observed_bankroll: int) -> PlayOutcome:
        """Bankroll-driven wager detection (READY/WAITING_FOR_WAGER → ROUND_PENDING)."""
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")
        if self.status == "DESYNCED":
            raise LiveSessionError("desynced", "Session is paused due to desync")
        if self.status != "WAITING_FOR_WAGER":
            raise LiveSessionError(
                "invalid_state",
                f"Cannot register wager deduction while status is {self.status}",
            )
        pending = self.current_recommendation
        if pending is None or pending.stake is None or pending.bet_type is None:
            raise LiveSessionError("no_recommendation", "No active recommendation")

        pre = self.bankroll
        stake = pending.stake
        expected_post = pre - stake

        if observed_bankroll == pre:
            return self._outcome()

        if observed_bankroll > pre:
            # Unexpected increase under Companion operating rule — resync if on-policy.
            try:
                self.bankroll = observed_bankroll
                self._append_event(
                    {
                        "kind": "external_bankroll_increase",
                        "at": utc_now_iso(),
                        "previous_bankroll": pre,
                        "observed_bankroll": observed_bankroll,
                    }
                )
                outcome = self.get_recommendation()
                outcome.message = (
                    "Unexpected balance increase — resynced recommendation."
                )
                return outcome
            except PolicyError:
                self.bankroll = pre
                self.status = "DESYNCED"
                self._append_event(
                    {
                        "kind": "bankroll_ambiguous",
                        "at": utc_now_iso(),
                        "observed_bankroll": observed_bankroll,
                    }
                )
                return self._outcome(
                    message="Balance change cannot be trusted — session paused."
                )

        if observed_bankroll < 0:
            raise LiveSessionError("invalid_bankroll", "Observed bankroll is negative")

        match_status = (
            "MATCHED" if observed_bankroll == expected_post else "MISMATCH"
        )
        round_id = f"deduction-{self.rounds_completed}-{utc_now_iso()}"
        self._wager_round_ids.add(round_id)
        self._active_round_id = round_id
        self._pending_round = {
            "round_id": round_id,
            "bankroll_before": pre,
            "recommended_bet_type": pending.bet_type,
            "recommended_stake": stake,
            "actual_bet_type": pending.bet_type,
            "actual_stake": pre - observed_bankroll,
            "observed_post_deduction_bankroll": observed_bankroll,
            "wager_match_status": match_status,
            "color_side": None,
            "recommendation": pending,
        }
        self.status = "ROUND_PENDING"
        self._append_event(
            {
                "kind": "wager_deduction",
                "at": utc_now_iso(),
                "round_id": round_id,
                "pre_wager_bankroll": pre,
                "recommended_bet_type": pending.bet_type,
                "recommended_stake": stake,
                "observed_post_deduction_bankroll": observed_bankroll,
                "wager_match_status": match_status,
            }
        )
        message = None
        if match_status == "MISMATCH":
            message = (
                "Wager differs from recommendation. "
                "The strategy will resync when the round finishes."
            )
        # Keep session bankroll at pre-wager until settlement (do not treat deduction as LOSS).
        return self._outcome(message=message)

    def _find_last_companion_settlement(self) -> dict[str, Any] | None:
        for event in reversed(self.events):
            if event.get("kind") == "companion_round_settled":
                return event
        return None

    def _idempotent_settle_outcome(self) -> PlayOutcome:
        if self.is_terminal():
            return self._outcome()
        if self.status == "DESYNCED":
            return self._outcome(
                message=(
                    "Logical bankroll is outside the policy grid — session paused."
                )
            )
        if self.status == "WAITING_FOR_WAGER":
            return self.get_recommendation()
        return self._outcome()

    def _pending_dom_wager_matches(
        self,
        bet_type: str,
        stake: int,
        color_side: str | None,
    ) -> bool:
        pending = self._pending_round
        if pending is None:
            return False
        norm_type, norm_side = _normalize_wager_type(bet_type, color_side)
        return (
            pending.get("actual_bet_type") == norm_type
            and pending.get("actual_stake") == stake
            and pending.get("color_side") == norm_side
        )

    def register_dom_placed_wager(
        self,
        bet_type: str,
        stake: int,
        *,
        color_side: str | None = None,
        observed_bankroll: int | None = None,
    ) -> PlayOutcome:
        """DOM-placed wager detection (WAITING_FOR_WAGER → ROUND_PENDING)."""
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")
        if self.status == "DESYNCED":
            raise LiveSessionError("desynced", "Session is paused due to desync")
        if self.status == "ROUND_PENDING":
            if self._pending_dom_wager_matches(bet_type, stake, color_side):
                message = None
                pending = self._pending_round
                if pending is not None and pending.get("wager_match_status") == "MISMATCH":
                    message = (
                        "Wager differs from recommendation. "
                        "The strategy will resync when the round finishes."
                    )
                return self._outcome(message=message)
            raise LiveSessionError(
                "invalid_state",
                f"Cannot register DOM wager while status is {self.status}",
            )
        if self.status != "WAITING_FOR_WAGER":
            raise LiveSessionError(
                "invalid_state",
                f"Cannot register DOM wager while status is {self.status}",
            )
        pending = self.current_recommendation
        if pending is None or pending.stake is None or pending.bet_type is None:
            raise LiveSessionError("no_recommendation", "No active recommendation")

        pre = self.bankroll
        norm_type, norm_side = _normalize_wager_type(bet_type, color_side)
        matched = _wagers_match(pending, bet_type, stake, color_side)
        match_status = "MATCHED" if matched else "MISMATCH"
        round_id = f"dom-{self.rounds_completed}-{utc_now_iso()}"
        self._wager_round_ids.add(round_id)
        self._active_round_id = round_id
        self._pending_round = {
            "round_id": round_id,
            "bankroll_before": pre,
            "recommended_bet_type": pending.bet_type,
            "recommended_stake": pending.stake,
            "actual_bet_type": norm_type,
            "actual_stake": stake,
            "observed_post_deduction_bankroll": observed_bankroll,
            "wager_match_status": match_status,
            "color_side": norm_side,
            "recommendation": pending,
        }
        if match_status == "MATCHED":
            win_b = pending.win_bankroll
            lose_b = pending.lose_bankroll
            if win_b is None or lose_b is None:
                raise PolicyError("Recommendation missing transitions")
        else:
            action = Action(norm_type, stake)
            win_b, lose_b = next_bankrolls(pre, action, self.loaded.game)
        self._pending_round["expected_win_bankroll"] = win_b
        self._pending_round["expected_lose_bankroll"] = lose_b
        self.status = "ROUND_PENDING"
        self._append_event(
            {
                "kind": "DOM_WAGER",
                "at": utc_now_iso(),
                "round_id": round_id,
                "pre_wager_bankroll": pre,
                "recommended_bet_type": pending.bet_type,
                "recommended_stake": pending.stake,
                "observed_bet_type": norm_type,
                "observed_stake": stake,
                "observed_color_side": norm_side,
                "observed_bankroll": observed_bankroll,
                "wager_match_status": match_status,
                "expected_win_bankroll": win_b,
                "expected_lose_bankroll": lose_b,
            }
        )
        message = None
        if match_status == "MISMATCH":
            message = (
                "Wager differs from recommendation. "
                "The strategy will resync when the round finishes."
            )
        return self._outcome(message=message)

    def settle_companion_round(self, winner_side: ResultOutcome) -> PlayOutcome:
        """Settle ROUND_PENDING from observed result outcome (no re-solve)."""
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")

        last_settled = self._find_last_companion_settlement()
        if self.status != "ROUND_PENDING":
            if (
                last_settled is not None
                and last_settled.get("winner_side") == winner_side
            ):
                return self._idempotent_settle_outcome()
            raise LiveSessionError(
                "invalid_state",
                f"Cannot settle companion round while status is {self.status}",
            )
        if self._pending_round is None:
            raise LiveSessionError("no_wager", "No pending wager deduction to settle")

        pending = self._pending_round
        round_id = pending["round_id"]
        if round_id in self._result_round_ids:
            if (
                last_settled is not None
                and last_settled.get("round_id") == round_id
                and last_settled.get("winner_side") == winner_side
            ):
                return self._idempotent_settle_outcome()
            raise LiveSessionError(
                "duplicate_result", "Result already registered for round"
            )

        recommendation: Recommendation = pending["recommendation"]
        actual_bet_type = pending["actual_bet_type"]
        actual_stake = pending["actual_stake"]
        color_side = pending.get("color_side")
        pre = pending["bankroll_before"]
        wager_match_status = pending.get("wager_match_status", "MATCHED")

        outcome_label = _resolve_outcome(actual_bet_type, color_side, winner_side)

        win_b = pending.get("expected_win_bankroll")
        lose_b = pending.get("expected_lose_bankroll")
        if win_b is None or lose_b is None:
            if wager_match_status == "MATCHED":
                win_b = recommendation.win_bankroll
                lose_b = recommendation.lose_bankroll
                if win_b is None or lose_b is None:
                    raise PolicyError("Recommendation missing transitions")
            else:
                action = Action(actual_bet_type, actual_stake)
                win_b, lose_b = next_bankrolls(pre, action, self.loaded.game)
        successor = win_b if outcome_label == "WIN" else lose_b

        self._result_round_ids.add(round_id)
        self._append_event(
            {
                "kind": "ROUND_RESULT",
                "at": utc_now_iso(),
                "round_id": round_id,
                "winner_side": winner_side,
                "outcome": outcome_label,
            }
        )
        self._append_event(
            {
                "kind": "LOGICAL_SETTLEMENT",
                "at": utc_now_iso(),
                "round_id": round_id,
                "pre_wager_bankroll": pre,
                "post_round_bankroll": successor,
                "classification": outcome_label,
            }
        )

        self.bankroll = successor
        self.rounds_completed += 1
        record = PlayRoundRecord(
            round_number=self.rounds_completed,
            bankroll_before=pre,
            bet_type=actual_bet_type,
            stake=actual_stake,
            outcome=outcome_label,
            bankroll_after=successor,
            website_round_id=round_id,
            recommended_bet_type=pending["recommended_bet_type"],
            recommended_stake=pending["recommended_stake"],
            color_side=color_side,
            result_outcome=winner_side,
            expected_bankroll_after=successor,
        )
        self.round_history.append(record)
        self._append_event(
            {
                "kind": "companion_round_settled",
                "at": utc_now_iso(),
                "round_id": round_id,
                "pre_wager_bankroll": pre,
                "recommended_bet_type": pending["recommended_bet_type"],
                "recommended_stake": pending["recommended_stake"],
                "observed_post_deduction_bankroll": pending.get(
                    "observed_post_deduction_bankroll"
                ),
                "wager_match_status": wager_match_status,
                "winner_side": winner_side,
                "settlement_classification": outcome_label,
                "next_bankroll": successor,
            }
        )
        self._clear_active_round()

        terminal = self._terminal_from_bankroll()
        if terminal is not None:
            return terminal

        session = self.loaded.session
        if (
            successor not in self.loaded.policy
            and session.floor_bankroll < successor < session.target_bankroll
        ):
            self.status = "DESYNCED"
            self._append_event(
                {
                    "kind": "policy_grid_miss",
                    "at": utc_now_iso(),
                    "round_id": round_id,
                    "logical_bankroll": successor,
                }
            )
            return self._outcome(
                message=(
                    "Logical bankroll is outside the policy grid — session paused."
                )
            )

        return self.get_recommendation()

    def register_observed_wager(
        self,
        round_id: str,
        bet_type: str,
        stake: int,
        *,
        color_side: str | None = None,
    ) -> PlayOutcome:
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")
        if round_id in self._wager_round_ids:
            raise LiveSessionError("duplicate_wager", "Wager already registered for round")
        if self.status == "DESYNCED":
            raise LiveSessionError("desynced", "Session is paused due to desync")
        if self.status != "WAITING_FOR_WAGER":
            raise LiveSessionError(
                "invalid_state",
                f"Cannot register wager while status is {self.status}",
            )
        pending = self.current_recommendation
        if pending is None:
            raise LiveSessionError("no_recommendation", "No active recommendation")
        norm_type, norm_side = _normalize_wager_type(bet_type, color_side)
        matched = _wagers_match(pending, bet_type, stake, color_side)
        self._wager_round_ids.add(round_id)
        self._active_round_id = round_id
        wager_event = {
            "kind": "observed_wager",
            "at": utc_now_iso(),
            "round_id": round_id,
            "bet_type": bet_type,
            "stake": stake,
            "color_side": norm_side,
        }
        self._append_event(wager_event)
        self._pending_round = {
            "round_id": round_id,
            "bankroll_before": self.bankroll,
            "recommended_bet_type": pending.bet_type,
            "recommended_stake": pending.stake,
            "actual_bet_type": norm_type,
            "actual_stake": stake,
            "color_side": norm_side,
            "recommendation": pending,
        }
        if matched:
            self.status = "WAITING_FOR_RESULT"
            self._append_event(
                {
                    "kind": "wager_confirmed",
                    "at": utc_now_iso(),
                    "round_id": round_id,
                }
            )
            return self._outcome()
        self.status = "DESYNCED"
        self._append_event(
            {
                "kind": "wager_mismatch",
                "at": utc_now_iso(),
                "round_id": round_id,
                "recommended_bet_type": pending.bet_type,
                "recommended_stake": pending.stake,
                "actual_bet_type": norm_type,
                "actual_stake": stake,
            }
        )
        return self._outcome()

    def register_observed_result(
        self,
        round_id: str,
        result: ResultOutcome,
    ) -> PlayOutcome:
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")
        if round_id in self._result_round_ids:
            raise LiveSessionError("duplicate_result", "Result already registered for round")
        if self.status != "WAITING_FOR_RESULT":
            raise LiveSessionError(
                "invalid_state",
                f"Cannot register result while status is {self.status}",
            )
        if self._active_round_id is None or round_id != self._active_round_id:
            raise LiveSessionError("wrong_round", "Result round does not match active round")
        if self._pending_round is None:
            raise LiveSessionError("no_wager", "Result received before wager confirmation")
        pending = self._pending_round
        bet_type = pending["actual_bet_type"]
        color_side = pending["color_side"]
        recommendation = pending["recommendation"]
        outcome_label = _resolve_outcome(bet_type, color_side, result)
        if outcome_label == "WIN":
            expected = recommendation.win_bankroll
        else:
            expected = recommendation.lose_bankroll
        if expected is None:
            raise PolicyError("Recommendation missing transitions")
        self._result_round_ids.add(round_id)
        self._expected_bankroll = expected
        self.status = "RECONCILING"
        self._append_event(
            {
                "kind": "observed_result",
                "at": utc_now_iso(),
                "round_id": round_id,
                "result": result,
            }
        )
        self._append_event(
            {
                "kind": "resolved_result",
                "at": utc_now_iso(),
                "round_id": round_id,
                "outcome": outcome_label,
                "expected_bankroll": expected,
            }
        )
        self._pending_round["outcome"] = outcome_label
        self._pending_round["result_outcome"] = result
        self._pending_round["expected_bankroll_after"] = expected
        return self._outcome()

    def reconcile_bankroll(self, observed_bankroll: int) -> PlayOutcome:
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")
        if self.status != "RECONCILING":
            raise LiveSessionError(
                "invalid_state",
                f"Cannot reconcile bankroll while status is {self.status}",
            )
        if self._expected_bankroll is None or self._pending_round is None:
            raise LiveSessionError("no_reconciliation", "No pending reconciliation")
        expected = self._expected_bankroll
        self._append_event(
            {
                "kind": "observed_bankroll",
                "at": utc_now_iso(),
                "round_id": self._active_round_id,
                "observed_bankroll": observed_bankroll,
                "expected_bankroll": expected,
            }
        )
        if observed_bankroll != expected:
            self.status = "DESYNCED"
            self._append_event(
                {
                    "kind": "bankroll_mismatch",
                    "at": utc_now_iso(),
                    "round_id": self._active_round_id,
                    "expected_bankroll": expected,
                    "observed_bankroll": observed_bankroll,
                }
            )
            return self._outcome()
        self.bankroll = observed_bankroll
        pending = self._pending_round
        self.rounds_completed += 1
        record = PlayRoundRecord(
            round_number=self.rounds_completed,
            bankroll_before=pending["bankroll_before"],
            bet_type=pending["actual_bet_type"],
            stake=pending["actual_stake"],
            outcome=pending["outcome"],
            bankroll_after=self.bankroll,
            website_round_id=pending["round_id"],
            recommended_bet_type=pending["recommended_bet_type"],
            recommended_stake=pending["recommended_stake"],
            color_side=pending["color_side"],
            result_outcome=pending["result_outcome"],
            expected_bankroll_after=expected,
        )
        self.round_history.append(record)
        self._append_event(
            {
                "kind": "bankroll_reconciled",
                "at": utc_now_iso(),
                "round_id": pending["round_id"],
                "bankroll": self.bankroll,
            }
        )
        self._clear_active_round()
        terminal = self._terminal_from_bankroll()
        if terminal is not None:
            return terminal
        return self.get_recommendation()

    def resync_bankroll(self, website_bankroll: int) -> PlayOutcome:
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")
        if self.status != "DESYNCED":
            raise LiveSessionError(
                "invalid_state",
                f"Resync is only valid while status is DESYNCED (current: {self.status})",
            )
        self.bankroll = website_bankroll
        self._clear_active_round()
        self._append_event(
            {
                "kind": "resync",
                "at": utc_now_iso(),
                "bankroll": website_bankroll,
            }
        )
        terminal = self._terminal_from_bankroll()
        if terminal is not None:
            return terminal
        return self.get_recommendation()

    def stop_session(self, message: str | None = None) -> PlayOutcome:
        if self.is_terminal():
            return self._outcome(message=message)
        if self.status == "ROUND_PENDING" and self._pending_round is not None:
            pending = self._pending_round
            self._append_event(
                {
                    "kind": "round_abandoned",
                    "at": utc_now_iso(),
                    "round_id": pending["round_id"],
                    "bankroll": self.bankroll,
                    "recommended_bet_type": pending.get("recommended_bet_type"),
                    "recommended_stake": pending.get("recommended_stake"),
                    "actual_bet_type": pending.get("actual_bet_type"),
                    "actual_stake": pending.get("actual_stake"),
                }
            )
        self._mark_terminal("USER_STOPPED")
        self._append_event(
            {
                "kind": "stop",
                "at": self.ended_at,
                "bankroll": self.bankroll,
            }
        )
        return self._outcome(message=message or "Session stopped")

    _DIAGNOSTIC_EVENT_KINDS = frozenset(
        {"BANKROLL_RECONCILED", "BANKROLL_RECONCILIATION_WARNING"}
    )

    def record_diagnostic_event(
        self,
        kind: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Append a lightweight companion diagnostic event (plan §30)."""
        if kind not in self._DIAGNOSTIC_EVENT_KINDS:
            raise LiveSessionError(
                "invalid_event",
                f"Unsupported diagnostic event kind: {kind}",
            )
        if self.is_terminal():
            raise LiveSessionError("session_terminal", "Session is already terminal")
        event: dict[str, Any] = {"kind": kind, "at": utc_now_iso()}
        if detail:
            event["detail"] = detail
        self._append_event(event)

    def build_saved_session(
        self,
        session_id: str,
        *,
        policy_identity: dict[str, Any],
        terminal_status: str,
    ) -> SavedLiveSession:
        return SavedLiveSession(
            session_id=session_id,
            source=self.source,
            started_at=self.started_at,
            ended_at=self.ended_at or utc_now_iso(),
            starting_bankroll=self.loaded.session.starting_bankroll,
            ending_bankroll=self.bankroll,
            target=self.loaded.session.target_bankroll,
            floor=self.loaded.session.floor_bankroll,
            terminal_status=terminal_status_for_save(terminal_status),
            round_count=self.rounds_completed,
            initial_loss_durability=self.initial_loss_durability,
            policy_identity=policy_identity,
            events=list(self.events),
        )

    @property
    def _pending(self) -> Recommendation | None:
        """Backward compatibility for API routes that checked _pending."""
        return self.current_recommendation


PlaySession = LiveSession


def run_play_loop(
    loaded: LoadedPolicy,
    bankroll: int,
    *,
    input_fn: Callable[[str], str],
    echo_fn: Callable[[str], None],
) -> PlayOutcome:
    session = LiveSession(loaded, bankroll)
    round_number = 1
    outcome = session.begin_round()
    while outcome.status == "CONTINUE":
        assert outcome.recommendation is not None
        if outcome.message:
            echo_fn(outcome.message)
        echo_fn(format_play_prompt(outcome.recommendation, round_number))
        raw = input_fn("")
        next_outcome = session.apply_input(raw)
        if next_outcome.status == "CONTINUE" and next_outcome.message:
            outcome = next_outcome
            continue
        outcome = next_outcome
        if outcome.status == "CONTINUE":
            round_number += 1
    echo_fn(
        format_play_terminal(outcome.status, outcome.bankroll, outcome.rounds_completed)
    )
    return outcome
