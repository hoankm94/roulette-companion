export type MoneyAmount = {
  cents: number;
  dollars: number;
};

export type Recommendation = {
  status: string;
  action: string | null;
  stake: MoneyAmount | null;
  target_hit_probability: number;
  win_bankroll: MoneyAmount | null;
  lose_bankroll: MoneyAmount | null;
  bankroll: MoneyAmount;
  consecutive_loss_durability?: number;
};

export type Verification = {
  deterministic_status: string;
  policy_evaluation_passed: boolean;
  bellman_passed: boolean;
  linear_value_bellman_passed: boolean;
  legal_actions_passed: boolean;
  max_value_difference: number;
  max_optimality_gap: number;
  vi_bellman_max_gap: number;
  linear_value_bellman_max_gap: number;
};

export type OptimizeResponse = {
  recommendation: Recommendation;
  session: {
    starting_bankroll: MoneyAmount;
    target_bankroll: MoneyAmount;
    floor_bankroll: MoneyAmount;
  };
  distribution: {
    color_count: number;
    dice_count: number;
    no_action_count: number;
    state_count: number;
  };
  policy: Array<{
    bankroll: MoneyAmount;
    action: string | null;
    stake: MoneyAmount | null;
    win_bankroll: MoneyAmount | null;
    lose_bankroll: MoneyAmount | null;
    target_hit_probability: number;
  }>;
  values: Array<{ bankroll: MoneyAmount; value: number }>;
  verification: Verification;
  solver: {
    converged: boolean;
    iterations: number;
    final_delta: number;
    solver: string;
  };
};

export type PlayState = {
  session_id: string;
  status: string;
  bankroll: MoneyAmount;
  target: MoneyAmount;
  floor: MoneyAmount;
  target_hit_probability: number | null;
  consecutive_loss_durability?: number | null;
  recommendation: Recommendation | null;
  rounds_completed: number;
  message: string | null;
  verification: Verification | null;
  awaiting_save?: boolean;
};

export type ApiError = {
  error?: string;
  detail?: string;
};

export type SessionInputs = {
  bankroll: string;
  target: string;
  floor: string;
};
