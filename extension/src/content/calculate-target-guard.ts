import type { CalculationStatus } from "../overlay/render.js";

export type CalculateTargetMessageResult =
  | { ok: true; targetCents: number; targetHitProbability: number }
  | { ok: false; error: string };

export interface CalculateTargetApplyState {
  accepted: boolean;
  calculationStatus: CalculationStatus;
  calculatedTargetCents: number | null;
  calculatedReachTarget: number | null;
  calculationError: string | null;
}

/** Bump when drafts invalidate or a new in-flight request starts. */
export function nextCalculationGeneration(current: number): number {
  return current + 1;
}

export function applyCalculateTargetResponse(
  requestGeneration: number,
  currentGeneration: number,
  response: CalculateTargetMessageResult,
): CalculateTargetApplyState {
  if (requestGeneration !== currentGeneration) {
    return {
      accepted: false,
      calculationStatus: "IDLE",
      calculatedTargetCents: null,
      calculatedReachTarget: null,
      calculationError: null,
    };
  }

  if (!response.ok) {
    return {
      accepted: true,
      calculationStatus: "ERROR",
      calculatedTargetCents: null,
      calculatedReachTarget: null,
      calculationError: response.error,
    };
  }

  return {
    accepted: true,
    calculationStatus: "READY",
    calculatedTargetCents: response.targetCents,
    calculatedReachTarget: response.targetHitProbability,
    calculationError: null,
  };
}
