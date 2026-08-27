import type { AdapterHealth, WebsiteObservation } from "../adapters/types.js";
import { applyCompanionApiResponse } from "../client/companion-map.js";
import { ApiError, BackendClient } from "../client/backend-client.js";
import type { CompanionStateResponse } from "../client/backend-client.js";
import { MSG, type CalculateTargetPayload, type CompanionMessage, type StartSessionPayload } from "../shared/messages.js";
import type { CompanionUiState, HealthState } from "../shared/types.js";
import { DEFAULT_BACKEND_URL, emptyUiState } from "../shared/types.js";
import { deriveHealthFromAdapter, reduceUiState } from "../state/ui-state.js";
import {
  advanceSeenClosed,
  buildSettlementTimeoutDiagnostics,
  compareWagerToRecommendation,
  evaluateBankrollReconciliation,
  evaluateDomWagerDetection,
  evaluateResultSettlement,
  hasPlacedWithoutAmount,
  manualRoundId,
  shouldOfferResultFallback,
  shouldOfferWagerFallback,
  shouldRearmWagerDetection,
  type BankrollReconciliationStatus,
} from "./observation-gates.js";
import type { ObservedWager, WagerSide } from "../adapters/types.js";
import {
  canAttemptResultSettlement,
  clearPersistedRoundSession,
  loadPersistedRoundSession,
  savePersistedRoundSession,
  snapshotRoundSession,
  type RoundBaseline,
  type RoundSessionStorage,
} from "./round-session.js";
import { bumpSessionEpoch, shouldApplyApiState } from "./session-guard.js";
import { isLegacyFallbackBlocked } from "./legacy-fallback-gates.js";
import { mergeHealthPollUpdate } from "./health-merge.js";

const HEALTH_POLL_MS = 15000;

function chromeSessionStorage(): RoundSessionStorage {
  return chrome.storage.session;
}

export interface CompanionControllerDeps {
  backend?: BackendClient;
  roundStorage?: RoundSessionStorage;
  skipInit?: boolean;
}

export class CompanionController {
  private uiState: CompanionUiState = emptyUiState();
  private backend: BackendClient;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private lastObservation: WebsiteObservation | null = null;
  private adapterHealth: AdapterHealth | null = null;
  private registeredWagerRounds = new Set<string>();
  private registeredResultRounds = new Set<string>();
  private wagerFallbackRoundId: string | null = null;
  private resultFallbackOffered = false;
  private reconcilingBankroll: number | null = null;
  private observationBusy = false;
  private pendingObservation: WebsiteObservation | null = null;
  private lastPhase: string | null = null;
  private lastHistoryFingerprint: string | null = null;
  private pendingSettlement = false;
  private domWagerRegistered = false;
  private seenClosed = false;
  private resultHandled = false;
  /** Diagnostics-only soft reconciliation; not LiveSession authority (M17). */
  private bankrollReconciliation: BankrollReconciliationStatus = "IDLE";
  private reconcilStartedAtMs: number | null = null;
  private expectedLogicalCents: number | null = null;
  private ambiguousWagerPolls = 0;
  private roundBaseline: RoundBaseline | null = null;
  private lastBettingState: string | null = null;
  private sessionEpoch = 0;
  private startInFlight: Promise<CompanionUiState> | null = null;

  private lastContentTabId: number | null = null;
  private roundStorage: RoundSessionStorage;

  constructor(deps: CompanionControllerDeps = {}) {
    this.backend = deps.backend ?? new BackendClient();
    this.roundStorage = deps.roundStorage ?? chromeSessionStorage();
    if (!deps.skipInit) {
      void this.init();
    }
  }

  getState(): CompanionUiState {
    return { ...this.uiState };
  }

  /** @internal test hook */
  seedForTest(partial: Partial<CompanionUiState>): void {
    this.uiState = { ...this.uiState, ...partial };
  }

  /** @internal test hook */
  broadcastStateForTest(): void {
    this.broadcastState();
  }

  /** @internal test hook */
  getLastContentTabIdForTest(): number | null {
    return this.lastContentTabId;
  }

  noteContentTab(tabId: number | undefined): void {
    if (tabId != null) this.lastContentTabId = tabId;
  }

  async init(): Promise<void> {
    const stored = await chrome.storage.local.get("companion_backend_url");
    const url = (stored.companion_backend_url as string | undefined) ?? DEFAULT_BACKEND_URL;
    this.backend.setBaseUrl(url);
    this.uiState.backendUrl = url;

    await this.reclaimPersistedRoundSession();
    await this.pollHealth();
    this.healthTimer = setInterval(() => this.pollHealth(), HEALTH_POLL_MS);
  }

  destroy(): void {
    if (this.healthTimer) clearInterval(this.healthTimer);
  }

  private persistRoundSession(): void {
    const snap = snapshotRoundSession({
      sessionId: this.uiState.backendSessionId,
      domWagerRegistered: this.domWagerRegistered,
      resultHandled: this.resultHandled,
      seenClosed: this.seenClosed,
      pendingSettlement: this.pendingSettlement,
      roundBaseline: this.roundBaseline,
    });
    void savePersistedRoundSession(this.roundStorage, snap);
  }

  private async reclaimPersistedRoundSession(): Promise<void> {
    const persisted = await loadPersistedRoundSession(this.roundStorage);
    if (!persisted) return;
    this.domWagerRegistered = persisted.domWagerRegistered;
    this.resultHandled = persisted.resultHandled;
    this.seenClosed = persisted.seenClosed;
    this.pendingSettlement = false;
    this.roundBaseline = persisted.roundBaseline;
    this.uiState.backendSessionId = persisted.sessionId;
    this.uiState.sessionActive = true;
    try {
      const api = await this.backend.companionGet(persisted.sessionId);
      this.applyApiState(api);
      this.persistRoundSession();
    } catch {
      /* keep flags; health poll may recover later */
    }
  }

  private broadcastState(): void {
    const payload = { type: MSG.STATE_CHANGED, payload: this.getState() };
    const fanOut = (): void => {
      chrome.tabs.query({ url: ["https://csgoempire.com/*", "https://*.csgoempire.com/*"] }, (tabs) => {
        for (const tab of tabs) {
          if (tab.id == null) continue;
          chrome.tabs.sendMessage(tab.id, payload).catch(() => {
            /* no content script in tab */
          });
        }
      });
    };
    if (this.lastContentTabId != null) {
      chrome.tabs
        .sendMessage(this.lastContentTabId, payload)
        .catch(() => {
          this.lastContentTabId = null;
          fanOut();
        });
      return;
    }
    fanOut();
  }

  private centsToDollars(cents: number): number {
    return cents / 100;
  }

  private applyApiState(api: CompanionStateResponse, atEpoch?: number): void {
    const epoch = atEpoch ?? this.sessionEpoch;
    if (
      !shouldApplyApiState({
        atEpoch: epoch,
        currentEpoch: this.sessionEpoch,
        currentSessionId: this.uiState.backendSessionId,
        sessionActive: this.uiState.sessionActive,
        responseSessionId: api.session_id,
      })
    ) {
      return;
    }
    this.uiState = applyCompanionApiResponse(this.uiState, api);
    if (api.session_status === "RECONCILING") {
      this.reconcilingBankroll = null;
    }
  }

  private handleApiError(err: unknown): void {
    if (err instanceof ApiError && err.code === "network") {
      this.uiState = reduceUiState(this.uiState, { type: "health_update", health: "BACKEND_OFFLINE" });
      return;
    }
    if (this.uiState.sessionActive) {
      this.uiState.health = "DESYNCED";
      this.uiState.statusLabel = "Paused";
    }
  }

  private canReadWager(): boolean {
    const readings = this.lastObservation?.readings;
    if (readings) {
      return (
        readings.wagerType.status === "AVAILABLE" &&
        readings.wagerStakeCents.status === "AVAILABLE"
      );
    }
    const caps = this.adapterHealth?.capabilities;
    return Boolean(
      caps?.has("CAN_READ_WAGER_TYPE") && caps?.has("CAN_READ_WAGER_STAKE"),
    );
  }

  private canReadResult(): boolean {
    const readings = this.lastObservation?.readings;
    if (readings) {
      return readings.result.status === "AVAILABLE" && readings.roundId.status === "AVAILABLE";
    }
    return Boolean(this.adapterHealth?.capabilities?.has("CAN_READ_RESULT"));
  }

  private applyObservation(observation: WebsiteObservation): void {
    this.lastObservation = observation;
    const bankroll = observation.bankrollCents;
    const available = bankroll != null;
    this.uiState = reduceUiState(this.uiState, {
      type: "adapter_bankroll",
      cents: bankroll,
      available,
    });
    if (this.uiState.view === "setup") {
      const backendOk = this.uiState.health !== "BACKEND_OFFLINE";
      const health = deriveHealthFromAdapter(available, backendOk);
      this.uiState.health = health;
      this.uiState.statusLabel = health === "CONNECTED" ? "Connected" : "Paused";
      this.uiState.canStart =
        health === "CONNECTED" &&
        bankroll != null &&
        this.uiState.targetCents != null &&
        this.uiState.floorCents != null &&
        this.uiState.targetCents > bankroll &&
        bankroll > (this.uiState.floorCents ?? 0);
    }

    if (this.uiState.sessionActive && this.uiState.backendSessionId) {
      this.processCompanionObservation(observation).catch(() => {
        /* logged via handleApiError */
      });
    }
  }

  private async flushPendingObservation(): Promise<void> {
    const pending = this.pendingObservation;
    this.pendingObservation = null;
    if (pending) {
      await this.processCompanionObservation(pending);
    }
  }

  private async processCompanionObservation(observation: WebsiteObservation): Promise<void> {
    if (this.observationBusy) {
      this.pendingObservation = observation;
      return;
    }
    if (this.uiState.health === "BACKEND_OFFLINE") return;

    const sessionStatus = this.uiState.apiSessionStatus;
    if (!sessionStatus) return;

    const phase = observation.phase;
    const historyFp = observation.historyFingerprint;
    const bettingReading = observation.readings.bettingState;
    const bettingKey =
      bettingReading.status === "AVAILABLE"
        ? `AVAILABLE:${bettingReading.value}`
        : bettingReading.status;

    if (this.lastBettingState !== bettingKey) {
      if (this.lastBettingState != null) {
        console.debug(
          "[companion] BETTING_STATE",
          this.lastBettingState,
          "→",
          bettingKey,
        );
      }
      this.lastBettingState = bettingKey;
    }

    if (sessionStatus === "WAITING_FOR_WAGER") {
      this.pendingSettlement = false;
      this.seenClosed = false;
      if (this.resultHandled) {
        if (
          shouldRearmWagerDetection({
            resultHandled: this.resultHandled,
            bettingStatus: bettingReading.status,
            bettingState: observation.bettingState,
            resultStatus: observation.resultStatus,
            placedWagers: observation.placedWagers,
          })
        ) {
          console.debug("[companion] re-arm wager detection");
          this.resultHandled = false;
          this.domWagerRegistered = false;
          this.roundBaseline = null;
          this.persistRoundSession();
        }
      }
      this.updateBankrollReconciliation(observation);
      if (!this.resultHandled) {
        await this.tryDomWagerDetection(observation);
      }
    } else if (sessionStatus === "ROUND_PENDING") {
      const prevSeen = this.seenClosed;
      this.seenClosed = advanceSeenClosed({
        seenClosed: this.seenClosed,
        bettingStatus: bettingReading.status,
        bettingState: observation.bettingState,
      });
      if (!prevSeen && this.seenClosed) {
        console.debug("[companion] seenClosed false → true");
        this.persistRoundSession();
      }
      if (!this.pendingSettlement) {
        await this.tryResultSettlement(observation);
      }
      this.updateBankrollReconciliation(observation);
    } else if (sessionStatus === "WAITING_FOR_RESULT") {
      if (!isLegacyFallbackBlocked(sessionStatus) && this.canReadResult()) {
        await this.tryAutoRegisterResult(observation);
      }
    } else if (sessionStatus === "RECONCILING" && observation.bankrollCents != null) {
      await this.tryReconcile(observation.bankrollCents);
    }

    if (phase && phase !== "UNKNOWN") {
      this.lastPhase = phase;
    }
    if (historyFp) {
      this.lastHistoryFingerprint = historyFp;
    }
  }

  private updateBankrollReconciliation(observation: WebsiteObservation): void {
    const prev = this.bankrollReconciliation;
    this.bankrollReconciliation = evaluateBankrollReconciliation({
      status: this.bankrollReconciliation,
      expectedLogicalCents: this.expectedLogicalCents,
      observedBankrollCents: observation.bankrollCents,
      startedAtMs: this.reconcilStartedAtMs,
      nowMs: Date.now(),
    });
    if (prev !== this.bankrollReconciliation) {
      if (this.bankrollReconciliation === "SYNCED") {
        console.debug("[companion] BANKROLL_RECONCILED", this.expectedLogicalCents);
        void this.recordDiagnosticEvent("BANKROLL_RECONCILED", {
          expected_logical_cents: this.expectedLogicalCents,
        });
      } else if (this.bankrollReconciliation === "WARNING") {
        const detail = buildSettlementTimeoutDiagnostics({
          preWagerBankrollCents: this.roundBaseline?.preWagerBankrollCents ?? 0,
          observedWager:
            this.roundBaseline?.observedWager ??
            ({
              side: "BLACK",
              family: "COLOR",
              stakeCents: 0,
              source: "DOM_PLACED_BUTTON",
            } as ObservedWager),
          recommendation: this.uiState.recommendation
            ? {
                betType: this.uiState.recommendation.betType,
                stakeCents: this.uiState.recommendation.stakeCents,
              }
            : null,
          expectedWinCents: this.roundBaseline?.expectedWinCents ?? 0,
          expectedLossCents: this.roundBaseline?.expectedLossCents ?? 0,
          currentObservedBankrollCents: observation.bankrollCents,
          wagers: observation.wagers,
          placedSide: this.roundBaseline?.placedSide ?? "BLACK",
          bettingState: observation.bettingState,
          bettingStatus: observation.readings.bettingState.status,
          elapsedSettlementWaitMs:
            this.reconcilStartedAtMs == null ? 0 : Date.now() - this.reconcilStartedAtMs,
        });
        console.debug("[companion] BANKROLL_RECONCILIATION_WARNING", detail);
        void this.recordDiagnosticEvent("BANKROLL_RECONCILIATION_WARNING", detail);
      }
    }
  }

  private async recordDiagnosticEvent(
    kind: "BANKROLL_RECONCILED" | "BANKROLL_RECONCILIATION_WARNING",
    detail?: object,
  ): Promise<void> {
    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return;
    try {
      await this.backend.companionDiagnosticEvent(
        sessionId,
        kind,
        detail as Record<string, unknown> | undefined,
      );
    } catch (err) {
      console.debug("[companion] diagnostic event failed", kind, err);
    }
  }

  private async tryDomWagerDetection(observation: WebsiteObservation): Promise<void> {
    if (this.domWagerRegistered) return;
    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return;

    const detection = evaluateDomWagerDetection({
      placedWagers: observation.placedWagers,
      wagers: observation.wagers,
      ambiguousPolls: this.ambiguousWagerPolls,
    });

    if (detection.kind === "MULTIPLE_WAGERS") {
      console.debug("[companion] MULTIPLE_WAGERS", detection.count);
      this.uiState.health = "DESYNCED";
      this.uiState.statusLabel = "Paused";
      this.broadcastState();
      return;
    }

    if (detection.kind === "AMBIGUOUS") {
      this.ambiguousWagerPolls += 1;
      console.debug("[companion] WAGER_AMBIGUOUS polls=", this.ambiguousWagerPolls);
      this.uiState.health = "DESYNCED";
      this.uiState.statusLabel = "Paused";
      this.broadcastState();
      return;
    }

    if (detection.kind === "NONE") {
      if (hasPlacedWithoutAmount(observation.wagers)) {
        this.ambiguousWagerPolls += 1;
      } else {
        this.ambiguousWagerPolls = 0;
      }
      return;
    }

    this.ambiguousWagerPolls = 0;
    const wager = detection.wager;
    const rec = this.uiState.recommendation;
    const preWagerBankrollCents =
      observation.bankrollCents ?? this.uiState.currentBankrollCents;
    if (preWagerBankrollCents == null) return;

    const match = rec
      ? compareWagerToRecommendation(wager, rec)
      : ("MATCH" as const);

    const atEpoch = this.sessionEpoch;
    this.observationBusy = true;
    this.domWagerRegistered = true;
    try {
      console.debug(
        "[companion] WAGER_DETECTED",
        `side=${wager.side}`,
        `family=${wager.family}`,
        `stake=${wager.stakeCents}`,
        match === "MISMATCH" ? "(mismatch)" : "",
      );
      const api = await this.backend.companionDomWager(sessionId, {
        observedBankrollDollars: this.centsToDollars(preWagerBankrollCents),
        betType: wager.side,
        stakeDollars: this.centsToDollars(wager.stakeCents),
      });
      this.applyApiState(api, atEpoch);
      const expectedWin =
        api.expected_win_bankroll?.cents ??
        (match === "MATCH" ? rec?.winBankrollCents : null);
      const expectedLoss =
        api.expected_lose_bankroll?.cents ??
        (match === "MATCH" ? rec?.loseBankrollCents : null);
      if (expectedWin != null && expectedLoss != null) {
        this.roundBaseline = {
          preWagerBankrollCents,
          expectedWinCents: expectedWin,
          expectedLossCents: expectedLoss,
          placedSide: wager.side,
          observedWager: wager,
        };
      } else {
        this.roundBaseline = {
          preWagerBankrollCents,
          expectedWinCents: preWagerBankrollCents,
          expectedLossCents: preWagerBankrollCents,
          placedSide: wager.side,
          observedWager: wager,
        };
      }
      this.persistRoundSession();
      if (api.message && api.session_status === "ROUND_PENDING") {
        this.uiState.statusLabel = "Wager detected";
      }
    } catch (err) {
      this.domWagerRegistered = false;
      this.roundBaseline = null;
      this.persistRoundSession();
      this.handleApiError(err);
    } finally {
      this.observationBusy = false;
      this.broadcastState();
      await this.flushPendingObservation();
    }
  }

  private async tryResultSettlement(observation: WebsiteObservation): Promise<void> {
    if (
      !canAttemptResultSettlement({
        sessionId: this.uiState.backendSessionId,
        apiSessionStatus: this.uiState.apiSessionStatus,
        roundBaseline: this.roundBaseline,
      })
    ) {
      return;
    }

    const settlement = evaluateResultSettlement({
      resultHandled: this.resultHandled,
      resultStatus: observation.resultStatus,
      winningSide: observation.winningSide,
    });
    if (settlement.action !== "SETTLE" || settlement.winnerSide == null) return;

    await this.trySettleRound(settlement.winnerSide);
  }

  private async trySettleRound(winnerSide: WagerSide): Promise<void> {
    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return;
    if (this.pendingSettlement || this.resultHandled) return;

    const atEpoch = this.sessionEpoch;
    this.pendingSettlement = true;
    this.observationBusy = true;
    this.uiState.statusLabel = "Settling…";
    this.broadcastState();

    try {
      console.debug("[companion] SETTLED", "winner=", winnerSide);
      const api = await this.backend.companionSettleRound(sessionId, winnerSide);
      this.applyApiState(api, atEpoch);
      this.resultHandled = true;
      this.domWagerRegistered = true;
      this.seenClosed = false;
      this.ambiguousWagerPolls = 0;
      this.roundBaseline = null;
      this.persistRoundSession();
      this.expectedLogicalCents = api.bankroll.cents;
      this.bankrollReconciliation = "PENDING";
      this.reconcilStartedAtMs = Date.now();
      if (api.message && api.settlement_classification === "DIVERGENCE") {
        this.uiState.statusLabel = "Balance resynced";
      }
      if (api.settlement_classification) {
        console.debug(
          "[companion] settlement classification",
          api.settlement_classification,
        );
      }
    } catch (err) {
      this.pendingSettlement = false;
      this.handleApiError(err);
    } finally {
      this.observationBusy = false;
      this.pendingSettlement = false;
      this.broadcastState();
      await this.flushPendingObservation();
    }
  }

  private maybeShowWagerFallback(): void {
    if (
      !shouldOfferWagerFallback({
        sessionStatus: this.uiState.apiSessionStatus,
        view: this.uiState.view,
        canReadWager: this.canReadWager(),
        alreadyOffered: this.wagerFallbackRoundId != null,
      })
    ) {
      return;
    }
    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return;
    this.wagerFallbackRoundId = manualRoundId(sessionId, this.uiState.roundsCompleted);
    const betType = this.uiState.recommendation?.betType ?? "DICE";
    this.uiState = reduceUiState(this.uiState, { type: "wager_fallback_needed", betType });
    this.broadcastState();
  }

  private maybeShowResultFallback(): void {
    if (
      !shouldOfferResultFallback({
        sessionStatus: this.uiState.apiSessionStatus,
        canReadResult: this.canReadResult(),
        alreadyOffered: this.resultFallbackOffered,
      })
    ) {
      return;
    }
    this.resultFallbackOffered = true;
    this.uiState.view = "result_fallback";
    this.uiState.statusLabel = "Waiting for result";
    this.broadcastState();
  }

  private offerManualFallbacksIfNeeded(): void {
    if (isLegacyFallbackBlocked(this.uiState.apiSessionStatus)) return;
    if (this.uiState.apiSessionStatus === "WAITING_FOR_WAGER") {
      this.maybeShowWagerFallback();
    } else if (this.uiState.apiSessionStatus === "WAITING_FOR_RESULT") {
      this.maybeShowResultFallback();
    }
  }

  private async tryAutoRegisterWager(observation: WebsiteObservation): Promise<void> {
    const roundId = observation.roundId;
    const wagerType = observation.wagerType;
    const stakeCents = observation.wagerStakeCents;
    if (!roundId || !wagerType || stakeCents == null) return;
    if (this.registeredWagerRounds.has(roundId)) return;

    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return;

    const atEpoch = this.sessionEpoch;
    this.observationBusy = true;
    try {
      const betType =
        wagerType === "COLOR" && observation.colorSide
          ? observation.colorSide
          : wagerType;
      const api = await this.backend.companionRegisterWager(sessionId, {
        round_id: roundId,
        bet_type: betType,
        stake: this.centsToDollars(stakeCents),
        color_side: observation.colorSide ?? undefined,
      });
      this.registeredWagerRounds.add(roundId);
      this.applyApiState(api, atEpoch);
    } catch (err) {
      if (err instanceof ApiError && err.code !== "duplicate_wager") {
        this.handleApiError(err);
      }
    } finally {
      this.observationBusy = false;
      this.broadcastState();
      await this.flushPendingObservation();
      this.offerManualFallbacksIfNeeded();
    }
  }

  private async tryAutoRegisterResult(observation: WebsiteObservation): Promise<void> {
    if (isLegacyFallbackBlocked(this.uiState.apiSessionStatus)) return;
    const roundId = observation.roundId;
    const result = observation.result;
    if (!roundId || !result || result === "GREEN") return;
    if (this.registeredResultRounds.has(roundId)) return;

    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return;

    const atEpoch = this.sessionEpoch;
    this.observationBusy = true;
    try {
      const api = await this.backend.companionRegisterResult(sessionId, {
        round_id: roundId,
        result,
      });
      this.registeredResultRounds.add(roundId);
      this.applyApiState(api, atEpoch);
      this.resultFallbackOffered = false;
    } catch (err) {
      if (err instanceof ApiError && err.code !== "duplicate_result") {
        this.handleApiError(err);
      }
    } finally {
      this.observationBusy = false;
      this.broadcastState();
      await this.flushPendingObservation();
      this.offerManualFallbacksIfNeeded();
    }
  }

  private async tryReconcile(bankrollCents: number): Promise<void> {
    if (this.reconcilingBankroll === bankrollCents) return;
    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return;

    const atEpoch = this.sessionEpoch;
    this.observationBusy = true;
    try {
      const api = await this.backend.companionReconcile(
        sessionId,
        this.centsToDollars(bankrollCents),
      );
      this.reconcilingBankroll = bankrollCents;
      this.applyApiState(api, atEpoch);
      if (api.session_status === "WAITING_FOR_WAGER") {
        this.wagerFallbackRoundId = null;
        this.resultFallbackOffered = false;
      }
    } catch (err) {
      this.handleApiError(err);
    } finally {
      this.observationBusy = false;
      this.broadcastState();
      await this.flushPendingObservation();
      this.offerManualFallbacksIfNeeded();
    }
  }

  private applyAdapterHealth(health: {
    siteSupported: boolean;
    issues: readonly string[];
    capabilities?: Iterable<string> | ReadonlySet<string>;
  }): void {
    const capabilities = new Set(
      [...(health.capabilities ?? [])],
    ) as Set<import("../adapters/types.js").AdapterCapability>;
    this.adapterHealth = {
      siteSupported: health.siteSupported,
      issues: [...health.issues] as AdapterHealth["issues"],
      capabilities,
    };
    if (!health.siteSupported) {
      this.uiState.health = "PAGE_UNSUPPORTED";
      this.uiState.statusLabel = "Paused";
      if (this.uiState.sessionActive) {
        this.uiState = reduceUiState(this.uiState, { type: "website_failure" });
        this.uiState.health = "PAGE_UNSUPPORTED";
      }
      return;
    }
    if (this.uiState.detectedBankrollCents != null && this.uiState.view === "setup") {
      if (this.uiState.health !== "BACKEND_OFFLINE" && this.uiState.health !== "DESYNCED") {
        this.uiState.health = "CONNECTED";
        this.uiState.statusLabel = "Connected";
      }
      return;
    }
    if (health.issues.includes("DOM_CHANGED")) {
      if (this.uiState.sessionActive) {
        this.uiState = reduceUiState(this.uiState, { type: "website_failure" });
      } else {
        this.uiState.health = "DOM_CHANGED";
      }
    } else if (health.issues.includes("BANKROLL_UNAVAILABLE")) {
      this.uiState.health = "BANKROLL_UNAVAILABLE";
    }
  }

  async pollHealth(): Promise<void> {
    const wasOffline = this.uiState.health === "BACKEND_OFFLINE";
    const preservedDesynced = this.uiState.health === "DESYNCED";
    const result = await this.backend.checkHealth();
    const polledHealth: HealthState = result.ok ? "CONNECTED" : "BACKEND_OFFLINE";
    const merged = mergeHealthPollUpdate(this.uiState.health, polledHealth);
    this.uiState = reduceUiState(this.uiState, { type: "health_update", health: merged });
    if (!result.ok && this.uiState.view === "setup") {
      this.uiState.health = "BACKEND_OFFLINE";
      this.uiState.statusLabel = "Offline";
    }
    if (preservedDesynced && result.ok) {
      this.uiState.health = "DESYNCED";
      this.uiState.statusLabel = "Paused";
    }
    if (result.ok && wasOffline && this.uiState.sessionActive && this.uiState.backendSessionId) {
      try {
        const api = await this.backend.companionGet(this.uiState.backendSessionId);
        this.applyApiState(api);
        this.persistRoundSession();
      } catch {
        /* keep paused offline state */
      }
    }
    if (this.lastObservation) {
      this.applyObservation(this.lastObservation);
    }
    this.broadcastState();
  }

  handleMessage(
    message: CompanionMessage,
  ): CompanionUiState | Promise<CompanionUiState | Record<string, unknown>> {
    switch (message.type) {
      case MSG.GET_STATE:
        return this.getState();

      case MSG.OBSERVATION_UPDATE:
        this.applyObservation(message.payload as WebsiteObservation);
        this.broadcastState();
        return this.getState();

      case MSG.ADAPTER_HEALTH:
        this.applyAdapterHealth(message.payload as AdapterHealth);
        this.broadcastState();
        return this.getState();

      case MSG.START_SESSION:
        return this.startSession(message.payload as StartSessionPayload);

      case MSG.CALCULATE_TARGET:
        return this.calculateTarget(message.payload as CalculateTargetPayload);

      case MSG.STOP_SESSION:
        this.uiState = reduceUiState(this.uiState, { type: "show_stop_dialog" });
        this.broadcastState();
        return this.getState();

      case MSG.CONFIRM_STOP:
        return this.confirmStop();

      case MSG.CANCEL_STOP:
        this.uiState = reduceUiState(this.uiState, { type: "cancel_stop" });
        this.broadcastState();
        return this.getState();

      case MSG.RETRY_CONNECTION:
        return this.pollHealth().then(() => this.getState());

      case MSG.RETRY_WEBSITE:
        if (this.lastObservation) {
          this.applyObservation(this.lastObservation);
        }
        if (
          this.uiState.health === "CONNECTED" ||
          this.uiState.health === "BANKROLL_UNAVAILABLE"
        ) {
          this.uiState.view = this.uiState.sessionActive ? "active" : "setup";
        }
        this.broadcastState();
        return this.getState();

      case MSG.RESYNC:
        return this.resyncFromWebsite();

      case MSG.CONFIRM_WAGER:
        return this.confirmWagerFallback(
          (message.payload as { side?: "ORANGE" | "BLACK" } | undefined)?.side,
        );

      case MSG.CONFIRM_RESULT:
        return this.confirmResultFallback(
          (message.payload as { result: "ORANGE" | "BLACK" | "DICE" }).result,
        );

      case MSG.SAVE_SESSION:
        return this.saveSession();

      case MSG.DISCARD_SESSION:
        return this.discardSession();

      case MSG.START_NEW:
        return this.startNewSession();

      case MSG.MOCK_ADVANCE:
        this.uiState = reduceUiState(this.uiState, { type: "mock_advance" });
        this.broadcastState();
        return this.getState();

      default:
        return this.getState();
    }
  }

  private resetSession(): void {
    this.sessionEpoch = bumpSessionEpoch(this.sessionEpoch);
    this.observationBusy = false;
    this.pendingSettlement = false;
    this.pendingObservation = null;
    this.uiState = reduceUiState(this.uiState, { type: "start_new" });
    this.registeredWagerRounds.clear();
    this.registeredResultRounds.clear();
    this.wagerFallbackRoundId = null;
    this.resultFallbackOffered = false;
    this.reconcilingBankroll = null;
    this.domWagerRegistered = false;
    this.resultHandled = false;
    this.bankrollReconciliation = "IDLE";
    this.reconcilStartedAtMs = null;
    this.expectedLogicalCents = null;
    this.ambiguousWagerPolls = 0;
    this.roundBaseline = null;
    this.seenClosed = false;
    void clearPersistedRoundSession(this.roundStorage);
  }

  private async startNewSession(): Promise<CompanionUiState> {
    const sessionId = this.uiState.backendSessionId;
    if (sessionId) {
      try {
        await this.backend.companionDiscard(sessionId);
      } catch {
        /* local reset still proceeds */
      }
    }
    this.resetSession();
    if (this.lastObservation) {
      this.applyObservation(this.lastObservation);
    }
    this.broadcastState();
    return this.getState();
  }

  private async startSession(payload: StartSessionPayload): Promise<CompanionUiState> {
    if (this.startInFlight) return this.startInFlight;
    this.startInFlight = this.runStartSession(payload).finally(() => {
      this.startInFlight = null;
    });
    return this.startInFlight;
  }

  private async runStartSession(payload: StartSessionPayload): Promise<CompanionUiState> {
    const bankrollCents =
      this.uiState.detectedBankrollCents ?? this.lastObservation?.bankrollCents;
    if (bankrollCents == null) return this.getState();

    this.uiState = reduceUiState(this.uiState, {
      type: "set_target_floor",
      targetCents: payload.targetCents,
      floorCents: payload.floorCents,
    });
    this.uiState = reduceUiState(this.uiState, { type: "start_session" });
    this.broadcastState();

    const atEpoch = bumpSessionEpoch(this.sessionEpoch);
    this.sessionEpoch = atEpoch;

    try {
      const api = await this.backend.companionStart({
        bankroll: this.centsToDollars(bankrollCents),
        target: this.centsToDollars(payload.targetCents),
        floor: this.centsToDollars(payload.floorCents),
      });
      this.registeredWagerRounds.clear();
      this.registeredResultRounds.clear();
      this.wagerFallbackRoundId = null;
      this.resultFallbackOffered = false;
      this.reconcilingBankroll = null;
      this.applyApiState(api, atEpoch);
      this.offerManualFallbacksIfNeeded();
      this.persistRoundSession();
    } catch (err) {
      this.resetSession();
      this.handleApiError(err);
    }
    this.broadcastState();
    return this.getState();
  }

  private async calculateTarget(
    payload: CalculateTargetPayload,
  ): Promise<{
    ok: true;
    targetCents: number;
    targetHitProbability: number;
    solves: number;
  } | { ok: false; error: string }> {
    try {
      const result = await this.backend.companionCalculateTarget({
        bankroll: this.centsToDollars(payload.bankrollCents),
        floor: this.centsToDollars(payload.floorCents),
        reachTargetProbability: payload.reachTargetProbability,
      });
      return {
        ok: true,
        targetCents: result.target.cents,
        targetHitProbability: result.target_hit_probability,
        solves: result.solves,
      };
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Calculate Target failed.";
      return { ok: false, error: message };
    }
  }

  private async confirmWagerFallback(side?: "ORANGE" | "BLACK"): Promise<CompanionUiState> {
    if (isLegacyFallbackBlocked(this.uiState.apiSessionStatus)) {
      return this.getState();
    }
    const sessionId = this.uiState.backendSessionId;
    const rec = this.uiState.recommendation;
    if (!sessionId || !rec) return this.getState();

    if (rec.betType === "COLOR" && !side) {
      return this.getState();
    }

    const roundId =
      this.wagerFallbackRoundId ??
      this.lastObservation?.roundId ??
      manualRoundId(sessionId, this.uiState.roundsCompleted);
    this.wagerFallbackRoundId = roundId;
    const betType =
      rec.betType === "COLOR" && side ? side : rec.betType;

    const atEpoch = this.sessionEpoch;
    try {
      const api = await this.backend.companionRegisterWager(sessionId, {
        round_id: roundId,
        bet_type: betType,
        stake: this.centsToDollars(rec.stakeCents),
        color_side: side,
      });
      this.registeredWagerRounds.add(roundId);
      this.resultFallbackOffered = false;
      this.applyApiState(api, atEpoch);
      this.offerManualFallbacksIfNeeded();
    } catch (err) {
      this.handleApiError(err);
    }
    this.broadcastState();
    return this.getState();
  }

  private async confirmResultFallback(
    result: "ORANGE" | "BLACK" | "DICE",
  ): Promise<CompanionUiState> {
    if (this.uiState.apiSessionStatus === "ROUND_PENDING") {
      await this.trySettleRound(result);
      return this.getState();
    }
    if (isLegacyFallbackBlocked(this.uiState.apiSessionStatus)) {
      return this.getState();
    }
    const sessionId = this.uiState.backendSessionId;
    if (!sessionId) return this.getState();

    const roundId =
      this.wagerFallbackRoundId ??
      this.lastObservation?.roundId ??
      [...this.registeredWagerRounds].at(-1) ??
      null;
    if (!roundId) return this.getState();

    const atEpoch = this.sessionEpoch;
    try {
      const api = await this.backend.companionRegisterResult(sessionId, {
        round_id: roundId,
        result,
      });
      this.registeredResultRounds.add(roundId);
      this.resultFallbackOffered = false;
      this.applyApiState(api, atEpoch);

      const bankroll = this.lastObservation?.bankrollCents ?? this.uiState.detectedBankrollCents;
      if (api.session_status === "RECONCILING" && bankroll != null) {
        await this.tryReconcile(bankroll);
      } else {
        this.offerManualFallbacksIfNeeded();
      }
    } catch (err) {
      this.handleApiError(err);
    }
    this.broadcastState();
    return this.getState();
  }

  private async confirmStop(): Promise<CompanionUiState> {
    const sessionId = this.uiState.backendSessionId;
    const atEpoch = this.sessionEpoch;
    if (sessionId) {
      try {
        const api = await this.backend.companionStop(sessionId);
        this.applyApiState(api, atEpoch);
      } catch (err) {
        this.uiState = reduceUiState(this.uiState, { type: "confirm_stop" });
        this.handleApiError(err);
      }
    } else {
      this.uiState = reduceUiState(this.uiState, { type: "confirm_stop" });
    }
    this.broadcastState();
    return this.getState();
  }

  private async resyncFromWebsite(): Promise<CompanionUiState> {
    const sessionId = this.uiState.backendSessionId;
    const bankrollCents = this.lastObservation?.bankrollCents;
    if (!sessionId || bankrollCents == null) return this.getState();

    const atEpoch = this.sessionEpoch;
    try {
      const api = await this.backend.companionResync(
        sessionId,
        this.centsToDollars(bankrollCents),
      );
      this.wagerFallbackRoundId = null;
      this.reconcilingBankroll = null;
      this.applyApiState(api, atEpoch);
    } catch (err) {
      this.handleApiError(err);
    }
    this.broadcastState();
    return this.getState();
  }

  private async saveSession(): Promise<CompanionUiState> {
    const sessionId = this.uiState.backendSessionId;
    let csvPath: string | null = null;
    let jsonPath: string | null = null;
    if (sessionId) {
      try {
        const result = await this.backend.companionSave(sessionId);
        csvPath = result.csv_path ?? null;
        jsonPath = result.json_path ?? null;
      } catch (err) {
        this.handleApiError(err);
        this.broadcastState();
        return this.getState();
      }
    }
    this.uiState = reduceUiState(this.uiState, {
      type: "save_session",
      csvPath,
      jsonPath,
    });
    this.resetSession();
    this.uiState.backendSessionId = null;
    this.broadcastState();
    return this.getState();
  }

  private async discardSession(): Promise<CompanionUiState> {
    const sessionId = this.uiState.backendSessionId;
    if (sessionId) {
      try {
        await this.backend.companionDiscard(sessionId);
      } catch (err) {
        this.handleApiError(err);
        this.broadcastState();
        return this.getState();
      }
    }
    this.uiState = reduceUiState(this.uiState, { type: "discard_session" });
    this.resetSession();
    this.uiState.backendSessionId = null;
    this.broadcastState();
    return this.getState();
  }
}
