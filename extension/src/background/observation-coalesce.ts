import type { WebsiteObservation } from "../adapters/types.js";

/** Coalesce observations dropped while wager/settle HTTP is in flight (H11). */
export function stashObservationWhileBusy(
  busy: boolean,
  current: WebsiteObservation | null,
  incoming: WebsiteObservation,
): WebsiteObservation | null {
  if (!busy) return current;
  return incoming;
}

export function takeStashedObservation(
  stashed: WebsiteObservation | null,
): WebsiteObservation | null {
  return stashed;
}
