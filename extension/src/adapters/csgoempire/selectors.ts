/**

 * CSGOEmpire roulette DOM selectors — ordered strategies per capability.

 *

 * Prefer semantic / testid / companion hooks. Do not use arbitrary page-wide

 * numeric text as a bankroll fallback (fail closed instead).

 */



export type StrategyDef = {

  id: string;

  selectors: readonly string[];

};



/** Bankroll: ordered trusted strategies (plan §6). */

export const BANKROLL_STRATEGIES: readonly StrategyDef[] = [

  {

    id: "BALANCE_TESTID_AMOUNT",

    selectors: [

      '[data-testid="balance"] [data-testid="currency-amount"]',

      '[data-testid="balance"] [data-testid="currency-value"] [data-testid="currency-amount"]',

      '[data-testid="balance"] [data-testid="currency-value"]',

    ],

  },

  {

    id: "HEADER_BALANCE",

    selectors: [

      '[data-testid="header-balance"] [data-testid="currency-amount"]',

      '[data-testid="header-balance"] [data-testid="currency-value"]',

      '[data-testid="user-balance"] [data-testid="currency-amount"]',

      '[data-testid="user-balance"] [data-testid="currency-value"]',

      "header [data-testid=\"currency-amount\"]",

      "nav [data-testid=\"currency-amount\"]",

    ],

  },

  {

    id: "COMPANION_BANKROLL",

    selectors: [

      '[data-companion-bankroll] [data-testid="currency-amount"]',

      '[data-companion-bankroll] [data-testid="currency-value"]',

      "[data-companion-bankroll]",

    ],

  },

];



export const ROUND_ID_STRATEGIES: readonly StrategyDef[] = [

  {

    id: "COMPANION_ROUND_ID",

    selectors: ["[data-companion-round-id]", '[data-testid="roulette-round-id"]'],

  },

  {

    id: "LEGACY_ROUND_ID",

    selectors: [".roulette-round-id"],

  },

];



export const ROUND_PHASE_STRATEGIES: readonly StrategyDef[] = [

  {

    id: "COMPANION_PHASE",

    selectors: ["[data-companion-round-phase]", '[data-testid="roulette-phase"]'],

  },

  {

    id: "LEGACY_PHASE",

    selectors: [".roulette-status"],

  },

];



export const RESULT_STRATEGIES: readonly StrategyDef[] = [

  {

    id: "COMPANION_RESULT",

    selectors: ["[data-companion-latest-result]"],

  },

  {

    id: "PREVIOUS_ROLLS",

    selectors: [".previous-rolls-item[data-result]", ".previous-rolls .previous-rolls-item"],

  },

];



export const WAGER_TYPE_STRATEGIES: readonly StrategyDef[] = [

  {

    id: "COMPANION_WAGER_TYPE",

    selectors: ["[data-companion-wager-type]", ".placed-bet[data-wager-type]"],

  },

  {

    id: "ACTIVE_BET_BTN",

    selectors: [".bet-btn.active[data-wager-type]"],

  },

];



export const WAGER_STAKE_STRATEGIES: readonly StrategyDef[] = [

  {

    id: "COMPANION_WAGER_STAKE",

    selectors: [

      "[data-companion-wager-stake]",

      ".bet-input__field input[data-submitted-stake]",

      '.placed-bet [data-testid="currency-value"]',

      ".placed-bet [data-submitted-stake]",

    ],

  },

];



export const COLOR_SIDE_STRATEGIES: readonly StrategyDef[] = [

  {

    id: "COMPANION_COLOR_SIDE",

    selectors: [

      "[data-companion-color-side]",

      ".placed-bet[data-color-side]",

      '.bet-btn.active[data-color-side="ORANGE"]',

      '.bet-btn.active[data-color-side="BLACK"]',

    ],

  },

];



/** Semantic Roulette bet controls (Dice / Black / Orange). */

export type BettingButtonRole = "DICE" | "BLACK" | "ORANGE";

export type BettingButtonDef = {

  role: BettingButtonRole;

  testId: string;

  elementId: string;

};

export const BETTING_BUTTON_DEFS: readonly BettingButtonDef[] = [

  { role: "DICE", testId: "bet-button-bonus", elementId: "bet-button-bonus" },

  { role: "BLACK", testId: "bet-button-ct", elementId: "bet-button-ct" },

  { role: "ORANGE", testId: "bet-button-t", elementId: "bet-button-t" },

];



/** Flattened lists kept for probe / legacy callers. */

export const CSGOEMPIRE_SELECTORS = {

  bankroll: BANKROLL_STRATEGIES.flatMap((s) => s.selectors),

  roundId: ROUND_ID_STRATEGIES.flatMap((s) => s.selectors),

  roundPhase: ROUND_PHASE_STRATEGIES.flatMap((s) => s.selectors),

  latestResult: RESULT_STRATEGIES.flatMap((s) => s.selectors),

  wagerStake: WAGER_STAKE_STRATEGIES.flatMap((s) => s.selectors),

  wagerType: WAGER_TYPE_STRATEGIES.flatMap((s) => s.selectors),

  colorSide: COLOR_SIDE_STRATEGIES.flatMap((s) => s.selectors),

} as const;



export type CSGOEmpireSelectorGroup = keyof typeof CSGOEMPIRE_SELECTORS;



export const CSGOEMPIRE_ROULETTE_URL_PATTERN =
  /^https?:\/\/(?:www\.)?csgoempire\.com(?:\/[a-z]{2}(?:-[a-z]{2})?)?\/roulette(?:\/|$|\?)/i;



/** Authoritative Roulette context gate (not manifest match patterns alone). */

export function isSupportedContext(url: string): boolean {

  return CSGOEMPIRE_ROULETTE_URL_PATTERN.test(url);

}


