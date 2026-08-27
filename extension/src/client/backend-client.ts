import { DEFAULT_BACKEND_URL } from "../shared/types";

export interface HealthCheckResult {
  ok: boolean;
  status: string | null;
  error: string | null;
}

export interface MoneyAmount {
  cents: number;
  dollars: number;
}

export interface RecommendationPayload {
  status: string;
  action: string | null;
  stake: MoneyAmount | null;
  target_hit_probability: number;
  win_bankroll: MoneyAmount | null;
  lose_bankroll: MoneyAmount | null;
  bankroll: MoneyAmount;
  consecutive_loss_durability?: number;
}

export interface CompanionWagerPayload {
  bet_type: string;
  stake: MoneyAmount;
  color_side?: "ORANGE" | "BLACK" | null;
}

export interface CompanionStateResponse {
  session_id: string;
  session_status: string;
  status: string;
  bankroll: MoneyAmount;
  target: MoneyAmount;
  floor: MoneyAmount;
  target_hit_probability?: number | null;
  consecutive_loss_durability?: number | null;
  recommendation: RecommendationPayload | null;
  rounds_completed: number;
  message?: string | null;
  awaiting_save: boolean;
  recommended_wager?: CompanionWagerPayload | null;
  observed_wager?: CompanionWagerPayload | null;
  expected_bankroll?: MoneyAmount | null;
  observed_bankroll?: MoneyAmount | null;
  expected_win_bankroll?: MoneyAmount | null;
  expected_lose_bankroll?: MoneyAmount | null;
  last_result?: "DICE" | "ORANGE" | "BLACK" | null;
  last_outcome?: "WIN" | "LOSS" | "DIVERGENCE" | null;
  settlement_classification?: "WIN" | "LOSS" | "DIVERGENCE" | null;
  wager_match_status?: "MATCHED" | "MISMATCH" | null;
  desync_reason?: "policy_grid_miss" | "wager_mismatch" | "bankroll_mismatch" | null;
}

export interface CompanionStartParams {
  bankroll: number;
  target: number;
  floor: number;
  solver?: string;
}

export interface CompanionCalculateTargetParams {
  bankroll: number;
  floor: number;
  reachTargetProbability: number;
  solver?: string;
}

export interface CompanionCalculateTargetResponse {
  target: MoneyAmount;
  target_hit_probability: number;
  solves: number;
}

export interface CompanionRegisterWagerParams {
  round_id: string;
  bet_type: "DICE" | "COLOR" | "ORANGE" | "BLACK";
  stake: number;
  color_side?: "ORANGE" | "BLACK";
}

export interface CompanionRegisterResultParams {
  round_id: string;
  result: "DICE" | "ORANGE" | "BLACK";
}

export class ApiError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}

function resolveApiErrorCode(
  status: number,
  body: { error?: string; detail?: string },
): string {
  if (body.error === "session_not_found") return "session_not_found";
  if (status === 404) {
    const detail = (body.detail ?? "").toLowerCase();
    if (detail.includes("session not found")) {
      return "session_not_found";
    }
  }
  return body.error ?? `HTTP_${status}`;
}

/**
 * Thin backend client for health checks and companion session routes.
 */
export class BackendClient {
  constructor(private baseUrl = DEFAULT_BACKEND_URL) {}

  setBaseUrl(url: string): void {
    this.baseUrl = url.replace(/\/$/, "");
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    try {
      const response = await fetch(url, {
        ...options,
        credentials: "omit",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          ...(options.headers ?? {}),
        },
      });
      const body = (await response.json()) as {
        error?: string;
        detail?: string;
        status?: string;
      };
      if (!response.ok) {
        const code = resolveApiErrorCode(response.status, body);
        const detail = body.detail ?? `HTTP ${response.status}`;
        throw new ApiError(code, detail);
      }
      return body as T;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      const message = err instanceof Error ? err.message : "Network error";
      throw new ApiError("network", message);
    }
  }

  async checkHealth(): Promise<HealthCheckResult> {
    try {
      const data = await this.request<{ status?: string }>("/api/health", {
        method: "GET",
      });
      return { ok: data.status === "ok", status: data.status ?? null, error: null };
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Network error";
      return { ok: false, status: null, error: message };
    }
  }

  async companionStart(params: CompanionStartParams): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>("/api/companion/start", {
      method: "POST",
      body: JSON.stringify({
        bankroll: params.bankroll,
        target: params.target,
        floor: params.floor,
        solver: params.solver ?? "numba",
      }),
    });
  }

  async companionCalculateTarget(
    params: CompanionCalculateTargetParams,
  ): Promise<CompanionCalculateTargetResponse> {
    return this.request<CompanionCalculateTargetResponse>(
      "/api/companion/calculate-target",
      {
        method: "POST",
        body: JSON.stringify({
          bankroll: params.bankroll,
          floor: params.floor,
          reach_target_probability: params.reachTargetProbability,
          solver: params.solver ?? "numba",
        }),
      },
    );
  }

  async companionGet(sessionId: string): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(`/api/companion/${sessionId}`, {
      method: "GET",
    });
  }

  /** @deprecated Legacy bankroll-deduction path; retained until live E2E confirms DOM flow. */
  async companionWagerDeduction(
    sessionId: string,
    observedBankrollDollars: number,
  ): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(
      `/api/companion/${sessionId}/wager-deduction`,
      {
        method: "POST",
        body: JSON.stringify({ observed_bankroll: observedBankrollDollars }),
      },
    );
  }

  async companionDomWager(
    sessionId: string,
    params: {
      observedBankrollDollars: number;
      betType: "DICE" | "ORANGE" | "BLACK";
      stakeDollars: number;
    },
  ): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(
      `/api/companion/${sessionId}/dom-wager`,
      {
        method: "POST",
        body: JSON.stringify({
          observed_bankroll: params.observedBankrollDollars,
          bet_type: params.betType,
          stake: params.stakeDollars,
        }),
      },
    );
  }

  async companionSettleRound(
    sessionId: string,
    winnerSide: "DICE" | "ORANGE" | "BLACK",
  ): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(
      `/api/companion/${sessionId}/settle-round`,
      {
        method: "POST",
        body: JSON.stringify({ winner_side: winnerSide }),
      },
    );
  }

  /** @deprecated Legacy register-wager path; not used by production service worker. */
  async companionRegisterWager(
    sessionId: string,
    params: CompanionRegisterWagerParams,
  ): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(
      `/api/companion/${sessionId}/register-wager`,
      {
        method: "POST",
        body: JSON.stringify(params),
      },
    );
  }

  /** @deprecated Legacy register-result path; not used by production service worker. */
  async companionRegisterResult(
    sessionId: string,
    params: CompanionRegisterResultParams,
  ): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(
      `/api/companion/${sessionId}/register-result`,
      {
        method: "POST",
        body: JSON.stringify(params),
      },
    );
  }

  async companionReconcile(
    sessionId: string,
    observedBankrollDollars: number,
  ): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(`/api/companion/${sessionId}/reconcile`, {
      method: "POST",
      body: JSON.stringify({ observed_bankroll: observedBankrollDollars }),
    });
  }

  async companionResync(
    sessionId: string,
    websiteBankrollDollars: number,
  ): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(`/api/companion/${sessionId}/resync`, {
      method: "POST",
      body: JSON.stringify({ observed_bankroll: websiteBankrollDollars }),
    });
  }

  async companionDiagnosticEvent(
    sessionId: string,
    kind: "BANKROLL_RECONCILED" | "BANKROLL_RECONCILIATION_WARNING",
    detail?: Record<string, unknown>,
  ): Promise<{ ok: boolean; session_id: string; kind: string }> {
    return this.request(`/api/companion/${sessionId}/diagnostic-event`, {
      method: "POST",
      body: JSON.stringify({ kind, detail: detail ?? null }),
    });
  }

  async companionStop(sessionId: string): Promise<CompanionStateResponse> {
    return this.request<CompanionStateResponse>(`/api/companion/${sessionId}/stop`, {
      method: "POST",
    });
  }

  async companionSave(sessionId: string): Promise<{
    saved: boolean;
    session_id: string;
    csv_path?: string | null;
    json_path?: string | null;
  }> {
    return this.request(`/api/companion/${sessionId}/save`, {
      method: "POST",
    });
  }

  async companionDiscard(sessionId: string): Promise<{ saved: boolean; session_id: string }> {
    return this.request<{ saved: boolean; session_id: string }>(
      `/api/companion/${sessionId}/discard`,
      { method: "POST" },
    );
  }
}
