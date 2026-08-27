/** Integer-cent money parsing for website DOM text. */

export class MoneyParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MoneyParseError";
  }
}

const MONEY_TEXT = /^\s*\$?\s*([\d,]+(?:\.\d{1,2})?)\s*$/;

/**
 * Parse a displayed dollar amount to integer cents.
 * Examples: "$19.53" -> 1953, "1,234.50" -> 123450
 */
export function parseMoneyToCents(raw: string): number {
  const trimmed = raw.trim();
  if (!trimmed) {
    throw new MoneyParseError("Empty money value");
  }

  const match = MONEY_TEXT.exec(trimmed);
  if (!match) {
    throw new MoneyParseError(`Invalid money value: ${raw}`);
  }

  const normalized = match[1].replace(/,/g, "");
  const [wholePart, fractionPart = ""] = normalized.split(".");
  if (!/^\d+$/.test(wholePart) || (fractionPart && !/^\d{1,2}$/.test(fractionPart))) {
    throw new MoneyParseError(`Invalid money value: ${raw}`);
  }

  const whole = Number(wholePart);
  const fraction = fractionPart.padEnd(2, "0").slice(0, 2);
  const cents = whole * 100 + Number(fraction);
  if (!Number.isSafeInteger(cents)) {
    throw new MoneyParseError(`Money value out of range: ${raw}`);
  }
  return cents;
}

/**
 * Best-effort parse; returns null instead of throwing.
 */
export function tryParseMoneyToCents(raw: string | null | undefined): number | null {
  if (raw == null) {
    return null;
  }
  try {
    return parseMoneyToCents(raw);
  } catch {
    return null;
  }
}
