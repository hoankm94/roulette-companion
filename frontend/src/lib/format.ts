/** Format dollars for display with fixed 2 decimals. */
export function formatDollars(
  value: number | { dollars: number; cents?: number } | null | undefined,
): string {
  if (value == null) return "—";
  const n = typeof value === "number" ? value : value.dollars;
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatProbability(p: number | null | undefined): string {
  if (p == null || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(2)}%`;
}

export function formatPct(p: number | null | undefined, digits = 2): string {
  if (p == null || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(digits)}%`;
}

export function formatNumber(n: number | null | undefined, digits = 6): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function parseDollarInput(raw: string): { ok: true; value: number } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: false, error: "Required" };
  const cleaned = trimmed.replace(/^\$/, "").replace(/,/g, "");
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return { ok: false, error: "Enter a valid dollar amount" };
  if (n < 0) return { ok: false, error: "Must be ≥ 0" };
  return { ok: true, value: n };
}

export function validateSessionInputs(bankroll: string, target: string, floor: string) {
  const b = parseDollarInput(bankroll);
  const t = parseDollarInput(target);
  const f = parseDollarInput(floor);
  const errors: { bankroll?: string; target?: string; floor?: string } = {};
  if (!b.ok) errors.bankroll = b.error;
  if (!t.ok) errors.target = t.error;
  if (!f.ok) errors.floor = f.error;
  if (b.ok && t.ok && f.ok) {
    if (!(t.value > b.value && b.value > f.value && f.value >= 0)) {
      errors.bankroll = errors.bankroll || "Require target > bankroll > floor ≥ 0";
      errors.target = errors.target || "Require target > bankroll > floor ≥ 0";
      errors.floor = errors.floor || "Require target > bankroll > floor ≥ 0";
    }
  }
  const hasErrors = Object.keys(errors).length > 0;
  return {
    errors,
    values:
      !hasErrors && b.ok && t.ok && f.ok
        ? { bankroll: b.value, target: t.value, floor: f.value }
        : null,
  };
}

export function actionClass(action: string | null | undefined): string {
  if (action === "COLOR") return "bet-color";
  if (action === "DICE") return "bet-dice";
  return "";
}

export function formatVerificationStatus(status: string): string {
  switch (status) {
    case "VALID":
      return "Valid";
    case "FAILED":
      return "Failed";
    case "SKIPPED":
      return "Skipped";
    case "NOT_RUN":
      return "Not run";
    default:
      return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

export function terminalLabel(status: string): string {
  switch (status) {
    case "TARGET":
      return "Target reached";
    case "FLOOR":
      return "Floor reached";
    case "NO_ACTION":
      return "No action available";
    case "QUIT":
      return "Session ended";
    case "CONTINUE":
      return "In progress";
    case "EXHAUSTED":
      return "Sequence exhausted";
    default:
      return status;
  }
}

/** Compact display for ISO-8601 estimated timestamps. */
export function formatEstimatedTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  if (m < 60) return `${m}m ${s.toFixed(0)}s`;
  const h = Math.floor(m / 60);
  const rm = m - h * 60;
  return `${h}h ${rm}m`;
}

export const REPLAY_TIMEZONES = [
  "UTC",
  "Asia/Taipei",
  "Asia/Tokyo",
  "Asia/Seoul",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Australia/Sydney",
] as const;
