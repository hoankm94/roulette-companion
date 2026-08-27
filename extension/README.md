# Roulette Optimizer — Edge Live Companion Extension

Microsoft Edge / Chromium MV3 overlay for CSGOEmpire Roulette. Observes DOM via `CSGOEmpireAdapter`, drives `/api/companion`, never places wagers.

**Version:** `0.2.0` · Status: [docs/edge_companion_setup_start_handoff.md](../docs/edge_companion_setup_start_handoff.md)

## Behavior

| Area | Implementation |
|------|----------------|
| Setup | Content-script drafts; Target **or** Reach target %; placeholders from bankroll; typing syncs Start gate without rebuilding inputs |
| Calculate Target | SW `MSG.CALCULATE_TARGET` → `POST /api/companion/calculate-target` (no session); expand+binary on grid; Start reuses cached final policy |
| Context | Roulette-only `isSupportedContext()` (optional locale path); SPA history hooks + href poll restart adapter |
| Adapter | Per-capability `CapabilityReading`; bankroll + `BETTING_STATE` + per-button wager/result DOM; CSS-hidden ignored |
| Wager | **Primary:** `bet-btn--placed` → `POST .../dom-wager` (idempotent) |
| Settle | **Primary:** complete win/loss → `POST .../settle-round` `{ winner_side }` (idempotent; SW session reclaim) |
| Waiting UI | Recommendation + metrics stay visible; status is additive |
| Metrics | Reach target % + DICE drought durability (95% survival horizon) |
| Bankroll | Background reconciliation only — never blocks next recommendation |
| Terminal | Save / Do Not Save → fresh setup (save banner with json path) |
| Build | Vite: content IIFE + background ES SW; `manifest.json` → `dist` |

## Production flow

```text
/roulette DOM
  → CSGOEmpireAdapter (500ms poll + mutations; re-query, no stale nodes)
  → content overlay
  → companion-controller gates → /api/companion/*
  → LiveSession (shared with Manual Live Play)
```

```text
WAITING_FOR_WAGER
  → DOM placed wager (side + stake) → dom-wager → ROUND_PENDING
  → complete win/loss classes → settle-round { winner_side }
  → next recommendation + metrics immediately
  → website bankroll reconciles in background
  → OPEN + cleared result → re-arm next wager
```

Mismatch (wrong family or stake) still enters `ROUND_PENDING` with an API warning; logical settle uses the **actual** observed action. No fixed settlement delay. Website bankroll does not block the next round.

## Legacy (retained until live E2E)

| Path | Status |
|------|--------|
| `wager-deduction` (bankroll Δ as primary wager signal) | **Deprecated** — endpoint kept; service worker no longer calls it |
| `register-wager` / `register-result` / manual confirm | **Deprecated** — gated under `ROUND_PENDING`; not production flow |
| `resync` | **Live** — overlay Resync |
| Missed-dip bankroll increase while `WAITING_FOR_WAGER` | Resync/TARGET via legacy deduction handler if ever re-enabled |

## Structure

```text
extension/
├── manifest.json
├── src/
│   ├── background/   # companion-controller, gates, round-session, SW entry
│   ├── content/      # Overlay, drafts, route-watch, calc guard, mount
│   ├── adapters/     # CSGOEmpire strategies, fixtures
│   ├── client/       # BackendClient, companion-map
│   ├── overlay/ state/ shared/ money/
├── vite.content.config.ts / vite.background.config.ts
└── tests/
```

## Load (Edge)

1. `docker compose up --build api` → `http://localhost:8000/api/health`
2. Build:

   ```bash
   docker compose --profile tools run --rm extension sh -c "npm install && npm test && npm run build"
   ```

3. Load unpacked → **`extension/dist`**. Confirm **0.2.0**. After code changes: rebuild + extension **Reload**.
4. Site access: csgoempire + localhost. Open `/roulette`.

## Backend

- Health 15s: `GET /api/health`
- Production: `POST .../start`, `calculate-target`, `dom-wager`, `settle-round`, stop / save / discard
- Legacy still mounted: `wager-deduction` (unused); register-wager / register-result / reconcile (zombie/fallback, cleanup after E2E). `resync` remains live.
- Offline → pause; override URL: `chrome.storage.local` `companion_backend_url`

## Safety

- Recommendations only; you place every wager.
- `AVAILABLE` betting drives round boundary; `AMBIGUOUS` fails closed.
- Ambiguous bankroll or placed-without-amount (persistent) fails closed.
- Terminal: Save / Do Not Save → fresh setup (save shows path briefly).
- Setup: Target **or** Reach target %; placeholders from bankroll; waiting keeps all active stats.

## Design

Tokens from `frontend` / `DESIGN.md`. Overlay: compact fluid width, content-driven height, draggable, collapsible, viewport-clamped.
