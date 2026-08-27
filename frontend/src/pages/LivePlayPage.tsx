import { useState } from "react";
import { apiPost, ApiClientError } from "../api/client";
import type { PlayState } from "../api/types";
import { MoneyField } from "../components/MoneyField";
import { RecommendationPanel } from "../components/RecommendationPanel";
import {
  EmptyState,
  ErrorBanner,
  LoadingBlock,
  SuccessBanner,
} from "../components/Feedback";
import {
  formatDollars,
  formatProbability,
  terminalLabel,
  validateSessionInputs,
} from "../lib/format";

const DURABILITY_HELP =
  "Number of consecutive losses the current optimal policy can take before reaching FLOOR or NO_ACTION.";

export function LivePlayPage() {
  const [bankroll, setBankroll] = useState("10.00");
  const [target, setTarget] = useState("12.00");
  const [floor, setFloor] = useState("7.00");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<PlayState | null>(null);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [savePaths, setSavePaths] = useState<{ csv: string; json: string } | null>(null);

  async function startSession(e: React.FormEvent) {
    e.preventDefault();
    const v = validateSessionInputs(bankroll, target, floor);
    setErrors(v.errors);
    if (!v.values) return;
    setLoading(true);
    setError(null);
    setConfirmEnd(false);
    setCompleted(false);
    setSavePaths(null);
    try {
      const data = await apiPost<PlayState>("/api/play/start", {
        ...v.values,
      });
      setState(data);
    } catch (err) {
      setState(null);
      setError(err instanceof ApiClientError ? err.message : "Could not start session");
    } finally {
      setLoading(false);
    }
  }

  async function act(path: "win" | "loss" | "end") {
    if (!state) return;
    setActing(true);
    setError(null);
    try {
      const data = await apiPost<PlayState>(`/api/play/${state.session_id}/${path}`, {});
      setState(data);
      setConfirmEnd(false);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Action failed");
    } finally {
      setActing(false);
    }
  }

  async function finishSession(save: boolean) {
    if (!state) return;
    setActing(true);
    setError(null);
    try {
      const result = await apiPost<{
        saved: boolean;
        session_id: string;
        csv_path?: string | null;
        json_path?: string | null;
      }>(`/api/play/${state.session_id}/${save ? "save" : "discard"}`, {});
      if (save && result.csv_path && result.json_path) {
        setSavePaths({ csv: result.csv_path, json: result.json_path });
      } else {
        setSavePaths(null);
      }
      setState(null);
      setCompleted(true);
      setConfirmEnd(false);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not finish session");
    } finally {
      setActing(false);
    }
  }

  function startNewSession() {
    setState(null);
    setCompleted(false);
    setSavePaths(null);
    setError(null);
    setConfirmEnd(false);
  }

  const active = state?.status === "CONTINUE";
  const awaitingSave = Boolean(state?.awaiting_save);
  const terminal = state && state.status !== "CONTINUE";
  const durability =
    state?.consecutive_loss_durability ??
    state?.recommendation?.consecutive_loss_durability ??
    null;

  return (
    <div>
      <header className="page-header">
        <h1>Live Play</h1>
        <p>
          Follow a fixed verified policy. Record each outcome with Win or Loss.
          Does not predict COLOR sides or place bets.
        </p>
      </header>

      <form className="panel" onSubmit={startSession}>
        <div className="panel-title">Start session</div>
        <div className="row">
          <MoneyField
            id="live-bankroll"
            label="Bankroll ($)"
            value={bankroll}
            onChange={setBankroll}
            error={errors.bankroll}
            disabled={active || awaitingSave}
          />
          <MoneyField
            id="live-target"
            label="Target ($)"
            value={target}
            onChange={setTarget}
            error={errors.target}
            disabled={active || awaitingSave}
          />
          <MoneyField
            id="live-floor"
            label="Hard floor ($)"
            value={floor}
            onChange={setFloor}
            error={errors.floor}
            disabled={active || awaitingSave}
          />
          <button
            className="btn btn-primary"
            type="submit"
            disabled={loading || active || awaitingSave}
          >
            {loading ? "Preparing…" : "Start"}
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
          <LoadingBlock label="Solving and verifying policy…" />
        </div>
      ) : null}

      {!state && !loading && !completed ? (
        <div className="block-gap">
          <EmptyState>
            Start a session to follow the verified policy at your bankroll.
          </EmptyState>
        </div>
      ) : null}

      {completed ? (
        <div className="panel block-gap stack">
          <SuccessBanner
            message={
              savePaths
                ? `Session saved to ${savePaths.csv} (full detail: ${savePaths.json}).`
                : "Session finished."
            }
          />
          {savePaths ? (
            <p className="field-hint">
              Files are under the repo <code>outputs/saved_sessions/</code> folder (Docker volume).
            </p>
          ) : null}
          <button type="button" className="btn btn-primary" onClick={startNewSession}>
            Start New Session
          </button>
        </div>
      ) : null}

      {state ? (
        <div className="stack block-gap">
          <div className="live-session-layout">
            <div className="stack">
              <div className="panel">
                <div className="panel-title">Session state</div>
                <div className="stat-strip">
                  <div className="metric">
                    <span className="metric-label">Current bankroll</span>
                    <span className="metric-value">{formatDollars(state.bankroll)}</span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Target</span>
                    <span className="metric-value">{formatDollars(state.target)}</span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Floor</span>
                    <span className="metric-value">{formatDollars(state.floor)}</span>
                  </div>
                  <div className="metric metric-emphasis">
                    <span className="metric-label" title={DURABILITY_HELP}>
                      Loss durability
                    </span>
                    <span className="metric-value" title={DURABILITY_HELP}>
                      {durability == null ? "—" : `${durability} losses`}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Status</span>
                    <span className="metric-value">
                      {awaitingSave
                        ? "Session complete"
                        : terminalLabel(state.status)}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Rounds</span>
                    <span className="metric-value">{state.rounds_completed}</span>
                  </div>
                </div>
              </div>

              {state.recommendation && state.status === "CONTINUE" ? (
                <RecommendationPanel
                  recommendation={state.recommendation}
                  verification={state.verification}
                />
              ) : null}

              {terminal && !awaitingSave ? (
                <SuccessBanner message={`${terminalLabel(state.status)}.`} />
              ) : null}

              {awaitingSave ? (
                <div className="panel stack session-complete-panel">
                  <div className="panel-title">Session complete</div>
                  <p>
                    {terminalLabel(state.status)}. Final bankroll{" "}
                    {formatDollars(state.bankroll)} after {state.rounds_completed} round
                    {state.rounds_completed === 1 ? "" : "s"}.
                  </p>
                  <p className="field-hint">
                    Save writes a CSV summary and JSON detail under{" "}
                    <code>outputs/saved_sessions/</code>. Do not save discards this session.
                  </p>
                  <div className="play-controls play-controls-primary">
                    <button
                      type="button"
                      className="btn btn-primary btn-lg"
                      disabled={acting}
                      onClick={() => finishSession(true)}
                    >
                      Save Session
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-lg"
                      disabled={acting}
                      onClick={() => finishSession(false)}
                    >
                      Do Not Save
                    </button>
                  </div>
                </div>
              ) : null}

              {active ? (
                <div className="panel">
                  <div className="panel-title">Record outcome</div>
                  <div className="play-controls">
                    <button
                      type="button"
                      className="btn btn-success btn-lg"
                      disabled={acting}
                      onClick={() => act("win")}
                    >
                      WIN
                    </button>
                    <button
                      type="button"
                      className="btn btn-risk btn-lg"
                      disabled={acting}
                      onClick={() => act("loss")}
                    >
                      LOSS
                    </button>
                    {!confirmEnd ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-lg"
                        disabled={acting}
                        onClick={() => setConfirmEnd(true)}
                      >
                        End session
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="btn btn-risk"
                          disabled={acting}
                          onClick={() => act("end")}
                        >
                          Confirm end session
                        </button>
                        <button
                          type="button"
                          className="btn"
                          disabled={acting}
                          onClick={() => setConfirmEnd(false)}
                        >
                          Cancel
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ) : null}
            </div>
            <div className="panel">
              <div className="panel-title">Distance to terminals</div>
              <dl className="def-list">
                <dt>To target</dt>
                <dd className="mono">
                  {(
                    state.target.dollars - state.bankroll.dollars
                  ).toFixed(2)}{" "}
                  $
                </dd>
                <dt>Above floor</dt>
                <dd className="mono">
                  {(
                    state.bankroll.dollars - state.floor.dollars
                  ).toFixed(2)}{" "}
                  $
                </dd>
                <dt>Target-hit probability</dt>
                <dd className="mono">
                  {formatProbability(state.target_hit_probability)}
                </dd>
              </dl>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
