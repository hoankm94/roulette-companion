import type { Recommendation, Verification } from "../api/types";
import { actionClass, formatDollars, formatProbability } from "../lib/format";

const DURABILITY_HELP =
  "Number of consecutive losses the current optimal policy can take before reaching FLOOR or NO_ACTION. Does not predict a future losing streak.";

export function RecommendationPanel({
  recommendation,
  verification,
}: {
  recommendation: Recommendation;
  verification?: Verification | null;
}) {
  const action = recommendation.action;
  const durability = recommendation.consecutive_loss_durability ?? 0;
  return (
    <div className="panel reco">
      <div className="reco-primary">
        <div className="panel-title">Recommended action</div>
        <div className="reco-action">
          {recommendation.status === "ACTION" && action ? (
            <>
              <span className={actionClass(action)}>{action}</span>{" "}
              <span className="mono">{formatDollars(recommendation.stake)}</span>
            </>
          ) : (
            <span>{recommendation.status}</span>
          )}
        </div>
        <div className="reco-meta">
          <div className="metric">
            <span className="metric-label">Target-hit probability</span>
            <span className="metric-value">
              {formatProbability(recommendation.target_hit_probability)}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Current bankroll</span>
            <span className="metric-value">{formatDollars(recommendation.bankroll)}</span>
          </div>
          <div className="metric metric-emphasis">
            <span className="metric-label" title={DURABILITY_HELP}>
              Loss durability
            </span>
            <span className="metric-value" title={DURABILITY_HELP}>
              {durability} {durability === 1 ? "loss" : "losses"} to terminal
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Win bankroll</span>
            <span className="metric-value success">
              {formatDollars(recommendation.win_bankroll)}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Loss bankroll</span>
            <span className="metric-value risk">
              {formatDollars(recommendation.lose_bankroll)}
            </span>
          </div>
        </div>
        <p className="field-hint">{DURABILITY_HELP}</p>
      </div>
      <div>
        <div className="panel-title">Verification</div>
        {verification ? (
          <dl className="def-list">
            <dt>Status</dt>
            <dd>
              <span
                className={`badge ${
                  verification.deterministic_status === "VALID" ? "badge-valid" : "badge-fail"
                }`}
              >
                {verification.deterministic_status}
              </span>
            </dd>
            <dt>Policy eval</dt>
            <dd>{verification.policy_evaluation_passed ? "Pass" : "Fail"}</dd>
            <dt>Bellman</dt>
            <dd>{verification.bellman_passed ? "Pass" : "Fail"}</dd>
            <dt>Legality</dt>
            <dd>{verification.legal_actions_passed ? "Pass" : "Fail"}</dd>
          </dl>
        ) : (
          <p className="brand-sub">Not available</p>
        )}
      </div>
    </div>
  );
}
