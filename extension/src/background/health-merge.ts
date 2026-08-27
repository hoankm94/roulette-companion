import type { HealthState } from "../shared/types.js";

/** Health poll must not clobber UI-only DESYNCED / soft pause (H10). */
export function mergeHealthPollUpdate(
  currentHealth: HealthState,
  polledHealth: HealthState,
): HealthState {
  if (currentHealth === "DESYNCED" && polledHealth === "CONNECTED") {
    return "DESYNCED";
  }
  return polledHealth;
}
