/** Companion health states (plan §16). */
export type HealthState =
  | "CONNECTED"
  | "BACKEND_OFFLINE"
  | "PAGE_UNSUPPORTED"
  | "BANKROLL_UNAVAILABLE"
  | "ROUND_UNAVAILABLE"
  | "WAGER_UNAVAILABLE"
  | "RESULT_UNAVAILABLE"
  | "DOM_CHANGED"
  | "STALE"
  | "DESYNCED";

/** User-facing status labels (plan §41). */
export type UserStatusLabel =
  | "Connected"
  | "Preparing"
  | "Ready"
  | "Waiting for wager"
  | "Wager detected"
  | "Waiting for round to finish"
  | "Waiting for result"
  | "Settling…"
  | "Syncing bankroll"
  | "Checking bankroll"
  | "Balance resynced"
  | "Synced"
  | "Paused"
  | "Offline"
  | "Target reached"
  | "Session ended";

export type BetType = "COLOR" | "DICE";
export type ColorSide = "ORANGE" | "BLACK";
export type RoundOutcome = "WIN" | "LOSS" | "DIVERGENCE";

export interface WagerObservation {
  betType: BetType;
  stakeCents: number;
  colorSide?: ColorSide;
}

export interface Recommendation {
  betType: BetType;
  stakeCents: number;
  winBankrollCents: number;
  loseBankrollCents: number;
  targetHitProbability?: number | null;
  consecutiveLossDurability?: number | null;
}

export type SessionView =
  | "setup"
  | "preparing"
  | "active"
  | "wager_confirmed"
  | "wager_fallback_dice"
  | "wager_fallback_color"
  | "wager_mismatch"
  | "policy_paused"
  | "waiting_result"
  | "result_fallback"
  | "result"
  | "reconciling"
  | "bankroll_mismatch"
  | "paused_offline"
  | "paused_website"
  | "terminal"
  | "stop_dialog"
  | "completed";

export type TerminalReason = "TARGET" | "FLOOR" | "NO_ACTION" | "USER_STOPPED";

export interface CompanionUiState {
  view: SessionView;
  health: HealthState;
  statusLabel: UserStatusLabel;
  backendUrl: string;
  detectedBankrollCents: number | null;
  targetCents: number | null;
  floorCents: number | null;
  currentBankrollCents: number | null;
  recommendation: Recommendation | null;
  /** Same Live Play fields — updated on start and every logical settlement. */
  targetHitProbability: number | null;
  consecutiveLossDurability: number | null;
  observedWager: WagerObservation | null;
  expectedBankrollCents: number | null;
  websiteBankrollCents: number | null;
  roundOutcome: RoundOutcome | null;
  terminalReason: TerminalReason | null;
  roundsCompleted: number;
  canStart: boolean;
  sessionActive: boolean;
  mockMode: boolean;
  backendSessionId: string | null;
  apiSessionStatus: string | null;
  savedCsvPath: string | null;
  savedJsonPath: string | null;
}

export const DEFAULT_BACKEND_URL = "http://localhost:8000";

export function emptyUiState(): CompanionUiState {
  return {
    view: "setup",
    health: "CONNECTED",
    statusLabel: "Connected",
    backendUrl: DEFAULT_BACKEND_URL,
    detectedBankrollCents: null,
    targetCents: null,
    floorCents: null,
    currentBankrollCents: null,
    recommendation: null,
    targetHitProbability: null,
    consecutiveLossDurability: null,
    observedWager: null,
    expectedBankrollCents: null,
    websiteBankrollCents: null,
    roundOutcome: null,
    terminalReason: null,
    roundsCompleted: 0,
    canStart: false,
    sessionActive: false,
    mockMode: false,
    backendSessionId: null,
    apiSessionStatus: null,
    savedCsvPath: null,
    savedJsonPath: null,
  };
}
