# CSGOEmpire roulette adapter

Owns CSGOEmpire DOM parsing for the Edge Live Companion.

## Model

```text
ordered strategies / semantic selectors
  → CapabilityReading { value, status, sourceStrategy }
  → flat WebsiteObservation fields only when AVAILABLE
```

Statuses: `AVAILABLE` | `UNAVAILABLE` | `AMBIGUOUS` | `STALE`.

Live automation uses **bankroll** + **`BETTING_STATE`**. Wager/result DOM is usually `UNAVAILABLE` on live (fixtures/legacy only).

## Capabilities

| Capability | Resolution |
|------------|------------|
| Bankroll | `BALANCE_TESTID_AMOUNT` → `HEADER_BALANCE` → `COMPANION_BANKROLL` |
| `BETTING_STATE` | Dice/Black/Orange: `[data-testid=bet-button-*]` then `#bet-button-*`; primary `disable`; secondary `bet-btn--disabled`/`--rolling`; all-agree OPEN/CLOSED; mixed/conflict → AMBIGUOUS |
| Round id / phase / result / wager | Companion/fixture strategies (not primary live settle) |

Do not scrape page-wide utility classes for bankroll. Do not retain HTMLElement refs across polls.

## Context / re-probe

`isSupportedContext(url)` — Roulette only. Each scan reparses current root. SPA leave/return restarts via content script.

## Fixtures

Under `fixtures/`: bankroll variants; `betting_open|closed|mixed|missing|conflicting_*|*_layout_variant|id_fallback.html`.
