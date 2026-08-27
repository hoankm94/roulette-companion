export type { ObservationStatus, CapabilityReading } from "./csgoempire/readings.js";
import type { CapabilityReading } from "./csgoempire/readings.js";

export const ADAPTER_CAPABILITIES = [
  "CAN_READ_BANKROLL",
  "CAN_READ_ROUND_ID",
  "CAN_READ_RESULT",
  "CAN_READ_WAGER_TYPE",
  "CAN_READ_WAGER_STAKE",
  "CAN_READ_COLOR_SIDE",
  "BETTING_STATE",
] as const;

export type AdapterCapability = (typeof ADAPTER_CAPABILITIES)[number];

export type RoundPhase = "OPEN" | "CLOSED" | "RESULT" | "UNKNOWN";

/** Roulette bet-controls window (Dice/Black/Orange aggregate). */
export type BettingState = "OPEN" | "CLOSED";

export type RoundResult = "DICE" | "ORANGE" | "BLACK" | "GREEN";

export type WagerType = "DICE" | "COLOR";

export type ColorSide = "ORANGE" | "BLACK";

/** Roulette wager control side (Dice / Black / Orange). */
export type WagerSide = "DICE" | "BLACK" | "ORANGE";

export type WagerFamily = "DICE" | "COLOR";

/** Complete roulette result from win/loss button classes. */
export type RouletteResultStatus = "NONE" | "COMPLETE" | "AMBIGUOUS" | "UNAVAILABLE";

export type ObservedWagerSource = "DOM_PLACED_BUTTON";

/** Per-button DOM observation for Dice / Black / Orange controls. */
export interface ButtonObs {
  present: boolean;
  side: WagerSide;
  family: WagerFamily;
  placed: boolean;
  amountCents: number | null;
  rolling: boolean;
  disabled: boolean;
  won: boolean;
  lost: boolean;
  disableAttr: string | null;
}

export interface ObservedWager {
  side: WagerSide;
  family: WagerFamily;
  stakeCents: number;
  source: ObservedWagerSource;
}

export interface WagerButtonObservations {
  dice: ButtonObs;
  black: ButtonObs;
  orange: ButtonObs;
}

export type AdapterIssueCode =
  | "PAGE_UNSUPPORTED"
  | "DOM_CHANGED"
  | "BANKROLL_UNAVAILABLE"
  | "BANKROLL_AMBIGUOUS"
  | "ROUND_UNAVAILABLE"
  | "WAGER_UNAVAILABLE"
  | "RESULT_UNAVAILABLE";

export interface WebsiteObservationReadings {
  bankroll: CapabilityReading<number>;
  roundId: CapabilityReading<string>;
  phase: CapabilityReading<RoundPhase>;
  result: CapabilityReading<RoundResult>;
  wagerType: CapabilityReading<WagerType>;
  wagerStakeCents: CapabilityReading<number>;
  colorSide: CapabilityReading<ColorSide>;
  bettingState: CapabilityReading<BettingState>;
}

export interface WebsiteObservation {
  /** Flat values — only set when the matching reading status is AVAILABLE. */
  bankrollCents: number | null;
  roundId: string | null;
  phase: RoundPhase | null;
  result: RoundResult | null;
  wagerType: WagerType | null;
  wagerStakeCents: number | null;
  colorSide: ColorSide | null;
  /** Aggregate Roulette bet-controls: OPEN / CLOSED when AVAILABLE. */
  bettingState: BettingState | null;
  /** Per-control wager DOM state (Dice / Black / Orange). */
  wagers: WagerButtonObservations;
  /** Placed buttons with a readable stake amount. */
  placedWagers: ObservedWager[];
  /** Winning side when resultStatus is COMPLETE. */
  winningSide: WagerSide | null;
  /** Normalized win/loss class completeness. */
  resultStatus: RouletteResultStatus;
  /** Fingerprint of latest history entry for round-boundary fallback. */
  historyFingerprint: string | null;
  observedAt: number;
  readings: WebsiteObservationReadings;
}

export interface AdapterHealth {
  siteSupported: boolean;
  capabilities: ReadonlySet<AdapterCapability>;
  issues: AdapterIssueCode[];
}

export type ObservationListener = (observation: WebsiteObservation) => void;

export interface SiteAdapter {
  readonly siteId: string;
  start(root?: Document | Element): void;
  stop(): void;
  probeCapabilities(root?: Document | Element): ReadonlySet<AdapterCapability>;
  getHealth(): AdapterHealth;
  readObservation(root?: Document | Element): WebsiteObservation | null;
  onObservation(listener: ObservationListener): () => void;
}

function wagerButtonFingerprint(button: ButtonObs): Record<string, unknown> {
  return {
    placed: button.placed,
    amountCents: button.amountCents,
    rolling: button.rolling,
    disabled: button.disabled,
    won: button.won,
    lost: button.lost,
  };
}

export function observationSnapshotKey(observation: WebsiteObservation): string {
  return JSON.stringify({
    bankrollCents: observation.bankrollCents,
    roundId: observation.roundId,
    phase: observation.phase,
    result: observation.result,
    wagerType: observation.wagerType,
    wagerStakeCents: observation.wagerStakeCents,
    colorSide: observation.colorSide,
    bettingState: observation.bettingState,
    bettingStatus: observation.readings?.bettingState.status,
    historyFingerprint: observation.historyFingerprint,
    bankrollStatus: observation.readings?.bankroll.status,
    wagerStatus: observation.readings?.wagerType.status,
    historyResultStatus: observation.readings?.result.status,
    rouletteResultStatus: observation.resultStatus,
    winningSide: observation.winningSide,
    wagers: {
      dice: wagerButtonFingerprint(observation.wagers.dice),
      black: wagerButtonFingerprint(observation.wagers.black),
      orange: wagerButtonFingerprint(observation.wagers.orange),
    },
    placedWagers: observation.placedWagers.map((w) => ({
      side: w.side,
      stakeCents: w.stakeCents,
    })),
  });
}
