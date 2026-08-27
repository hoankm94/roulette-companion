const COMPANION_ROOT_ID = "roulette-companion-root";

export function ensureSingleCompanionRoot(createRoot: () => HTMLElement): HTMLElement {
  const existing = document.getElementById(COMPANION_ROOT_ID);
  if (existing instanceof HTMLElement) {
    return existing;
  }
  const root = createRoot();
  root.id = COMPANION_ROOT_ID;
  return root;
}
