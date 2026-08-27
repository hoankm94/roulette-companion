import { useRef, useState, type ReactNode } from "react";
import { apiPost, ApiClientError } from "../api/client";
import { MoneyField } from "../components/MoneyField";
import { DataTable } from "../components/DataTable";
import {
  EmptyState,
  ErrorBanner,
  InfoBanner,
  LoadingBlock,
} from "../components/Feedback";
import {
  extremeHelp,
  extremeTitle,
  isPrimaryPolicyExtreme,
} from "../lib/extremes";
import {
  actionClass,
  formatDollars,
  formatDurationSeconds,
  formatEstimatedTime,
  formatPct,
  formatProbability,
  REPLAY_TIMEZONES,
  terminalLabel,
  validateSessionInputs,
} from "../lib/format";

type ColorAssumption = "alternate" | "orange" | "black";

function colorAssumptionPayload(assumption: ColorAssumption): {
  color_side: string;
  alternate_first?: string;
} {
  if (assumption === "alternate") {
    return { color_side: "alternate", alternate_first: "orange" };
  }
  return { color_side: assumption };
}

type TimingFields = {
  estimated_start_time?: string | null;
  estimated_end_time?: string | null;
  estimated_duration_seconds?: number | null;
  timezone?: string | null;
  timing_status?: string | null;
};

type AnalyzeResponse = {
  round_start: number;
  round_end: number;
  total_rolls: number;
  dice_count: number;
  orange_count: number;
  black_count: number;
  dice_pct: number;
  orange_pct: number;
  black_pct: number;
  theoretical_dice_pct: number;
  theoretical_color_pct: number;
  longest_orange_streak: Streak;
  longest_black_streak: Streak;
  longest_same_color_streak: Streak;
  longest_dice_streak: Streak;
  longest_dice_drought: Drought;
  dice_droughts_ge_35: number;
  dice_droughts_ge_45: number;
  longest_orange_drought: Drought;
  longest_black_drought: Drought;
  window_extremes: WindowExt[];
  seed_date?: string | null;
  timezone?: string | null;
  average_cycle_seconds?: number | null;
  timing_status?: string | null;
};

type Streak = TimingFields & {
  outcome: string;
  length: number;
  start_round: number;
  end_round: number;
};
type Drought = TimingFields & {
  missing: string;
  length: number;
  start_round: number;
  end_round: number;
  dice_count: number;
  orange_count: number;
  black_count: number;
};
type WindowExt = TimingFields & {
  window_size: number;
  outcome: string;
  extremum: string;
  count: number;
  start_round: number;
  end_round: number;
};

type RunResponse = {
  summaries: Summary[];
  sessions: SessionRow[];
  solve_calls: number;
  note: string;
};

type Summary = {
  scenario: string;
  color_side: string;
  start_mode: string;
  start_bankroll: { dollars: number };
  target: { dollars: number };
  floor: { dollars: number };
  start_count: number;
  target_count: number;
  floor_count: number;
  no_action_count: number;
  exhausted_count: number;
  resolved_count: number;
  target_rate_all: number;
  target_rate_resolved: number;
  theoretical_V_start: number;
  largest_drawdown: { dollars: number };
  longest_losing_bet_streak: number;
  seed_date?: string | null;
  timezone?: string | null;
  average_cycle_seconds?: number | null;
  timing_status?: string | null;
};

type SessionRow = {
  start_round: number;
  last_round: number | null;
  terminal_status: string;
  end_bankroll: { dollars: number };
  maximum_drawdown: { dollars: number };
  color_side: string;
  rolls_consumed: number;
  longest_losing_bet_streak?: number;
  starting_loss_durability?: number;
  minimum_loss_durability?: number;
  ending_loss_durability?: number;
  estimated_start_time?: string | null;
  estimated_last_time?: string | null;
  timezone?: string | null;
  timing_status?: string | null;
};

type ExtremesResponse = {
  analysis: AnalyzeResponse;
  extreme_rows: ExtremeRow[];
  summaries: Summary[];
  solve_calls: number;
};

type ExtremeRow = TimingFields & {
  extreme_kind: string;
  extreme_label: string;
  extreme_start_round: number;
  extreme_end_round: number;
  color_side: string;
  session: SessionRow & {
    start_bankroll: { dollars: number };
    target: { dollars: number };
    floor: { dollars: number };
  };
};

type Tab = "overview" | "replay" | "extremes";

function OutcomeLabel({ outcome }: { outcome: string }) {
  const cls = actionClass(outcome);
  return <span className={cls || undefined}>{outcome}</span>;
}

function colorAssumptionLabel(assumption: ColorAssumption): ReactNode {
  if (assumption === "alternate") {
    return (
      <>
        Alternate (<span className="bet-color">Orange</span> first)
      </>
    );
  }
  if (assumption === "orange") {
    return (
      <>
        Fixed <span className="bet-color">Orange</span>
      </>
    );
  }
  return (
    <>
      Fixed <span className="bet-color">Black</span>
    </>
  );
}

function hasTiming(status: string | null | undefined): boolean {
  return status === "ESTIMATED";
}

function TimingBadge() {
  return <span className="badge badge-warn">Estimated</span>;
}

function timingColumns<T extends TimingFields>(enabled: boolean) {
  if (!enabled) return [];
  return [
    {
      key: "est_start",
      header: "Est. start",
      mono: true,
      sortValue: (r: T) => r.estimated_start_time ?? "",
      render: (r: T) => formatEstimatedTime(r.estimated_start_time),
    },
    {
      key: "est_end",
      header: "Est. end",
      mono: true,
      sortValue: (r: T) => r.estimated_end_time ?? "",
      render: (r: T) => formatEstimatedTime(r.estimated_end_time),
    },
    {
      key: "est_dur",
      header: "Duration",
      mono: true,
      sortValue: (r: T) => r.estimated_duration_seconds ?? null,
      render: (r: T) => formatDurationSeconds(r.estimated_duration_seconds),
    },
  ];
}

export function ReplayLabPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [serverSeed, setServerSeed] = useState("");
  const [publicSeed, setPublicSeed] = useState("");
  const [rounds, setRounds] = useState("12609767 - 12609790");
  const [seedDate, setSeedDate] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [bankroll, setBankroll] = useState("13.68");
  const [target, setTarget] = useState("15.00");
  const [floor, setFloor] = useState("7.00");
  const [colorAssumption, setColorAssumption] =
    useState<ColorAssumption>("alternate");
  const [startMode, setStartMode] = useState<"first" | "random" | "all">("first");
  const [samples, setSamples] = useState("50");
  const [sampleSeed, setSampleSeed] = useState("42");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState("Processing historical sequence…");
  const [error, setError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [run, setRun] = useState<RunResponse | null>(null);
  const [extremes, setExtremes] = useState<ExtremesResponse | null>(null);
  const [selectedExtreme, setSelectedExtreme] = useState<ExtremeRow | null>(null);
  const [softWarn, setSoftWarn] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function seedPayload() {
    const body: Record<string, unknown> = {
      server_seed: serverSeed,
      public_seed: publicSeed,
      rounds,
      timezone,
    };
    if (seedDate.trim()) body.seed_date = seedDate.trim();
    return body;
  }

  function beginRequest(label: string) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setLoadingLabel(label);
    setError(null);
    return controller;
  }

  function endRequest(controller: AbortController) {
    if (abortRef.current === controller) {
      abortRef.current = null;
      setLoading(false);
    }
  }

  function cancelRequest() {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setError(null);
    setSoftWarn(null);
  }

  function isAbortError(err: unknown): boolean {
    return (
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError")
    );
  }

  async function runAnalyze() {
    setSoftWarn(null);
    const controller = beginRequest("Analyzing seed overview…");
    try {
      const data = await apiPost<AnalyzeResponse>(
        "/api/replay/analyze",
        seedPayload(),
        { signal: controller.signal },
      );
      setAnalysis(data);
      setTab("overview");
    } catch (err) {
      if (isAbortError(err)) return;
      setError(err instanceof ApiClientError ? err.message : "Analyze failed");
    } finally {
      endRequest(controller);
    }
  }

  async function runReplay() {
    setSoftWarn(null);
    const v = validateSessionInputs(bankroll, target, floor);
    setFieldErrors(v.errors);
    if (!v.values) return;
    const controller = beginRequest("Running historical replay…");
    try {
      const body: Record<string, unknown> = {
        ...seedPayload(),
        ...v.values,
        ...colorAssumptionPayload(colorAssumption),
        start_mode: startMode,
      };
      if (startMode === "random") {
        body.samples = Number(samples);
        body.sample_seed = Number(sampleSeed);
      }
      const data = await apiPost<RunResponse>("/api/replay/run", body, {
        signal: controller.signal,
      });
      setRun(data);
      setTab("replay");
    } catch (err) {
      if (isAbortError(err)) return;
      setError(err instanceof ApiClientError ? err.message : "Replay failed");
    } finally {
      endRequest(controller);
    }
  }

  async function runExtremes() {
    const v = validateSessionInputs(bankroll, target, floor);
    setFieldErrors(v.errors);
    if (!v.values) return;
    if (!analysis) {
      setSoftWarn(
        "Overview is not loaded yet. Extremes will still run and will fill Overview seed stats when it finishes. Cancel anytime.",
      );
    } else {
      setSoftWarn(null);
    }
    const controller = beginRequest("Computing extreme sequences…");
    try {
      const data = await apiPost<ExtremesResponse>(
        "/api/replay/extremes",
        {
          ...seedPayload(),
          ...v.values,
          ...colorAssumptionPayload(colorAssumption),
        },
        { signal: controller.signal },
      );
      setExtremes(data);
      setAnalysis(data.analysis);
      setSelectedExtreme(null);
      setSoftWarn(null);
      setTab("extremes");
    } catch (err) {
      if (isAbortError(err)) return;
      setError(err instanceof ApiClientError ? err.message : "Extremes failed");
    } finally {
      endRequest(controller);
    }
  }

  const analysisTimed = hasTiming(analysis?.timing_status);
  const runTimed = hasTiming(run?.sessions[0]?.timing_status ?? run?.summaries[0]?.timing_status);
  const extremesTimed = hasTiming(
    extremes?.extreme_rows[0]?.timing_status ?? extremes?.analysis?.timing_status,
  );

  return (
    <div>
      <header className="page-header">
        <h1>Replay Lab</h1>
        <p>
          Reconstruct a revealed historical seed sequence. Observed rates are not
          the same as theoretical V(start). Optional seed date maps rounds to
          estimated wall-clock times.
        </p>
      </header>

      <div className="workspace-split">
      <div className="panel stack">
        <div className="panel-title">Seed & scenario</div>
        <div className="field">
          <label htmlFor="server-seed">Server seed</label>
          <input
            id="server-seed"
            value={serverSeed}
            onChange={(e) => setServerSeed(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="public-seed">Public seed</label>
          <input
            id="public-seed"
            value={publicSeed}
            onChange={(e) => setPublicSeed(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="rounds">Rounds</label>
          <input
            id="rounds"
            value={rounds}
            onChange={(e) => setRounds(e.target.value)}
            placeholder="12609767 - 12613349"
          />
        </div>

        <div className="row">
          <MoneyField
            id="rp-bankroll"
            label="Bankroll ($)"
            value={bankroll}
            onChange={setBankroll}
            error={fieldErrors.bankroll}
          />
          <MoneyField
            id="rp-target"
            label="Target ($)"
            value={target}
            onChange={setTarget}
            error={fieldErrors.target}
          />
          <MoneyField
            id="rp-floor"
            label="Floor ($)"
            value={floor}
            onChange={setFloor}
            error={fieldErrors.floor}
          />
        </div>

        <details className="disclose" open={Boolean(seedDate)}>
          <summary>Estimated timing</summary>
          <div className="disclose-body">
            <div className="row">
              <div className="field">
                <label htmlFor="seed-date">Seed date (optional)</label>
                <input
                  id="seed-date"
                  type="date"
                  value={seedDate}
                  onChange={(e) => setSeedDate(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="timezone">Timezone</label>
                <select
                  id="timezone"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  disabled={!seedDate}
                >
                  {REPLAY_TIMEZONES.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <p className="field-hint">
              Leave empty to skip timestamps. Round numbers stay authoritative. Timezone is
              an IANA name; default UTC when seed date is set.
            </p>
            {seedDate ? (
              <InfoBanner message="Timestamps are estimated from the seed day's 24-hour span and total round count. Individual rounds may drift due to delays or downtime." />
            ) : null}
          </div>
        </details>

        <details className="disclose">
          <summary>Policy assumptions</summary>
          <div className="disclose-body">
            <div className="row">
              <div className="field">
                <label htmlFor="color-side">COLOR assumption</label>
                <select
                  id="color-side"
                  value={colorAssumption}
                  onChange={(e) =>
                    setColorAssumption(e.target.value as ColorAssumption)
                  }
                >
                  <option value="alternate">Alternate</option>
                  <option value="orange">Fixed Orange</option>
                  <option value="black">Fixed Black</option>
                </select>
                <p className="field-hint">
                  Alternate uses Orange first, then Black, then Orange…
                </p>
              </div>
              <div className="field">
                <label htmlFor="start-mode">Start mode</label>
                <select
                  id="start-mode"
                  value={startMode}
                  onChange={(e) => setStartMode(e.target.value as typeof startMode)}
                >
                  <option value="first">First</option>
                  <option value="random">Random</option>
                  <option value="all">All</option>
                </select>
              </div>
              {startMode === "random" ? (
                <>
                  <div className="field">
                    <label htmlFor="samples">Sample count</label>
                    <input
                      id="samples"
                      value={samples}
                      onChange={(e) => setSamples(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="sample-seed">Sampling seed</label>
                    <input
                      id="sample-seed"
                      value={sampleSeed}
                      onChange={(e) => setSampleSeed(e.target.value)}
                    />
                  </div>
                </>
              ) : null}
            </div>
            <p className="field-hint">
              Alternation advances only when the policy places a COLOR bet. DICE bets
              do not change the next COLOR side.
            </p>
          </div>
        </details>

        <div className="row cta-primary-row">
          <button
            type="button"
            className="btn"
            disabled={loading}
            onClick={runAnalyze}
            title="Fills the Overview tab"
          >
            Analyze → Overview
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={loading}
            onClick={runReplay}
            title="Fills the Replay tab"
          >
            Run → Replay
          </button>
          <button
            type="button"
            className="btn"
            disabled={loading}
            onClick={runExtremes}
            title="Fills the Extremes tab"
          >
            Compute → Extremes
          </button>
        </div>
      </div>

      <div className="panel stack">
        <div className="panel-title">Loaded seed summary</div>
        {analysis ? (
          <dl className="def-list">
            <dt>Rounds</dt>
            <dd className="mono">
              {analysis.round_start}–{analysis.round_end} ({analysis.total_rolls})
            </dd>
            <dt>DICE / ORANGE / BLACK</dt>
            <dd className="mono">
              {formatPct(analysis.dice_pct)} / {formatPct(analysis.orange_pct)} /{" "}
              {formatPct(analysis.black_pct)}
            </dd>
            <dt>Longest gap without DICE</dt>
            <dd className="mono">{analysis.longest_dice_drought.length} rolls</dd>
            <dt>Droughts of 35+ / 45+ rolls</dt>
            <dd className="mono">
              {analysis.dice_droughts_ge_35} / {analysis.dice_droughts_ge_45}
            </dd>
            <dt>Timing</dt>
            <dd>
              {analysisTimed ? (
                <>
                  <TimingBadge />{" "}
                  {analysis.average_cycle_seconds != null
                    ? `${analysis.average_cycle_seconds.toFixed(2)}s/cycle`
                    : "Estimated"}
                </>
              ) : (
                "Not requested"
              )}
            </dd>
          </dl>
        ) : (
          <p className="brand-sub">Analyze → Overview to load seed stats here.</p>
        )}
        <div className="panel-title">Current replay configuration</div>
        <dl className="def-list">
          <dt>Bankroll / Target / Floor</dt>
          <dd className="mono">
            ${bankroll} / ${target} / ${floor}
          </dd>
          <dt>COLOR assumption</dt>
          <dd>{colorAssumptionLabel(colorAssumption)}</dd>
          <dt>Start mode</dt>
          <dd>{startMode}</dd>
        </dl>
      </div>
      </div>

      {softWarn ? (
        <div className="block-gap">
          <InfoBanner message={softWarn} />
        </div>
      ) : null}
      {error ? (
        <div className="block-gap">
          <ErrorBanner message={error} />
        </div>
      ) : null}
      {loading ? (
        <div className="panel block-gap loading-bar">
          <LoadingBlock label={loadingLabel} />
          <button type="button" className="btn btn-ghost" onClick={cancelRequest}>
            Cancel
          </button>
        </div>
      ) : null}

      <div className="tabs tabs-gap" role="tablist" aria-label="Replay lab views">
        {(
          [
            { id: "overview" as const, label: "Overview", ready: Boolean(analysis) },
            { id: "replay" as const, label: "Replay", ready: Boolean(run) },
            { id: "extremes" as const, label: "Extremes", ready: Boolean(extremes) },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            id={`replay-tab-${t.id}`}
            role="tab"
            className="tab"
            aria-selected={tab === t.id}
            aria-controls={`replay-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.ready ? <span className="tab-ready">ready</span> : null}
          </button>
        ))}
      </div>

      <div
        id="replay-panel-overview"
        role="tabpanel"
        aria-labelledby="replay-tab-overview"
        hidden={tab !== "overview"}
      >
        {analysis ? (
          <div className="stack">
            <div className="panel">
              <div className="panel-title">
                Outcome counts vs theory {analysisTimed ? <TimingBadge /> : null}
              </div>
              <DataTable
                caption="Outcome distribution vs theoretical"
                columns={[
                  {
                    key: "o",
                    header: "Outcome",
                    sortValue: (r) => r.outcome,
                    render: (r) => <OutcomeLabel outcome={r.outcome} />,
                  },
                  {
                    key: "c",
                    header: "Count",
                    mono: true,
                    sortValue: (r) => r.count,
                    render: (r) => r.count,
                  },
                  {
                    key: "p",
                    header: "Observed",
                    mono: true,
                    sortValue: (r) => r.pct,
                    render: (r) => formatPct(r.pct),
                  },
                  {
                    key: "t",
                    header: "Theoretical",
                    mono: true,
                    sortValue: (r) => r.theory,
                    render: (r) => formatPct(r.theory),
                  },
                ]}
                rows={[
                  {
                    outcome: "DICE",
                    count: analysis.dice_count,
                    pct: analysis.dice_pct,
                    theory: analysis.theoretical_dice_pct,
                  },
                  {
                    outcome: "ORANGE",
                    count: analysis.orange_count,
                    pct: analysis.orange_pct,
                    theory: analysis.theoretical_color_pct,
                  },
                  {
                    outcome: "BLACK",
                    count: analysis.black_count,
                    pct: analysis.black_pct,
                    theory: analysis.theoretical_color_pct,
                  },
                ]}
                rowKey={(r) => r.outcome}
              />
            </div>
            <div className="workspace-wide">
            <div className="panel">
              <div className="panel-title">
                Longest streaks {analysisTimed ? <TimingBadge /> : null}
              </div>
              <DataTable
                columns={[
                  {
                    key: "o",
                    header: "Outcome",
                    sortValue: (r) => r.outcome,
                    render: (r) => <OutcomeLabel outcome={r.outcome} />,
                  },
                  {
                    key: "l",
                    header: "Length",
                    mono: true,
                    sortValue: (r) => r.length,
                    render: (r) => r.length,
                  },
                  {
                    key: "r",
                    header: "Rounds",
                    mono: true,
                    sortValue: (r) => r.start_round,
                    render: (r) => `${r.start_round}–${r.end_round}`,
                  },
                  ...timingColumns<Streak>(analysisTimed),
                ]}
                rows={[
                  analysis.longest_orange_streak,
                  analysis.longest_black_streak,
                  analysis.longest_dice_streak,
                  analysis.longest_same_color_streak,
                ]}
                rowKey={(r, i) => `${r.outcome}-${r.start_round}-${i}`}
              />
            </div>
            <div className="panel">
              <div className="panel-title">
                DICE droughts {analysisTimed ? <TimingBadge /> : null}
              </div>
              <DataTable
                columns={[
                  {
                    key: "metric",
                    header: "Metric",
                    sortValue: (r) => r.metric,
                    render: (r) => r.metric,
                  },
                  {
                    key: "l",
                    header: "Count / length",
                    mono: true,
                    sortValue: (r) => r.value,
                    render: (r) => r.value,
                  },
                  {
                    key: "r",
                    header: "Rounds",
                    mono: true,
                    sortValue: (r) => r.rounds ?? "",
                    render: (r) => r.rounds ?? "—",
                  },
                  ...timingColumns<{ metric: string; value: number; rounds?: string } & TimingFields>(
                    analysisTimed,
                  ),
                ]}
                rows={[
                  {
                    metric: "Longest gap without DICE",
                    value: analysis.longest_dice_drought.length,
                    rounds: `${analysis.longest_dice_drought.start_round}–${analysis.longest_dice_drought.end_round}`,
                    estimated_start_time: analysis.longest_dice_drought.estimated_start_time,
                    estimated_end_time: analysis.longest_dice_drought.estimated_end_time,
                    estimated_duration_seconds:
                      analysis.longest_dice_drought.estimated_duration_seconds,
                    timezone: analysis.longest_dice_drought.timezone,
                    timing_status: analysis.longest_dice_drought.timing_status,
                  },
                  {
                    metric: "Droughts of 35+ rolls",
                    value: analysis.dice_droughts_ge_35,
                  },
                  {
                    metric: "Droughts of 45+ rolls",
                    value: analysis.dice_droughts_ge_45,
                  },
                ]}
                rowKey={(r) => r.metric}
              />
            </div>
            <div className="panel">
              <div className="panel-title">
                Most DICE-heavy windows {analysisTimed ? <TimingBadge /> : null}
              </div>
              <DataTable
                columns={[
                  {
                    key: "w",
                    header: "Window",
                    mono: true,
                    sortValue: (r) => r.window_size,
                    render: (r) => r.window_size,
                  },
                  {
                    key: "o",
                    header: "Outcome",
                    sortValue: (r) => r.outcome,
                    render: (r) => <OutcomeLabel outcome={r.outcome} />,
                  },
                  {
                    key: "e",
                    header: "Extremum",
                    sortValue: (r) => r.extremum,
                    render: (r) => r.extremum,
                  },
                  {
                    key: "c",
                    header: "Count",
                    mono: true,
                    sortValue: (r) => r.count,
                    render: (r) => r.count,
                  },
                  {
                    key: "r",
                    header: "Rounds",
                    mono: true,
                    sortValue: (r) => r.start_round,
                    render: (r) => `${r.start_round}–${r.end_round}`,
                  },
                  ...timingColumns<WindowExt>(analysisTimed),
                ]}
                rows={analysis.window_extremes.filter(
                  (w) =>
                    w.window_size === 50 &&
                    w.outcome === "DICE" &&
                    w.extremum === "highest",
                )}
                rowKey={(r, i) => `${r.window_size}-${r.outcome}-${r.extremum}-${i}`}
              />
            </div>
            </div>
          </div>
        ) : (
          <EmptyState>
            Use Analyze → Overview to load distribution and streak stats.
          </EmptyState>
        )}
      </div>

      <div
        id="replay-panel-replay"
        role="tabpanel"
        aria-labelledby="replay-tab-replay"
        hidden={tab !== "replay"}
      >
        {run ? (
          <div className="stack">
            <InfoBanner message={run.note} />
            {run.summaries.map((s) => (
              <div className="panel" key={`${s.color_side}-${s.start_mode}`}>
                <div className="panel-title">
                  Summary — {s.color_side} / {s.start_mode}{" "}
                  {hasTiming(s.timing_status) ? <TimingBadge /> : null}
                </div>
                <dl className="def-list">
                  <dt>TARGET / FLOOR / NO_ACTION / EXHAUSTED</dt>
                  <dd>
                    {s.target_count} / {s.floor_count} / {s.no_action_count} /{" "}
                    {s.exhausted_count}
                  </dd>
                  <dt>Target rate (all starts)</dt>
                  <dd>{formatPct(s.target_rate_all)} — historical observed</dd>
                  <dt>Target rate (resolved)</dt>
                  <dd>{formatPct(s.target_rate_resolved)} — historical observed</dd>
                  <dt>Theoretical V(start)</dt>
                  <dd>{formatProbability(s.theoretical_V_start)} — solver</dd>
                  <dt>Largest bankroll drawdown</dt>
                  <dd>
                    {formatDollars(s.largest_drawdown)}
                    {extremeHelp("largest_bankroll_drawdown") ? (
                      <span className="field-hint">
                        {extremeHelp("largest_bankroll_drawdown")}
                      </span>
                    ) : null}
                  </dd>
                  <dt>Longest losing bet streak</dt>
                  <dd>
                    {s.longest_losing_bet_streak}
                    {extremeHelp("longest_losing_bet_streak") ? (
                      <span className="field-hint">
                        {extremeHelp("longest_losing_bet_streak")}
                      </span>
                    ) : null}
                  </dd>
                  {hasTiming(s.timing_status) ? (
                    <>
                      <dt>Seed date</dt>
                      <dd className="mono">{s.seed_date}</dd>
                      <dt>Timezone</dt>
                      <dd className="mono">{s.timezone}</dd>
                      <dt>Avg cycle</dt>
                      <dd className="mono">
                        {s.average_cycle_seconds != null
                          ? `${s.average_cycle_seconds.toFixed(3)}s`
                          : "—"}
                      </dd>
                    </>
                  ) : null}
                </dl>
              </div>
            ))}
            <div className="panel">
              <div className="panel-title">
                Sessions (sample) {runTimed ? <TimingBadge /> : null}
              </div>
              <DataTable
                columns={[
                  {
                    key: "side",
                    header: "Color",
                    sortValue: (r) => r.color_side,
                    render: (r) => r.color_side,
                  },
                  {
                    key: "sr",
                    header: "Start",
                    mono: true,
                    sortValue: (r) => r.start_round,
                    render: (r) => r.start_round,
                  },
                  {
                    key: "lr",
                    header: "Last",
                    mono: true,
                    sortValue: (r) => r.last_round ?? null,
                    render: (r) => r.last_round ?? "—",
                  },
                  ...(runTimed
                    ? [
                        {
                          key: "est_s",
                          header: "Est. start",
                          mono: true,
                          sortValue: (r: SessionRow) => r.estimated_start_time ?? "",
                          render: (r: SessionRow) =>
                            formatEstimatedTime(r.estimated_start_time),
                        },
                        {
                          key: "est_l",
                          header: "Est. last",
                          mono: true,
                          sortValue: (r: SessionRow) => r.estimated_last_time ?? "",
                          render: (r: SessionRow) =>
                            formatEstimatedTime(r.estimated_last_time),
                        },
                      ]
                    : []),
                  {
                    key: "st",
                    header: "Status",
                    sortValue: (r) => r.terminal_status,
                    render: (r) => terminalLabel(r.terminal_status),
                  },
                  {
                    key: "eb",
                    header: "End bankroll",
                    mono: true,
                    sortValue: (r) => r.end_bankroll.dollars,
                    render: (r) => formatDollars(r.end_bankroll),
                  },
                  {
                    key: "dd",
                    header: "Drawdown",
                    mono: true,
                    sortValue: (r) => r.maximum_drawdown.dollars,
                    render: (r) => formatDollars(r.maximum_drawdown),
                  },
                  {
                    key: "lose_streak",
                    header: "Lose streak",
                    mono: true,
                    sortValue: (r) => r.longest_losing_bet_streak ?? 0,
                    render: (r) => r.longest_losing_bet_streak ?? "—",
                  },
                  {
                    key: "dur_start",
                    header: "Start durability",
                    mono: true,
                    sortValue: (r) => r.starting_loss_durability ?? 0,
                    render: (r) => r.starting_loss_durability ?? "—",
                  },
                  {
                    key: "dur_min",
                    header: "Min durability",
                    mono: true,
                    sortValue: (r) => r.minimum_loss_durability ?? 0,
                    render: (r) => r.minimum_loss_durability ?? "—",
                  },
                  {
                    key: "dur_end",
                    header: "End durability",
                    mono: true,
                    sortValue: (r) => r.ending_loss_durability ?? 0,
                    render: (r) => r.ending_loss_durability ?? "—",
                  },
                ]}
                rows={run.sessions}
                rowKey={(r, i) => `${r.start_round}-${r.color_side}-${i}`}
              />
            </div>
            <p className="field-hint">
              Compare starting / minimum / ending loss durability with the longest
              historical losing-bet streak on each session.
            </p>
          </div>
        ) : (
          <EmptyState>
            Use Run → Replay to compare historical terminals against theoretical V.
          </EmptyState>
        )}
      </div>

      <div
        id="replay-panel-extremes"
        role="tabpanel"
        aria-labelledby="replay-tab-extremes"
        hidden={tab !== "extremes"}
      >
        {extremes ? (
          <div className="stack">
            <InfoBanner message="Select a row for definition and session detail. Labels use policy and historical extreme names." />
            <div className="panel">
              <div className="panel-title">
                Extreme rows {extremesTimed ? <TimingBadge /> : null}
              </div>
              <DataTable
                columns={[
                  {
                    key: "k",
                    header: "Kind",
                    sortValue: (r) => r.extreme_kind,
                    render: (r) => r.extreme_kind,
                  },
                  {
                    key: "l",
                    header: "Label",
                    sortValue: (r) => extremeTitle(r.extreme_label),
                    render: (r) => extremeTitle(r.extreme_label),
                  },
                  {
                    key: "r",
                    header: "Range",
                    mono: true,
                    sortValue: (r) => r.extreme_start_round,
                    render: (r) => `${r.extreme_start_round}–${r.extreme_end_round}`,
                  },
                  ...timingColumns<ExtremeRow>(extremesTimed),
                  {
                    key: "c",
                    header: "Color",
                    sortValue: (r) => r.color_side,
                    render: (r) => r.color_side,
                  },
                  {
                    key: "s",
                    header: "Terminal",
                    sortValue: (r) => r.session.terminal_status,
                    render: (r) => terminalLabel(r.session.terminal_status),
                  },
                  {
                    key: "e",
                    header: "End $",
                    mono: true,
                    sortValue: (r) => r.session.end_bankroll.dollars,
                    render: (r) => formatDollars(r.session.end_bankroll),
                  },
                ]}
                rows={extremes.extreme_rows.filter(
                  (r) =>
                    r.extreme_kind.startsWith("website:") ||
                    isPrimaryPolicyExtreme(r.extreme_label),
                )}
                rowKey={(r) =>
                  `${r.extreme_label}-${r.color_side}-${r.extreme_start_round}-${r.extreme_end_round}`
                }
                selectedKey={
                  selectedExtreme
                    ? `${selectedExtreme.extreme_label}-${selectedExtreme.color_side}-${selectedExtreme.extreme_start_round}-${selectedExtreme.extreme_end_round}`
                    : null
                }
                onSelect={setSelectedExtreme}
              />
            </div>
            {selectedExtreme ? (
              <div className="panel">
                <div className="panel-title">
                  Selected extreme detail{" "}
                  {hasTiming(selectedExtreme.timing_status) ? <TimingBadge /> : null}
                </div>
                <dl className="def-list">
                  <dt>Label</dt>
                  <dd>
                    {extremeTitle(selectedExtreme.extreme_label)}
                    {extremeHelp(selectedExtreme.extreme_label) ? (
                      <span className="field-hint">
                        {extremeHelp(selectedExtreme.extreme_label)}
                      </span>
                    ) : null}
                  </dd>
                  <dt>Round range</dt>
                  <dd>
                    {selectedExtreme.extreme_start_round}–{selectedExtreme.extreme_end_round}
                  </dd>
                  {hasTiming(selectedExtreme.timing_status) ? (
                    <>
                      <dt>Est. start</dt>
                      <dd className="mono">
                        {formatEstimatedTime(selectedExtreme.estimated_start_time)}
                      </dd>
                      <dt>Est. end</dt>
                      <dd className="mono">
                        {formatEstimatedTime(selectedExtreme.estimated_end_time)}
                      </dd>
                      <dt>Duration</dt>
                      <dd className="mono">
                        {formatDurationSeconds(selectedExtreme.estimated_duration_seconds)}
                      </dd>
                      <dt>Timezone</dt>
                      <dd className="mono">{selectedExtreme.timezone}</dd>
                    </>
                  ) : null}
                  <dt>Session start</dt>
                  <dd>{selectedExtreme.session.start_round}</dd>
                  <dt>Terminal</dt>
                  <dd>{terminalLabel(selectedExtreme.session.terminal_status)}</dd>
                  <dt>End bankroll</dt>
                  <dd>{formatDollars(selectedExtreme.session.end_bankroll)}</dd>
                  <dt>Drawdown</dt>
                  <dd>{formatDollars(selectedExtreme.session.maximum_drawdown)}</dd>
                  <dt>Longest losing bet streak</dt>
                  <dd>{selectedExtreme.session.longest_losing_bet_streak ?? "—"}</dd>
                  <dt>Starting durability</dt>
                  <dd>{selectedExtreme.session.starting_loss_durability ?? "—"}</dd>
                  <dt>Minimum durability</dt>
                  <dd>{selectedExtreme.session.minimum_loss_durability ?? "—"}</dd>
                  <dt>Ending durability</dt>
                  <dd>{selectedExtreme.session.ending_loss_durability ?? "—"}</dd>
                  <dt>Rolls consumed</dt>
                  <dd>{selectedExtreme.session.rolls_consumed}</dd>
                </dl>
              </div>
            ) : null}
          </div>
        ) : (
          <EmptyState>
            Use Compute → Extremes for droughts, streaks, windows, and policy stress rows.
          </EmptyState>
        )}
      </div>
    </div>
  );
}
