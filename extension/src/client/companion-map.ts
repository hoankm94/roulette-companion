import type {
  BetType,
  CompanionUiState,
  DiceDroughtMetrics,
  Recommendation,
  RoundOutcome,
  SessionView,
  TerminalReason,
  WagerObservation,
} from "../shared/types.js";
import { emptyDiceDroughtMetrics } from "../shared/types.js";
import type { CompanionStateResponse } from "./backend-client.js";

function mapDiceDrought(api: CompanionStateResponse): DiceDroughtMetrics {
  return {
    diceDroughtDurability: api.dice_drought_durability ?? null,
    diceDroughtSurvivalThreshold: api.dice_drought_survival_threshold ?? null,
    diceDroughtSurvivalAtP90: api.dice_drought_survival_at_p90 ?? null,
    diceDroughtSurvivalAtP95: api.dice_drought_survival_at_p95 ?? null,
    diceDroughtSurvivalAtP99: api.dice_drought_survival_at_p99 ?? null,
    diceDroughtDurabilityCapped: api.dice_drought_durability_capped === true,
    historicalDiceDroughtMedian: api.historical_dice_drought_median ?? null,
    historicalDiceDroughtP90: api.historical_dice_drought_p90 ?? null,
    historicalDiceDroughtP95: api.historical_dice_drought_p95 ?? null,
    historicalDiceDroughtP99: api.historical_dice_drought_p99 ?? null,
  };
}

function mapRecommendation(api: CompanionStateResponse): Recommendation | null {
  const rec = api.recommendation;
  if (rec && rec.status === "ACTION" && rec.action) {
    return {
      betType: rec.action as BetType,
      stakeCents: rec.stake?.cents ?? 0,
      winBankrollCents: rec.win_bankroll?.cents ?? 0,
      loseBankrollCents: rec.lose_bankroll?.cents ?? 0,
      targetHitProbability: rec.target_hit_probability ?? api.target_hit_probability ?? null,
    };
  }
  if (api.recommended_wager) {
    return {
      betType: api.recommended_wager.bet_type as BetType,
      stakeCents: api.recommended_wager.stake.cents,
      winBankrollCents: 0,
      loseBankrollCents: 0,
      targetHitProbability: api.target_hit_probability ?? null,
    };
  }
  return null;
}

function mapObservedWager(api: CompanionStateResponse): WagerObservation | null {
  if (!api.observed_wager) return null;
  return {
    betType: api.observed_wager.bet_type as BetType,
    stakeCents: api.observed_wager.stake.cents,
    colorSide: api.observed_wager.color_side ?? undefined,
  };
}

function mapTerminalReason(status: string): TerminalReason {
  switch (status) {
    case "TARGET":
      return "TARGET";
    case "FLOOR":
      return "FLOOR";
    case "NO_ACTION":
      return "NO_ACTION";
    default:
      return "USER_STOPPED";
  }
}

/** Restore overlay view after cancel_stop from backend session status (M16). */
export function viewForActiveSession(apiSessionStatus: string | null): SessionView {
  switch (apiSessionStatus) {
    case "WAITING_FOR_WAGER":
      return "active";
    case "ROUND_PENDING":
    case "WAITING_FOR_RESULT":
      return "waiting_result";
    case "RECONCILING":
      return "reconciling";
    case "DESYNCED":
      return "wager_mismatch";
    default:
      return "active";
  }
}

export function applyCompanionApiResponse(
  state: CompanionUiState,
  api: CompanionStateResponse,
): CompanionUiState {
  const next: CompanionUiState = { ...state };
  next.backendSessionId = api.session_id;
  next.apiSessionStatus = api.session_status;
  next.currentBankrollCents = api.bankroll.cents;
  next.targetCents = api.target.cents;
  next.floorCents = api.floor.cents;
  next.roundsCompleted = api.rounds_completed;
  next.mockMode = false;
  next.targetHitProbability =
    api.target_hit_probability ?? api.recommendation?.target_hit_probability ?? null;
  next.diceDrought = mapDiceDrought(api);

  const mappedRec = mapRecommendation(api);
  if (mappedRec) {
    if (api.recommendation?.win_bankroll) {
      mappedRec.winBankrollCents = api.recommendation.win_bankroll.cents;
      mappedRec.loseBankrollCents = api.recommendation.lose_bankroll?.cents ?? 0;
    }
    next.recommendation = mappedRec;
  } else if (!api.awaiting_save && api.session_status !== "DESYNCED") {
    next.recommendation = null;
  }

  const observed = mapObservedWager(api);
  if (observed) {
    next.observedWager = observed;
  }

  if (api.expected_bankroll) {
    next.expectedBankrollCents = api.expected_bankroll.cents;
  }
  if (api.observed_bankroll) {
    next.websiteBankrollCents = api.observed_bankroll.cents;
  }
  if (api.last_outcome) {
    next.roundOutcome = api.last_outcome as RoundOutcome;
  }

  if (api.awaiting_save || ["TARGET", "FLOOR", "NO_ACTION", "QUIT", "USER_STOPPED"].includes(api.status)) {
    next.view = "terminal";
    next.terminalReason = mapTerminalReason(api.status);
    next.sessionActive = false;
    next.recommendation = null;
    next.health = "CONNECTED";
    next.statusLabel = api.status === "TARGET" ? "Target reached" : "Session ended";
    next.canStart = false;
    return next;
  }

  next.sessionActive = true;

  if (api.session_status === "DESYNCED") {
    if (api.desync_reason === "policy_grid_miss") {
      next.view = "policy_paused";
    } else if (
      api.desync_reason === "bankroll_mismatch" ||
      (api.expected_bankroll && api.observed_bankroll)
    ) {
      next.view = "bankroll_mismatch";
    } else {
      next.view = "wager_mismatch";
    }
    next.health = "DESYNCED";
    next.statusLabel = "Paused";
    next.recommendation = mappedRec ?? next.recommendation;
  } else if (api.session_status === "WAITING_FOR_WAGER") {
    next.view = "active";
    next.observedWager = null;
    next.roundOutcome = null;
    next.expectedBankrollCents = null;
    next.websiteBankrollCents = null;
    next.health = "CONNECTED";
  } else if (api.session_status === "ROUND_PENDING") {
    next.view = "waiting_result";
    next.health = "CONNECTED";
  } else if (api.session_status === "WAITING_FOR_RESULT") {
    next.view = "waiting_result";
    next.health = "CONNECTED";
  } else if (api.session_status === "RECONCILING") {
    next.view = api.last_result ? "result" : "reconciling";
    next.health = "CONNECTED";
  } else if (state.view === "preparing") {
    next.view = "active";
    next.health = "CONNECTED";
  }

  if (next.health === "CONNECTED") {
    if (api.message && api.session_status === "ROUND_PENDING") {
      next.statusLabel = "Wager detected";
    } else if (
      api.message &&
      (api.settlement_classification === "DIVERGENCE" ||
        /resynced|increase/i.test(api.message))
    ) {
      next.statusLabel = "Balance resynced";
    } else {
      next.statusLabel =
        next.view === "active"
          ? "Waiting for wager"
          : next.view === "waiting_result"
            ? "Waiting for round to finish"
            : next.view === "result" || next.view === "reconciling"
              ? "Syncing bankroll"
              : "Synced";
    }
  }

  next.canStart = false;
  return next;
}

export { emptyDiceDroughtMetrics, mapDiceDrought };
