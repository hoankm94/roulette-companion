import { parseMoneyToCents, tryParseMoneyToCents } from "../money/parseMoney.js";

export type MoneyParseResult =
  | { ok: true; cents: number }
  | { ok: false; error: string };

export { parseMoneyToCents, tryParseMoneyToCents, MoneyParseError } from "../money/parseMoney.js";

/** Format integer cents for display. */
export function formatCents(cents: number | null | undefined): string {
  if (cents == null || !Number.isFinite(cents)) return "—";
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100);
  const frac = abs % 100;
  const formatted = `${dollars.toLocaleString("en-US")}.${frac.toString().padStart(2, "0")}`;
  return negative ? `-$${formatted}` : `$${formatted}`;
}

/** Parse user dollar input to cents. */
export function parseDollarInput(raw: string): MoneyParseResult {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: false, error: "Required" };
  const cleaned = trimmed.replace(/^\$/, "").replace(/,/g, "");
  try {
    return { ok: true, cents: parseMoneyToCents(cleaned) };
  } catch {
    return { ok: false, error: "Enter a valid dollar amount" };
  }
}

export function parseMoneyToCentsSafe(raw: string): MoneyParseResult {
  const cents = tryParseMoneyToCents(raw);
  if (cents == null) return { ok: false, error: "Invalid money format" };
  return { ok: true, cents };
}

/** True while the user is mid-decimal (e.g. "30.") — avoid aggressive validation. */
export function isIncompleteMoneyDraft(raw: string): boolean {
  const trimmed = raw.trim();
  if (!trimmed) return false;
  if (/\.$/.test(trimmed) || trimmed === "." || trimmed === "$." || trimmed === "$.") return true;
  if (!/^\$?[\d,]*\.?\d*$/.test(trimmed)) return false;
  return !parseDollarInput(trimmed).ok;
}

/** Validate session money: target > bankroll > floor ≥ 0. */
export function validateSessionMoney(
  bankrollCents: number,
  targetRaw: string,
  floorRaw: string,
): { ok: true; targetCents: number; floorCents: number } | { ok: false; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const targetTrim = targetRaw.trim();
  const floorTrim = floorRaw.trim();
  const target = parseDollarInput(targetRaw);
  const floor = parseDollarInput(floorRaw);

  if (!target.ok) errors.target = targetTrim ? target.error : "Enter a target.";
  if (!floor.ok) errors.floor = floorTrim ? floor.error : "Enter a hard floor.";

  if (target.ok && floor.ok) {
    const bankFmt = formatCents(bankrollCents);
    if (!(target.cents > bankrollCents)) {
      errors.target = `Target must be greater than current bankroll (${bankFmt}).`;
    }
    if (!(bankrollCents > floor.cents)) {
      errors.floor = `Hard floor must be below current bankroll (${bankFmt}).`;
    } else if (floor.cents < 0) {
      errors.floor = "Hard floor must be ≥ 0.";
    }
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    targetCents: (target as { ok: true; cents: number }).cents,
    floorCents: (floor as { ok: true; cents: number }).cents,
  };
}

export type SetupStartGate = {
  canStart: boolean;
  /** Concise reason when Start cannot proceed; null while typing an incomplete draft. */
  reason: string | null;
};

/** Format cents as placeholder dollars without currency symbol (e.g. "15.01"). */
export function centsToPlaceholder(cents: number): string {
  const abs = Math.abs(Math.trunc(cents));
  const dollars = Math.floor(abs / 100);
  const frac = abs % 100;
  return `${dollars}.${frac.toString().padStart(2, "0")}`;
}

/** Exact dollar amount for API JSON (avoids float cents/100 drift e.g. 2819 → 28.19). */
export function centsToDollarAmount(cents: number): number {
  return Number(centsToPlaceholder(Math.trunc(cents)));
}

/**
 * Dynamic setup placeholders from trusted bankroll (integer cents).
 * Target = bankroll × 1.07; Hard Floor = bankroll / 3 on bankroll_step grid.
 */
export function setupPlaceholders(
  bankrollCents: number,
  bankrollStep = 1,
): { targetPlaceholder: string; floorPlaceholder: string } {
  const targetCents = Math.round(bankrollCents * 1.07);
  let floorCents = Math.floor(bankrollCents / 3);
  if (bankrollStep > 1) {
    floorCents = Math.floor(floorCents / bankrollStep) * bankrollStep;
  }
  return {
    targetPlaceholder: centsToPlaceholder(targetCents),
    floorPlaceholder: centsToPlaceholder(floorCents),
  };
}

export type SetupMode = "TARGET" | "REACH_TARGET";

export function parseReachTargetPercent(raw: string): MoneyParseResult & { fraction?: number } {
  const trimmed = raw.trim().replace(/%$/, "");
  if (!trimmed) return { ok: false, error: "Enter a Reach target %." };
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return { ok: false, error: "Enter a valid Reach target %." };
  if (n <= 0 || n > 100) {
    return { ok: false, error: "Reach target % must be greater than 0 and at most 100." };
  }
  return { ok: true, cents: Math.round(n * 100), fraction: n / 100 };
}

/** Content-script Start gate from local drafts + mirrored health/bankroll. */
export function explainSetupStart(
  health: string,
  bankrollCents: number | null,
  targetDraft: string,
  floorDraft: string,
  options?: {
    setupMode?: SetupMode;
    calculatedTargetCents?: number | null;
    calculationReady?: boolean;
  },
): SetupStartGate {
  if (health === "BACKEND_OFFLINE") {
    return { canStart: false, reason: "Optimizer offline — local backend is not connected" };
  }
  if (health === "PAGE_UNSUPPORTED") {
    return { canStart: false, reason: "Open CSGOEmpire Roulette to use Live Companion." };
  }
  if (bankrollCents == null || health === "BANKROLL_UNAVAILABLE") {
    return {
      canStart: false,
      reason: "Live Companion cannot start until the balance can be read.",
    };
  }
  if (health !== "CONNECTED") {
    return { canStart: false, reason: "Waiting for a stable connection." };
  }

  const mode = options?.setupMode ?? "TARGET";
  const floorTrim = floorDraft.trim();

  if (mode === "REACH_TARGET") {
    if (!floorTrim) return { canStart: false, reason: "Enter a hard floor." };
    if (!options?.calculationReady || options.calculatedTargetCents == null) {
      return { canStart: false, reason: "Calculate Target before starting." };
    }
    if (isIncompleteMoneyDraft(floorDraft)) {
      return { canStart: false, reason: null };
    }
    const floor = parseDollarInput(floorDraft);
    if (!floor.ok) {
      return { canStart: false, reason: floor.error };
    }
    const bankFmt = formatCents(bankrollCents);
    if (!(bankrollCents > floor.cents)) {
      return {
        canStart: false,
        reason: `Hard floor must be below current bankroll (${bankFmt}).`,
      };
    }
    if (!(options.calculatedTargetCents > bankrollCents)) {
      return { canStart: false, reason: "Calculated Target must be above bankroll." };
    }
    return { canStart: true, reason: null };
  }

  const targetTrim = targetDraft.trim();
  if (!targetTrim) return { canStart: false, reason: "Enter a target." };
  if (!floorTrim) return { canStart: false, reason: "Enter a hard floor." };
  if (isIncompleteMoneyDraft(targetDraft) || isIncompleteMoneyDraft(floorDraft)) {
    return { canStart: false, reason: null };
  }

  const validation = validateSessionMoney(bankrollCents, targetDraft, floorDraft);
  if (!validation.ok) {
    return {
      canStart: false,
      reason: validation.errors.target ?? validation.errors.floor ?? "Check target and floor.",
    };
  }
  return { canStart: true, reason: null };
}
