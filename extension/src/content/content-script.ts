import { CSGOEmpireAdapter } from "../adapters/csgoempire/CSGOEmpireAdapter.js";
import { MSG, type CompanionMessage } from "../shared/messages.js";
import {
  validateSessionMoney,
  explainSetupStart,
  formatCents,
  parseDollarInput,
  parseReachTargetPercent,
  type SetupMode,
} from "../shared/money.js";
import type { CompanionUiState } from "../shared/types.js";
import overlayCss from "../overlay/overlay.css?inline";
import {
  applyOverlayPosition,
  loadOverlayLayout,
  saveOverlayLayout,
  setupOverlayDrag,
  setupOverlayViewportGuard,
  type OverlayPosition,
} from "../overlay/overlay-position.js";
import {
  renderOverlayBody,
  renderStopDialog,
  setupDomMatchesView,
  statusBadgeClass,
  syncSetupControls,
  syncSetupView,
  type CalculationStatus,
  type OverlayAction,
} from "../overlay/render.js";
import {
  applyCalculateTargetResponse,
  nextCalculationGeneration,
} from "./calculate-target-guard.js";
import { ensureSingleCompanionRoot } from "./mount-guard.js";
import { installRouteWatcher } from "./route-watch.js";
import {
  captureSetupInputFocus,
  restoreSetupInputFocus,
} from "./setup-focus.js";
import { readSetupDraftsFromDom } from "./setup-drafts.js";

function sendMessage<T>(message: CompanionMessage): Promise<T> {
  return chrome.runtime.sendMessage(message) as Promise<T>;
}

class CompanionOverlay {
  private root: HTMLElement;
  private panel: HTMLElement;
  private body: HTMLElement;
  private statusBadge: HTMLElement;
  private collapsed = false;
  private position: OverlayPosition = { x: 16, y: 16 };
  private state: CompanionUiState | null = null;
  private fieldErrors: Record<string, string> = {};
  /** Uncommitted setup drafts — never overwritten by observation STATE_CHANGED. */
  private targetDraft = "";
  private floorDraft = "";
  private reachDraft = "";
  private setupMode: SetupMode = "TARGET";
  private calculatedTargetCents: number | null = null;
  private calculatedReachTarget: number | null = null;
  private calculationStatus: CalculationStatus = "IDLE";
  private calculationError: string | null = null;
  private calculationGeneration = 0;
  private saveBanner: string | null = null;
  private saveBannerTimer: ReturnType<typeof setTimeout> | null = null;
  private stopDialog: HTMLElement | null = null;
  private teardownDrag: (() => void) | null = null;
  private teardownViewport: (() => void) | null = null;
  private unsubObservation: (() => void) | null = null;
  private teardownRouteWatch: (() => void) | null = null;
  private mounted = false;
  private lastHref = "";
  private adapter: CSGOEmpireAdapter;

  constructor() {
    this.adapter = new CSGOEmpireAdapter();

    this.root = document.createElement("div");
    this.root.id = "roulette-companion-root";

    this.panel = document.createElement("aside");
    this.panel.className = "companion-overlay";
    this.panel.setAttribute("role", "region");
    this.panel.setAttribute("aria-label", "Roulette Optimizer Live Companion");

    const header = document.createElement("header");
    header.className = "companion-header";
    header.setAttribute("data-companion-drag", "true");

    const title = document.createElement("div");
    title.className = "companion-title";
    title.textContent = "Live Companion";

    this.statusBadge = document.createElement("span");
    this.statusBadge.className = "companion-status-badge";

    const collapseBtn = document.createElement("button");
    collapseBtn.type = "button";
    collapseBtn.className = "companion-header-btn";
    collapseBtn.setAttribute("aria-expanded", "true");
    collapseBtn.setAttribute("aria-label", "Collapse companion panel");
    collapseBtn.textContent = "−";
    collapseBtn.addEventListener("click", () => this.handleAction({ type: "toggle_collapse" }));

    header.append(title, this.statusBadge, collapseBtn);

    this.body = document.createElement("div");
    this.body.className = "companion-body";
    this.body.addEventListener("input", (event) => {
      const el = event.target;
      if (!(el instanceof HTMLInputElement)) return;
      if (el.id === "companion-target") this.onSetupDraftInput("target", el.value);
      else if (el.id === "companion-floor") this.onSetupDraftInput("floor", el.value);
      else if (el.id === "companion-reach") this.onSetupDraftInput("reach", el.value);
    });

    const footer = document.createElement("footer");
    footer.className = "companion-footer";
    footer.textContent = "Never places wagers automatically.";

    this.panel.append(header, this.body, footer);
    this.root.appendChild(this.panel);
  }

  async mount(): Promise<void> {
    if (this.mounted || document.getElementById("roulette-companion-root")) {
      return;
    }
    this.mounted = true;

    this.root = ensureSingleCompanionRoot(() => this.root);

    const style = document.createElement("style");
    style.textContent = overlayCss;
    this.root.prepend(style);

    document.documentElement.appendChild(this.root);

    const layout = await loadOverlayLayout();
    this.collapsed = layout.collapsed;
    this.position = layout.position;
    this.panel.classList.toggle("is-collapsed", this.collapsed);
    applyOverlayPosition(this.panel, this.position);

    this.teardownDrag = setupOverlayDrag(this.panel, (pos) => {
      this.position = pos;
      this.persistLayout();
    });

    this.teardownViewport = setupOverlayViewportGuard(
      this.panel,
      () => this.position,
      (pos) => {
        this.position = pos;
        this.persistLayout();
      },
    );

    chrome.runtime.onMessage.addListener((message) => {
      if (message?.type === MSG.STATE_CHANGED) {
        this.setState(message.payload as CompanionUiState);
      }
    });

    this.lastHref = typeof location !== "undefined" ? location.href : "";
    this.teardownRouteWatch = installRouteWatcher(() => this.checkRoute());
    this.checkRoute();

    await this.startAdapter();
    const state = await sendMessage<CompanionUiState>({ type: MSG.GET_STATE });
    this.setState(state);
  }

  private checkRoute(): void {
    if (typeof location === "undefined") return;
    if (location.href === this.lastHref) return;
    this.lastHref = location.href;
    void this.restartAdapterForRoute();
  }

  private async restartAdapterForRoute(): Promise<void> {
    this.adapter.stop();
    this.unsubObservation?.();
    this.unsubObservation = null;
    await this.startAdapter();
  }

  private async startAdapter(): Promise<void> {
    this.unsubObservation?.();

    // Subscribe before start so the initial scan is delivered (start notifies listeners).
    const firstObservation = new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      this.unsubObservation = this.adapter.onObservation((observation) => {
        const health = this.adapter.getHealth();
        void sendMessage({
          type: MSG.ADAPTER_HEALTH,
          payload: {
            siteSupported: health.siteSupported,
            issues: health.issues,
            capabilities: [...health.capabilities],
          },
        }).catch(() => {
          /* worker may be asleep */
        });
        void sendMessage<CompanionUiState>({
          type: MSG.OBSERVATION_UPDATE,
          payload: observation,
        })
          .then((state) => {
            this.setState(state);
            finish();
          })
          .catch(() => {
            finish();
          });
      });
      // Unsupported pages / empty scan: don't hang mount.
      setTimeout(finish, 500);
    });

    this.adapter.start(document);
    const health = this.adapter.getHealth();
    try {
      const state = await sendMessage<CompanionUiState>({
        type: MSG.ADAPTER_HEALTH,
        payload: {
          siteSupported: health.siteSupported,
          issues: health.issues,
          capabilities: [...health.capabilities],
        },
      });
      this.setState(state);
    } catch {
      /* worker may be asleep */
    }
    await firstObservation;
  }

  destroy(): void {
    this.teardownRouteWatch?.();
    this.teardownRouteWatch = null;
    this.mounted = false;
    this.unsubObservation?.();
    this.unsubObservation = null;
    this.adapter.stop();
    this.teardownDrag?.();
    this.teardownViewport?.();
    this.root.remove();
  }

  private persistLayout(): void {
    saveOverlayLayout({ position: this.position, collapsed: this.collapsed });
  }

  private setState(state: CompanionUiState): void {
    const prevView = this.state?.view;
    const prevHealth = this.state?.health;
    const prevBankroll = this.state?.detectedBankrollCents;
    const enteringSetup =
      this.state != null && this.state.view !== "setup" && state.view === "setup";
    let clearedCalcUi = false;
    // Leaving an active session back to setup clears committed SW money; keep drafts empty.
    if (enteringSetup) {
      this.resetSetupDrafts();
      if (state.savedJsonPath) {
        this.showSaveBanner(state.savedJsonPath);
      }
    } else if (
      state.view === "setup" &&
      this.setupMode === "REACH_TARGET" &&
      prevBankroll !== state.detectedBankrollCents
    ) {
      this.clearCalculatedTarget();
      clearedCalcUi = true;
    }

    this.state = state;
    this.updateHeader(state);

    const stayingOnSetup = state.view === "setup" && prevView === "setup" && !enteringSetup;
    const healthLayoutChanged =
      (prevHealth === "PAGE_UNSUPPORTED") !== (state.health === "PAGE_UNSUPPORTED");
    const canIncrementalSetup =
      stayingOnSetup &&
      !healthLayoutChanged &&
      setupDomMatchesView(this.body, this.setupMode, state.health);

    if (canIncrementalSetup) {
      this.syncSetupFromState({ clearCalculationUi: clearedCalcUi });
    } else if (stayingOnSetup) {
      this.renderBodyPreservingSetupFocus();
    } else {
      this.renderBody();
    }

    if (state.view === "stop_dialog") {
      this.showStopDialog();
    } else {
      this.hideStopDialog();
    }
  }

  private resetSetupDrafts(): void {
    this.calculationGeneration = nextCalculationGeneration(this.calculationGeneration);
    this.targetDraft = "";
    this.floorDraft = "";
    this.reachDraft = "";
    this.setupMode = "TARGET";
    this.calculatedTargetCents = null;
    this.calculatedReachTarget = null;
    this.calculationStatus = "IDLE";
    this.calculationError = null;
    this.fieldErrors = {};
  }

  private showSaveBanner(path: string): void {
    this.saveBanner = path;
    if (this.saveBannerTimer) clearTimeout(this.saveBannerTimer);
    this.saveBannerTimer = setTimeout(() => {
      this.saveBanner = null;
      this.saveBannerTimer = null;
      if (this.state?.view === "setup") this.renderBody();
    }, 4500);
  }

  private clearCalculatedTarget(): void {
    this.calculationGeneration = nextCalculationGeneration(this.calculationGeneration);
    this.calculatedTargetCents = null;
    this.calculatedReachTarget = null;
    this.calculationStatus = "IDLE";
    this.calculationError = null;
  }

  private renderBodyPreservingSetupFocus(): void {
    this.pullSetupDraftsFromDom();
    const captured =
      this.state?.view === "setup" ? captureSetupInputFocus() : { focusId: null, selectionStart: null, selectionEnd: null };
    this.renderBody();
    if (this.state?.view === "setup") {
      restoreSetupInputFocus(this.body, captured);
    }
  }

  /** Sync in-memory drafts from live setup inputs before gate/render. */
  private pullSetupDraftsFromDom(): void {
    if (this.state?.view !== "setup") return;
    if (!setupDomMatchesView(this.body, this.setupMode, this.state.health)) return;
    const dom = readSetupDraftsFromDom(this.body, this.setupMode);
    if (this.setupMode === "TARGET") {
      this.targetDraft = dom.target;
    } else {
      this.reachDraft = dom.reach;
    }
    this.floorDraft = dom.floor;
  }

  private explainSetupGate() {
    this.pullSetupDraftsFromDom();
    if (!this.state) return { canStart: false, reason: null as string | null };
    return explainSetupStart(
      this.state.health,
      this.state.detectedBankrollCents,
      this.targetDraft,
      this.floorDraft,
      {
        setupMode: this.setupMode,
        calculatedTargetCents: this.calculatedTargetCents,
        calculationReady: this.calculationStatus === "READY",
      },
    );
  }

  private onSetupDraftInput(field: "target" | "floor" | "reach", value: string): void {
    if (this.state?.view !== "setup") return;
    let clearedCalc = false;
    if (field === "target") this.targetDraft = value;
    else if (field === "floor") {
      this.floorDraft = value;
      if (this.setupMode === "REACH_TARGET") {
        this.clearCalculatedTarget();
        clearedCalc = true;
      }
    } else if (field === "reach") {
      this.reachDraft = value;
      this.clearCalculatedTarget();
      clearedCalc = true;
    }
    this.fieldErrors = {};
    this.syncSetupStartGate({ clearCalculationUi: clearedCalc });
  }

  private renderBody(): void {
    if (!this.state) return;
    const gate =
      this.state.view === "setup"
        ? this.explainSetupGate()
        : { canStart: false, reason: null };

    renderOverlayBody(
      {
        state: this.state,
        fieldErrors: this.fieldErrors,
        targetDraft: this.targetDraft,
        floorDraft: this.floorDraft,
        reachDraft: this.reachDraft,
        setupMode: this.setupMode,
        calculatedTargetCents: this.calculatedTargetCents,
        calculatedReachTarget: this.calculatedReachTarget,
        calculationStatus: this.calculationStatus,
        calculationError: this.calculationError,
        saveBanner: this.saveBanner,
        canStartLocal: gate.canStart,
        startBlockedReason: gate.reason,
        onAction: (action) => this.handleAction(action),
      },
      this.body,
    );
  }

  /** Update Start enablement/reason without rebuilding inputs (preserves caret). */
  private syncSetupFromState(opts?: { clearCalculationUi?: boolean }): void {
    if (!this.state || this.state.view !== "setup") return;
    const gate = this.explainSetupGate();
    syncSetupView(this.body, {
      state: this.state,
      setupMode: this.setupMode,
      canStart: gate.canStart,
      startBlockedReason: gate.reason,
      calculating: this.calculationStatus === "CALCULATING",
      clearCalculationUi: opts?.clearCalculationUi,
    });
  }

  private syncSetupStartGate(opts?: { clearCalculationUi?: boolean }): void {
    if (!this.state || this.state.view !== "setup") return;
    const gate = this.explainSetupGate();
    syncSetupControls(this.body, {
      canStart: gate.canStart,
      startBlockedReason: gate.reason,
      calculating: this.calculationStatus === "CALCULATING",
      clearCalculationUi: opts?.clearCalculationUi,
      bankrollAvailable: this.state.detectedBankrollCents != null,
    });
  }

  private updateHeader(state: CompanionUiState): void {
    this.statusBadge.textContent = state.statusLabel;
    this.statusBadge.className = `companion-status-badge ${statusBadgeClass(state.statusLabel)}`;
    this.statusBadge.setAttribute("role", "status");
  }

  private showStopDialog(): void {
    if (this.stopDialog) return;
    this.stopDialog = renderStopDialog(
      () => this.send(MSG.CONFIRM_STOP),
      () => this.send(MSG.CANCEL_STOP),
    );
    this.root.appendChild(this.stopDialog);
  }

  private hideStopDialog(): void {
    if (this.stopDialog) {
      this.stopDialog.remove();
      this.stopDialog = null;
    }
  }

  private async send(type: string, payload?: unknown): Promise<void> {
    const state = await sendMessage<CompanionUiState>({
      type: type as CompanionMessage["type"],
      payload,
    });
    this.setState(state);
  }

  private handleAction(action: OverlayAction): void {
    if (!this.state) return;

    switch (action.type) {
      case "toggle_collapse":
        this.collapsed = !this.collapsed;
        this.panel.classList.toggle("is-collapsed", this.collapsed);
        this.persistLayout();
        return;

      case "set_setup_mode":
        if (action.mode === this.setupMode) return;
        this.setupMode = action.mode;
        if (action.mode === "TARGET") {
          this.reachDraft = "";
          this.clearCalculatedTarget();
        } else {
          this.targetDraft = "";
          this.clearCalculatedTarget();
        }
        this.fieldErrors = {};
        this.renderBody();
        return;

      case "draft_change":
        this.onSetupDraftInput(action.field, action.value);
        return;

      case "calculate_target":
        void this.runCalculateTarget();
        return;

      case "start": {
        this.pullSetupDraftsFromDom();
        this.floorDraft = action.floor;
        if (this.setupMode === "TARGET") {
          this.targetDraft = action.target;
        }
        const bankroll = this.state.detectedBankrollCents;
        if (bankroll == null) {
          this.fieldErrors = {
            target: "Live Companion cannot start until the balance can be read.",
          };
          this.renderBody();
          return;
        }
        if (this.setupMode === "REACH_TARGET") {
          if (this.calculationStatus !== "READY" || this.calculatedTargetCents == null) {
            this.fieldErrors = { reach: "Calculate Target before starting." };
            this.renderBody();
            return;
          }
          const floor = parseDollarInput(action.floor);
          if (!floor.ok) {
            this.fieldErrors = { floor: floor.error };
            this.renderBody();
            return;
          }
          this.fieldErrors = {};
          this.send(MSG.START_SESSION, {
            targetCents: this.calculatedTargetCents,
            floorCents: floor.cents,
          });
          return;
        }
        this.targetDraft = action.target;
        const validation = validateSessionMoney(bankroll, action.target, action.floor);
        if (!validation.ok) {
          this.fieldErrors = validation.errors;
          this.renderBody();
          return;
        }
        this.fieldErrors = {};
        this.send(MSG.START_SESSION, {
          targetCents: validation.targetCents,
          floorCents: validation.floorCents,
        });
        return;
      }

      case "stop":
        this.send(MSG.STOP_SESSION);
        return;

      case "retry_connection":
        this.send(MSG.RETRY_CONNECTION);
        return;

      case "retry_website":
        const obs = this.adapter.readObservation();
        if (obs) {
          sendMessage({ type: MSG.OBSERVATION_UPDATE, payload: obs });
        }
        const health = this.adapter.getHealth();
        sendMessage({
          type: MSG.ADAPTER_HEALTH,
          payload: {
            siteSupported: health.siteSupported,
            issues: health.issues,
            capabilities: [...health.capabilities],
          },
        });
        this.send(MSG.RETRY_WEBSITE);
        return;

      case "resync":
        this.send(MSG.RESYNC);
        return;

      case "confirm_wager":
        this.send(MSG.CONFIRM_WAGER, action.side ? { side: action.side } : undefined);
        return;

      case "confirm_result":
        this.send(MSG.CONFIRM_RESULT, { result: action.result });
        return;

      case "save":
        this.send(MSG.SAVE_SESSION);
        return;

      case "discard":
        this.send(MSG.DISCARD_SESSION);
        return;

      case "start_new":
        this.resetSetupDrafts();
        this.saveBanner = null;
        this.send(MSG.START_NEW);
        return;

      case "mock_advance":
        this.send(MSG.MOCK_ADVANCE);
        return;
    }
  }

  private async runCalculateTarget(): Promise<void> {
    if (!this.state) return;
    this.pullSetupDraftsFromDom();
    const bankroll = this.state.detectedBankrollCents;
    if (bankroll == null) {
      this.calculationStatus = "ERROR";
      this.calculationError = "Live Companion cannot calculate until the balance can be read.";
      this.renderBody();
      return;
    }
    const floor = parseDollarInput(this.floorDraft);
    const reach = parseReachTargetPercent(this.reachDraft);
    const errors: Record<string, string> = {};
    if (!floor.ok) errors.floor = floor.error;
    if (!reach.ok) errors.reach = reach.error;
    if (Object.keys(errors).length || !floor.ok || !reach.ok) {
      this.fieldErrors = errors;
      this.calculationStatus = "ERROR";
      this.calculationError = errors.reach ?? errors.floor ?? null;
      this.renderBody();
      return;
    }
    if (!(bankroll > floor.cents)) {
      this.fieldErrors = {
        floor: `Hard floor must be below current bankroll (${formatCents(bankroll)}).`,
      };
      this.calculationStatus = "ERROR";
      this.calculationError = this.fieldErrors.floor;
      this.renderBody();
      return;
    }
    const fraction = reach.fraction;
    if (fraction == null) {
      this.calculationStatus = "ERROR";
      this.calculationError = "Enter a Reach target %.";
      this.renderBody();
      return;
    }

    this.fieldErrors = {};
    this.calculationGeneration = nextCalculationGeneration(this.calculationGeneration);
    this.calculationStatus = "CALCULATING";
    this.calculationError = null;
    const requestGeneration = this.calculationGeneration;
    const requestSetupMode = this.setupMode;
    this.renderBodyPreservingSetupFocus();

    try {
      const result = await sendMessage<
        | {
            ok: true;
            targetCents: number;
            targetHitProbability: number;
            solves: number;
          }
        | { ok: false; error: string }
      >({
        type: MSG.CALCULATE_TARGET,
        payload: {
          bankrollCents: bankroll,
          floorCents: floor.cents,
          reachTargetProbability: fraction,
        },
      });
      const applied = applyCalculateTargetResponse(
        requestGeneration,
        this.calculationGeneration,
        result,
        { requestSetupMode, currentSetupMode: this.setupMode },
      );
      if (!applied.accepted) {
        return;
      }
      this.calculatedTargetCents = applied.calculatedTargetCents;
      this.calculatedReachTarget = applied.calculatedReachTarget;
      this.calculationStatus = applied.calculationStatus;
      this.calculationError = applied.calculationError;
    } catch (err) {
      if (requestGeneration !== this.calculationGeneration) {
        return;
      }
      this.calculatedTargetCents = null;
      this.calculatedReachTarget = null;
      this.calculationStatus = "ERROR";
      this.calculationError = err instanceof Error ? err.message : "Calculate Target failed.";
    }
    this.renderBodyPreservingSetupFocus();
  }
}

if (!document.getElementById("roulette-companion-root")) {
  const overlay = new CompanionOverlay();
  void overlay.mount();
}
