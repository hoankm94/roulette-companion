export interface RouteWatcherOptions {
  pollMs?: number;
  getHref?: () => string;
}

/** Detect SPA navigations via history hooks with poll fallback. */
export function installRouteWatcher(
  onRouteChange: () => void,
  options: RouteWatcherOptions = {},
): () => void {
  const getHref = options.getHref ?? (() => location.href);
  let lastHref = getHref();

  const check = (): void => {
    const href = getHref();
    if (href === lastHref) return;
    lastHref = href;
    onRouteChange();
  };

  const originalPushState = history.pushState.bind(history);
  const originalReplaceState = history.replaceState.bind(history);

  history.pushState = function pushState(
    this: History,
    ...args: Parameters<History["pushState"]>
  ): void {
    originalPushState(...args);
    check();
  };

  history.replaceState = function replaceState(
    this: History,
    ...args: Parameters<History["replaceState"]>
  ): void {
    originalReplaceState(...args);
    check();
  };

  const onPopState = (): void => {
    check();
  };
  window.addEventListener("popstate", onPopState);

  const pollMs = options.pollMs ?? 500;
  const pollTimer = setInterval(check, pollMs);

  return () => {
    clearInterval(pollTimer);
    window.removeEventListener("popstate", onPopState);
    history.pushState = originalPushState;
    history.replaceState = originalReplaceState;
  };
}
