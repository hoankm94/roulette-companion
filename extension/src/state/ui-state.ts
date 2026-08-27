import type {
  CompanionUiState,
  HealthState,
  Recommendation,
  RoundOutcome,
  SessionView,
  TerminalReason,
  UserStatusLabel,
  WagerObservation,
} from "../shared/types";
import { emptyUiState } from "../shared/types";
import { viewForActiveSession } from "../client/companion-map.js";

export type UiAction =
  | { type: "health_update"; health: HealthState }
  | { type: "adapter_bankroll"; cents: number | null; available: boolean }
  | { type: "set_target_floor"; targetCents: number; floorCents: number }
  | { type: "start_session" }
  | { type: "preparing_complete"; recommendation: Recommendation; bankrollCents: number }
  | { type: "wager_observed"; wager: WagerObservation; matches: boolean }
  | { type: "wager_fallback_needed"; betType: "DICE" | "COLOR" }
  | { type: "confirm_wager"; side?: "ORANGE" | "BLACK" }
  | { type: "result_observed"; outcome: RoundOutcome }
  | { type: "reconcile"; expectedCents: number; websiteCents: number; matches: boolean }
  | { type: "advance_recommendation"; recommendation: Recommendation; bankrollCents: number }
  | { type: "terminal"; reason: TerminalReason; bankrollCents: number; rounds: number }
  | { type: "show_stop_dialog" }
  | { type: "cancel_stop" }
  | { type: "confirm_stop" }
  | { type: "save_session"; csvPath?: string | null; jsonPath?: string | null }
  | { type: "discard_session" }
  | { type: "start_new" }
  | { type: "website_failure" }
  | { type: "mock_advance" };

function statusForView(state: CompanionUiState): UserStatusLabel {
  const { view, health, terminalReason } = state;
  if (health === "BACKEND_OFFLINE") return "Offline";
  if (health === "DESYNCED" || view === "wager_mismatch" || view === "bankroll_mismatch" || view === "policy_paused") {
    return "Paused";
  }
  switch (view) {
    case "setup":
      return health === "CONNECTED" ? "Connected" : "Paused";
    case "preparing":
      return "Preparing";
    case "active":
    case "wager_fallback_dice":
    case "wager_fallback_color":
      return "Waiting for wager";
    case "wager_confirmed":
    case "waiting_result":
    case "result_fallback":
      return "Waiting for result";
    case "result":
    case "reconciling":
      return "Checking bankroll";
    case "paused_offline":
      return "Offline";
    case "paused_website":
      return "Paused";
    case "terminal":
      return terminalReason === "TARGET" ? "Target reached" : "Session ended";
    case "completed":
      return "Session ended";
    default:
      return "Synced";
  }
}

function canStart(state: CompanionUiState): boolean {
  return (
    state.view === "setup" &&
    state.health === "CONNECTED" &&
    state.detectedBankrollCents != null &&
    state.targetCents != null &&
    state.floorCents != null &&
    state.targetCents > state.detectedBankrollCents &&
    state.detectedBankrollCents > state.floorCents
  );
}

export function reduceUiState(state: CompanionUiState, action: UiAction): CompanionUiState {
  let next: CompanionUiState = { ...state };

  switch (action.type) {
    case "health_update":
      if (action.health === "CONNECTED" && next.health === "DESYNCED") {
        break;
      }
      next.health = action.health;
      if (action.health === "BACKEND_OFFLINE" && next.sessionActive) {
        next.view = "paused_offline";
      }
      break;

    case "adapter_bankroll":
      next.detectedBankrollCents = action.cents;
      if (!next.sessionActive) {
        next.currentBankrollCents = action.cents;
      }
      if (!action.available && next.view === "setup") {
        next.health = "BANKROLL_UNAVAILABLE";
      }
      break;

    case "set_target_floor":
      next.targetCents = action.targetCents;
      next.floorCents = action.floorCents;
      break;

    case "start_session":
      next.view = "preparing";
      next.sessionActive = true;
      next.roundsCompleted = 0;
      next.recommendation = null;
      next.observedWager = null;
      next.roundOutcome = null;
      next.terminalReason = null;
      break;

    case "preparing_complete":
      next.view = "active";
      next.recommendation = action.recommendation;
      next.currentBankrollCents = action.bankrollCents;
      break;

    case "wager_observed":
      next.observedWager = action.wager;
      if (action.matches) {
        next.view = "wager_confirmed";
      } else {
        next.view = "wager_mismatch";
        next.health = "DESYNCED";
      }
      break;

    case "wager_fallback_needed":
      next.view = action.betType === "DICE" ? "wager_fallback_dice" : "wager_fallback_color";
      break;

    case "confirm_wager":
      next.observedWager = {
        betType: next.recommendation?.betType ?? "DICE",
        stakeCents: next.recommendation?.stakeCents ?? 0,
        colorSide: action.side,
      };
      next.view = "waiting_result";
      break;

    case "result_observed":
      next.roundOutcome = action.outcome;
      next.view = "result";
      break;

    case "reconcile":
      next.expectedBankrollCents = action.expectedCents;
      next.websiteBankrollCents = action.websiteCents;
      if (action.matches) {
        next.view = "reconciling";
      } else {
        next.view = "bankroll_mismatch";
        next.health = "DESYNCED";
      }
      break;

    case "advance_recommendation":
      next.roundsCompleted += 1;
      next.recommendation = action.recommendation;
      next.currentBankrollCents = action.bankrollCents;
      next.observedWager = null;
      next.roundOutcome = null;
      next.expectedBankrollCents = null;
      next.websiteBankrollCents = null;
      next.view = "active";
      next.health = "CONNECTED";
      break;

    case "terminal":
      next.view = "terminal";
      next.terminalReason = action.reason;
      next.currentBankrollCents = action.bankrollCents;
      next.roundsCompleted = action.rounds;
      next.recommendation = null;
      next.sessionActive = false;
      break;

    case "show_stop_dialog":
      next.view = "stop_dialog";
      break;

    case "cancel_stop":
      next.view = next.sessionActive ? viewForActiveSession(next.apiSessionStatus) : "setup";
      break;

    case "confirm_stop":
      next.view = "terminal";
      next.terminalReason = "USER_STOPPED";
      next.sessionActive = false;
      next.recommendation = null;
      break;

    case "save_session": {
      const bankroll = next.detectedBankrollCents;
      const backendUrl = next.backendUrl;
      const health =
        next.health === "DESYNCED" || next.health === "DOM_CHANGED"
          ? bankroll == null
            ? "BANKROLL_UNAVAILABLE"
            : "CONNECTED"
          : next.health;
      next = emptyUiState();
      next.backendUrl = backendUrl;
      next.detectedBankrollCents = bankroll;
      next.currentBankrollCents = bankroll;
      next.health = health;
      next.savedCsvPath = action.csvPath ?? null;
      next.savedJsonPath = action.jsonPath ?? null;
      break;
    }

    case "discard_session": {
      const bankroll = next.detectedBankrollCents;
      const backendUrl = next.backendUrl;
      const health =
        next.health === "DESYNCED" || next.health === "DOM_CHANGED"
          ? bankroll == null
            ? "BANKROLL_UNAVAILABLE"
            : "CONNECTED"
          : next.health;
      next = emptyUiState();
      next.backendUrl = backendUrl;
      next.detectedBankrollCents = bankroll;
      next.currentBankrollCents = bankroll;
      next.health = health;
      break;
    }

    case "start_new":
      return emptyUiState();

    case "website_failure":
      next.view = "paused_website";
      next.health = "DOM_CHANGED";
      break;

    case "mock_advance":
      // Demo progression for shell testing without companion API.
      return mockAdvance(next);

    default:
      break;
  }

  next.statusLabel = statusForView(next);
  next.canStart = canStart(next);
  return next;
}

function mockAdvance(state: CompanionUiState): CompanionUiState {
  const rec: Recommendation = state.recommendation ?? {
    betType: "DICE",
    stakeCents: 100,
    winBankrollCents: state.currentBankrollCents ?? 1000 + 1300,
    loseBankrollCents: state.currentBankrollCents ?? 1000 - 100,
  };
  const bankroll = state.currentBankrollCents ?? state.detectedBankrollCents ?? 1000;

  switch (state.view) {
    case "setup":
      if (!canStart({ ...state, canStart: false })) return state;
      return reduceUiState(state, { type: "start_session" });

    case "preparing":
      return reduceUiState(state, {
        type: "preparing_complete",
        recommendation: rec,
        bankrollCents: bankroll,
      });

    case "active":
      return reduceUiState(state, {
        type: "wager_observed",
        wager: { betType: rec.betType, stakeCents: rec.stakeCents },
        matches: true,
      });

    case "wager_confirmed":
      return reduceUiState(state, { type: "confirm_wager" });

    case "waiting_result":
      return reduceUiState(state, { type: "result_observed", outcome: "WIN" });

    case "result":
      const expected = rec.winBankrollCents;
      return reduceUiState(state, {
        type: "reconcile",
        expectedCents: expected,
        websiteCents: expected,
        matches: true,
      });

    case "reconciling":
      return reduceUiState(state, {
        type: "advance_recommendation",
        recommendation: {
          betType: "COLOR",
          stakeCents: 200,
          winBankrollCents: bankroll + 200,
          loseBankrollCents: bankroll - 200,
        },
        bankrollCents: bankroll + 100,
      });

    case "terminal":
      return reduceUiState(state, { type: "save_session" });

    default:
      return state;
  }
}

export function deriveHealthFromAdapter(
  bankrollAvailable: boolean,
  backendOk: boolean,
): HealthState {
  if (!backendOk) return "BACKEND_OFFLINE";
  if (!bankrollAvailable) return "BANKROLL_UNAVAILABLE";
  return "CONNECTED";
}
