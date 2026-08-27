/** Centralized Companion timing constants. */

/** Bankroll / site snapshot poll interval. */
export const BANKROLL_POLL_MS = 500;

/** @deprecated Final-bankroll stable polls — replaced by result-driven settlement. */
export const FINAL_BANKROLL_STABLE_POLLS = 2;

/** Diagnostic threshold for delayed website bankroll reconciliation (non-blocking). */
export const BANKROLL_RECONCILIATION_WARN_MS = 12_000;

/** @deprecated Alias for BANKROLL_RECONCILIATION_WARN_MS. */
export const FINAL_BANKROLL_TIMEOUT_MS = BANKROLL_RECONCILIATION_WARN_MS;

/** Transient AMBIGUOUS betting-state polls before treating as persistent. */
export const AMBIGUOUS_PERSISTENCE_POLLS = 3;
