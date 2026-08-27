import type { CompanionUiState, RoundOutcome } from "../shared/types";
import {
  formatCents,
  setupPlaceholders,
  type SetupMode,
} from "../shared/money.js";

export type OverlayAction =
  | { type: "start"; target: string; floor: string }
  | { type: "draft_change"; field: "target" | "floor" | "reach"; value: string }
  | { type: "set_setup_mode"; mode: SetupMode }
  | { type: "calculate_target" }
  | { type: "stop" }
  | { type: "confirm_stop" }
  | { type: "cancel_stop" }
  | { type: "retry_connection" }
  | { type: "retry_website" }
  | { type: "resync" }
  | { type: "confirm_wager"; side?: "ORANGE" | "BLACK" }
  | { type: "confirm_result"; result: "ORANGE" | "BLACK" | "DICE" }
  | { type: "save" }
  | { type: "discard" }
  | { type: "start_new" }
  | { type: "toggle_collapse" }
  | { type: "mock_advance" };

export type CalculationStatus = "IDLE" | "CALCULATING" | "READY" | "ERROR";

export interface OverlayRenderContext {
  state: CompanionUiState;
  fieldErrors?: Record<string, string>;
  /** Uncommitted setup drafts owned by the content script. */
  targetDraft?: string;
  floorDraft?: string;
  reachDraft?: string;
  setupMode?: SetupMode;
  calculatedTargetCents?: number | null;
  calculatedReachTarget?: number | null;
  calculationStatus?: CalculationStatus;
  calculationError?: string | null;
  /** Transient save path banner (content-script owned). */
  saveBanner?: string | null;
  /** Why Start is disabled; shown under the button when present. */
  startBlockedReason?: string | null;
  /** Local Start gate from drafts (overrides state.canStart when set). */
  canStartLocal?: boolean;
  onAction: (action: OverlayAction) => void;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function btn(
  label: string,
  className = "companion-btn",
  onClick?: () => void,
  disabled = false,
): HTMLButtonElement {
  const button = el("button", className, label) as HTMLButtonElement;
  button.type = "button";
  button.disabled = disabled;
  if (onClick) button.addEventListener("click", onClick);
  return button;
}

function terminalLabel(reason: string | null): string {
  switch (reason) {
    case "TARGET":
      return "Target reached";
    case "FLOOR":
      return "Floor reached";
    case "NO_ACTION":
      return "No action available";
    case "USER_STOPPED":
      return "Session ended";
    default:
      return "Session ended";
  }
}

function outcomeLabel(outcome: RoundOutcome): string {
  return outcome === "WIN" ? "Win" : "Loss";
}

function outcomeDisplay(outcome: RoundOutcome | null | undefined): string {
  if (outcome == null) return "—";
  return outcomeLabel(outcome);
}

function appendPauseBanner(container: HTMLElement): void {
  const banner = el("div", "companion-banner companion-banner-error");
  banner.appendChild(el("strong", "companion-pause-title", "Session paused"));
  container.appendChild(banner);
}

function renderUnsupported(container: HTMLElement): void {
  const banner = el("p", "companion-banner companion-banner-info");
  banner.textContent = "Live Companion is available on the Roulette page only.";
  container.appendChild(banner);
}

function renderSetup(ctx: OverlayRenderContext, container: HTMLElement): void {
  const { state, fieldErrors, onAction } = ctx;
  const setupMode: SetupMode = ctx.setupMode ?? "TARGET";
  const targetDraft = ctx.targetDraft ?? "";
  const floorDraft = ctx.floorDraft ?? "";
  const reachDraft = ctx.reachDraft ?? "";
  const canStart = ctx.canStartLocal ?? state.canStart;
  const calcStatus = ctx.calculationStatus ?? "IDLE";
  const placeholders =
    state.detectedBankrollCents != null
      ? setupPlaceholders(state.detectedBankrollCents)
      : null;

  if (ctx.saveBanner) {
    const saved = el("div", "companion-banner companion-banner-success companion-save-banner");
    saved.appendChild(el("strong", undefined, "Saved"));
    saved.appendChild(el("p", "companion-status-line", ctx.saveBanner));
    container.appendChild(saved);
  }

  const conn = el("p", "companion-banner companion-banner-info");
  conn.textContent =
    state.health === "CONNECTED"
      ? "Connected to local optimizer"
      : state.health === "BACKEND_OFFLINE"
        ? "Optimizer offline — local backend is not connected"
        : "Website bankroll unavailable";

  container.appendChild(conn);

  const bankrollField = el("div", "companion-field");
  bankrollField.appendChild(el("label", undefined, "Detected bankroll"));
  const bankrollValue = el(
    "div",
    "companion-metric-value",
    state.detectedBankrollCents != null
      ? formatCents(state.detectedBankrollCents)
      : "Unavailable",
  );
  bankrollField.appendChild(bankrollValue);
  container.appendChild(bankrollField);

  const modeRow = el("div", "companion-setup-mode");
  modeRow.appendChild(el("span", "companion-metric-label", "Set:"));
  const targetModeBtn = btn(
    "Target",
    `companion-btn companion-mode-btn${setupMode === "TARGET" ? " is-active" : ""}`,
    () => onAction({ type: "set_setup_mode", mode: "TARGET" }),
  );
  const reachModeBtn = btn(
    "Reach target %",
    `companion-btn companion-mode-btn${setupMode === "REACH_TARGET" ? " is-active" : ""}`,
    () => onAction({ type: "set_setup_mode", mode: "REACH_TARGET" }),
  );
  modeRow.append(targetModeBtn, reachModeBtn);
  container.appendChild(modeRow);

  const row = el("div", "companion-row");

  if (setupMode === "TARGET") {
    const targetField = el("div", "companion-field");
    const targetLabel = el("label");
    targetLabel.textContent = "Target ($)";
    const targetInput = el("input") as HTMLInputElement;
    targetInput.id = "companion-target";
    targetInput.name = "target";
    targetInput.inputMode = "decimal";
    targetInput.autocomplete = "off";
    targetInput.placeholder = placeholders?.targetPlaceholder ?? "e.g. 40.00";
    targetInput.value = targetDraft;
    targetLabel.htmlFor = targetInput.id;
    targetInput.addEventListener("input", () =>
      onAction({ type: "draft_change", field: "target", value: targetInput.value }),
    );
    targetField.append(targetLabel, targetInput);
    if (fieldErrors?.target) {
      targetField.appendChild(el("span", "companion-field-error", fieldErrors.target));
    }
    row.appendChild(targetField);
  } else {
    const reachField = el("div", "companion-field");
    const reachLabel = el("label");
    reachLabel.textContent = "Reach target %";
    const reachInput = el("input") as HTMLInputElement;
    reachInput.id = "companion-reach";
    reachInput.name = "reach";
    reachInput.inputMode = "decimal";
    reachInput.autocomplete = "off";
    reachInput.placeholder = "e.g. 89.23";
    reachInput.value = reachDraft;
    reachLabel.htmlFor = reachInput.id;
    reachInput.addEventListener("input", () =>
      onAction({ type: "draft_change", field: "reach", value: reachInput.value }),
    );
    reachField.append(reachLabel, reachInput);
    if (fieldErrors?.reach) {
      reachField.appendChild(el("span", "companion-field-error", fieldErrors.reach));
    }
    row.appendChild(reachField);
  }

  const floorField = el("div", "companion-field");
  const floorLabel = el("label");
  floorLabel.textContent = "Hard floor ($)";
  const floorInput = el("input") as HTMLInputElement;
  floorInput.id = "companion-floor";
  floorInput.name = "floor";
  floorInput.inputMode = "decimal";
  floorInput.autocomplete = "off";
  floorInput.placeholder = placeholders?.floorPlaceholder ?? "e.g. 10.00";
  floorInput.value = floorDraft;
  floorLabel.htmlFor = floorInput.id;
  floorInput.addEventListener("input", () =>
    onAction({ type: "draft_change", field: "floor", value: floorInput.value }),
  );
  floorField.append(floorLabel, floorInput);
  if (fieldErrors?.floor) {
    floorField.appendChild(el("span", "companion-field-error", fieldErrors.floor));
  }

  row.appendChild(floorField);
  container.appendChild(row);

  if (setupMode === "REACH_TARGET") {
    if (calcStatus === "READY" && ctx.calculatedTargetCents != null) {
      const calcOut = el("div", "companion-calc-output");
      calcOut.setAttribute("data-calc-output", "");
      calcOut.appendChild(
        metric("Target", formatCents(ctx.calculatedTargetCents)),
      );
      if (ctx.calculatedReachTarget != null) {
        calcOut.appendChild(
          metric("Reach target", formatProbability(ctx.calculatedReachTarget)),
        );
      }
      container.appendChild(calcOut);
    }
    if (calcStatus === "ERROR" && ctx.calculationError) {
      const err = el("p", "companion-field-error", ctx.calculationError);
      err.setAttribute("data-calc-error", "");
      container.appendChild(err);
    }
    if (calcStatus === "CALCULATING") {
      const loading = el("div", "companion-loading companion-loading-inline");
      loading.setAttribute("data-calc-loading", "");
      loading.appendChild(el("div", "companion-spinner"));
      loading.appendChild(document.createTextNode("Calculating Target…"));
      container.appendChild(loading);
    }
  }

  container.appendChild(
    el(
      "p",
      "companion-status-line",
      "While Companion is active, use your CSGOEmpire balance only for this roulette session.",
    ),
  );

  const actions = el("div", "companion-actions");
  if (setupMode === "REACH_TARGET") {
    const calcBtn = btn(
      "Calculate Target",
      "companion-btn companion-btn-ghost",
      () => onAction({ type: "calculate_target" }),
      calcStatus === "CALCULATING" || state.detectedBankrollCents == null,
    );
    calcBtn.setAttribute("data-calc-btn", "");
    actions.appendChild(calcBtn);
  }
  const startBtn = btn(
    "Start Live Companion",
    "companion-btn companion-btn-primary companion-btn-lg",
    () =>
      onAction({
        type: "start",
        target:
          setupMode === "REACH_TARGET" && ctx.calculatedTargetCents != null
            ? centsToDollarInput(ctx.calculatedTargetCents)
            : targetDraft,
        floor: floorInput.value,
      }),
    !canStart || calcStatus === "CALCULATING",
  );
  startBtn.setAttribute("data-start-btn", "");
  actions.appendChild(startBtn);
  if (ctx.startBlockedReason) {
    const reason = el("p", "companion-field-error", ctx.startBlockedReason);
    reason.setAttribute("data-start-reason", "");
    actions.appendChild(reason);
  }
  if (state.mockMode) {
    actions.appendChild(
      btn("Demo next step", "companion-btn companion-btn-ghost", () =>
        onAction({ type: "mock_advance" }),
      ),
    );
  }
  container.appendChild(actions);
}

function centsToDollarInput(cents: number): string {
  const abs = Math.abs(Math.trunc(cents));
  const dollars = Math.floor(abs / 100);
  const frac = abs % 100;
  return `${dollars}.${frac.toString().padStart(2, "0")}`;
}

function renderPreparing(container: HTMLElement): void {
  const loading = el("div", "companion-loading");
  loading.appendChild(el("div", "companion-spinner"));
  loading.appendChild(document.createTextNode("Preparing strategy…"));
  container.appendChild(loading);
  container.appendChild(el("div", "companion-shimmer"));
}

function renderRecommendation(ctx: OverlayRenderContext, container: HTMLElement): void {
  const { state } = ctx;
  const rec = state.recommendation;
  if (!rec) return;

  const reco = el("div", "companion-reco");
  reco.appendChild(el("p", "companion-section-title", "Recommendation"));
  const action = el("div", "companion-reco-action");
  const typeSpan = el("span", rec.betType === "COLOR" ? "bet-color" : "bet-dice", rec.betType);
  action.append(typeSpan, document.createTextNode(" · "));
  const stakeSpan = el("span", undefined, formatCents(rec.stakeCents));
  stakeSpan.style.fontFamily = "var(--font-mono)";
  action.appendChild(stakeSpan);
  reco.appendChild(action);

  const liveMetrics = el("div", "companion-live-metrics");
  const reach = metric(
    "Reach target",
    formatProbability(state.targetHitProbability ?? rec.targetHitProbability),
  );
  const durability = metric(
    "Consecutive loss durability",
    formatDurability(state.consecutiveLossDurability ?? rec.consecutiveLossDurability),
  );
  liveMetrics.append(reach, durability);
  reco.appendChild(liveMetrics);

  const metrics = el("div", "companion-metrics");
  const bankroll = metric("Current bankroll", formatCents(state.currentBankrollCents));
  const win = metric("Win bankroll", formatCents(rec.winBankrollCents), "success");
  const loss = metric("Loss bankroll", formatCents(rec.loseBankrollCents), "risk");
  const target = metric("Target", formatCents(state.targetCents));
  const floor = metric("Floor", formatCents(state.floorCents));
  metrics.append(bankroll, win, loss, target, floor);
  reco.appendChild(metrics);
  container.appendChild(reco);
}

function formatProbability(p: number | null | undefined): string {
  if (p == null || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(2)}%`;
}

function formatDurability(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return String(n);
}

function metric(label: string, value: string, valueClass?: string): HTMLElement {
  const m = el("div", "companion-metric");
  m.appendChild(el("span", "companion-metric-label", label));
  m.appendChild(el("span", `companion-metric-value${valueClass ? ` ${valueClass}` : ""}`, value));
  return m;
}

function renderActive(ctx: OverlayRenderContext, container: HTMLElement): void {
  renderRecommendation(ctx, container);
  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-ghost", () => ctx.onAction({ type: "stop" })),
  );
  if (ctx.state.mockMode) {
    actions.appendChild(
      btn("Demo next step", "companion-btn companion-btn-ghost", () =>
        ctx.onAction({ type: "mock_advance" }),
      ),
    );
  }
  container.appendChild(actions);
}

function renderWagerConfirmed(ctx: OverlayRenderContext, container: HTMLElement): void {
  renderRecommendation(ctx, container);
  const wager = ctx.state.observedWager;
  const banner = el("div", "companion-banner companion-banner-success");
  banner.textContent = wager
    ? `Wager detected — ${wager.betType} ${formatCents(wager.stakeCents)}`
    : "Wager detected";
  container.appendChild(banner);
  container.appendChild(el("p", "companion-status-line", "Waiting for round to finish…"));
  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-ghost", () => ctx.onAction({ type: "stop" })),
  );
  if (ctx.state.mockMode) {
    actions.appendChild(
      btn("Demo next step", "companion-btn companion-btn-ghost", () =>
        ctx.onAction({ type: "mock_advance" }),
      ),
    );
  }
  container.appendChild(actions);
}

function renderWagerFallback(ctx: OverlayRenderContext, container: HTMLElement): void {
  renderRecommendation(ctx, container);
  const rec = ctx.state.recommendation;
  if (!rec) return;

  container.appendChild(
    el(
      "p",
      "companion-status-line",
      "Website wager not readable — confirm after you place the recommended bet.",
    ),
  );

  if (ctx.state.view === "wager_fallback_dice") {
    container.appendChild(
      btn(
        `Confirm DICE ${formatCents(rec.stakeCents)} placed`,
        "companion-btn companion-btn-primary",
        () => ctx.onAction({ type: "confirm_wager" }),
      ),
    );
  } else {
    container.appendChild(el("p", undefined, "Which color did you place?"));
    const picker = el("div", "companion-side-picker");
    picker.appendChild(
      btn(
        "Orange",
        "companion-btn companion-side-btn is-orange",
        () => ctx.onAction({ type: "confirm_wager", side: "ORANGE" }),
      ),
    );
    picker.appendChild(
      btn(
        "Black",
        "companion-btn companion-side-btn is-black",
        () => ctx.onAction({ type: "confirm_wager", side: "BLACK" }),
      ),
    );
    container.appendChild(picker);
  }

  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-ghost", () => ctx.onAction({ type: "stop" })),
  );
  container.appendChild(actions);
}

function renderResultFallback(ctx: OverlayRenderContext, container: HTMLElement): void {
  container.appendChild(el("p", "companion-status-line", "Round result cannot be read automatically."));
  container.appendChild(el("p", undefined, "What pocket did the wheel land on?"));
  const picker = el("div", "companion-side-picker");
  picker.appendChild(
    btn("Orange", "companion-btn companion-side-btn is-orange", () =>
      ctx.onAction({ type: "confirm_result", result: "ORANGE" }),
    ),
  );
  picker.appendChild(
    btn("Black", "companion-btn companion-side-btn is-black", () =>
      ctx.onAction({ type: "confirm_result", result: "BLACK" }),
    ),
  );
  picker.appendChild(
    btn("Dice", "companion-btn companion-btn-primary", () =>
      ctx.onAction({ type: "confirm_result", result: "DICE" }),
    ),
  );
  container.appendChild(picker);
  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-ghost", () => ctx.onAction({ type: "stop" })),
  );
  container.appendChild(actions);
}

function renderMismatch(ctx: OverlayRenderContext, container: HTMLElement): void {
  appendPauseBanner(container);

  const rec = ctx.state.recommendation;
  const obs = ctx.state.observedWager;
  const compare = el("div", "companion-compare");

  if (rec && obs) {
    compare.append(
      metric("Recommended", `${rec.betType} ${formatCents(rec.stakeCents)}`),
      metric("Observed", `${obs.betType} ${formatCents(obs.stakeCents)}`, "risk"),
    );
    container.appendChild(compare);
    container.appendChild(
      el(
        "p",
        "companion-status-line",
        "The wager on the website does not match the recommendation. Resync or stop the session.",
      ),
    );
  } else {
    container.appendChild(
      el("p", "companion-status-line", "Wager does not match the recommendation."),
    );
  }

  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Resync From Website", "companion-btn companion-btn-primary", () =>
      ctx.onAction({ type: "resync" }),
    ),
  );
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-risk", () => ctx.onAction({ type: "stop" })),
  );
  container.appendChild(actions);
}

function renderPolicyPaused(ctx: OverlayRenderContext, container: HTMLElement): void {
  appendPauseBanner(container);
  container.appendChild(
    el(
      "p",
      "companion-status-line",
      "Logical bankroll is outside the policy grid — session paused. Stop and save, or resync to the website bankroll if it is on-grid.",
    ),
  );
  const metrics = el("div", "companion-metrics");
  metrics.append(metric("Logical bankroll", formatCents(ctx.state.currentBankrollCents), "risk"));
  container.appendChild(metrics);

  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Resync From Website", "companion-btn companion-btn-ghost", () =>
      ctx.onAction({ type: "resync" }),
    ),
  );
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-risk", () => ctx.onAction({ type: "stop" })),
  );
  container.appendChild(actions);
}

function renderWaitingResult(ctx: OverlayRenderContext, container: HTMLElement): void {
  renderRecommendation(ctx, container);
  const banner = el("div", "companion-banner companion-banner-success");
  banner.textContent = "Wager detected";
  container.appendChild(banner);
  if (ctx.state.statusLabel === "Wager detected") {
    container.appendChild(
      el(
        "p",
        "companion-banner companion-banner-warn",
        "Wager differs from recommendation. The strategy will resync when the round finishes.",
      ),
    );
  }
  container.appendChild(
    el("p", "companion-status-line", "Waiting for round to finish…"),
  );
  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-ghost", () => ctx.onAction({ type: "stop" })),
  );
  container.appendChild(actions);
}

function renderResult(ctx: OverlayRenderContext, container: HTMLElement): void {
  const outcome = ctx.state.roundOutcome;
  container.appendChild(el("p", "companion-section-title", "Result"));
  container.appendChild(el("p", "companion-outcome", outcomeDisplay(outcome)));
  container.appendChild(el("p", "companion-status-line", "Checking bankroll…"));
  if (ctx.state.mockMode) {
    container.appendChild(
      btn("Demo next step", "companion-btn companion-btn-ghost", () =>
        ctx.onAction({ type: "mock_advance" }),
      ),
    );
  }
}

function renderBankrollMismatch(ctx: OverlayRenderContext, container: HTMLElement): void {
  appendPauseBanner(container);
  container.appendChild(el("p", "companion-status-line", "Bankroll mismatch"));

  const metrics = el("div", "companion-metrics");
  metrics.append(
    metric("Expected", formatCents(ctx.state.expectedBankrollCents)),
    metric("Website", formatCents(ctx.state.websiteBankrollCents), "risk"),
  );
  container.appendChild(metrics);

  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Resync", "companion-btn companion-btn-primary", () => ctx.onAction({ type: "resync" })),
  );
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-risk", () => ctx.onAction({ type: "stop" })),
  );
  container.appendChild(actions);
}

function renderPausedOffline(ctx: OverlayRenderContext, container: HTMLElement): void {
  container.appendChild(
    el("div", "companion-banner companion-banner-error", "Optimizer offline"),
  );
  container.appendChild(
    el("p", "companion-status-line", "Local backend is not connected. Session paused."),
  );
  container.appendChild(
    btn("Retry Connection", "companion-btn companion-btn-primary", () =>
      ctx.onAction({ type: "retry_connection" }),
    ),
  );
}

function renderPausedWebsite(ctx: OverlayRenderContext, container: HTMLElement): void {
  container.appendChild(el("p", "companion-section-title", "Session paused"));
  container.appendChild(
    el("p", "companion-status-line", "Website state cannot be read reliably."),
  );
  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Retry", "companion-btn companion-btn-primary", () =>
      ctx.onAction({ type: "retry_website" }),
    ),
  );
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-risk", () => ctx.onAction({ type: "stop" })),
  );
  container.appendChild(actions);
}

function renderTerminal(ctx: OverlayRenderContext, container: HTMLElement): void {
  container.appendChild(
    el("p", "companion-section-title", terminalLabel(ctx.state.terminalReason)),
  );
  container.appendChild(
    el(
      "p",
      undefined,
      `Final bankroll ${formatCents(ctx.state.currentBankrollCents)} after ${ctx.state.roundsCompleted} round${ctx.state.roundsCompleted === 1 ? "" : "s"}.`,
    ),
  );
  const actions = el("div", "companion-actions");
  actions.appendChild(
    btn("Save Session", "companion-btn companion-btn-primary companion-btn-lg", () =>
      ctx.onAction({ type: "save" }),
    ),
  );
  actions.appendChild(
    btn("Do Not Save", "companion-btn companion-btn-ghost companion-btn-lg", () =>
      ctx.onAction({ type: "discard" }),
    ),
  );
  container.appendChild(actions);
}

function renderCompleted(ctx: OverlayRenderContext, container: HTMLElement): void {
  // Legacy view — save/discard now return to setup automatically.
  renderSetup(ctx, container);
}

/** Update Start/Calculate gate without rebuilding setup inputs (preserves focus/caret). */
export function syncSetupControls(
  body: HTMLElement,
  opts: {
    canStart: boolean;
    startBlockedReason: string | null;
    calculating?: boolean;
    clearCalculationUi?: boolean;
    bankrollAvailable?: boolean;
  },
): void {
  const startBtn = body.querySelector<HTMLButtonElement>("[data-start-btn]");
  if (startBtn) {
    startBtn.disabled = !opts.canStart || !!opts.calculating;
  }

  const calcBtn = body.querySelector<HTMLButtonElement>("[data-calc-btn]");
  if (calcBtn) {
    const bankrollOk = opts.bankrollAvailable !== false;
    calcBtn.disabled = !!opts.calculating || !bankrollOk;
  }

  const actions = body.querySelector(".companion-actions");
  let reason = body.querySelector<HTMLElement>("[data-start-reason]");
  if (opts.startBlockedReason) {
    if (!reason) {
      reason = el("p", "companion-field-error", opts.startBlockedReason);
      reason.setAttribute("data-start-reason", "");
      actions?.appendChild(reason);
    } else {
      reason.textContent = opts.startBlockedReason;
    }
  } else if (reason) {
    reason.remove();
  }

  if (opts.clearCalculationUi) {
    body.querySelector("[data-calc-output]")?.remove();
    body.querySelector("[data-calc-error]")?.remove();
    body.querySelector("[data-calc-loading]")?.remove();
  }

  body.querySelectorAll(".companion-field .companion-field-error").forEach((node) => {
    node.remove();
  });
}

export function renderOverlayBody(ctx: OverlayRenderContext, body: HTMLElement): void {
  body.replaceChildren();
  switch (ctx.state.view) {
    case "setup":
      if (ctx.state.health === "PAGE_UNSUPPORTED") {
        renderUnsupported(body);
      } else {
        renderSetup(ctx, body);
      }
      break;
    case "preparing":
      renderPreparing(body);
      break;
    case "active":
      renderActive(ctx, body);
      break;
    case "wager_confirmed":
      renderWagerConfirmed(ctx, body);
      break;
    case "waiting_result":
      renderWaitingResult(ctx, body);
      break;
    case "wager_fallback_dice":
    case "wager_fallback_color":
      renderActive(ctx, body);
      break;
    case "wager_mismatch":
      renderMismatch(ctx, body);
      break;
    case "policy_paused":
      renderPolicyPaused(ctx, body);
      break;
    case "result_fallback":
      renderWaitingResult(ctx, body);
      break;
    case "result":
    case "reconciling":
      renderResult(ctx, body);
      break;
    case "bankroll_mismatch":
      renderBankrollMismatch(ctx, body);
      break;
    case "paused_offline":
      renderPausedOffline(ctx, body);
      break;
    case "paused_website":
      renderPausedWebsite(ctx, body);
      break;
    case "terminal":
      renderTerminal(ctx, body);
      break;
    case "completed":
      renderCompleted(ctx, body);
      break;
    case "stop_dialog":
      renderActive(ctx, body);
      break;
    default:
      body.appendChild(el("p", "companion-status-line", "Updating…"));
  }
}

export function renderStopDialog(onConfirm: () => void, onCancel: () => void): HTMLElement {
  const backdrop = el("div", "companion-dialog-backdrop");
  backdrop.setAttribute("role", "presentation");

  const dialog = el("div", "companion-dialog");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "companion-stop-title");

  dialog.appendChild(el("h2", undefined, "Stop this session?"));
  const title = dialog.querySelector("h2");
  if (title) title.id = "companion-stop-title";
  dialog.appendChild(
    el(
      "p",
      undefined,
      "You will need to save or discard this session before starting again.",
    ),
  );

  const actions = el("div", "companion-actions");
  actions.appendChild(btn("Cancel", "companion-btn", onCancel));
  actions.appendChild(
    btn("Stop Session", "companion-btn companion-btn-risk", onConfirm),
  );
  dialog.appendChild(actions);
  backdrop.appendChild(dialog);
  return backdrop;
}

export function statusBadgeClass(label: string): string {
  if (label === "Offline") return "is-offline";
  if (label === "Paused") return "is-paused";
  if (label === "Preparing" || label === "Checking bankroll") return "is-preparing";
  if (label === "Target reached") return "is-target";
  if (label === "Session ended") return "is-ended";
  if (label.startsWith("Waiting")) return "is-waiting";
  if (label === "Connected" || label === "Synced" || label === "Ready") return "is-connected";
  return "";
}
