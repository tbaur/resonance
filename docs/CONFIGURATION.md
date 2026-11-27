# Configuration

All settings are environment variables with the `RESONANCE_` prefix. Copy [.env.example](../.env.example) to `.env` in the **repo root** (or export variables in your shell) before starting the backend. The settings loader resolves the repo-root `.env` even when uvicorn is started from `backend/` (cwd-relative `.env` is also accepted as a fallback).

Default settings are for local development: bind localhost, discover via mDNS+LSDP, long-poll player Status, and throttle both outbound BluOS calls and inbound mutating API requests (plus expensive GETs such as `/api/v1/fleet/upgrades`).

Local UI is Vite on **port 8765** (`make run` / `frontend` `npm run dev`). CORS defaults match that origin. The API defaults to **port 8000**. `make serve` puts the UI and API on one port, **8780** (`SERVE_PORT`), so CORS does not apply to it.

BluOS control paths follow the BluOS API spec (queue via `/Playlist`, capture inputs via `/Settings?id=capture`, Bluetooth via `/audiomodes`, audio/player settings via `/Settings?id=audio|player`). Device diagnostics and upgrade checks use the player web UI on port 80 (`/diagnostics`, `/upgrade`). A setting write uses the control path that the player's own `/Settings` page names for it (for example `/audiomodes` or `/alsa_setting`). The reverse-engineered web UI `POST /settings` form is the fallback, used only when the player names no path or answers 404 or 405 on it. A write that times out is not sent again through the web UI, because the player may already have applied it.

## Network exposure

BluOS players have no authentication — each device already exposes control on the LAN (and Resonance consolidates that). There is nothing extra to configure for device auth.

- **Default (`RESONANCE_HOST=127.0.0.1`):** only this machine can reach Resonance.
- **LAN bind (`0.0.0.0`):** same practical exposure as opening any player's BluOS UI to the network. Set `RESONANCE_API_TOKEN` so API calls require a Bearer token; tighten `RESONANCE_CORS_ORIGINS`; set `RESONANCE_ENABLE_OPENAPI=false` if you do not want `/api/docs` on the LAN. The browser asks for the token once and keeps an HttpOnly session cookie. Do not build the token into the UI: anyone who can load the page could read it. A build with `VITE_API_TOKEN` set stops with an error.
- **Do not** expose Resonance to the internet.

Every request under `/api/` passes these checks, whether or not a token is set:

- **Writes need `X-Resonance-Request: 1`.** Every `POST` (any method other than `GET`, `HEAD`, or `OPTIONS`) without it gets **403** `missing_request_header`. A web page on another site can send a plain `POST` to `127.0.0.1` without asking first, but it cannot add this header without a CORS preflight, which a foreign origin fails. The UI always sends it. Scripts and other API clients must send it too.
- **Writes from a browser must come from this server or a configured origin.** A request whose `Origin` header is not this server and not in `RESONANCE_CORS_ORIGINS` gets **403** `origin_not_allowed`.
- **Without a token, the `Host` header must be one this server answers to:** an IP address, `localhost`, a `*.localhost` or `*.local` name, `RESONANCE_HOST`, a host named in `RESONANCE_CORS_ORIGINS`, or one in `RESONANCE_ALLOWED_HOSTS`. Anything else gets **400** `host_not_allowed`. This stops DNS rebinding, where a web page points its own domain at this server to read the API. Health, readiness, and version answer under any name. With a token set, the check is off, because a rebinding page has no credential.

BluOS control calls go only to discovered private IPs (see `RESONANCE_ALLOW_NON_PRIVATE_IPS`). Cover art is the exception. A player-relative cover is fetched from that player, and the path has to look like a cover. Any other host that the player names is fetched over HTTPS, and an `http://` link is upgraded, so stream metadata can't point the server at a router or another device on the home network. That covers Apple Music, Amazon Music, TIDAL, Spotify and any other service without a list to keep up. A cover host must also resolve only to public addresses, so a device on the home network with a real certificate (a NAS, a router, a split-horizon name) is refused too; the request then goes to the address that passed the check, with TLS still verified for the host name. Every redirect gets the same check. A host other than the player is fetched only when a player reported that cover. The body is capped at 10 MB, and only JPEG, PNG, WebP and HEIC are served, judged from the bytes. Control-call redirects stay on the player. The browser loads the cover from the Resonance server.

## Server

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESONANCE_HOST` | `127.0.0.1` | Bind address |
| `RESONANCE_PORT` | `8000` | Bind port |
| `RESONANCE_LOG_LEVEL` | `INFO` | Log level |
| `RESONANCE_CORS_ORIGINS` | `http://127.0.0.1:8765,http://localhost:8765` | Allowed CORS origins (comma-separated) |
| `RESONANCE_API_TOKEN` | *(empty)* | When set, require `Authorization: Bearer …`, `X-API-Token`, or the `resonance_session` cookie for everything under `/api/`, including `/api/docs` and `/api/openapi.json` (health, readiness, and version are exempt). The SSE stream authenticates the same way; a `?token=` query is not accepted. The token does not lock players on the LAN; they have no auth. It locks a Resonance server that is reachable from a network that cannot reach the players. `POST /api/v1/session` with the bearer token sets the cookie (an HMAC of the token, not the token). The UI asks for the token in the browser; it is never built into the page |
| `RESONANCE_ALLOWED_HOSTS` | *(empty)* | Comma-separated host names the API answers to when no token is set, such as the name a reverse proxy passes on. Addresses, `localhost`, and `*.local` names are always allowed. See **Network exposure** |
| `RESONANCE_TRUSTED_PROXIES` | *(empty)* | Comma-separated peer IPs allowed to supply `X-Forwarded-For` (the API rate-limit key uses the right-most address that is not one of these proxies) and `X-Forwarded-Proto` (an `https` value marks the session cookie `Secure`) |
| `RESONANCE_STATIC_DIR` | *(empty)* | Built UI to serve from the API process (path relative to the uvicorn working directory). Empty means an API-only server: `/` shows a small API home page. `make serve` sets it to `frontend/dist` |
| `RESONANCE_ENABLE_OPENAPI` | auto | OpenAPI/Swagger at `/api/docs`; auto-off when binding beyond localhost. With a token set, the docs need the token too (sign in through the UI first) |
| `RESONANCE_VALENCE_URL` | *(empty)* | When set to an `http` or `https` address, the header shows a Valence pill that links there |

`make run` reads `RESONANCE_HOST` and `RESONANCE_PORT` through the backend's settings loader, so it follows the same precedence as the API. It also passes the port to Vite so the dev proxy follows it. When `RESONANCE_HOST` is `0.0.0.0`, the health probe and the UI proxy still use `127.0.0.1`.

`make serve` uses `RESONANCE_HOST` but listens on the make variable `SERVE_PORT` (default `8780`) instead of `RESONANCE_PORT`, so it does not collide with `make run`. Set it on the command line or in the environment (`make serve SERVE_PORT=9000`). `.env` does not set it, because the API does not read it.

Binding beyond loopback with an empty `RESONANCE_API_TOKEN` logs an `insecure_bind` warning at startup. On the player LAN that is the same exposure as the players themselves. The token matters when Resonance is the only service a caller can reach.

## Discovery

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESONANCE_DISCOVERY_METHOD` | `both` | `mdns`, `lsdp`, or `both` (merge) |
| `RESONANCE_DISCOVERY_TIMEOUT` | `5` | Discovery window (seconds) |
| `RESONANCE_DISCOVERY_CACHE_TTL` | `300` | How often the **poller** re-browses a non-empty fleet. Mute/volume/skip use the live snapshot and never wait on this window |
| `RESONANCE_EMPTY_FLEET_REDISCOVERY_SECONDS` | `30` | How often the **poller** re-browses when the fleet is empty. `GET /devices` does not scan; use **Rescan** for an on-demand browse |
| `RESONANCE_DISCOVERED_GRACE_TTL` | `60` | Control grace after a player drops from discovery |
| `RESONANCE_ALLOW_NON_PRIVATE_IPS` | `false` | Escape hatch — allow non-private device IPs (unsafe) |
| `RESONANCE_BLUOS_PORT` | `11000` | Default BluOS HTTP port, `1024` to `65535`. CI secondary zones use their own port (e.g. `11010`) from the mDNS SRV record or the LSDP announce |
| `RESONANCE_WEB_UI_PORT` | `80` | Device web UI port (diagnostics, upgrade, setting writes) |

Players are keyed as canonical `ip:port`. Only endpoints that answer `/SyncStatus` are added to the fleet. A player that a browse misses (a lost LSDP reply or mDNS announce) stays in the fleet while the poller still reaches it, for up to two browses in a row (`discovery_kept_unannounced` in the log). A third miss, or a miss while the poller cannot reach it, removes it into the grace period. Its drop history stays until it ages out of the 24-hour window.

- **mDNS** browses primary players (`_musc._tcp.local.`) and CI secondary zones (`_musp._tcp.local.`, e.g. NAD CI S2).
- **LSDP** listens on UDP 11430 and sends its query to the broadcast address of each network interface. It asks for primary players (class `0x0001`), secondary zones (class `0x0003`), and hubs (class `0x0008`). A zone's port comes from the `port` value in its announce. LSDP skips a secondary zone that announces no port, and it does not guess `11010`, `11020`, and so on.
- **Stereo-pair slaves** (`_musz`, LSDP class `0x0006`) are left out on purpose. The primary controls them and the BluOS app hides them, so listing them would add rooms that do not exist.
- **Player IDs** come from the MAC that LSDP announces, when LSDP heard the player. A zone on a port other than `11000` gets `-<port>` added, so the zones of one chassis keep separate IDs. A player that only mDNS found gets an ID hashed from its address.

### Multi-zone and volume UI

NAD CI multi-zone chassis expose each zone as its own BluOS endpoint, on ports ten apart (`:11000` is zone 1, `:11010` zone 2, `:11020` zone 3, …). The fleet UI shows zone numbers next to the model name. **Bluesound** volume applies to bluesound.com players (Nodes/Pulse) with 20 / 48 / 60 chips; **NAD CI S2** volume applies only to CI S2 zones with 42 / 50 / 60 / 70 chips. Other brands (NAD C658) are not on either house slider.

### Sync / orphan groups

`POST /api/v1/sync/enable` groups **free (standalone) rooms only** under the chosen primary — it never pulls followers out of existing groups. `POST /api/v1/sync/break` and `POST /api/v1/sync/remove` dissolve runtime groups; break returns per-link succeeded/failed counts (502 only when every link fails). `POST /api/v1/sync/add` refuses (**409**) a lead that is itself following another room (`master_is_follower`) and a room that is already in a group (`slave_already_grouped`). When the primary has left discovery, secondaries that still report a master are surfaced as orphan groups (Sync panel lead name **Offline primary**, role chip `offline`). Break/remove then use reparent-ungroup against **other free/standalone** online endpoints (never members of another group), trying at most three donors within 30 seconds. Break all resolves each group before it changes anything; a group that cannot be resolved is reported as failed and the others still break. The legacy `/Sync` call is used as a fallback only for a primary zone on `:11000`, because it names a follower by address alone. See [RUNBOOK.md](RUNBOOK.md) **Multi-room sync notes**.

### Bluetooth

`GET /api/v1/devices/{id}/bluetooth` returns `supported: false` when the model is known-unsupported, the capture probe reports no Bluetooth, **or the probe hard-fails** — not a 502. `POST` to set a mode returns **404** `bluetooth_unsupported` in those same cases (including probe hard-fail). The player detail UI hides the Bluetooth section when unsupported.

## Polling and device HTTP

Each online player holds one etag long-poll, never both `/Status` and `/SyncStatus`. A BluOS player keeps playing with those two holds open, then stops answering HTTP, so the room looks stale or offline. A room that is not a grouped follower holds `/Status` until playback, volume, or grouping changes, or until `RESONANCE_STATUS_LONG_POLL_SECONDS` elapses. `secs` is interpolated in the UI and does not wake the poll. A grouped follower holds `/SyncStatus` instead, so its own mute and volume show up at once; its track and seek position are copied from the group lead. `/SyncStatus` is also read when a lead's `<syncStat>` changes, and again every minute, because a follower can join a group without that value moving. One more call to that player (skip, art, queue) can run beside the hold. Long-polls do not take a `RESONANCE_MAX_CONCURRENT_DEVICE_CALLS` slot. A house or per-player control cancels that held read (waits up to `RESONANCE_CONTROL_INTERRUPT_WAIT_SECONDS`) so `/Volume` and `/Skip` are not queued behind the 100s hold. Offline rooms are omitted from mute-all / volume-all so a dead player cannot stall the rest behind `RESONANCE_DEVICE_HTTP_TIMEOUT`. Connect failures still use `RESONANCE_DEVICE_HTTP_TIMEOUT` so a powered-off player is not waited out for 100s.

Discovery (mDNS/LSDP + enrich) runs at startup, on **Rescan**, when the fleet is empty (`RESONANCE_EMPTY_FLEET_REDISCOVERY_SECONDS`), and in the poller when `RESONANCE_DISCOVERY_CACHE_TTL` expires. `GET /devices`, `GET /sync`, and house control read the in-memory snapshot.

Drop history (`GET /api/v1/fleet/health`, House page Health, player 12-hour presence) is **in-memory for this process** — it resets when the server restarts. A miss only counts as a drop after that player was seen online. Device `:80/diagnostics` and `/upgrade` are not in the poll loop; the player page aborts those scrapes on leave so they cannot starve Skip.

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESONANCE_POLL_INTERVAL` | `3` | Retry delay after a missed Status long-poll (before circuit slow-poll) |
| `RESONANCE_STATUS_LONG_POLL_SECONDS` | `100` | `/Status?timeout=` hold time (BluOS API spec recommends 100s; minimum 10s) |
| `RESONANCE_LONG_POLL_READ_SLACK_SECONDS` | `5` | Extra HTTP read time so httpx does not cut off the player at exactly `timeout=` |
| `RESONANCE_LONG_POLL_GAP_SECONDS` | `1` | Minimum spacing between consecutive `/Status` GETs on the same player (BluOS API spec requires ≥ 1s) |
| `RESONANCE_DEVICE_HTTP_TIMEOUT` | `3` | Connect/control HTTP timeout (long-poll read timeout is separate) |
| `RESONANCE_MAX_CONCURRENT_DEVICE_CALLS` | `20` | Cap concurrent BluOS HTTP calls |
| `RESONANCE_CONTROL_RATE_LIMIT_SECONDS` | `0.1` | Per **device endpoint** (`ip:port`) spacing for outbound BluOS control and web-UI writes |
| `RESONANCE_CONTROL_INTERRUPT_WAIT_SECONDS` | `0.25` | Max wait after cancelling a Status long-poll before the control HTTP call proceeds |
| `RESONANCE_API_RATE_LIMIT_SECONDS` | `0.05` | Minimum spacing per **HTTP client IP + method + path** for mutating API requests and expensive GETs (`/api/v1/fleet/upgrades`). Each client gets its own bucket for its first 64 paths; later paths share one bucket, so a flood of made-up paths cannot grow the table. Excess requests return **429** (they do not wait). Cheap in-memory GETs such as `/api/v1/devices` and `/api/v1/sync` are not throttled so overlapping UI loads (mount, Strict Mode, in-flight reload) cannot fail. Outbound BluOS control still uses sleep-based spacing (`RESONANCE_CONTROL_RATE_LIMIT_SECONDS`). Behind a reverse proxy, set `RESONANCE_TRUSTED_PROXIES` so `X-Forwarded-For` is honored |
| `RESONANCE_CIRCUIT_FAILURE_THRESHOLD` | `5` | Failures before slow-poll |
| `RESONANCE_CIRCUIT_SLOW_POLL_SECONDS` | `15` | Slow-poll interval after circuit open |
| `RESONANCE_FLEET_UPGRADES_CACHE_SECONDS` | `30` | Cache TTL for `GET /api/v1/fleet/upgrades` |

Device HTTP reads retry with jittered backoff after a timeout or a connection error. Replies are read in chunks and refused once they pass `RESONANCE_MAX_XML_SIZE`.

## Live events (SSE)

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESONANCE_SSE_KEEPALIVE_SECONDS` | `15` | Keepalive interval on `GET /api/v1/events`. The response names it in `X-Resonance-Keepalive`, and the UI drops and reopens a stream that sends nothing for two and a half intervals |
| `RESONANCE_SSE_QUEUE_SIZE` | `32` | Per-subscriber SSE queue size (drop-oldest under backpressure) |

Every event carries `sent_at`, the server's clock, and `GET /api/v1/devices` carries `server_time`. The UI places `secs_at` readings on that clock, so a browser with a wrong clock still shows the right playhead.

## XML hardening

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESONANCE_MAX_XML_SIZE` | `1048576` | Max bytes for a BluOS XML body |
| `RESONANCE_MAX_XML_DEPTH` | `20` | Max XML depth |
| `RESONANCE_MAX_XML_ELEMENTS` | `10000` | Max XML elements |

## Common adjustments

- **Single-process deploy:** `make serve`, or `make build` and then set `RESONANCE_STATIC_DIR=../frontend/dist` from `backend/` (the path is relative to the uvicorn working directory). Without it the API serves no UI. See [RUNBOOK.md](RUNBOOK.md).
- **Reverse proxy without a token:** add the name the proxy passes in `Host` to `RESONANCE_ALLOWED_HOSTS`.
- **Discovery trouble:** try `RESONANCE_DISCOVERY_METHOD=lsdp` or increase `RESONANCE_DISCOVERY_TIMEOUT`.
- **Slow VPN/firewall:** increase `RESONANCE_DEVICE_HTTP_TIMEOUT` (connect/control) or `RESONANCE_STATUS_LONG_POLL_SECONDS` (Status hold).

## See also

- [RUNBOOK.md](RUNBOOK.md) — start commands, health endpoints, failures, logs
- [SECURITY.md](../SECURITY.md) — vulnerability reporting
- [README.md](../README.md) — project overview
