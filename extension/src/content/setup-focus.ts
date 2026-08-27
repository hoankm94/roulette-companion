export interface SetupInputFocus {
  focusId: "companion-target" | "companion-floor" | "companion-reach" | null;
  selectionStart: number | null;
  selectionEnd: number | null;
}

export function captureSetupInputFocus(): SetupInputFocus {
  const active = document.activeElement as HTMLInputElement | null;
  const focusId =
    active?.id === "companion-target" ||
    active?.id === "companion-floor" ||
    active?.id === "companion-reach"
      ? (active.id as SetupInputFocus["focusId"])
      : null;
  return {
    focusId,
    selectionStart: focusId != null ? active!.selectionStart : null,
    selectionEnd: focusId != null ? active!.selectionEnd : null,
  };
}

export function restoreSetupInputFocus(
  body: HTMLElement,
  captured: SetupInputFocus,
): void {
  if (!captured.focusId) return;
  const input = body.querySelector(`#${captured.focusId}`) as HTMLInputElement | null;
  if (!input) return;
  input.focus();
  if (captured.selectionStart != null && captured.selectionEnd != null) {
    input.setSelectionRange(captured.selectionStart, captured.selectionEnd);
  }
}
