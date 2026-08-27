import { CSGOEmpireAdapter } from "../csgoempire/CSGOEmpireAdapter.js";
import { parseCSGOEmpireObservation } from "../csgoempire/parseObservation.js";
import type {
  AdapterCapability,
  AdapterHealth,
  ObservationListener,
  WebsiteObservation,
} from "../types.js";

/**
 * Test helper that drives the CSGOEmpire parser against fixture HTML without a live site.
 */
export class MockCSGOEmpireAdapter {
  readonly siteId = "csgoempire-mock";

  private readonly inner: CSGOEmpireAdapter;
  private readonly container: HTMLElement;

  constructor(html: string, pageUrl = "https://csgoempire.com/roulette") {
    this.container = document.createElement("div");
    this.container.innerHTML = html;
    document.body.appendChild(this.container);

    this.inner = new CSGOEmpireAdapter({
      getDocument: () => document,
      getPageUrl: () => pageUrl,
      debounceMs: 0,
    });
  }

  start(): void {
    this.inner.start(this.container);
  }

  stop(): void {
    this.inner.stop();
    this.container.remove();
  }

  probeCapabilities(): ReadonlySet<AdapterCapability> {
    return this.inner.probeCapabilities(this.container);
  }

  getHealth(): AdapterHealth {
    return this.inner.getHealth();
  }

  readObservation(): WebsiteObservation | null {
    return parseCSGOEmpireObservation(this.container);
  }

  onObservation(listener: ObservationListener): () => void {
    return this.inner.onObservation(listener);
  }

  mutate(mutator: (root: HTMLElement) => void): void {
    mutator(this.container);
  }

  setHtml(html: string): void {
    this.container.innerHTML = html;
  }
}
