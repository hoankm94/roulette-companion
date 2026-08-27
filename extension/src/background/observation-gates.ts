import {
  AMBIGUOUS_PERSISTENCE_POLLS,
  BANKROLL_POLL_MS,
  BANKROLL_RECONCILIATION_WARN_MS,
  FINAL_BANKROLL_STABLE_POLLS,
  FINAL_BANKROLL_TIMEOUT_MS,
} from "../shared/timing.js";
import { deriveRouletteResult } from "../adapters/csgoempire/parseObservation.js";
import type {
  BettingState,
  ButtonObs,
  ObservedWager,
  ObservationStatus,
  RouletteResultStatus,
  WagerButtonObservations,
  WagerFamily,
  WagerSide,
} from "../adapters/types.js";

/** Pure gates for DOM wager + result-driven Companion automation. */

export {
  AMBIGUOUS_PERSISTENCE_POLLS,
  BANKROLL_POLL_MS,
  BANKROLL_RECONCILIATION_WARN_MS,
  FINAL_BANKROLL_STABLE_POLLS,
  FINAL_BANKROLL_TIMEOUT_MS,
};

export { deriveRouletteResult };

export type DomWagerDetectResult =
  | { kind: "NONE" }
  | { kind: "VALID"; wager: ObservedWager }
  | { kind: "MULTIPLE_WAGERS"; count: number }
  | { kind: "AMBIGUOUS" };

export type WagerMatchStatus = "MATCH" | "MISMATCH";

export type BankrollReconciliationStatus = "IDLE" | "PENDING" | "SYNCED" | "WARNING";

export type ResultSettlementAction = "NONE" | "SETTLE" | "WAIT";

export interface ResultSettlementResult {
  action: ResultSettlementAction;
  winnerSide: WagerSide | null;
  resultStatus: RouletteResultStatus;
}

/** @deprecated Bankroll-driven settlement — kept for transitional tests. */
export type FinalBankrollSettlementAction =
  | "NONE"
  | "SETTLE_WIN"
  | "SETTLE_LOSS"
  | "SETTLE_TERMINAL_TARGET"
  | "SETTLE_TERMINAL_FLOOR"
  | "TIMEOUT_DIVERGENCE";

/** @deprecated */
export interface FinalBankrollSettlementResult {
  action: FinalBankrollSettlementAction;
  lossStablePolls: number;
}

function buttonForSide(wagers: WagerButtonObservations, side: WagerSide): ButtonObs {
  switch (side) {
    case "DICE":
      return wagers.dice;
    case "BLACK":
      return wagers.black;
    case "ORANGE":
      return wagers.orange;
  }
}

/** True when a placed button exists but stake amount is unreadable. */
export function hasPlacedWithoutAmount(wagers: WagerButtonObservations): boolean {
  return [wagers.dice, wagers.black, wagers.orange].some(
    (b) => b.placed && b.amountCents == null,
  );
}

/** DOM-primary wager detection from normalized placedWagers. */
export function evaluateDomWagerDetection(opts: {
  placedWagers: ObservedWager[];
  wagers: WagerButtonObservations;
  ambiguousPolls: number;
  ambiguousThreshold?: number;
}): DomWagerDetectResult {
  const threshold = opts.ambiguousThreshold ?? AMBIGUOUS_PERSISTENCE_POLLS;

  if (opts.placedWagers.length > 1) {
    return { kind: "MULTIPLE_WAGERS", count: opts.placedWagers.length };
  }
  if (opts.placedWagers.length === 1) {
    return { kind: "VALID", wager: opts.placedWagers[0]! };
  }
  if (hasPlacedWithoutAmount(opts.wagers)) {
    if (opts.ambiguousPolls >= threshold) {
      return { kind: "AMBIGUOUS" };
    }
    return { kind: "NONE" };
  }
  return { kind: "NONE" };
}

/** Compare observed DOM wager against current recommendation. */
export function compareWagerToRecommendation(
  wager: ObservedWager,
  recommendation: {
    betType: "DICE" | "COLOR" | "ORANGE" | "BLACK";
    stakeCents: number;
    colorSide?: "ORANGE" | "BLACK";
  },
): WagerMatchStatus {
  if (wager.stakeCents !== recommendation.stakeCents) {
    return "MISMATCH";
  }
  if (recommendation.betType === "DICE") {
    return wager.family === "DICE" && wager.side === "DICE" ? "MATCH" : "MISMATCH";
  }
  if (wager.family !== "COLOR") return "MISMATCH";
  const recommendedSide =
    recommendation.colorSide ??
    (recommendation.betType === "ORANGE" || recommendation.betType === "BLACK"
      ? recommendation.betType
      : null);
  if (recommendedSide == null) {
    return "MATCH";
  }
  return wager.side === recommendedSide ? "MATCH" : "MISMATCH";
}

/** Mark seenClosed when BETTING_STATE is confidently CLOSED. */
export function advanceSeenClosed(opts: {
  seenClosed: boolean;
  bettingStatus: ObservationStatus | null | undefined;
  bettingState: BettingState | null | undefined;
}): boolean {
  if (opts.bettingStatus === "AVAILABLE" && opts.bettingState === "CLOSED") {
    return true;
  }
  return opts.seenClosed;
}

/**
 * Settle when a complete win/loss result snapshot is observed (once).
 * Does not wait for OPEN or website bankroll.
 */
export function evaluateResultSettlement(opts: {
  resultHandled: boolean;
  resultStatus: RouletteResultStatus;
  winningSide: WagerSide | null;
}): ResultSettlementResult {
  if (opts.resultHandled) {
    return { action: "NONE", winnerSide: null, resultStatus: opts.resultStatus };
  }
  if (opts.resultStatus === "COMPLETE" && opts.winningSide != null) {
    return {
      action: "SETTLE",
      winnerSide: opts.winningSide,
      resultStatus: "COMPLETE",
    };
  }
  if (opts.resultStatus === "AMBIGUOUS" || opts.resultStatus === "NONE") {
    return {
      action: "WAIT",
      winnerSide: null,
      resultStatus: opts.resultStatus,
    };
  }
  return { action: "WAIT", winnerSide: null, resultStatus: opts.resultStatus };
}

/** Re-arm next wager detection after result handled + controls reset. */
export function shouldRearmWagerDetection(opts: {
  resultHandled: boolean;
  bettingStatus: ObservationStatus | null | undefined;
  bettingState: BettingState | null | undefined;
  resultStatus: RouletteResultStatus;
  placedWagers: ObservedWager[];
}): boolean {
  if (!opts.resultHandled) return false;
  if (opts.bettingStatus !== "AVAILABLE" || opts.bettingState !== "OPEN") return false;
  if (opts.placedWagers.length > 0) return false;
  return true;
}

/** Background bankroll reconciliation (non-blocking). */
export function evaluateBankrollReconciliation(opts: {
  status: BankrollReconciliationStatus;
  expectedLogicalCents: number | null;
  observedBankrollCents: number | null;
  startedAtMs: number | null;
  nowMs: number;
  warnMs?: number;
}): BankrollReconciliationStatus {
  if (opts.status === "IDLE" || opts.status === "SYNCED") return opts.status;
  if (opts.expectedLogicalCents == null) return opts.status;
  if (
    opts.observedBankrollCents != null &&
    opts.observedBankrollCents === opts.expectedLogicalCents
  ) {
    return "SYNCED";
  }
  const warnMs = opts.warnMs ?? BANKROLL_RECONCILIATION_WARN_MS;
  if (
    opts.status === "PENDING" &&
    opts.startedAtMs != null &&
    opts.nowMs - opts.startedAtMs >= warnMs
  ) {
    return "WARNING";
  }
  return opts.status;
}

/**
 * @deprecated CLOSED then OPEN entered WAITING_FOR_FINAL_BANKROLL — no longer used
 * for settlement. Kept for transitional imports/tests.
 */
export function shouldEnterFinalBankrollWait(opts: {
  seenClosed: boolean;
  waitingForFinalBankroll: boolean;
  bettingStatus: ObservationStatus | null | undefined;
  bettingState: BettingState | null | undefined;
}): boolean {
  if (opts.waitingForFinalBankroll) return false;
  if (!opts.seenClosed) return false;
  if (opts.bettingStatus !== "AVAILABLE") return false;
  return opts.bettingState === "OPEN";
}

/** @deprecated Use shouldEnterFinalBankrollWait — kept for transitional imports. */
export function shouldSettleOnBettingBoundary(opts: {
  seenClosed: boolean;
  bettingStatus: ObservationStatus | null | undefined;
  bettingState: BettingState | null | undefined;
}): boolean {
  return shouldEnterFinalBankrollWait({
    seenClosed: opts.seenClosed,
    waitingForFinalBankroll: false,
    bettingStatus: opts.bettingStatus,
    bettingState: opts.bettingState,
  });
}

/** Supporting evidence: placed side shows bet-btn--win. */
export function isWinExpectedFromWagers(
  wagers: WagerButtonObservations,
  placedSide: WagerSide,
): boolean {
  const button = buttonForSide(wagers, placedSide);
  return button.placed && button.won;
}

/** @deprecated State-driven bankroll settlement — replaced by evaluateResultSettlement. */
export function evaluateFinalBankrollSettlement(opts: {
  bankrollCents: number | null | undefined;
  expectedWinCents: number;
  expectedLossCents: number;
  targetCents: number;
  floorCents: number;
  winExpected: boolean;
  lossStablePolls: number;
  stablePollsRequired?: number;
  elapsedMs: number;
  timeoutMs?: number;
}): FinalBankrollSettlementResult {
  const stableRequired = opts.stablePollsRequired ?? FINAL_BANKROLL_STABLE_POLLS;
  const timeoutMs = opts.timeoutMs ?? FINAL_BANKROLL_TIMEOUT_MS;
  const bankroll = opts.bankrollCents;

  if (bankroll == null) {
    if (opts.elapsedMs >= timeoutMs) {
      return { action: "TIMEOUT_DIVERGENCE", lossStablePolls: 0 };
    }
    return { action: "NONE", lossStablePolls: 0 };
  }

  if (bankroll === opts.expectedWinCents) {
    return { action: "SETTLE_WIN", lossStablePolls: 0 };
  }
  if (bankroll >= opts.targetCents) {
    return { action: "SETTLE_TERMINAL_TARGET", lossStablePolls: 0 };
  }
  if (bankroll <= opts.floorCents) {
    return { action: "SETTLE_TERMINAL_FLOOR", lossStablePolls: 0 };
  }

  if (bankroll === opts.expectedLossCents) {
    if (opts.winExpected) {
      return { action: "NONE", lossStablePolls: 0 };
    }
    const nextStable = opts.lossStablePolls + 1;
    if (nextStable >= stableRequired) {
      return { action: "SETTLE_LOSS", lossStablePolls: nextStable };
    }
    return { action: "NONE", lossStablePolls: nextStable };
  }

  if (opts.elapsedMs >= timeoutMs) {
    return { action: "TIMEOUT_DIVERGENCE", lossStablePolls: 0 };
  }
  return { action: "NONE", lossStablePolls: 0 };
}

/** Diagnostics payload when bankroll reconciliation times out (non-blocking warn). */
export interface SettlementTimeoutDiagnostics {
  preWagerBankrollCents: number;
  observedWagerSide: WagerSide;
  observedWagerFamily: WagerFamily;
  observedStakeCents: number;
  recommendedWager: { betType: "DICE" | "COLOR"; stakeCents: number } | null;
  expectedLossCents: number;
  expectedWinCents: number;
  currentObservedBankrollCents: number | null;
  resultStateEvidence: {
    placedSide: WagerSide;
    winExpected: boolean;
    lost: boolean;
  };
  bettingState: BettingState | null;
  bettingStatus: ObservationStatus | null;
  elapsedSettlementWaitMs: number;
}

export function buildSettlementTimeoutDiagnostics(opts: {
  preWagerBankrollCents: number;
  observedWager: ObservedWager;
  recommendation: { betType: "DICE" | "COLOR"; stakeCents: number } | null;
  expectedWinCents: number;
  expectedLossCents: number;
  currentObservedBankrollCents: number | null;
  wagers: WagerButtonObservations;
  placedSide: WagerSide;
  bettingState: BettingState | null;
  bettingStatus: ObservationStatus | null;
  elapsedSettlementWaitMs: number;
}): SettlementTimeoutDiagnostics {
  const button = buttonForSide(opts.wagers, opts.placedSide);
  return {
    preWagerBankrollCents: opts.preWagerBankrollCents,
    observedWagerSide: opts.observedWager.side,
    observedWagerFamily: opts.observedWager.family,
    observedStakeCents: opts.observedWager.stakeCents,
    recommendedWager: opts.recommendation,
    expectedLossCents: opts.expectedLossCents,
    expectedWinCents: opts.expectedWinCents,
    currentObservedBankrollCents: opts.currentObservedBankrollCents,
    resultStateEvidence: {
      placedSide: opts.placedSide,
      winExpected: isWinExpectedFromWagers(opts.wagers, opts.placedSide),
      lost: button.lost,
    },
    bettingState: opts.bettingState,
    bettingStatus: opts.bettingStatus,
    elapsedSettlementWaitMs: opts.elapsedSettlementWaitMs,
  };
}

/** @deprecated Prefer isRoundBoundaryOpen for legacy phase fallback. */
export function isRoundBoundaryOpen(opts: {
  previousPhase: string | null | undefined;
  currentPhase: string | null | undefined;
}): boolean {
  const prev = opts.previousPhase;
  const cur = opts.currentPhase;
  if (cur !== "OPEN") return false;
  if (prev == null || prev === "OPEN" || prev === "UNKNOWN") return false;
  return true;
}

/** @deprecated Prefer betting-controls boundary; kept until live E2E cleanup. */
export function isHistoryBoundary(opts: {
  previousFingerprint: string | null | undefined;
  currentFingerprint: string | null | undefined;
}): boolean {
  if (!opts.currentFingerprint || !opts.previousFingerprint) return false;
  return opts.currentFingerprint !== opts.previousFingerprint;
}

import { isLegacyFallbackBlocked } from "./legacy-fallback-gates.js";

/** @deprecated Manual wager confirm is retired; always false. */
export function shouldOfferWagerFallback(opts: {
  sessionStatus: string | null | undefined;
  view: string;
  canReadWager: boolean;
  alreadyOffered: boolean;
}): boolean {
  if (isLegacyFallbackBlocked(opts.sessionStatus)) return false;
  return false;
}

/** @deprecated Manual result confirm is retired; always false. */
export function shouldOfferResultFallback(opts: {
  sessionStatus: string | null | undefined;
  canReadResult: boolean;
  alreadyOffered: boolean;
}): boolean {
  if (isLegacyFallbackBlocked(opts.sessionStatus)) return false;
  return false;
}

/** Stable client round id when website round id is unavailable. */
export function manualRoundId(sessionId: string, roundsCompleted: number): string {
  return `manual-${sessionId}-r${roundsCompleted}`;
}

/** Pure reducer for simulated gate sequences (tests + diagnostics). */
export type CompanionRoundSimState = {
  sessionStatus: "WAITING_FOR_WAGER" | "ROUND_PENDING";
  seenClosed: boolean;
  resultHandled: boolean;
  domWagerRegistered: boolean;
  ambiguousPolls: number;
  bankrollReconciliation: BankrollReconciliationStatus;
  expectedLogicalCents: number | null;
  reconcilStartedAtMs: number | null;
  nowMs: number;
  settlements: number;
  roundBaseline: {
    expectedWinCents: number;
    expectedLossCents: number;
    placedSide: WagerSide;
  } | null;
  /** @deprecated */
  waitingForFinalBankroll?: boolean;
  /** @deprecated */
  lossStablePolls?: number;
  /** @deprecated */
  waitStartedAtMs?: number | null;
};

export function reduceCompanionRoundTick(
  state: CompanionRoundSimState,
  tick: {
    placedWagers: ObservedWager[];
    wagers: WagerButtonObservations;
    bettingStatus: ObservationStatus;
    bettingState: BettingState | null;
    bankrollCents: number | null;
    targetCents: number;
    floorCents: number;
    recommendation: {
      betType: "DICE" | "COLOR";
      stakeCents: number;
      winBankrollCents: number;
      loseBankrollCents: number;
    } | null;
    resultStatus?: RouletteResultStatus;
    winningSide?: WagerSide | null;
  },
): CompanionRoundSimState {
  const next = { ...state };
  const derived =
    tick.resultStatus != null
      ? { status: tick.resultStatus, winnerSide: tick.winningSide ?? null }
      : deriveRouletteResult(tick.wagers);
  const resultStatus = derived.status;
  const winningSide =
    derived.status === "COMPLETE" && "winnerSide" in derived && derived.winnerSide
      ? derived.winnerSide
      : (tick.winningSide ?? null);

  if (next.sessionStatus === "WAITING_FOR_WAGER") {
    next.seenClosed = false;
    if (next.resultHandled) {
      if (
        shouldRearmWagerDetection({
          resultHandled: next.resultHandled,
          bettingStatus: tick.bettingStatus,
          bettingState: tick.bettingState,
          resultStatus,
          placedWagers: tick.placedWagers,
        })
      ) {
        next.resultHandled = false;
        next.domWagerRegistered = false;
        next.roundBaseline = null;
      }
    }

    next.bankrollReconciliation = evaluateBankrollReconciliation({
      status: next.bankrollReconciliation,
      expectedLogicalCents: next.expectedLogicalCents,
      observedBankrollCents: tick.bankrollCents,
      startedAtMs: next.reconcilStartedAtMs,
      nowMs: next.nowMs,
    });

    if (next.resultHandled || next.domWagerRegistered) {
      return next;
    }

    const detection = evaluateDomWagerDetection({
      placedWagers: tick.placedWagers,
      wagers: tick.wagers,
      ambiguousPolls: next.ambiguousPolls,
    });
    if (detection.kind === "AMBIGUOUS") {
      next.ambiguousPolls += 1;
      return next;
    }
    if (detection.kind === "NONE" && hasPlacedWithoutAmount(tick.wagers)) {
      next.ambiguousPolls += 1;
      return next;
    }
    next.ambiguousPolls = 0;
    if (detection.kind !== "VALID" || !tick.recommendation) return next;

    next.domWagerRegistered = true;
    next.sessionStatus = "ROUND_PENDING";
    next.resultHandled = false;
    next.roundBaseline = {
      expectedWinCents: tick.recommendation.winBankrollCents,
      expectedLossCents: tick.recommendation.loseBankrollCents,
      placedSide: detection.wager.side,
    };
    return next;
  }

  // ROUND_PENDING
  next.seenClosed = advanceSeenClosed({
    seenClosed: next.seenClosed,
    bettingStatus: tick.bettingStatus,
    bettingState: tick.bettingState,
  });

  const settlement = evaluateResultSettlement({
    resultHandled: next.resultHandled,
    resultStatus,
    winningSide,
  });

  if (
    settlement.action === "SETTLE" &&
    (next.roundBaseline != null || next.sessionStatus === "ROUND_PENDING")
  ) {
    const win =
      next.roundBaseline != null &&
      settlement.winnerSide === next.roundBaseline.placedSide;
    next.settlements += 1;
    next.sessionStatus = "WAITING_FOR_WAGER";
    next.resultHandled = true;
    next.domWagerRegistered = true; // block until re-arm
    next.expectedLogicalCents =
      next.roundBaseline == null
        ? null
        : win
          ? next.roundBaseline.expectedWinCents
          : next.roundBaseline.expectedLossCents;
    next.bankrollReconciliation = "PENDING";
    next.reconcilStartedAtMs = next.nowMs;
    next.roundBaseline = null;
    return next;
  }

  next.bankrollReconciliation = evaluateBankrollReconciliation({
    status: next.bankrollReconciliation,
    expectedLogicalCents: next.expectedLogicalCents,
    observedBankrollCents: tick.bankrollCents,
    startedAtMs: next.reconcilStartedAtMs,
    nowMs: next.nowMs,
  });

  return next;
}
