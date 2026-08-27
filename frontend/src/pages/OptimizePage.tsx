import { useState } from "react";
import { apiPost, ApiClientError } from "../api/client";
import type { OptimizeResponse } from "../api/types";
import { MoneyField } from "../components/MoneyField";
import { RecommendationPanel } from "../components/RecommendationPanel";
import { DataTable } from "../components/DataTable";
import { EmptyState, ErrorBanner, LoadingBlock } from "../components/Feedback";
import {
  formatDollars,
  formatProbability,
  validateSessionInputs,
} from "../lib/format";

export function OptimizePage() {
  const [bankroll, setBankroll] = useState("10.00");
  const [target, setTarget] = useState("12.00");
  const [floor, setFloor] = useState("7.00");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OptimizeResponse | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const v = validateSessionInputs(bankroll, target, floor);
    setErrors(v.errors);
    if (!v.values) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiPost<OptimizeResponse>("/api/optimize", {
        ...v.values,
      });
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiClientError ? err.message : "Optimize failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <header className="page-header">
        <h1>Optimize</h1>
        <p>
          Solve and verify a Dynamic Goal-Directed policy. Money is entered in
          dollars; the API converts to integer cents for the solver.
        </p>
      </header>

      <form className="panel" onSubmit={onSubmit}>
        <div className="panel-title">Session</div>
        <div className="row">
          <MoneyField
            id="opt-bankroll"
            label="Bankroll ($)"
            value={bankroll}
            onChange={setBankroll}
            error={errors.bankroll}
          />
          <MoneyField
            id="opt-target"
            label="Target ($)"
            value={target}
            onChange={setTarget}
            error={errors.target}
          />
          <MoneyField
            id="opt-floor"
            label="Hard floor ($)"
            value={floor}
            onChange={setFloor}
            error={errors.floor}
          />
          <button className="btn btn-primary" type="submit" disabled={loading}>
            {loading ? "Solving…" : "Solve & verify"}
          </button>
        </div>
      </form>

      {error ? (
        <div className="stack block-gap">
          <ErrorBanner message={error} />
        </div>
      ) : null}

      {loading ? (
        <div className="panel block-gap">
          <LoadingBlock label="Running value iteration and verification…" />
        </div>
      ) : null}

      {!loading && !result && !error ? (
        <div className="block-gap">
          <EmptyState>
            Enter bankroll, target, and floor, then solve to see the recommended
            action and verified policy.
          </EmptyState>
        </div>
      ) : null}

      {result ? (
        <div className="stack block-gap">
          <div className="workspace-wide">
            <RecommendationPanel
              recommendation={result.recommendation}
              verification={result.verification}
            />
            <div className="panel">
              <div className="panel-title">Policy distribution</div>
              <dl className="def-list">
                <dt>COLOR states</dt>
                <dd>{result.distribution.color_count}</dd>
                <dt>DICE states</dt>
                <dd>{result.distribution.dice_count}</dd>
                <dt>NO_ACTION</dt>
                <dd>{result.distribution.no_action_count}</dd>
                <dt>Non-terminals</dt>
                <dd>{result.distribution.state_count}</dd>
                <dt>Iterations</dt>
                <dd>{result.solver.iterations}</dd>
                <dt>Final delta</dt>
                <dd>{result.solver.final_delta}</dd>
              </dl>
            </div>
          </div>

          <div className="workspace-wide table-secondary">
          <div className="panel">
            <div className="panel-title">Bankroll / value</div>
            <DataTable
              caption="Value table V(B)"
              columns={[
                {
                  key: "b",
                  header: "Bankroll",
                  mono: true,
                  sortValue: (r) => r.bankroll.cents,
                  render: (r) => formatDollars(r.bankroll),
                },
                {
                  key: "v",
                  header: "V(B)",
                  mono: true,
                  sortValue: (r) => r.value,
                  render: (r) => formatProbability(r.value),
                },
              ]}
              rows={result.values}
              rowKey={(r) => String(r.bankroll.cents)}
            />
          </div>

          <div className="panel">
            <div className="panel-title">Policy table</div>
            <DataTable
              caption="Policy by bankroll"
              columns={[
                {
                  key: "b",
                  header: "Bankroll",
                  mono: true,
                  sortValue: (r) => r.bankroll.cents,
                  render: (r) => formatDollars(r.bankroll),
                },
                {
                  key: "a",
                  header: "Action",
                  sortValue: (r) => r.action ?? "",
                  render: (r) => r.action ?? "—",
                },
                {
                  key: "s",
                  header: "Stake",
                  mono: true,
                  sortValue: (r) => r.stake?.cents ?? null,
                  render: (r) => formatDollars(r.stake),
                },
                {
                  key: "w",
                  header: "Win to",
                  mono: true,
                  sortValue: (r) => r.win_bankroll?.cents ?? null,
                  render: (r) => formatDollars(r.win_bankroll),
                },
                {
                  key: "l",
                  header: "Loss to",
                  mono: true,
                  sortValue: (r) => r.lose_bankroll?.cents ?? null,
                  render: (r) => formatDollars(r.lose_bankroll),
                },
                {
                  key: "p",
                  header: "P(target)",
                  mono: true,
                  sortValue: (r) => r.target_hit_probability,
                  render: (r) => formatProbability(r.target_hit_probability),
                },
              ]}
              rows={result.policy}
              rowKey={(r) => String(r.bankroll.cents)}
            />
          </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
