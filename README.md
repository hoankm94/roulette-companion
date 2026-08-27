# Roulette Companion

Overlay for [CSGOEmpire Roulette](https://csgoempire.com/roulette) that recommends COLOR / DICE stakes from a verified goal-directed policy. **It never places bets for you** — you wager manually on the site.

**You only need:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) and [Microsoft Edge](https://www.microsoft.com/edge).

---

## Quick start

### 1. Start the local API

From the repo root:

```bash
docker compose up --build api
```

Leave this running. Check health: [http://localhost:8000/api/health](http://localhost:8000/api/health)

Optional web UI (same API): `docker compose up --build api frontend` → [http://localhost:5173](http://localhost:5173)

### 2. Build the Edge extension

```bash
docker compose --profile tools run --rm extension sh -c "npm install && npm run build"
```

This writes the loadable extension to `extension/dist`.

### 3. Load it in Edge

1. Open `edge://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → choose the `extension/dist` folder
4. Confirm version **0.1.4**
5. Allow site access for `csgoempire.com` and `localhost:8000` if Edge asks

### 4. Play

1. Open [https://csgoempire.com/roulette](https://csgoempire.com/roulette) and log in
2. The overlay should show **Connected** and your bankroll
3. Set **Target** (or **Reach target %** + **Calculate Target**) and **Hard Floor**
4. Click **Start**
5. Place every recommended wager yourself on the site
6. When a session ends, choose **Save Session** or **Do Not Save**

After any extension code change: rebuild (step 2), then **Reload** the extension in Edge. Restarting Docker alone does not refresh a loaded `dist`.

---

## How it works

| Piece | Role |
|-------|------|
| Docker `api` | Solves and caches a policy once at Start; tracks the live session |
| Edge extension | Reads the roulette page DOM; shows recommendations; never clicks bets |
| You | Place every wager on CSGOEmpire |

Round flow:

1. Overlay recommends a COLOR or DICE stake
2. You place that bet on the site
3. Extension detects the placed wager and the result
4. Overlay updates bankroll metrics and the next recommendation

Saved sessions (if you choose Save) land in `outputs/saved_sessions/` on your machine via the API container mount.

---

## Safety

- Recommendations only — no auto-betting
- While a session is active, do not deposit, withdraw, open cases, or place unrelated wagers (external balance changes break tracking)
- Ambiguous bankroll or incomplete result markers fail closed (no guessing)

---

## Requirements

| Need | Notes |
|------|--------|
| Docker Desktop | Builds and runs the API (and optional UI / extension build) |
| Microsoft Edge | Load the unpacked MV3 extension |
| CSGOEmpire account | You must be able to open `/roulette` in Edge |

No host Python, Node, or npm install is required.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Overlay missing | Confirm you are on `/roulette`, extension is enabled, version 0.1.4 |
| Not connected | API must be up (`docker compose up --build api`); allow `localhost:8000` |
| Stale UI after rebuild | Edge → Extensions → **Reload** Companion |
| Port 8000 in use | Stop whatever is using 8000, or change the compose port mapping |
