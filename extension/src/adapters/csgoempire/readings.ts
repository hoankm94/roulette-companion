/** Normalized per-capability readings (hardening plan §§8–11). */

export type ObservationStatus = "AVAILABLE" | "UNAVAILABLE" | "AMBIGUOUS" | "STALE";

export interface CapabilityReading<T> {
  value: T | null;
  status: ObservationStatus;
  /** Diagnostic only — never show in normal UI. */
  sourceStrategy: string | null;
  observedAt: number;
}

export function readingAvailable<T>(
  value: T,
  sourceStrategy: string,
  observedAt: number,
): CapabilityReading<T> {
  return { value, status: "AVAILABLE", sourceStrategy, observedAt };
}

export function readingUnavailable<T>(observedAt: number): CapabilityReading<T> {
  return { value: null, status: "UNAVAILABLE", sourceStrategy: null, observedAt };
}

export function readingAmbiguous<T>(
  sourceStrategy: string,
  observedAt: number,
): CapabilityReading<T> {
  return { value: null, status: "AMBIGUOUS", sourceStrategy, observedAt };
}

export function valueIfAvailable<T>(reading: CapabilityReading<T>): T | null {
  return reading.status === "AVAILABLE" ? reading.value : null;
}
