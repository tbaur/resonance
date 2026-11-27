# Runbook

## Start (development)

```bash
make run
```

That installs dependencies if needed, starts the API with reload, waits for `GET /api/v1/healthz`, then starts the UI (so Vite never proxies to a dead API). It checks the API and UI ports first and stops with a message if either is taken, so an old API cannot answer in place of the new one. The UI waits up to `RESONANCE_DISCOVERY_TIMEOUT` plus 30 seconds for the API. Ctrl-C stops both.

The API bind comes from `RESONANCE_HOST` / `RESONANCE_PORT`, resolved by the backend's own settings loader: environment first, then the repo-root `.env`, else `127.0.0.1:8000`. The Vite dev proxy follows the port. The UI stays on `127.0.0.1:8765`.

Or two terminals (start UI only after healthz returns 200):

```bash
# Terminal 1 — API (Python package lives in backend/)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" -c constraints.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# or: resonance

# Terminal 2 — UI
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:8765/

## Start (production-ish single process)

```bash
make serve
```

That builds `frontend/dist` and runs the backend console entrypoint (`python -m app.cli`, the same code as the `resonance` command) with `RESONANCE_STATIC_DIR` pointing at it. Open http://127.0.0.1:8780/. It listens on `SERVE_PORT` (default `8780`), not `RESONANCE_PORT`, so it can stay up while `make run` uses `8000` and `8765`. It stops with a message if that port is already taken. Change it with `make serve SERVE_PORT=9000`. `RESONANCE_HOST` and every other `RESONANCE_` setting still apply. The manual equivalent:

```bash
make build
cd backend && RESONANCE_PORT=8780 RESONANCE_STATIC_DIR=../frontend/dist .venv/bin/resonance
```

Without `RESONANCE_STATIC_DIR` the API serves no UI, only a small API home page at `/`. That keeps the `make run` API on `:8000` from serving an old build left in `frontend/dist`.

Environment variables: [CONFIGURATION.md](CONFIGURATION.md). Network exposure notes are in that doc's **Network exposure** section.

## Health

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/healthz` | Liveness — process up; `status: degraded` when the poller is stopped or has not ticked for longer than a healthy pass can take (15 s plus `RESONANCE_DISCOVERY_TIMEOUT` plus three `RESONANCE_DEVICE_HTTP_TIMEOUT` reads and 5 s of retry backoff, since a pass may include a full rediscovery) |
| `GET /api/v1/readyz` | Readiness — 503 under the same conditions. Its `details` hold `device_count`, `last_poll_at`, `last_error_kind` and `last_control_failure_kind` (class or kind only; the message goes to logs, since this endpoint needs no token), `discovery_age_seconds`, `stale_count`, `slow_poll_count`, `sse_dropped_events`, and `sse_subscribers` |
| `GET /api/v1/version` | Release version |
| `GET /api/v1/fleet/health` | In-memory poller drop history (this process; 24h window; resets on restart). Also included on SSE `fleet` events |
| `GET /health` | Redirects to `/api/v1/healthz` (so SPA catch-all never serves HTML for `/health`) |

## Ports (local)

| Service | URL |
|---------|-----|
| UI (Vite, `make run`) | http://127.0.0.1:8765/ |
| API (`make run`) | http://127.0.0.1:8000/ |
| UI and API (`make serve`) | http://127.0.0.1:8780/ |

Under `make run`, Vite proxies `/api` → the API. CORS defaults allow both `http://127.0.0.1:8765` and `http://localhost:8765`.

## Common failures

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Empty fleet | Discovery blocked (VPN/firewall) or no players | Wait for empty-fleet rediscovery (`RESONANCE_EMPTY_FLEET_REDISCOVERY_SECONDS`); Rescan; try `RESONANCE_DISCOVERY_METHOD=lsdp` |
| Missing CI secondary zones | Neither mDNS (`_musp`) nor LSDP (class `0x0003`) saw the zone, or its LSDP announce had no `port` | Rescan. Keep `RESONANCE_DISCOVERY_METHOD=both` (the default) so either method can add the zone |
| LSDP finds nothing and logs `lsdp_discovery_error` with `Address already in use` | Another program holds UDP 11430 without sharing it | Stop that program (`lsof -nP -iUDP:11430`), or set `RESONANCE_DISCOVERY_METHOD=mdns` |
| CI zones too loud/quiet vs Nodes when using one slider | Different amp volume scales | Use **NAD CI S2** for the CI chassis and **Bluesound** for Nodes/Pulse — they are separate. Bluesound chips are 20 / 48 / 60; CI S2 chips are 42 / 50 / 60 / 70 |
| NAD C658 jumps to 0 when house volume is 20 | C658 analog floor is ~40; it is not a bluesound.com device | Set C658 volume on its player row; Bluesound slider is Pulse/Node only |
| `device_not_found` on control | Player dropped off discovery (grace expired) | Rescan network; check `RESONANCE_DISCOVERED_GRACE_TTL` |
| Rooms stuck “synced” / reconnecting after primary power-off | Orphan group (primary offline) | **Ungroup** / **Ungroup all** / House **Break all groups** — backend reparents onto a live donor then removes |
| Add rooms disabled on “Offline primary” | Expected — membership changes need a live primary | Ungroup orphans, then form a new group under an online lead |
| One player stuck offline | Circuit slow-poll after consecutive long-poll/connect failures | Power-cycle the player; wait for `RESONANCE_CIRCUIT_SLOW_POLL_SECONDS` |
| Several rooms flap stale or offline together while music keeps playing | The player API port is out of HTTP slots. Art and queue time out; port 80 diagnostics still answer. `failure_kind` on `player_stale` / `player_offline` names the socket error | Restart on a build that holds one long-poll per player. A second hold is an old process |
| House Health empty after restart | Drop history is process-local (not on disk) | Expected — first online in this process starts the 12h presence bar |
| `Request timed out` on Skip or a queue move from a player page | The browser allows six HTTP/1.1 connections per host. Diagnostics, upgrade checks, and SSE can hold those slots | Leave the page; those scrapes abort. The queue loads when the page opens. Inputs, presets, and settings load when Advanced is opened |
| Player still “online” after power-off | Hung TCP on a Status long-poll | Connect failures fail in `RESONANCE_DEVICE_HTTP_TIMEOUT` (~3s). A stuck read can wait until `RESONANCE_STATUS_LONG_POLL_SECONDS` + slack |
| Bluetooth section missing | Model/probe reports unsupported | Normal for many CI zones and players without BT |
| Empty cover | The cover host doesn't answer over HTTPS, resolves to a private address (`blocked_artwork_host`), the image isn't JPEG, PNG, WebP or HEIC, it is larger than 10 MB, or the page asked for a cover that no player reports | Covers from other hosts are always fetched over HTTPS, so a host that only serves HTTP shows no cover. Player paths must look like a cover. Roon covers are files on the player |
| SSE reconnecting / stale UI | Proxy buffering, backend restart, or SSE backpressure | Check backend logs for `sse_drop_subscriber`; UI uses exponential reconnect, then after 8 failures shows **Offline**, keeps REST polling every 5s, and retries SSE every 60s until live again (empty fleet uses `RESONANCE_EMPTY_FLEET_REDISCOVERY_SECONDS` cache — not a full discovery each poll) |
| `make run` says `Port … is already in use` | Something already listens on the API/UI port (often an earlier `make run`) | Stop that process (`lsof -nP -iTCP:8000 -sTCP:LISTEN`), or set a different `RESONANCE_PORT` |
| `bad interpreter` from a `backend/.venv/bin/` tool after moving the checkout | `backend/.venv` records its original path | `make distclean install` |
| Logs show `insecure_bind` | `RESONANCE_HOST` is not loopback and `RESONANCE_API_TOKEN` is empty | Set `RESONANCE_API_TOKEN`; the browser asks for it once. See [CONFIGURATION.md](CONFIGURATION.md) **Network exposure** |
| Page says **Can’t reach Resonance** | The UI loaded but `/api/v1` is not answering (API starting, restarting, or a proxy in front of it is down) | It retries every few seconds. Check `/api/v1/healthz` and the API logs. The token form appears only on a real `401` |
| `401 unauthorized` from API, or the token form comes back | The token is missing or wrong, or `RESONANCE_API_TOKEN` changed since this browser signed in (that ends every session) | Enter the current token in the form. Scripts send `Authorization: Bearer <token>` |
| `403 missing_request_header` from a script | Writes need `X-Resonance-Request: 1` | Send that header on every `POST` |
| `403 origin_not_allowed` | A page on another origin sent a write, or a reverse proxy changes the `Host` header so the page no longer looks same-origin | Add that origin to `RESONANCE_CORS_ORIGINS` if it is yours, or have the proxy pass `Host` through |
| `400 host_not_allowed`, or the page says **Resonance refused this page** | No token is set and the request used a host name this server does not know, such as a reverse proxy's or a plain LAN name | Open it by IP address or `localhost`, add the name to `RESONANCE_ALLOWED_HOSTS`, or set `RESONANCE_API_TOKEN` |
| `npm run build` or `make serve` stops with `VITE_API_TOKEN is set` | A `frontend/.env` from older instructions builds the token into the page | Delete the `VITE_API_TOKEN` line; the browser asks for the token instead |
| Footer shows `(server v…)` | The page is older or newer than the server | Reload the page; after an upgrade with `make serve`, the build runs again |
| Vite `ECONNREFUSED` / proxy errors to `:8000` | UI started before API was healthy | Use `make run` (waits for healthz); or start API first and confirm healthz before `npm run dev` |

Variable names and defaults: [CONFIGURATION.md](CONFIGURATION.md).

## Multi-room sync notes

- Ungrouping always targets the **primary** with `RemoveSlave` (or legacy `/Sync?remove=`, only for a follower on `:11000`).
- If the primary is offline, the API tries the slave, then **reparent-ungroup**: briefly `AddSlave` onto another **free/standalone** online player (never a member of another group), then `RemoveSlave` there, and verifies standalone via `/SyncStatus`. It tries at most three donors and gives up after 30 seconds (`reparent_ungroup_gave_up`).
- A failed group change logs `control_failed` with `failure_kind` (for example `bluos_error` or `timeout`), the same as other controls.
- After a successful leave, freed players are **stopped** so leftover AirPlay/capture sessions clear (primary only when it has no remaining followers).
- The lead often reports no slaves before the follower drops `master`. The snapshot and fleet row treat that leftover claim as standalone so the row does not stay SYNCED after the group is gone.
- Orphan groups appear in the Sync panel with lead name **Offline primary** and an `offline` role chip; you can ungroup followers but cannot add rooms until a live primary exists.
- **Group all free rooms** / `POST /api/v1/sync/enable` attaches only standalones — existing groups are left alone.
- **Ungroup all** / `POST /api/v1/sync/break` returns succeeded/failed counts; HTTP 502 only when every link removal fails. A group that cannot be resolved (it left, or its address is refused) logs `sync_break_group_skipped` and counts as failed; the other groups still break.
- **Add room** / `POST /api/v1/sync/add` returns 409 when the lead is following another room or the room is already in a group.

## Process

Run one process. More than one uvicorn worker splits the fleet across processes that do not share discovery or the long-polls.

On SIGINT or SIGTERM the app ends every open SSE stream first, so an open browser tab does not hold up a stop or a `--reload` restart. Browsers reconnect when the server is back.

A crash should start that same process again. Example:

```ini
[Service]
WorkingDirectory=/opt/resonance/backend
EnvironmentFile=/opt/resonance/.env
ExecStart=/opt/resonance/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
```

After a restart the health log is empty, discovery runs again, and rooms stay stale or offline until the first successful long-poll. Readiness (`/api/v1/readyz`) reports `discovery_age_seconds`, `stale_count`, and `slow_poll_count`. It returns 503 when the poller task has stopped ticking. It does not include player names or addresses.

## Logs

Stdout carries one JSON object per line, uvicorn's own lines included, and each has `request_id`. Every HTTP request emits `http_request` with method, path, status, and `duration_ms`, including requests refused with 400, 401, 403, or 429; an open SSE stream is the only exception. A client may send its own `X-Request-ID` (1 to 64 letters, digits, `.`, `_`, or `-`); anything else is replaced. Control paths emit `control_op` / `control_failed` / `control_during_grace` with `op`, `device_id`, and `device_ip`, and `control_failed` names `failure_kind`. Fleet-wide actions log per-device results plus `fleet_action_complete` (`action`, `succeeded`, `failed`, and `skipped_muted` for volume). Scoped fleet volume also logs `fleet_volume_targets` with `target_count` / `scoped`. Stop-after-ungroup warnings include `role` (`slave` / `primary`).

Poller misses log `player_stale` on the first miss and `player_offline` at the circuit threshold, both at INFO with `failure_kind`; `poll_device_error` is the per-miss line at DEBUG. `device_watch_failed` and `poller_cycle_failed` are errors in the poller itself. Discovery logs `discovery_complete`, `enrich_failed` and `enrich_unverified` (an announced address that did not answer `/SyncStatus`, so it was not added), and `discovery_kept_unannounced`. Cover art logs `artwork_refused` and `artwork_fetch_failed` with `failure_kind`. Correlate UI toast request IDs with log lines.

## See also

- [CONFIGURATION.md](CONFIGURATION.md) — all `RESONANCE_` variables
- [SECURITY.md](../SECURITY.md) — supported versions and vulnerability reporting
- [README.md](../README.md) — project overview
- [CONTRIBUTING.md](../CONTRIBUTING.md) — setup and checks
