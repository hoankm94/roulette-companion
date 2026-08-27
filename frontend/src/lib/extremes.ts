/** Primary extreme labels and display helpers for Replay Lab. */

export const PRIMARY_POLICY_EXTREME_LABELS = new Set([
  "worst_starting_round",
  "best_starting_round",
  "fastest_FLOOR",
  "fastest_TARGET",
  "largest_bankroll_drawdown",
  "longest_losing_bet_streak",
  "longest_resolved_session",
]);

export const EXTREME_DISPLAY: Record<string, { title: string; help: string }> = {
  worst_starting_round: {
    title: "Worst Historical Start",
    help: "Starting round that produced the worst policy result under the replay ranking.",
  },
  best_starting_round: {
    title: "Best Historical Start",
    help: "Starting round that produced the best policy result under the replay ranking.",
  },
  fastest_TARGET: {
    title: "Fastest TARGET",
    help: "Fewest rolls to reach TARGET under the policy.",
  },
  fastest_FLOOR: {
    title: "Fastest FLOOR",
    help: "Fewest rolls to reach FLOOR under the policy.",
  },
  longest_resolved_session: {
    title: "Longest Session to Resolution",
    help: "Replay requiring the most rolls before TARGET, FLOOR, or NO_ACTION.",
  },
  largest_bankroll_drawdown: {
    title: "Largest Bankroll Drawdown",
    help: "Largest drop from a previous bankroll peak to a later low.",
  },
  longest_losing_bet_streak: {
    title: "Longest Losing Bet Streak",
    help: "Most consecutive policy bets that lost during a replay.",
  },
  "longest DICE drought": {
    title: "Longest DICE Drought",
    help: "Longest historical sequence with no DICE result.",
  },
  "highest-DICE 50-roll window": {
    title: "Most DICE-Heavy 50-Roll Window",
    help: "50 consecutive historical rolls containing the most DICE results.",
  },
  "longest ORANGE streak": {
    title: "Longest ORANGE Streak",
    help: "Longest consecutive ORANGE outcomes in the historical sequence.",
  },
  "longest BLACK streak": {
    title: "Longest BLACK Streak",
    help: "Longest consecutive BLACK outcomes in the historical sequence.",
  },
};

export function extremeTitle(label: string): string {
  return EXTREME_DISPLAY[label]?.title ?? label;
}

export function extremeHelp(label: string): string | undefined {
  return EXTREME_DISPLAY[label]?.help;
}

export function isPrimaryPolicyExtreme(label: string): boolean {
  return PRIMARY_POLICY_EXTREME_LABELS.has(label);
}

export function isPrimaryWebsiteExtreme(label: string): boolean {
  return label in EXTREME_DISPLAY && !PRIMARY_POLICY_EXTREME_LABELS.has(label);
}
