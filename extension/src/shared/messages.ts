/** Message protocol between content script and service worker. */

export const MSG = {
  GET_STATE: "companion/get-state",
  START_SESSION: "companion/start-session",
  CALCULATE_TARGET: "companion/calculate-target",
  STOP_SESSION: "companion/stop-session",
  CONFIRM_STOP: "companion/confirm-stop",
  CANCEL_STOP: "companion/cancel-stop",
  RETRY_CONNECTION: "companion/retry-connection",
  RETRY_WEBSITE: "companion/retry-website",
  RESYNC: "companion/resync",
  CONFIRM_WAGER: "companion/confirm-wager",
  CONFIRM_RESULT: "companion/confirm-result",
  SAVE_SESSION: "companion/save-session",
  DISCARD_SESSION: "companion/discard-session",
  START_NEW: "companion/start-new",
  MOCK_ADVANCE: "companion/mock-advance",
  OBSERVATION_UPDATE: "companion/observation-update",
  ADAPTER_HEALTH: "companion/adapter-health",
  HEALTH_CHANGED: "companion/health-changed",
  STATE_CHANGED: "companion/state-changed",
} as const;

export type MessageType = typeof MSG[keyof typeof MSG];

export interface CompanionMessage<T = unknown> {
  type: MessageType;
  payload?: T;
}

export interface StartSessionPayload {
  targetCents: number;
  floorCents: number;
}

export interface CalculateTargetPayload {
  bankrollCents: number;
  floorCents: number;
  reachTargetProbability: number;
}

export interface ConfirmWagerSidePayload {
  side: "ORANGE" | "BLACK";
}
