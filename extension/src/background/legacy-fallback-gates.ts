/** Block legacy register/reconcile fallbacks when DOM settle is primary (H8). */

export function isLegacyFallbackBlocked(
  sessionStatus: string | null | undefined,
): boolean {
  return sessionStatus === "ROUND_PENDING";
}
