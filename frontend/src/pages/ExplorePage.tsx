import { useMemo, useState } from "react";
import { apiPost, ApiClientError } from "../api/client";
import { MoneyField } from "../components/MoneyField";
import { DataTable } from "../components/DataTable";
import { EmptyState, ErrorBanner, LoadingBlock } from "../components/Feedback";
import {
  formatDollars,
  formatNumber,
  formatProbability,
  formatVerificationStatus,
  validateSessionInputs,
} from "../lib/format";

type DiceMapResponse = {
  state_count: number;
  dice_count: number;
  color_count: number;
  no_action_count: number;
  min_difference: number | null;
  max_difference: number | null;
  median_difference: number | null;
  rows: Array<{
    bankroll: { cents: number; dollars: number };
    dice_stake: { dollars: number };
    dice_q: number;
    best_color_stake: { dollars: number } | null;
    best_color_q: number | null;
    difference: number | null;
  }>;
  solver: string;
};

type SweepCell = {
  target_profit: { cents: number; dollars: number };
  maximum_loss: { cents: number; dollars: number };
  target: { dollars: number };
  floor: { dollars: number };
  V_start: number | null;
  initial_loss_durability: number;
  COLOR_state_count: number;
  DICE_state_count: number;
  NO_ACTION_state_count: number;
  solve_seconds: number;
  verification_status: string;
};

type SweepResponse = {
  bankroll: { dollars: number };
  target_profits: Array<{ cents: number; dollars: number }>;
  floor_losses: Array<{ cents: number; dollars: number }>;
  cells: SweepCell[];
  successful: number;
  failed: number;
  total_seconds: number;
};

type Section = "dice" | "sweep";

function heatColor(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "var(--raised)";
  const t = Math.max(0, Math.min(1, v));
  const a = 0.12 + t * 0.55;
  return `rgba(61, 184, 255, ${a})`;
}

export function ExplorePage() {
  const [section, setSection] = useState<Section>("dice");
  const [bankroll, setBankroll] = useState("10.00");
  const [target, setTarget] = useState("12.00");
  const [floor, setFloor] = useState("7.00");
  const [profits, setProfits] = useState("0.50,1.00,2.00");
  const [losses, setLosses] = useState("0.50,1.00,2.00");
  const [verify, setVerify] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diceMap, setDiceMap] = useState<DiceMapResponse | null>(null);
  const [selectedDice, setSelectedDice] = useState<DiceMapResponse["rows"][0] | null>(
    null,
  );
  const [sweep, setSweep] = useState<SweepResponse | null>(null);
  const [selectedCell, setSelectedCell] = useState<SweepCell | null>(null);

  async function runDiceMap() {
    const v = validateSessionInputs(bankroll, target, floor);
    setErrors(v.errors);
    if (!v.values) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiPost<DiceMapResponse>("/api/explore/dice-map", {
        ...v.values,
      });
      setDiceMap(data);
      setSelectedDice(data.rows[0] ?? null);
      setSection("dice");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Dice map failed");
    } finally {
      setLoading(false);
    }
  }

  async function runSweep() {
    const b = Number(bankroll);
    if (!Number.isFinite(b)) {
      setErrors({ bankroll: "Enter a valid dollar amount" });
      return;
    }
    const tp = profits
      .split(",")
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n > 0);
    const fl = losses
      .split(",")
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n > 0);
    if (!tp.length || !fl.length) {
      setError("Provide comma-separated positive target profits and floor losses.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await apiPost<SweepResponse>("/api/explore/sweep", {
        bankroll: b,
        target_profits: tp,
        floor_losses: fl,
        verify,
      });
      setSweep(data);
      setSelectedCell(data.cells[0] ?? null);
      setSection("sweep");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Sweep failed");
    } finally {
      setLoading(false);
    }
  }

  const heatGrid = useMemo(() => {
    if (!sweep) return null;
    const cols = sweep.floor_losses;
    const rows = sweep.target_profits;
    const map = new Map(
      sweep.cells.map((c) => [`${c.target_profit.cents}:${c.maximum_loss.cents}`, c]),
    );
    return { cols, rows, map };
  }, [sweep]);

  return (
    <div>
      <header className="page-header">
        <h1>Explore</h1>
        <p>Dice-map diagnostics and target-profit × floor-loss sweep heatmaps.</p>
      </header>

      <div className="tabs" role="tablist" aria-label="Explore tools">
        <button
          type="button"
          id="explore-tab-dice"
          className="tab"
          role="tab"
          aria-selected={section === "dice"}
          aria-controls="explore-panel-dice"
          tabIndex={section === "dice" ? 0 : -1}
          onClick={() => setSection("dice")}
        >
          Dice Map
        </button>
        <button
          type="button"
          id="explore-tab-sweep"
          className="tab"
          role="tab"
          aria-selected={section === "sweep"}
          aria-controls="explore-panel-sweep"
          tabIndex={section === "sweep" ? 0 : -1}
          onClick={() => setSection("sweep")}
        >
          Sweep
        </button>
      </div>

      {error ? <ErrorBanner message={error} /> : null}
      {loading ? (
        <div className="panel">
          <LoadingBlock label="Exploring parameter space…" />
        </div>
      ) : null}

      <div
        id="explore-panel-dice"
        role="tabpanel"
        aria-labelledby="explore-tab-dice"
        className="stack"
        hidden={section !== "dice"}
      >
          <form
            className="panel"
            onSubmit={(e) => {
              e.preventDefault();
              void runDiceMap();
            }}
          >
            <div className="panel-title">Session</div>
            <div className="row">
              <MoneyField
                id="ex-bankroll"
                label="Bankroll ($)"
                value={bankroll}
                onChange={setBankroll}
                error={errors.bankroll}
              />
              <MoneyField
                id="ex-target"
                label="Target ($)"
                value={target}
                onChange={setTarget}
                error={errors.target}
              />
              <MoneyField
                id="ex-floor"
                label="Floor ($)"
                value={floor}
                onChange={setFloor}
                error={errors.floor}
              />
              <button className="btn btn-primary" type="submit" disabled={loading}>
                Build dice map
              </button>
            </div>
          </form>

          {diceMap ? (
            <>
              <div className="panel">
                <div className="panel-title">Summary</div>
                <dl className="def-list">
                  <dt>States</dt>
                  <dd>{diceMap.state_count}</dd>
                  <dt>COLOR / DICE / NONE</dt>
                  <dd>
                    {diceMap.color_count} / {diceMap.dice_count} / {diceMap.no_action_count}
                  </dd>
                  <dt>ΔQ min / median / max</dt>
                  <dd>
                    {formatNumber(diceMap.min_difference)} /{" "}
                    {formatNumber(diceMap.median_difference)} /{" "}
                    {formatNumber(diceMap.max_difference)}
                  </dd>
                </dl>
              </div>
              <div className="panel">
                <div className="panel-title">DICE-optimal states</div>
                <DataTable
                  caption="Dice map rows"
                  columns={[
                    {
                      key: "b",
                      header: "Bankroll",
                      mono: true,
                      sortValue: (r) => r.bankroll.cents,
                      render: (r) => formatDollars(r.bankroll),
                    },
                    {
                      key: "ds",
                      header: "DICE stake",
                      mono: true,
                      sortValue: (r) => r.dice_stake.dollars,
                      render: (r) => formatDollars(r.dice_stake),
                    },
                    {
                      key: "dq",
                      header: "DICE Q",
                      mono: true,
                      sortValue: (r) => r.dice_q,
                      render: (r) => formatNumber(r.dice_q),
                    },
                    {
                      key: "cs",
                      header: "Best COLOR stake",
                      mono: true,
                      sortValue: (r) => r.best_color_stake?.dollars ?? null,
                      render: (r) => formatDollars(r.best_color_stake),
                    },
                    {
                      key: "cq",
                      header: "Best COLOR Q",
                      mono: true,
                      sortValue: (r) => r.best_color_q,
                      render: (r) => formatNumber(r.best_color_q),
                    },
                    {
                      key: "d",
                      header: "ΔQ",
                      mono: true,
                      sortValue: (r) => r.difference,
                      render: (r) => formatNumber(r.difference),
                    },
                  ]}
                  rows={diceMap.rows}
                  rowKey={(r) => String(r.bankroll.cents)}
                  selectedKey={selectedDice ? String(selectedDice.bankroll.cents) : null}
                  onSelect={setSelectedDice}
                />
              </div>
              {selectedDice ? (
                <div className="panel">
                  <div className="panel-title">Selected row</div>
                  <dl className="def-list">
                    <dt>Bankroll</dt>
                    <dd>{formatDollars(selectedDice.bankroll)}</dd>
                    <dt>DICE stake</dt>
                    <dd>{formatDollars(selectedDice.dice_stake)}</dd>
                    <dt>Best COLOR alternative</dt>
                    <dd>
                      {selectedDice.best_color_stake
                        ? `${formatDollars(selectedDice.best_color_stake)} (Q=${formatNumber(selectedDice.best_color_q)})`
                        : "None"}
                    </dd>
                    <dt>Exact Q difference</dt>
                    <dd>{formatNumber(selectedDice.difference)}</dd>
                  </dl>
                </div>
              ) : null}
            </>
          ) : (
            !loading && <EmptyState>Build a dice map to inspect DICE vs COLOR Q gaps.</EmptyState>
          )}
        </div>

        <div
          id="explore-panel-sweep"
          role="tabpanel"
          aria-labelledby="explore-tab-sweep"
          className="stack"
          hidden={section !== "sweep"}
        >
          <form
            className="panel"
            onSubmit={(e) => {
              e.preventDefault();
              void runSweep();
            }}
          >
            <div className="panel-title">Sweep parameters</div>
            <div className="row">
              <MoneyField
                id="sw-bankroll"
                label="Bankroll ($)"
                value={bankroll}
                onChange={setBankroll}
              />
              <div className="field">
                <label htmlFor="profits">Target profits ($)</label>
                <input
                  id="profits"
                  value={profits}
                  onChange={(e) => setProfits(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="losses">Floor losses ($)</label>
                <input id="losses" value={losses} onChange={(e) => setLosses(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="verify">Verify</label>
                <select
                  id="verify"
                  value={verify ? "yes" : "no"}
                  onChange={(e) => setVerify(e.target.value === "yes")}
                >
                  <option value="no">No</option>
                  <option value="yes">Yes</option>
                </select>
              </div>
              <button className="btn btn-primary" type="submit" disabled={loading}>
                Run sweep
              </button>
            </div>
            <p className="field-hint">
              Keep target−floor spans modest (cent grid). Very large bankrolls with deep
              floors exceed the 20 000-state interactive limit and are rejected before solve.
            </p>
          </form>

          {sweep && heatGrid ? (
            <>
              <div className="panel">
                <div className="panel-title">
                  Heatmap — cell value = V(start) · {sweep.successful} ok / {sweep.failed}{" "}
                  failed · {sweep.total_seconds.toFixed(2)}s
                </div>
                <div
                  className="heatmap"
                  style={{
                    gridTemplateColumns: `max-content repeat(${heatGrid.cols.length}, minmax(3.25rem, 1fr))`,
                  }}
                  role="grid"
                  aria-label="Sweep heatmap of V(start)"
                >
                  <div />
                  {heatGrid.cols.map((c) => (
                    <div
                      key={c.cents}
                      className="mono"
                      style={{ fontSize: "0.75rem", color: "var(--text-muted)", textAlign: "center" }}
                    >
                      −{formatDollars(c)}
                    </div>
                  ))}
                  {heatGrid.rows.map((r) => (
                    <div key={`row-${r.cents}`} style={{ display: "contents" }}>
                      <div
                        className="mono"
                        style={{
                          fontSize: "0.75rem",
                          color: "var(--text-muted)",
                          alignSelf: "center",
                        }}
                      >
                        +{formatDollars(r)}
                      </div>
                      {heatGrid.cols.map((c) => {
                        const cell = heatGrid.map.get(`${r.cents}:${c.cents}`);
                        const selected =
                          selectedCell &&
                          selectedCell.target_profit.cents === r.cents &&
                          selectedCell.maximum_loss.cents === c.cents;
                        return (
                          <button
                            key={`${r.cents}-${c.cents}`}
                            type="button"
                            className={`heat-cell${selected ? " selected" : ""}`}
                            style={{ background: heatColor(cell?.V_start ?? null) }}
                            onClick={() => cell && setSelectedCell(cell)}
                            title={
                              cell
                                ? `V=${cell.V_start ?? "n/a"}; durability=${cell.initial_loss_durability}`
                                : undefined
                            }
                          >
                            {cell?.V_start == null
                              ? "—"
                              : formatProbability(cell.V_start).replace("%", "")}
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
                <p className="brand-sub block-gap">
                  Accessible table equivalent below.
                </p>
                <DataTable
                  caption="Sweep cells"
                  columns={[
                    {
                      key: "tp",
                      header: "Target profit",
                      mono: true,
                      sortValue: (r) => r.target_profit.cents,
                      render: (r) => formatDollars(r.target_profit),
                    },
                    {
                      key: "fl",
                      header: "Floor loss",
                      mono: true,
                      sortValue: (r) => r.maximum_loss.cents,
                      render: (r) => formatDollars(r.maximum_loss),
                    },
                    {
                      key: "v",
                      header: "V(start)",
                      mono: true,
                      sortValue: (r) => r.V_start,
                      render: (r) => formatProbability(r.V_start),
                    },
                    {
                      key: "ild",
                      header: "Loss durability",
                      mono: true,
                      sortValue: (r) => r.initial_loss_durability,
                      render: (r) =>
                        `${r.initial_loss_durability} loss${r.initial_loss_durability === 1 ? "" : "es"}`,
                    },
                    {
                      key: "ver",
                      header: "Verify",
                      sortValue: (r) => r.verification_status,
                      render: (r) => (
                        <span
                          className={
                            r.verification_status === "VALID"
                              ? "badge badge-valid"
                              : r.verification_status === "FAILED"
                                ? "badge badge-fail"
                                : "badge"
                          }
                        >
                          {formatVerificationStatus(r.verification_status)}
                        </span>
                      ),
                    },
                  ]}
                  rows={sweep.cells}
                  rowKey={(r) => `${r.target_profit.cents}-${r.maximum_loss.cents}`}
                  selectedKey={
                    selectedCell
                      ? `${selectedCell.target_profit.cents}-${selectedCell.maximum_loss.cents}`
                      : null
                  }
                  onSelect={setSelectedCell}
                />
              </div>
              {selectedCell ? (
                <div className="panel">
                  <div className="panel-title">Selected cell</div>
                  <dl className="def-list">
                    <dt>Target</dt>
                    <dd>{formatDollars(selectedCell.target)}</dd>
                    <dt>Floor</dt>
                    <dd>{formatDollars(selectedCell.floor)}</dd>
                    <dt>Initial loss durability</dt>
                    <dd>
                      {selectedCell.initial_loss_durability} loss
                      {selectedCell.initial_loss_durability === 1 ? "" : "es"}
                    </dd>
                    <dt>COLOR / DICE / NONE</dt>
                    <dd>
                      {selectedCell.COLOR_state_count} / {selectedCell.DICE_state_count} /{" "}
                      {selectedCell.NO_ACTION_state_count}
                    </dd>
                    <dt>Solve time</dt>
                    <dd>{selectedCell.solve_seconds.toFixed(4)}s</dd>
                    <dt>Verification</dt>
                    <dd>{formatVerificationStatus(selectedCell.verification_status)}</dd>
                    <dt>V(start)</dt>
                    <dd>{formatProbability(selectedCell.V_start)}</dd>
                  </dl>
                </div>
              ) : null}
            </>
          ) : (
            !loading && <EmptyState>Run a sweep to populate the V(start) heatmap.</EmptyState>
          )}
        </div>
    </div>
  );
}
