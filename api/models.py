"""Pydantic request/response models. Dollars on the wire; cents inside domain."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class SessionMoneyInput(BaseModel):
    bankroll: float = Field(..., description="Starting bankroll in dollars")
    target: float = Field(..., description="Target bankroll in dollars")
    floor: float = Field(..., description="Hard floor in dollars")
    solver: Literal["numpy", "reference", "numba", "policy_iteration"] = "numba"
    force: bool = False


class OptimizeRequest(SessionMoneyInput):
    pass


class MoneyAmount(BaseModel):
    cents: int
    dollars: float


class PolicyRow(BaseModel):
    bankroll: MoneyAmount
    action: str | None
    stake: MoneyAmount | None
    win_bankroll: MoneyAmount | None
    lose_bankroll: MoneyAmount | None
    target_hit_probability: float


class VerificationPayload(BaseModel):
    deterministic_status: str
    policy_evaluation_passed: bool
    bellman_passed: bool
    linear_value_bellman_passed: bool
    legal_actions_passed: bool
    max_value_difference: float
    max_optimality_gap: float
    vi_bellman_max_gap: float
    linear_value_bellman_max_gap: float


class SolverMeta(BaseModel):
    converged: bool
    iterations: int
    final_delta: float
    solver: str


class PolicyDistribution(BaseModel):
    color_count: int
    dice_count: int
    no_action_count: int
    state_count: int


class RecommendationPayload(BaseModel):
    status: str
    action: str | None
    stake: MoneyAmount | None
    target_hit_probability: float
    win_bankroll: MoneyAmount | None
    lose_bankroll: MoneyAmount | None
    bankroll: MoneyAmount
    consecutive_loss_durability: int = 0


class OptimizeResponse(BaseModel):
    recommendation: RecommendationPayload
    session: dict[str, Any]
    distribution: PolicyDistribution
    policy: list[PolicyRow]
    values: list[dict[str, Any]]
    verification: VerificationPayload
    solver: SolverMeta


class PlayStartRequest(SessionMoneyInput):
    pass


class PlayStateResponse(BaseModel):
    session_id: str
    status: str
    bankroll: MoneyAmount
    target: MoneyAmount
    floor: MoneyAmount
    target_hit_probability: float | None
    consecutive_loss_durability: int | None = None
    recommendation: RecommendationPayload | None
    rounds_completed: int
    message: str | None = None
    verification: VerificationPayload | None = None
    awaiting_save: bool = False


class PlaySaveResponse(BaseModel):
    saved: bool
    session_id: str
    csv_path: str | None = None
    json_path: str | None = None


class CompanionStartRequest(SessionMoneyInput):
    """Start companion session using website bankroll as starting bankroll."""


class CompanionCalculateTargetRequest(BaseModel):
    """Setup-only Target search for a requested Reach target %."""

    bankroll: float = Field(..., description="Starting bankroll in dollars")
    floor: float = Field(..., description="Hard floor in dollars")
    reach_target_probability: float = Field(
        ...,
        description="Requested Reach target probability as a fraction in (0, 1]",
    )
    solver: Literal["numpy", "reference", "numba", "policy_iteration"] = "numba"
    force: bool = False


class CompanionCalculateTargetResponse(BaseModel):
    target: MoneyAmount
    target_hit_probability: float
    solves: int


class CompanionRegisterWagerRequest(BaseModel):
    round_id: str
    bet_type: Literal["DICE", "COLOR", "ORANGE", "BLACK"]
    stake: float = Field(..., description="Stake in dollars")
    color_side: Literal["ORANGE", "BLACK"] | None = None


class CompanionRegisterResultRequest(BaseModel):
    round_id: str
    result: Literal["DICE", "ORANGE", "BLACK"]


class CompanionBankrollRequest(BaseModel):
    observed_bankroll: float = Field(..., description="Observed bankroll in dollars")


class CompanionDomWagerRequest(BaseModel):
    observed_bankroll: float = Field(..., description="Observed bankroll in dollars")
    bet_type: Literal["DICE", "ORANGE", "BLACK"] = Field(
        ..., description="Observed wager side from DOM"
    )
    stake: float = Field(..., description="Observed stake in dollars")


class CompanionSettleRoundRequest(BaseModel):
    winner_side: Literal["DICE", "ORANGE", "BLACK"]


class CompanionDiagnosticEventRequest(BaseModel):
    kind: Literal["BANKROLL_RECONCILED", "BANKROLL_RECONCILIATION_WARNING"]
    detail: dict[str, Any] | None = None


class CompanionWagerPayload(BaseModel):
    bet_type: str
    stake: MoneyAmount
    color_side: Literal["ORANGE", "BLACK"] | None = None


class CompanionStateResponse(BaseModel):
    session_id: str
    session_status: str
    status: str
    bankroll: MoneyAmount
    target: MoneyAmount
    floor: MoneyAmount
    target_hit_probability: float | None = None
    consecutive_loss_durability: int | None = None
    recommendation: RecommendationPayload | None
    rounds_completed: int
    message: str | None = None
    awaiting_save: bool = False
    recommended_wager: CompanionWagerPayload | None = None
    observed_wager: CompanionWagerPayload | None = None
    expected_bankroll: MoneyAmount | None = None
    observed_bankroll: MoneyAmount | None = None
    expected_win_bankroll: MoneyAmount | None = None
    expected_lose_bankroll: MoneyAmount | None = None
    last_result: Literal["DICE", "ORANGE", "BLACK"] | None = None
    last_outcome: Literal["WIN", "LOSS", "DIVERGENCE"] | None = None
    settlement_classification: Literal["WIN", "LOSS", "DIVERGENCE"] | None = None
    wager_match_status: Literal["MATCHED", "MISMATCH"] | None = None
    desync_reason: (
        Literal["policy_grid_miss", "wager_mismatch", "bankroll_mismatch"] | None
    ) = None


class SavedLiveSessionPayload(BaseModel):
    session_id: str
    source: Literal["MANUAL", "COMPANION"]
    started_at: str
    ended_at: str
    starting_bankroll: MoneyAmount
    ending_bankroll: MoneyAmount
    target: MoneyAmount
    floor: MoneyAmount
    terminal_status: str
    round_count: int
    initial_loss_durability: int
    policy_identity: dict[str, Any]
    events: list[dict[str, Any]] = Field(default_factory=list)


class ReplaySeedInput(BaseModel):
    server_seed: str
    public_seed: str
    rounds: str = Field(..., description='Inclusive range, e.g. "12609767 - 12613349"')
    seed_date: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD enabling estimated timestamps",
    )
    timezone: str = Field(default="UTC", description="IANA timezone when seed_date is set")


class ReplayAnalyzeRequest(ReplaySeedInput):
    pass


class EstimatedTimingFields(BaseModel):
    estimated_start_time: str | None = None
    estimated_end_time: str | None = None
    estimated_duration_seconds: float | None = None
    timezone: str | None = None
    timing_status: str | None = None


class StreakPayload(EstimatedTimingFields):
    outcome: str
    length: int
    start_round: int
    end_round: int


class DroughtPayload(EstimatedTimingFields):
    missing: str
    length: int
    start_round: int
    end_round: int
    dice_count: int
    orange_count: int
    black_count: int


class WindowExtremePayload(EstimatedTimingFields):
    window_size: int
    outcome: str
    extremum: str
    count: int
    start_round: int
    end_round: int


class ReplayAnalyzeResponse(BaseModel):
    round_start: int
    round_end: int
    total_rolls: int
    dice_count: int
    orange_count: int
    black_count: int
    dice_pct: float
    orange_pct: float
    black_pct: float
    theoretical_dice_pct: float
    theoretical_color_pct: float
    longest_orange_streak: StreakPayload
    longest_black_streak: StreakPayload
    longest_same_color_streak: StreakPayload
    longest_dice_streak: StreakPayload
    longest_dice_drought: DroughtPayload
    longest_orange_drought: DroughtPayload
    longest_black_drought: DroughtPayload
    dice_droughts_ge_35: int
    dice_droughts_ge_45: int
    window_extremes: list[WindowExtremePayload]
    seed_date: str | None = None
    timezone: str | None = None
    average_cycle_seconds: float | None = None
    timing_status: str | None = None


class ReplayRunRequest(ReplaySeedInput):
    bankroll: float
    target: float
    floor: float
    color_side: Literal["orange", "black", "both", "alternate"] = "alternate"
    alternate_first: Literal["black", "orange"] = "orange"
    start_mode: Literal["first", "random", "all"] = "first"
    samples: int | None = None
    sample_seed: int | None = None
    solver: Literal["numpy", "reference", "numba", "policy_iteration"] = "numba"


class ReplaySummaryPayload(BaseModel):
    scenario: str
    color_side: str
    start_mode: str
    start_bankroll: MoneyAmount
    target: MoneyAmount
    floor: MoneyAmount
    start_count: int
    target_count: int
    floor_count: int
    no_action_count: int
    exhausted_count: int
    resolved_count: int
    target_rate_all: float
    target_rate_resolved: float
    theoretical_V_start: float
    mean_rounds_resolved: float
    median_rounds_resolved: float
    largest_drawdown: MoneyAmount
    longest_losing_bet_streak: int
    solver: str
    seed_date: str | None = None
    timezone: str | None = None
    average_cycle_seconds: float | None = None
    timing_status: str | None = None


class ReplaySessionPayload(BaseModel):
    scenario: str
    color_side: str
    start_mode: str
    start_round: int
    last_round: int | None
    rolls_consumed: int
    start_bankroll: MoneyAmount
    end_bankroll: MoneyAmount
    target: MoneyAmount
    floor: MoneyAmount
    terminal_status: str
    maximum_drawdown: MoneyAmount
    longest_losing_bet_streak: int
    starting_loss_durability: int = 0
    minimum_loss_durability: int = 0
    ending_loss_durability: int = 0
    trace: list[dict[str, Any]] = Field(default_factory=list)
    estimated_start_time: str | None = None
    estimated_last_time: str | None = None
    timezone: str | None = None
    timing_status: str | None = None


class ReplayRunResponse(BaseModel):
    summaries: list[ReplaySummaryPayload]
    sessions: list[ReplaySessionPayload]
    solve_calls: int
    note: str = (
        "Historical target rates are observed outcomes on this seed sequence; "
        "theoretical_V_start is the solver probability, not the same quantity."
    )


class ReplayExtremesRequest(ReplaySeedInput):
    bankroll: float
    target: float
    floor: float
    color_side: Literal["orange", "black", "both", "alternate"] = "alternate"
    alternate_first: Literal["black", "orange"] = "orange"
    solver: Literal["numpy", "reference", "numba", "policy_iteration"] = "numba"


class ExtremeRowPayload(BaseModel):
    scenario: str
    color_side: str
    extreme_kind: str
    extreme_label: str
    extreme_start_round: int
    extreme_end_round: int
    session: ReplaySessionPayload
    estimated_start_time: str | None = None
    estimated_end_time: str | None = None
    estimated_duration_seconds: float | None = None
    timezone: str | None = None
    timing_status: str | None = None


class ReplayExtremesResponse(BaseModel):
    analysis: ReplayAnalyzeResponse
    extreme_rows: list[ExtremeRowPayload]
    summaries: list[ReplaySummaryPayload]
    solve_calls: int


class DiceMapRequest(SessionMoneyInput):
    pass


class DiceMapRowPayload(BaseModel):
    bankroll: MoneyAmount
    dice_stake: MoneyAmount
    dice_q: float
    best_color_stake: MoneyAmount | None
    best_color_q: float | None
    difference: float | None


class DiceMapResponse(BaseModel):
    state_count: int
    dice_count: int
    color_count: int
    no_action_count: int
    min_difference: float | None
    max_difference: float | None
    median_difference: float | None
    rows: list[DiceMapRowPayload]
    solver: str


class SweepRequest(BaseModel):
    bankroll: float
    target_profits: list[float] = Field(..., description="Target profits in dollars")
    floor_losses: list[float] = Field(..., description="Floor losses in dollars")
    solver: Literal["numpy", "reference", "numba", "policy_iteration"] = "numba"
    verify: bool = False
    force: bool = False


class SweepCellPayload(BaseModel):
    target_profit: MoneyAmount
    maximum_loss: MoneyAmount
    target: MoneyAmount
    floor: MoneyAmount
    V_start: float | None
    initial_loss_durability: int
    COLOR_state_count: int
    DICE_state_count: int
    NO_ACTION_state_count: int
    iterations: int
    final_delta: float | None
    solve_seconds: float
    verification_status: str
    failure_info: str


class SweepResponse(BaseModel):
    bankroll: MoneyAmount
    target_profits: list[MoneyAmount]
    floor_losses: list[MoneyAmount]
    cells: list[SweepCellPayload]
    successful: int
    failed: int
    total_seconds: float


class ValidateRequest(SessionMoneyInput):
    sessions: int = 10000
    seed: int = 42
    max_rounds: int = 10000
    seeds: list[int] | None = None


class ValidateResponse(BaseModel):
    deterministic_status: str
    verification: VerificationPayload
    solver: SolverMeta
    solver_probability: float
    monte_carlo: dict[str, Any] | None
    seeds: list[dict[str, Any]] | None = None
    max_absolute_difference: float | None = None
