import type { SetupMode } from "../shared/money.js";

/** Read uncommitted setup values from live inputs (survives renderBody rebuilds). */
export function readSetupDraftsFromDom(
  body: HTMLElement,
  setupMode: SetupMode,
): { target: string; floor: string; reach: string } {
  const floor = body.querySelector<HTMLInputElement>("#companion-floor")?.value ?? "";
  if (setupMode === "REACH_TARGET") {
    return {
      target: "",
      floor,
      reach: body.querySelector<HTMLInputElement>("#companion-reach")?.value ?? "",
    };
  }
  return {
    target: body.querySelector<HTMLInputElement>("#companion-target")?.value ?? "",
    floor,
    reach: "",
  };
}
