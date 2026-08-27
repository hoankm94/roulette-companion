import { useState } from "react";
import { apiPost, ApiClientError } from "../api/client";
import type { OptimizeResponse, Verification } from "../api/types";
import { MoneyField } from "../components/MoneyField";
import { EmptyState, ErrorBanner, LoadingBlock } from "../components/Feedback";
import {
  formatNumber,
  formatProbability,
  validateSessionInputs,
} from "../lib/format";

type ValidateResponse = {
  deterministic_status: string;
  verification: Verification;
  solver: {
    converged: boolean;
    iterations: number;
    final_delta: number;
    solver: string;
  };
  solver_probability: number;
  monte_carlo: {
    seed: number;
    sessions: number;
    target_hits: number;
    floor_hits: number;
    timeouts: number;
    p_hat: number;
    se: number;
    ci_lower: number;
    ci_upper: number;
    z_score: number;
    absolute_error: number;
  } | null;
  seeds: Array<{
    seed: number;
    p_hat: number;
    absolute_error: number;
    z_score: number;
  }> | null;
  max_absolute_difference: number | null;
};

export function DiagnosticsPage() {
  const [bankroll, setBankroll] = useState("0.01");
  const [target, setTarget] = useState("0.02");
  const [floor, setFloor] = useState("0.00");
  const [sessions, setSessions] = useState("1000");
  const [seed, setSeed] = useState("42");
  const [maxRounds, setMaxRounds] = useState("100");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verifyResult, setVerifyResult] = useState<OptimizeResponse | null>(null);
  const [validateResult, setValidateResult] = useState<ValidateResponse | null>(null);

  async function runVerify() {
    const v = validateSessionInputs(bankroll, target, floor);
    setErrors(v.errors);
    if (!v.values) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiPost<OptimizeResponse>("/api/diagnostics/verify", {
        ...v.values,
      });
      setVerifyResult(data);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  }

  async function runValidate() {
    const v = validateSessionInputs(bankroll, target, floor);
    setErrors(v.errors);
    if (!v.values) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiPost<ValidateResponse>("/api/diagnostics/validate", {
        ...v.values,
        sessions: Number(sessions),
        seed: Number(seed),
        max_rounds: Number(maxRounds),
      });
      setValidateResult(data);
      setVerifyResult(null);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Validation failed");
    } finally {
      setLoading(false);
    }
  }

  const verification = validateResult?.verification ?? verifyResult?.verification;
  const solver = validateResult?.solver ?? verifyResult?.solver;

  return (
    <div>
      <header className="page-header">
        <h1>Diagnostics</h1>
        <p>
          Technical verification and Monte Carlo checks. Secondary to normal
          optimize / live play use.
        </p>
      </header>

      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <div className="panel-title">Session & Monte Carlo controls</div>
        <div className="row">
          <MoneyField
            id="diag-bankroll"
            label="Bankroll ($)"
            value={bankroll}
            onChange={setBankroll}
            error={errors.bankroll}
          />
          <MoneyField
            id="diag-target"
            label="Target ($)"
            value={target}
            onChange={setTarget}
            error={errors.target}
          />
          <MoneyField
            id="diag-floor"
            label="Floor ($)"
            value={floor}
            onChange={setFloor}
            error={errors.floor}
          />
        </div>
        <div className="row">
          <div className="field">
            <label htmlFor="mc-sessions">MC sessions</label>
            <input
              id="mc-sessions"
              value={sessions}
              onChange={(e) => setSessions(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="mc-seed">Seed</label>
            <input id="mc-seed" value={seed} onChange={(e) => setSeed(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="mc-max">Max rounds</label>
            <input
              id="mc-max"
              value={maxRounds}
              onChange={(e) => setMaxRounds(e.target.value)}
            />
          </div>
        </div>
        <div className="row">
          <button type="button" className="btn" disabled={loading} onClick={runVerify}>
            Deterministic verify
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={loading}
            onClick={runValidate}
          >
            Verify + Monte Carlo
          </button>
        </div>
      </form>

      {error ? (
        <div className="block-gap">
          <ErrorBanner message={error} />
        </div>
      ) : null}
      {loading ? (
        <div className="panel block-gap">
          <LoadingBlock label="Running diagnostics…" />
        </div>
      ) : null}

      {!verification && !loading ? (
        <div className="block-gap">
          <EmptyState>
            Run deterministic verification or Monte Carlo validation when you need
            technical assurance beyond the Optimize readout.
          </EmptyState>
        </div>
      ) : null}

      {verification && solver ? (
        <div className="stack block-gap">
          <div className="workspace-wide">
          <div className="panel">
            <div className="panel-title">Deterministic verification</div>
            <dl className="def-list">
              <dt>Status</dt>
              <dd>
                <span
                  className={`badge ${
                    (validateResult?.deterministic_status ??
                      verification.deterministic_status) === "VALID"
                      ? "badge-valid"
                      : "badge-fail"
                  }`}
                >
                  {validateResult?.deterministic_status ?? verification.deterministic_status}
                </span>
              </dd>
              <dt>Policy evaluation</dt>
              <dd>{verification.policy_evaluation_passed ? "Pass" : "Fail"}</dd>
              <dt>Bellman (VI)</dt>
              <dd>{verification.bellman_passed ? "Pass" : "Fail"}</dd>
              <dt>Bellman (linear values)</dt>
              <dd>{verification.linear_value_bellman_passed ? "Pass" : "Fail"}</dd>
              <dt>Legality</dt>
              <dd>{verification.legal_actions_passed ? "Pass" : "Fail"}</dd>
              <dt>Max value difference</dt>
              <dd>{formatNumber(verification.max_value_difference, 12)}</dd>
              <dt>Max optimality gap</dt>
              <dd>{formatNumber(verification.max_optimality_gap, 12)}</dd>
              <dt>VI Bellman max gap</dt>
              <dd>{formatNumber(verification.vi_bellman_max_gap, 12)}</dd>
              <dt>Linear Bellman max gap</dt>
              <dd>{formatNumber(verification.linear_value_bellman_max_gap, 12)}</dd>
            </dl>
          </div>

          <div className="panel">
            <div className="panel-title">Convergence</div>
            <dl className="def-list">
              <dt>Converged</dt>
              <dd>{solver.converged ? "Yes" : "No"}</dd>
              <dt>Iterations</dt>
              <dd>{solver.iterations}</dd>
              <dt>Final delta</dt>
              <dd>{formatNumber(solver.final_delta, 12)}</dd>
              <dt>Solver</dt>
              <dd>{solver.solver}</dd>
              {validateResult ? (
                <>
                  <dt>Solver probability</dt>
                  <dd>{formatProbability(validateResult.solver_probability)}</dd>
                </>
              ) : null}
            </dl>
          </div>
          </div>

          {validateResult?.monte_carlo ? (
            <div className="panel">
              <div className="panel-title">Monte Carlo</div>
              <dl className="def-list">
                <dt>Seed</dt>
                <dd>{validateResult.monte_carlo.seed}</dd>
                <dt>Sessions</dt>
                <dd>{validateResult.monte_carlo.sessions}</dd>
                <dt>Target hits</dt>
                <dd>{validateResult.monte_carlo.target_hits}</dd>
                <dt>Floor hits</dt>
                <dd>{validateResult.monte_carlo.floor_hits}</dd>
                <dt>Timeouts</dt>
                <dd>{validateResult.monte_carlo.timeouts}</dd>
                <dt>p̂</dt>
                <dd>{formatProbability(validateResult.monte_carlo.p_hat)}</dd>
                <dt>95% CI</dt>
                <dd>
                  [{formatProbability(validateResult.monte_carlo.ci_lower)},{" "}
                  {formatProbability(validateResult.monte_carlo.ci_upper)}]
                </dd>
                <dt>z-score</dt>
                <dd>{formatNumber(validateResult.monte_carlo.z_score, 4)}</dd>
                <dt>|p̂ − V|</dt>
                <dd>{formatNumber(validateResult.monte_carlo.absolute_error, 6)}</dd>
              </dl>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
