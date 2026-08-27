# Edge Live Companion

Microsoft Edge / Chromium MV3 overlay for CSGOEmpire Roulette. Reads site state, talks to the local `/api/companion` backend, and **never places wagers**.

**Version:** `0.1.4`

## Load (Docker + Edge only)

From the **repo root**:

```bash
docker compose up --build api
docker compose --profile tools run --rm extension sh -c "npm install && npm run build"
```

Then Edge → Extensions → Developer mode → **Load unpacked** → `extension/dist`.

Full steps: see the root [README](../README.md).

## Permissions

- `storage` — overlay position / collapsed state
- Hosts: `csgoempire.com`, `localhost:8000` / `127.0.0.1:8000`
- No `<all_urls>`
