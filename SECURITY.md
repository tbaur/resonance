# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 4.x     | ✅ Active support |
| < 4.0   | ❌ Not supported |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue**
2. Use GitHub's private vulnerability reporting (Security tab), or contact the maintainer directly
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested fixes

## Context

BluOS players have no authentication — each device already exposes control on the LAN. Resonance consolidates that surface. Operational guidance (bind address, CORS, OpenAPI) is in [docs/CONFIGURATION.md](docs/CONFIGURATION.md) under **Network exposure**.

## Security Measures

The backend applies:

- Discovered-device targeting with a short grace TTL
- Private IPv4 gate on BluOS calls (unless explicitly overridden)
- Same-host validation when following BluOS HTTP redirects. Cover fetches are the exception: the player may be reached over HTTP, but only on paths that look like a cover. Any other host must use HTTPS, and an `http://` link is fetched as HTTPS, so stream metadata can't point the server at a router or another device on the home network. That host must also resolve only to public addresses, and the request connects to the address that was checked, so a home device with a valid certificate or a second DNS answer cannot be reached either. Every redirect gets the same check. A host other than the player is fetched only when a player reported that cover. The body is capped at 10 MB, and only JPEG, PNG, WebP and HEIC are served, judged from the bytes.
- Per-device and per-client rate limiting, with a bounded number of buckets per client
- Cross-site request checks on every `/api/` write: `X-Resonance-Request: 1` is required, and a browser `Origin` must be this server or a configured one
- A `Host` header check when no token is set, so a DNS-rebinding page cannot read or drive the API
- Device replies read in chunks and refused once they pass the XML size cap
- XML size/depth/element caps (including sync-control response OK checks via the hardened parser)
- Pydantic input validation and HTTP security headers
- Dependency auditing via Dependabot (npm, pip, GitHub Actions), dependency review on pull requests, CodeQL, `npm audit`, and `pip-audit` in CI

There is **no interactive login**. Players on the LAN have no authentication of their own: a host that can reach a player can already play, change settings, and reboot it. Resonance does not add that ability. `RESONANCE_API_TOKEN` matters when someone can open Resonance and cannot route to the players (a forward, a tunnel, or another VLAN). For that case, the UI asks for the token in the browser, and `POST /api/v1/session` with the bearer token sets an HttpOnly `resonance_session` cookie (`Secure` over HTTPS, including behind a trusted TLS proxy). The cookie holds an HMAC derived from the token, not the token itself, and changing `RESONANCE_API_TOKEN` invalidates it; the UI then asks for the token again. The token is never built into the UI bundle, and a build with `VITE_API_TOKEN` set fails. Every mutating request must send `X-Resonance-Request: 1`, with or without a token. Tokens are never accepted in the query string. The token also covers `/api/docs` and `/api/openapi.json`. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) **Network exposure**. Otherwise treat bind address and CORS as the exposure boundary. Starting with a non-loopback bind and no token logs an `insecure_bind` warning; tokens are compared as bytes in constant time, so a malformed header is rejected rather than raising.

Details and variable names: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

Local development: `make run` (UI `:8765`, API `:8000`). Everyday single process: `make serve` (UI and API on `:8780`). Ops and health endpoints: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Best Practices for Users

1. Keep dependencies updated
2. Do not commit `.env` files
3. Do not expose Resonance to the internet

## Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix timeline**: Depends on severity
  - Critical: 24–48 hours
  - High: 1 week
  - Medium: 2 weeks
  - Low: Next release

---

*Last updated: 2026-08-14*
