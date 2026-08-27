import type {
  AdapterHealth,
  AdapterCapability,
  ObservationListener,
  SiteAdapter,
  WebsiteObservation,
} from "../types.js";
import { observationSnapshotKey } from "../types.js";
import {
  capabilitiesFromReadings,
  issuesFromReadings,
  parseCSGOEmpireObservation,
} from "./parseObservation.js";
import { isSupportedContext } from "./selectors.js";
import { BANKROLL_POLL_MS } from "../../shared/timing.js";

export interface CSGOEmpireAdapterOptions {
  /** Defaults to globalThis.document when available. */
  getDocument?: () => Document;
  /** Defaults to globalThis.location.href when available. */
  getPageUrl?: () => string;
  /** Debounce DOM bursts before notifying listeners. */
  debounceMs?: number;
  /** Periodic snapshot interval (plan default 500ms). */
  pollMs?: number;
}

export class CSGOEmpireAdapter implements SiteAdapter {
  readonly siteId = "csgoempire";

  private root: Document | Element | null = null;
  private observer: MutationObserver | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<ObservationListener>();
  private latest: WebsiteObservation | null = null;
  private lastSnapshotKey: string | null = null;
  private capabilities = new Set<AdapterCapability>();
  private issues: AdapterHealth["issues"] = [];
  private siteSupported = false;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private scanBusy = false;
  private readonly debounceMs: number;
  private readonly pollMs: number;
  private readonly getDocument: () => Document;
  private readonly getPageUrl: () => string;

  constructor(options: CSGOEmpireAdapterOptions = {}) {
    this.debounceMs = options.debounceMs ?? 50;
    this.pollMs = options.pollMs ?? BANKROLL_POLL_MS;
    this.getDocument = options.getDocument ?? (() => {
      if (typeof document === "undefined") {
        throw new Error("document is not available");
      }
      return document;
    });
    this.getPageUrl = options.getPageUrl ?? (() => {
      if (typeof location === "undefined") {
        return "";
      }
      return location.href;
    });
  }

  start(root?: Document | Element): void {
    this.stop();
    this.root = root ?? this.getDocument();
    this.refreshCapabilities(this.root);

    if (!this.siteSupported) {
      this.latest = null;
      this.lastSnapshotKey = null;
      return;
    }

    this.scanAndNotify(true);

    if (typeof MutationObserver !== "undefined") {
      this.observer = new MutationObserver(() => {
        this.scheduleScan();
      });
      this.observer.observe(this.root, {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true,
      });
    }

    this.pollTimer = setInterval(() => {
      this.scanAndNotify(false);
    }, this.pollMs);
  }

  /** Roulette-only Companion context. */
  isSupportedContext(): boolean {
    return isSupportedContext(this.getPageUrl());
  }

  stop(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.observer?.disconnect();
    this.observer = null;
    this.scanBusy = false;
  }

  probeCapabilities(root?: Document | Element): ReadonlySet<AdapterCapability> {
    const probeRoot = root ?? this.root ?? this.getDocument();
    const observation = parseCSGOEmpireObservation(probeRoot);
    return capabilitiesFromReadings(observation.readings);
  }

  getHealth(): AdapterHealth {
    return {
      siteSupported: this.siteSupported,
      capabilities: new Set(this.capabilities),
      issues: [...this.issues],
    };
  }

  readObservation(root?: Document | Element): WebsiteObservation | null {
    const probeRoot = root ?? this.root ?? this.getDocument();
    if (!isSupportedContext(this.getPageUrl()) && root == null) {
      return null;
    }
    return parseCSGOEmpireObservation(probeRoot);
  }

  onObservation(listener: ObservationListener): () => void {
    this.listeners.add(listener);
    if (this.latest) {
      listener(this.latest);
    }
    return () => {
      this.listeners.delete(listener);
    };
  }

  private refreshCapabilities(root: ParentNode): void {
    this.siteSupported = isSupportedContext(this.getPageUrl());
    if (!this.siteSupported) {
      this.capabilities = new Set();
      this.issues = ["PAGE_UNSUPPORTED"];
      return;
    }
    const observation = parseCSGOEmpireObservation(root);
    this.capabilities = capabilitiesFromReadings(observation.readings);
    this.issues = issuesFromReadings(this.siteSupported, observation.readings);
  }

  private scheduleScan(): void {
    if (!this.root || !this.siteSupported) return;
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      this.scanAndNotify(false);
    }, this.debounceMs);
  }

  private scanAndNotify(force: boolean): void {
    if (!this.root) return;
    if (this.scanBusy) return;
    this.scanBusy = true;
    try {
      this.siteSupported = isSupportedContext(this.getPageUrl());
      if (!this.siteSupported) {
        this.capabilities = new Set();
        this.issues = ["PAGE_UNSUPPORTED"];
        this.latest = null;
        this.lastSnapshotKey = null;
        return;
      }
      // Full re-probe every scan — do not retain stale HTMLElement targets.
      const observation = parseCSGOEmpireObservation(this.root);
      this.capabilities = capabilitiesFromReadings(observation.readings);
      this.issues = issuesFromReadings(this.siteSupported, observation.readings);

      const snapshotKey = observationSnapshotKey(observation);
      if (!force && snapshotKey === this.lastSnapshotKey) {
        return;
      }
      this.lastSnapshotKey = snapshotKey;
      this.latest = observation;
      for (const listener of this.listeners) {
        listener(observation);
      }
    } finally {
      this.scanBusy = false;
    }
  }
}
