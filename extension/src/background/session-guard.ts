/** Guards in-flight API responses after discard / Start New (H1). */

export function bumpSessionEpoch(epoch: number): number {
  return epoch + 1;
}

export function shouldApplyApiState(opts: {
  atEpoch: number;
  currentEpoch: number;
  currentSessionId: string | null;
  sessionActive: boolean;
  responseSessionId: string;
}): boolean {
  if (opts.atEpoch !== opts.currentEpoch) return false;
  if (opts.currentSessionId != null && opts.responseSessionId !== opts.currentSessionId) {
    return false;
  }
  if (!opts.sessionActive && opts.currentSessionId == null) return false;
  return true;
}
