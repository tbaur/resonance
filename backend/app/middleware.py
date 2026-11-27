# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""ASGI middleware that must not buffer streaming responses (SSE)."""

from __future__ import annotations

import hmac
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from ipaddress import ip_address
from urllib.parse import unquote_to_bytes, urlsplit

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth import REQUEST_HEADER, SESSION_COOKIE, session_cookie_value
from app.bluos.rate_limit import RateLimiter
from app.config import Settings, get_settings
from app.logging import request_id_var

logger = logging.getLogger(__name__)

# Album art is proxied through /api/v1/devices/{id}/art, so images stay same-origin.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "frame-ancestors 'none'"
)
# FastAPI Swagger UI loads bundle/CSS from jsDelivr and boots with an inline script.
_SWAGGER_CSP = (
    "default-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' data: https: http:; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'"
)
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

# Cheap in-memory GETs (/devices, /sync) overlap on UI mount / Strict Mode;
# 429ing them surfaces "Too many requests" while an earlier load still succeeds.
_EXPENSIVE_GET_PATHS = frozenset({"/api/v1/fleet/upgrades"})
# Methods a cookie may use without the X-Resonance-Request header (no side effects).
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_AUTH_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/healthz",
        "/api/v1/readyz",
        "/api/v1/version",
        "/health",
    }
)
# Everything under /api/ is gated, including /api/docs and /api/openapi.json.
_API_PREFIX = "/api/"
_EVENTS_PATH = "/api/v1/events"
# A client-supplied X-Request-ID is echoed into logs and headers, so keep it short and plain.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# The rate-limit key holds the request path, which the client chooses. Each client
# gets this many distinct paths; later ones share one bucket, so a flood of unique
# paths cannot grow the table or push out other clients' cooldowns.
_RATE_PATHS_PER_CLIENT = 64
_RATE_CLIENTS = 256
_RATE_OVERFLOW_PATH = "*"
# Host names a DNS-rebinding page cannot point at this server.
_LOCAL_HOST_SUFFIXES = (".localhost", ".local")


class RequestContextMiddleware:
    """Attach request IDs, security headers, API guards, rate limits, and access logs.

    FastAPI's ``@app.middleware("http")`` uses BaseHTTPMiddleware, which
    buffers responses and breaks Server-Sent Events. This pure ASGI wrapper
    streams through unchanged.

    Every ``/api/`` request passes these guards, in order:

    - Host: with no API token, the Host header must be an address, a local
      name, or a configured name, so a DNS-rebinding page cannot read the API.
    - Token: with an API token, a bearer token, X-API-Token, or the session
      cookie is required.
    - Cross-site writes: a request with side effects must carry
      ``X-Resonance-Request: 1`` (a browser sends it cross-site only after a
      CORS preflight, which a foreign origin fails) and, when it has an
      Origin header, that origin must be this server or a configured one.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        settings = get_settings()
        self._api_rate = RateLimiter(
            settings.api_rate_limit_seconds,
            max_keys=_RATE_CLIENTS * (_RATE_PATHS_PER_CLIENT + 1),
        )
        self._rate_paths: OrderedDict[str, set[str]] = OrderedDict()
        # Bytes, not str: headers arrive as bytes and hmac.compare_digest raises
        # TypeError on str with non-ASCII characters.
        self._api_token = (settings.api_token or "").strip().encode("utf-8")
        self._session_cookie = session_cookie_value(self._api_token) if self._api_token else b""
        self._trusted_proxies = settings.trusted_proxy_set()
        self._allowed_origins = frozenset(o.rstrip("/") for o in settings.cors_origin_list())
        self._allowed_hosts = _allowed_host_names(settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        peer = (scope.get("client") or ("unknown", 0))[0] or "unknown"

        request_id = _request_id(scope)
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.monotonic()
        status_code = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in _SECURITY_HEADERS.items():
                    headers[name] = value
                headers["Content-Security-Policy"] = _csp_for_path(path)
            await send(message)

        try:
            refusal = await self._refusal(scope, method, path, peer)
            if refusal is not None:
                status, code, message, extra = refusal
                await _send_json(
                    send_with_headers,
                    status,
                    {"error": code, "message": message, "code": code, "request_id": request_id},
                    extra_headers=extra,
                )
                return
            await self.app(scope, receive, send_with_headers)
        finally:
            duration_ms = round((time.monotonic() - started) * 1000, 1)
            if path != _EVENTS_PATH or status_code != 200:
                logger.info(
                    "http_request",
                    extra={
                        "http_method": method,
                        "http_path": path,
                        "http_status": status_code,
                        "duration_ms": duration_ms,
                    },
                )
            request_id_var.reset(token)

    async def _refusal(
        self, scope: Scope, method: str, path: str, peer: str
    ) -> tuple[int, str, str, list[tuple[bytes, bytes]] | None] | None:
        """The error to send instead of running the route, or None to run it."""
        if not path.startswith(_API_PREFIX):
            return None
        exempt = path in _AUTH_EXEMPT_PATHS
        if not self._api_token and not exempt and not self._host_allowed(scope):
            return (
                400,
                "host_not_allowed",
                "Host name is not allowed. Add it to RESONANCE_ALLOWED_HOSTS.",
                None,
            )
        if self._api_token and not exempt:
            if not _authorized(scope, self._api_token, self._session_cookie):
                return 401, "unauthorized", "Valid API token required", None
        if method not in _SAFE_METHODS:
            if _header_raw(scope, REQUEST_HEADER) != b"1":
                return (
                    403,
                    "missing_request_header",
                    "Requests that change state must send X-Resonance-Request: 1",
                    None,
                )
            if not self._origin_allowed(scope):
                return 403, "origin_not_allowed", "Cross-site request refused", None

        rate_limit = (method == "POST" and path != _EVENTS_PATH) or (
            method == "GET" and path in _EXPENSIVE_GET_PATHS
        )
        if rate_limit:
            client_host = _client_ip(scope, peer, self._trusted_proxies)
            bucket = f"{client_host}:{method}:{self._rate_path(client_host, path)}"
            if not await self._api_rate.acquire(bucket):
                return 429, "rate_limited", "Too many requests", [(b"retry-after", b"1")]
        return None

    def _rate_path(self, client: str, path: str) -> str:
        """``path``, or a shared bucket once ``client`` has used its share of paths."""
        paths = self._rate_paths.get(client)
        if paths is None:
            paths = set()
            self._rate_paths[client] = paths
            while len(self._rate_paths) > _RATE_CLIENTS:
                self._rate_paths.popitem(last=False)
        else:
            self._rate_paths.move_to_end(client)
        if path in paths:
            return path
        if len(paths) >= _RATE_PATHS_PER_CLIENT:
            return _RATE_OVERFLOW_PATH
        paths.add(path)
        return path

    def _host_allowed(self, scope: Scope) -> bool:
        host = _host_name(_header_value(scope, b"host") or "")
        if not host:
            return False
        if host in self._allowed_hosts or host == "localhost":
            return True
        if host.endswith(_LOCAL_HOST_SUFFIXES):
            return True
        try:
            ip_address(host)
        except ValueError:
            return False
        return True

    def _origin_allowed(self, scope: Scope) -> bool:
        origin = _header_value(scope, b"origin")
        if origin is None:
            # Not a browser cross-site request: curl, scripts, same-origin GET-style calls.
            return True
        origin = origin.strip().rstrip("/")
        if origin in self._allowed_origins:
            return True
        host = (_header_value(scope, b"host") or "").strip().lower()
        parts = urlsplit(origin)
        return bool(host) and parts.scheme in {"http", "https"} and parts.netloc.lower() == host


def _allowed_host_names(settings: Settings) -> frozenset[str]:
    names = {settings.host.lower()}
    names.update(name.lower() for name in settings.allowed_host_set())
    for origin in settings.cors_origin_list():
        hostname = urlsplit(origin).hostname
        if hostname:
            names.add(hostname.lower())
    return frozenset(names)


def _host_name(host: str) -> str:
    """The name in a Host header, without the port or IPv6 brackets."""
    value = host.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else ""
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value.rstrip(".")


def _request_id(scope: Scope) -> str:
    supplied = _header_value(scope, b"x-request-id")
    if supplied and _REQUEST_ID_RE.fullmatch(supplied):
        return supplied
    return str(uuid.uuid4())


def _csp_for_path(path: str) -> str:
    if path == "/api/docs" or path.startswith("/api/docs/"):
        return _SWAGGER_CSP
    return _DEFAULT_CSP


def _header_raw(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return bytes(value)
    return None


def _header_value(scope: Scope, name: bytes) -> str | None:
    raw = _header_raw(scope, name)
    return None if raw is None else raw.decode("latin-1")


def _client_ip(scope: Scope, peer: str, trusted_proxies: set[str]) -> str:
    """The address that reached the first trusted proxy.

    Each proxy appends the address it heard from, so the client can write any
    value at the left of X-Forwarded-For. Walk from the right and stop at the
    first address that is not one of our proxies.
    """
    if peer not in trusted_proxies:
        return peer
    forwarded = _header_value(scope, b"x-forwarded-for")
    if not forwarded:
        return peer
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if hop not in trusted_proxies:
            return hop
    return hops[0] if hops else peer


def _cookie_value(scope: Scope, name: bytes) -> bytes | None:
    raw = _header_raw(scope, b"cookie")
    if not raw:
        return None
    for part in raw.split(b";"):
        key, sep, value = part.strip().partition(b"=")
        if sep and key == name:
            return unquote_to_bytes(value)
    return None


def _authorized(scope: Scope, token: bytes, session_cookie: bytes) -> bool:
    """Compare credentials as bytes so a non-ASCII value cannot raise."""
    auth = _header_raw(scope, b"authorization")
    if auth and auth[:7].lower() == b"bearer ":
        if hmac.compare_digest(auth[7:].strip(), token):
            return True
    header_token = _header_raw(scope, b"x-api-token")
    if header_token and hmac.compare_digest(header_token.strip(), token):
        return True
    cookie = _cookie_value(scope, SESSION_COOKIE.encode("ascii"))
    if cookie is not None and hmac.compare_digest(cookie, session_cookie):
        # A foreign site can send the cookie. It cannot set this header.
        if scope.get("method") not in _SAFE_METHODS:
            return _header_raw(scope, REQUEST_HEADER) == b"1"
        return True
    return False


async def _send_json(
    send: Send,
    status: int,
    body: dict[str, str],
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    payload = json.dumps(body).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": payload})
