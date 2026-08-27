import { tryParseMoneyToCents as parseMoneyText } from "../../money/parseMoney.js";
import type {
  AdapterCapability,
  BettingState,
  ButtonObs,
  ColorSide,
  ObservedWager,
  RoundPhase,
  RoundResult,
  WagerFamily,
  WagerSide,
  WagerType,
  WagerButtonObservations,
  WebsiteObservation,
  WebsiteObservationReadings,
} from "../types.js";
import {
  readingAmbiguous,
  readingAvailable,
  readingUnavailable,
  valueIfAvailable,
  type CapabilityReading,
} from "./readings.js";
import {
  BANKROLL_STRATEGIES,
  BETTING_BUTTON_DEFS,
  COLOR_SIDE_STRATEGIES,
  CSGOEMPIRE_SELECTORS,
  RESULT_STRATEGIES,
  ROUND_ID_STRATEGIES,
  ROUND_PHASE_STRATEGIES,
  WAGER_STAKE_STRATEGIES,
  WAGER_TYPE_STRATEGIES,
  type BettingButtonRole,
  type CSGOEmpireSelectorGroup,
  type StrategyDef,
} from "./selectors.js";

export interface ParsedCSGOEmpireObservation extends WebsiteObservation {}

export function queryFirst(root: ParentNode, selectors: readonly string[]): Element | null {
  for (const selector of selectors) {
    const element = root.querySelector(selector);
    if (element) return element;
  }
  return null;
}

function readText(element: Element | null): string | null {
  if (!element) return null;
  const text = (element.textContent ?? element.getAttribute("value") ?? "").trim();
  return text || null;
}

function attributeOrNull(element: Element, name: string): string | null {
  const value = element.getAttribute(name);
  if (value == null || value.trim() === "") return null;
  return value;
}

function parseMoneyField(raw: string | null | undefined): number | null {
  if (raw == null) return null;
  const cleaned = raw
    .replace(/[^\d.,$]/g, " ")
    .trim()
    .split(/\s+/)
    .find((token) => /^\$?\d[\d,]*(?:\.\d{1,2})?$/.test(token));
  return parseMoneyText(cleaned ?? raw);
}

const BANKROLL_EXCLUDE =
  ".bet-btn, .bet-input, .previous-rolls, [class*='place-bet'], [class*='PlaceBet'], .placed-bet";

function isExcludedBankrollCandidate(element: Element): boolean {
  return element.closest(BANKROLL_EXCLUDE) !== null;
}

function isHiddenOrStale(element: Element): boolean {
  if (element.hasAttribute("hidden")) return true;
  if (element.getAttribute("aria-hidden") === "true") return true;

  if (!(element instanceof HTMLElement)) return false;

  if (typeof element.checkVisibility === "function") {
    try {
      return !element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    } catch {
      /* fall through */
    }
  }

  if (typeof window !== "undefined" && typeof window.getComputedStyle === "function") {
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") {
      return true;
    }
    if (parseFloat(style.opacity) === 0) return true;
  } else {
    const inline = element.getAttribute("style") ?? "";
    if (/display\s*:\s*none/i.test(inline) || /visibility\s*:\s*hidden/i.test(inline)) {
      return true;
    }
  }

  return false;
}

function collectElements(root: ParentNode, selectors: readonly string[]): Element[] {
  const out: Element[] = [];
  const seen = new Set<Element>();
  for (const selector of selectors) {
    if (typeof root.querySelectorAll !== "function") {
      const single = root.querySelector?.(selector);
      if (single && !seen.has(single)) {
        seen.add(single);
        out.push(single);
      }
      continue;
    }
    for (const el of root.querySelectorAll(selector)) {
      if (!seen.has(el)) {
        seen.add(el);
        out.push(el);
      }
    }
  }
  return out;
}

/**
 * Run ordered strategies. First strategy with a single trusted value wins.
 * Conflicting values within a strategy → AMBIGUOUS (fail closed).
 */
function resolveWithStrategies<T>(
  root: ParentNode,
  strategies: readonly StrategyDef[],
  observedAt: number,
  extract: (el: Element) => T | null,
  options?: { exclude?: (el: Element) => boolean },
): CapabilityReading<T> {
  for (const strategy of strategies) {
    const values = new Map<string, T>();
    for (const el of collectElements(root, strategy.selectors)) {
      if (options?.exclude?.(el)) continue;
      if (isHiddenOrStale(el)) continue;
      const value = extract(el);
      if (value == null) continue;
      values.set(JSON.stringify(value), value);
    }
    if (values.size === 1) {
      const value = [...values.values()][0]!;
      return readingAvailable(value, strategy.id, observedAt);
    }
    if (values.size > 1) {
      return readingAmbiguous(strategy.id, observedAt);
    }
  }
  return readingUnavailable(observedAt);
}

function normalizeRoundId(raw: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return trimmed.startsWith("#") ? trimmed : `#${trimmed}`;
}

function parseRoundPhase(raw: string | null): RoundPhase | null {
  if (!raw) return null;
  const normalized = raw.trim().toUpperCase();
  if (normalized.includes("BET") || normalized.includes("OPEN")) return "OPEN";
  if (normalized.includes("ROLL") || normalized.includes("SPIN") || normalized.includes("CLOSE")) {
    return "CLOSED";
  }
  if (normalized.includes("RESULT") || normalized.includes("RESOLVED")) return "RESULT";
  return "UNKNOWN";
}

function parseRoundResult(element: Element): RoundResult | null {
  const explicit =
    attributeOrNull(element, "data-result") ??
    attributeOrNull(element, "data-pocket") ??
    attributeOrNull(element, "data-companion-latest-result");
  const token = (explicit ?? readText(element) ?? "").trim().toUpperCase();
  if (!token) return null;
  if (token === "DICE" || token === "BONUS") return "DICE";
  if (token === "ORANGE" || token === "CT") return "ORANGE";
  if (token === "BLACK" || token === "T") return "BLACK";
  if (token === "GREEN" || token === "0") return "GREEN";
  return null;
}

function parseWagerType(element: Element): WagerType | null {
  const raw =
    attributeOrNull(element, "data-wager-type") ??
    attributeOrNull(element, "data-companion-wager-type") ??
    readText(element);
  const token = (raw ?? "").trim().toUpperCase();
  if (token === "DICE") return "DICE";
  if (token === "COLOR") return "COLOR";
  return null;
}

function parseColorSide(element: Element): ColorSide | null {
  const raw =
    attributeOrNull(element, "data-color-side") ??
    attributeOrNull(element, "data-companion-color-side") ??
    readText(element);
  const token = (raw ?? "").trim().toUpperCase();
  if (token === "ORANGE" || token === "CT") return "ORANGE";
  if (token === "BLACK" || token === "T") return "BLACK";
  return null;
}

function parseStakeFromElement(element: Element): number | null {
  const fromValue = element.getAttribute("value");
  const fromData = element.getAttribute("data-submitted-stake");
  return parseMoneyField(fromData ?? fromValue ?? readText(element));
}

/** Prefer header/nav wallet balance; skip bet-column currency values. */
export function findBankrollElement(root: ParentNode): Element | null {
  for (const strategy of BANKROLL_STRATEGIES) {
    for (const el of collectElements(root, strategy.selectors)) {
      if (isExcludedBankrollCandidate(el) || isHiddenOrStale(el)) continue;
      if (parseMoneyField(readText(el)) != null) return el;
    }
  }
  return null;
}

export function readBankroll(
  root: ParentNode,
  observedAt = Date.now(),
): CapabilityReading<number> {
  return resolveWithStrategies(
    root,
    BANKROLL_STRATEGIES,
    observedAt,
    (el) => parseMoneyField(readText(el)),
    { exclude: isExcludedBankrollCandidate },
  );
}

export function probeSelectorGroups(
  root: ParentNode,
): Record<CSGOEmpireSelectorGroup, boolean> {
  const at = Date.now();
  return {
    bankroll: readBankroll(root, at).status === "AVAILABLE",
    roundId:
      resolveWithStrategies(root, ROUND_ID_STRATEGIES, at, (el) =>
        normalizeRoundId(readText(el)),
      ).status === "AVAILABLE",
    roundPhase:
      resolveWithStrategies(root, ROUND_PHASE_STRATEGIES, at, (el) =>
        parseRoundPhase(readText(el)),
      ).status === "AVAILABLE",
    latestResult:
      resolveWithStrategies(root, RESULT_STRATEGIES, at, parseRoundResult).status === "AVAILABLE",
    wagerStake:
      resolveWithStrategies(root, WAGER_STAKE_STRATEGIES, at, parseStakeFromElement).status ===
      "AVAILABLE",
    wagerType:
      resolveWithStrategies(root, WAGER_TYPE_STRATEGIES, at, parseWagerType).status === "AVAILABLE",
    colorSide:
      resolveWithStrategies(root, COLOR_SIDE_STRATEGIES, at, parseColorSide).status === "AVAILABLE",
  };
}

export function capabilitiesFromProbe(
  probe: Record<CSGOEmpireSelectorGroup, boolean>,
): Set<AdapterCapability> {
  const capabilities = new Set<AdapterCapability>();
  if (probe.bankroll) capabilities.add("CAN_READ_BANKROLL");
  if (probe.roundId) capabilities.add("CAN_READ_ROUND_ID");
  if (probe.latestResult) capabilities.add("CAN_READ_RESULT");
  if (probe.wagerType) capabilities.add("CAN_READ_WAGER_TYPE");
  if (probe.wagerStake) capabilities.add("CAN_READ_WAGER_STAKE");
  if (probe.colorSide) capabilities.add("CAN_READ_COLOR_SIDE");
  return capabilities;
}

export function capabilitiesFromReadings(
  readings: WebsiteObservationReadings,
): Set<AdapterCapability> {
  const capabilities = new Set<AdapterCapability>();
  if (readings.bankroll.status === "AVAILABLE") capabilities.add("CAN_READ_BANKROLL");
  if (readings.roundId.status === "AVAILABLE") capabilities.add("CAN_READ_ROUND_ID");
  if (readings.result.status === "AVAILABLE") capabilities.add("CAN_READ_RESULT");
  if (readings.wagerType.status === "AVAILABLE") capabilities.add("CAN_READ_WAGER_TYPE");
  if (readings.wagerStakeCents.status === "AVAILABLE") capabilities.add("CAN_READ_WAGER_STAKE");
  if (readings.colorSide.status === "AVAILABLE") capabilities.add("CAN_READ_COLOR_SIDE");
  if (readings.bettingState.status === "AVAILABLE") capabilities.add("BETTING_STATE");
  return capabilities;
}

function familyForSide(side: WagerSide): WagerFamily {
  return side === "DICE" ? "DICE" : "COLOR";
}

function emptyButtonObs(side: WagerSide): ButtonObs {
  return {
    present: false,
    side,
    family: familyForSide(side),
    placed: false,
    amountCents: null,
    rolling: false,
    disabled: false,
    won: false,
    lost: false,
    disableAttr: null,
  };
}

function buttonClassName(el: Element): string {
  return typeof el.className === "string" ? el.className : String(el.className ?? "");
}

function readButtonElement(el: Element | null, side: WagerSide): ButtonObs {
  if (!el) return emptyButtonObs(side);

  const className = buttonClassName(el);
  const disableAttr = el.getAttribute("disable");
  const placed = className.includes("bet-btn--placed");
  const rolling = className.includes("bet-btn--rolling");
  const disabled = disableAttr === "true" || className.includes("bet-btn--disabled");
  const won = className.includes("bet-btn--win");
  const lost = className.includes("bet-btn--loss");

  let amountCents: number | null = null;
  if (placed) {
    const amountEl = el.querySelector('[data-testid="currency-amount"]');
    amountCents = parseMoneyField(amountEl?.textContent ?? null);
  }

  return {
    present: true,
    side,
    family: familyForSide(side),
    placed,
    amountCents,
    rolling,
    disabled,
    won,
    lost,
    disableAttr,
  };
}

export function buildPlacedWagers(wagers: WagerButtonObservations): ObservedWager[] {
  const out: ObservedWager[] = [];
  for (const button of [wagers.dice, wagers.black, wagers.orange]) {
    if (button.present && button.placed && button.amountCents != null) {
      out.push({
        side: button.side,
        family: button.family,
        stakeCents: button.amountCents,
        source: "DOM_PLACED_BUTTON",
      });
    }
  }
  return out;
}

export type RouletteResultDerivation =
  | { status: "NONE" }
  | { status: "COMPLETE"; winnerSide: WagerSide }
  | { status: "AMBIGUOUS" }
  | { status: "UNAVAILABLE" };

/**
 * Pure helper: complete result requires exactly one --win and two --loss,
 * with all three controls present. Partial updates → wait (NONE/AMBIGUOUS).
 */
export function deriveRouletteResult(
  wagers: WagerButtonObservations,
): RouletteResultDerivation {
  const buttons = [wagers.dice, wagers.black, wagers.orange];
  if (buttons.some((b) => !b.present)) {
    return { status: "UNAVAILABLE" };
  }

  const winners = buttons.filter((b) => b.won);
  const losers = buttons.filter((b) => b.lost);
  const anyResultClass = buttons.some((b) => b.won || b.lost);

  if (!anyResultClass) {
    return { status: "NONE" };
  }

  if (winners.length === 1 && losers.length === 2 && !winners[0]!.lost) {
    const winner = winners[0]!;
    const otherLost = buttons.filter((b) => b !== winner).every((b) => b.lost && !b.won);
    if (otherLost) {
      return { status: "COMPLETE", winnerSide: winner.side };
    }
  }

  return { status: "AMBIGUOUS" };
}

/** Read per-control wager DOM state for Dice / Black / Orange buttons. */
export function readWagers(root: ParentNode): WagerButtonObservations {
  let resolved = queryBettingButtons(root, "testid");
  if (!resolved) {
    resolved = queryBettingButtons(root, "id");
  }

  const readRole = (role: BettingButtonRole): ButtonObs => {
    if (!resolved) return emptyButtonObs(role);
    return readButtonElement(resolved.get(role) ?? null, role);
  };

  return {
    dice: readRole("DICE"),
    black: readRole("BLACK"),
    orange: readRole("ORANGE"),
  };
}

type PerButtonState = "OPEN" | "CLOSED" | "AMBIGUOUS";

function resolvePerButtonState(el: Element): PerButtonState {
  const disable = el.getAttribute("disable");
  const className = buttonClassName(el);
  const classSaysClosed =
    className.includes("bet-btn--disabled") || className.includes("bet-btn--rolling");

  if (disable === "false") {
    if (classSaysClosed) return "AMBIGUOUS";
    return "OPEN";
  }
  if (disable === "true") {
    // Closed classes support CLOSED; no separate open-class signal to conflict.
    return "CLOSED";
  }
  return "AMBIGUOUS";
}

function queryBettingButtons(
  root: ParentNode,
  mode: "testid" | "id",
): Map<BettingButtonRole, Element> | null {
  const found = new Map<BettingButtonRole, Element>();
  for (const def of BETTING_BUTTON_DEFS) {
    const selector =
      mode === "testid" ? `[data-testid="${def.testId}"]` : `#${def.elementId}`;
    const el = root.querySelector?.(selector) ?? null;
    if (!el) return null;
    found.set(def.role, el);
  }
  return found;
}

/** Aggregate Dice/Black/Orange bet controls into one BETTING_STATE reading. */
export function readBettingState(
  root: ParentNode,
  observedAt = Date.now(),
): CapabilityReading<BettingState> {
  let strategy: "TESTID" | "ID" = "TESTID";
  let resolved = queryBettingButtons(root, "testid");
  if (!resolved) {
    resolved = queryBettingButtons(root, "id");
    strategy = "ID";
  }
  if (!resolved) {
    return readingUnavailable(observedAt);
  }

  const states: PerButtonState[] = [];
  for (const def of BETTING_BUTTON_DEFS) {
    states.push(resolvePerButtonState(resolved.get(def.role)!));
  }

  if (states.some((s) => s === "AMBIGUOUS")) {
    return readingAmbiguous(strategy, observedAt);
  }
  const allOpen = states.every((s) => s === "OPEN");
  const allClosed = states.every((s) => s === "CLOSED");
  if (allOpen) {
    return readingAvailable("OPEN", strategy, observedAt);
  }
  if (allClosed) {
    return readingAvailable("CLOSED", strategy, observedAt);
  }
  return readingAmbiguous(strategy, observedAt);
}

function readHistoryFingerprint(root: ParentNode): string | null {
  const item = queryFirst(root, [
    ".previous-rolls-item[data-result]",
    ".previous-rolls .previous-rolls-item",
    "[data-companion-latest-result]",
    '[data-testid="previous-rolls"] [data-result]',
  ]);
  if (!item) return null;
  const resultAttr = item.getAttribute("data-result");
  const text = (item.textContent ?? "").trim();
  const key = `${resultAttr ?? ""}|${text}`;
  return key || null;
}

export function parseCSGOEmpireObservation(
  root: ParentNode,
  observedAt = Date.now(),
): ParsedCSGOEmpireObservation {
  const readings: WebsiteObservationReadings = {
    bankroll: readBankroll(root, observedAt),
    roundId: resolveWithStrategies(root, ROUND_ID_STRATEGIES, observedAt, (el) =>
      normalizeRoundId(readText(el)),
    ),
    phase: resolveWithStrategies(root, ROUND_PHASE_STRATEGIES, observedAt, (el) =>
      parseRoundPhase(readText(el)),
    ),
    result: resolveWithStrategies(root, RESULT_STRATEGIES, observedAt, parseRoundResult),
    wagerType: resolveWithStrategies(root, WAGER_TYPE_STRATEGIES, observedAt, parseWagerType),
    wagerStakeCents: resolveWithStrategies(
      root,
      WAGER_STAKE_STRATEGIES,
      observedAt,
      parseStakeFromElement,
    ),
    colorSide: resolveWithStrategies(root, COLOR_SIDE_STRATEGIES, observedAt, parseColorSide),
    bettingState: readBettingState(root, observedAt),
  };

  const wagers = readWagers(root);
  const placedWagers = buildPlacedWagers(wagers);
  const derived = deriveRouletteResult(wagers);

  return {
    bankrollCents: valueIfAvailable(readings.bankroll),
    roundId: valueIfAvailable(readings.roundId),
    phase: valueIfAvailable(readings.phase),
    result: valueIfAvailable(readings.result),
    wagerType: valueIfAvailable(readings.wagerType),
    wagerStakeCents: valueIfAvailable(readings.wagerStakeCents),
    colorSide: valueIfAvailable(readings.colorSide),
    bettingState: valueIfAvailable(readings.bettingState),
    wagers,
    placedWagers,
    winningSide: derived.status === "COMPLETE" ? derived.winnerSide : null,
    resultStatus: derived.status,
    historyFingerprint: readHistoryFingerprint(root),
    observedAt,
    readings,
  };
}

export type AdapterIssueCode =
  | "PAGE_UNSUPPORTED"
  | "DOM_CHANGED"
  | "BANKROLL_UNAVAILABLE"
  | "BANKROLL_AMBIGUOUS"
  | "ROUND_UNAVAILABLE"
  | "WAGER_UNAVAILABLE"
  | "RESULT_UNAVAILABLE";

export function issuesFromProbe(
  siteSupported: boolean,
  probe: Record<CSGOEmpireSelectorGroup, boolean>,
): AdapterIssueCode[] {
  const issues: AdapterIssueCode[] = [];
  if (!siteSupported) {
    issues.push("PAGE_UNSUPPORTED");
    return issues;
  }
  if (!probe.bankroll) {
    issues.push("BANKROLL_UNAVAILABLE");
  }
  return issues;
}

export function issuesFromReadings(
  siteSupported: boolean,
  readings: WebsiteObservationReadings,
): AdapterIssueCode[] {
  const issues: AdapterIssueCode[] = [];
  if (!siteSupported) {
    issues.push("PAGE_UNSUPPORTED");
    return issues;
  }
  if (readings.bankroll.status === "AMBIGUOUS") {
    issues.push("BANKROLL_AMBIGUOUS");
  } else if (readings.bankroll.status !== "AVAILABLE") {
    issues.push("BANKROLL_UNAVAILABLE");
  }
  return issues;
}

// Re-export for callers that imported selectors via this module historically.
export { CSGOEMPIRE_SELECTORS };
