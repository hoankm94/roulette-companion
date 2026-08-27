export interface OverlayPosition {
  x: number;
  y: number;
}

export interface OverlayPersistedState {
  position: OverlayPosition;
  collapsed: boolean;
}

const STORAGE_KEY = "companion_overlay_layout";
const DEFAULT_POSITION: OverlayPosition = { x: 16, y: 16 };
const HEADER_DRAG_SELECTOR = "[data-companion-drag]";

export async function loadOverlayLayout(): Promise<OverlayPersistedState> {
  try {
    const result = await chrome.storage.local.get(STORAGE_KEY);
    const stored = result[STORAGE_KEY] as OverlayPersistedState | undefined;
    if (stored?.position) {
      return {
        position: stored.position,
        collapsed: stored.collapsed ?? false,
      };
    }
  } catch {
    /* storage unavailable in tests */
  }
  return { position: DEFAULT_POSITION, collapsed: false };
}

export async function saveOverlayLayout(state: OverlayPersistedState): Promise<void> {
  try {
    await chrome.storage.local.set({ [STORAGE_KEY]: state });
  } catch {
    /* ignore in tests */
  }
}

export function clampPosition(
  position: OverlayPosition,
  panel: HTMLElement,
  margin = 8,
): OverlayPosition {
  const rect = panel.getBoundingClientRect();
  const maxX = Math.max(margin, window.innerWidth - rect.width - margin);
  const maxY = Math.max(margin, window.innerHeight - rect.height - margin);
  return {
    x: Math.min(Math.max(margin, position.x), maxX),
    y: Math.min(Math.max(margin, position.y), maxY),
  };
}

export function applyOverlayPosition(panel: HTMLElement, position: OverlayPosition): void {
  panel.style.left = `${position.x}px`;
  panel.style.top = `${position.y}px`;
}

export function setupOverlayDrag(
  panel: HTMLElement,
  onPositionChange: (pos: OverlayPosition) => void,
): () => void {
  const header = panel.querySelector(HEADER_DRAG_SELECTOR);
  if (!header) return () => undefined;

  let dragging = false;
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;

  const onPointerDown = (e: PointerEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    originX = panel.offsetLeft;
    originY = panel.offsetTop;
    header.setPointerCapture(e.pointerId);
    panel.classList.add("is-dragging");
  };

  const onPointerMove = (e: PointerEvent) => {
    if (!dragging) return;
    const raw: OverlayPosition = {
      x: originX + e.clientX - startX,
      y: originY + e.clientY - startY,
    };
    const clamped = clampPosition(raw, panel);
    applyOverlayPosition(panel, clamped);
    onPositionChange(clamped);
  };

  const onPointerUp = (e: PointerEvent) => {
    if (!dragging) return;
    dragging = false;
    panel.classList.remove("is-dragging");
    header.releasePointerCapture(e.pointerId);
    const clamped = clampPosition(
      { x: panel.offsetLeft, y: panel.offsetTop },
      panel,
    );
    applyOverlayPosition(panel, clamped);
    onPositionChange(clamped);
  };

  header.addEventListener("pointerdown", onPointerDown as EventListener);
  header.addEventListener("pointermove", onPointerMove as EventListener);
  header.addEventListener("pointerup", onPointerUp as EventListener);
  header.addEventListener("pointercancel", onPointerUp as EventListener);

  return () => {
    header.removeEventListener("pointerdown", onPointerDown as EventListener);
    header.removeEventListener("pointermove", onPointerMove as EventListener);
    header.removeEventListener("pointerup", onPointerUp as EventListener);
    header.removeEventListener("pointercancel", onPointerUp as EventListener);
  };
}

export function setupOverlayViewportGuard(
  panel: HTMLElement,
  getPosition: () => OverlayPosition,
  onPositionChange: (pos: OverlayPosition) => void,
): () => void {
  const recheck = () => {
    const clamped = clampPosition(getPosition(), panel);
    applyOverlayPosition(panel, clamped);
    onPositionChange(clamped);
  };

  window.addEventListener("resize", recheck);
  window.addEventListener("scroll", recheck, { passive: true });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", recheck);
  }

  recheck();

  return () => {
    window.removeEventListener("resize", recheck);
    window.removeEventListener("scroll", recheck);
    if (window.visualViewport) {
      window.visualViewport.removeEventListener("resize", recheck);
    }
  };
}
