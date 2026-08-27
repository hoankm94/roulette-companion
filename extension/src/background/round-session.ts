import type { ObservedWager, WagerSide } from "../adapters/types.js";

/** chrome.storage.session key for MV3 durable round reclaim. */
export const ROUND_SESSION_STORAGE_KEY = "companion_round_session";

export type RoundBaseline = {
  preWagerBankrollCents: number;
  expectedWinCents: number;
  expectedLossCents: number;
  placedSide: WagerSide;
  observedWager: ObservedWager;
};

export type PersistedCompanionRoundSession = {
  sessionId: string;
  domWagerRegistered: boolean;
  resultHandled: boolean;
  seenClosed: boolean;
  pendingSettlement: boolean;
  roundBaseline: RoundBaseline | null;
};

/** Minimal storage surface (chrome.storage.session or test double). */
export type RoundSessionStorage = {
  get(keys: string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
  remove(keys: string[]): Promise<void>;
};

/**
 * Settle eligibility after SW death: ROUND_PENDING from API is enough;
 * in-memory baseline is preferred but not required.
 */
export function canAttemptResultSettlement(opts: {
  sessionId: string | null | undefined;
  apiSessionStatus: string | null | undefined;
  roundBaseline: RoundBaseline | null;
}): boolean {
  if (!opts.sessionId) return false;
  if (opts.roundBaseline != null) return true;
  return opts.apiSessionStatus === "ROUND_PENDING";
}

export function snapshotRoundSession(opts: {
  sessionId: string | null | undefined;
  domWagerRegistered: boolean;
  resultHandled: boolean;
  seenClosed: boolean;
  pendingSettlement: boolean;
  roundBaseline: RoundBaseline | null;
}): PersistedCompanionRoundSession | null {
  if (!opts.sessionId) return null;
  return {
    sessionId: opts.sessionId,
    domWagerRegistered: opts.domWagerRegistered,
    resultHandled: opts.resultHandled,
    seenClosed: opts.seenClosed,
    pendingSettlement: opts.pendingSettlement,
    roundBaseline: opts.roundBaseline,
  };
}

function isWagerSide(v: unknown): v is WagerSide {
  return v === "DICE" || v === "ORANGE" || v === "BLACK";
}

function parseBaseline(raw: unknown): RoundBaseline | null {
  if (raw == null) return null;
  if (typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (
    typeof o.preWagerBankrollCents !== "number" ||
    typeof o.expectedWinCents !== "number" ||
    typeof o.expectedLossCents !== "number" ||
    !isWagerSide(o.placedSide) ||
    o.observedWager == null ||
    typeof o.observedWager !== "object"
  ) {
    return null;
  }
  const w = o.observedWager as Record<string, unknown>;
  if (
    !isWagerSide(w.side) ||
    (w.family !== "DICE" && w.family !== "COLOR") ||
    typeof w.stakeCents !== "number" ||
    typeof w.source !== "string"
  ) {
    return null;
  }
  return {
    preWagerBankrollCents: o.preWagerBankrollCents,
    expectedWinCents: o.expectedWinCents,
    expectedLossCents: o.expectedLossCents,
    placedSide: o.placedSide,
    observedWager: {
      side: w.side,
      family: w.family,
      stakeCents: w.stakeCents,
      source: w.source as ObservedWager["source"],
    },
  };
}

export function parsePersistedRoundSession(
  raw: unknown,
): PersistedCompanionRoundSession | null {
  if (raw == null || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.sessionId !== "string" || o.sessionId.length === 0) return null;
  return {
    sessionId: o.sessionId,
    domWagerRegistered: Boolean(o.domWagerRegistered),
    resultHandled: Boolean(o.resultHandled),
    seenClosed: Boolean(o.seenClosed),
    pendingSettlement: Boolean(o.pendingSettlement),
    roundBaseline: parseBaseline(o.roundBaseline),
  };
}

export async function loadPersistedRoundSession(
  storage: RoundSessionStorage,
): Promise<PersistedCompanionRoundSession | null> {
  const raw = await storage.get([ROUND_SESSION_STORAGE_KEY]);
  return parsePersistedRoundSession(raw[ROUND_SESSION_STORAGE_KEY]);
}

export async function savePersistedRoundSession(
  storage: RoundSessionStorage,
  snapshot: PersistedCompanionRoundSession | null,
): Promise<void> {
  if (snapshot == null) {
    await storage.remove([ROUND_SESSION_STORAGE_KEY]);
    return;
  }
  await storage.set({ [ROUND_SESSION_STORAGE_KEY]: snapshot });
}

export async function clearPersistedRoundSession(
  storage: RoundSessionStorage,
): Promise<void> {
  await storage.remove([ROUND_SESSION_STORAGE_KEY]);
}
