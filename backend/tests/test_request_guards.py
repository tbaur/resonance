# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Host, origin, request-header, request-id, and session-cookie guards on /api/."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import SESSION_COOKIE
from app.config import Settings, get_settings
from app.middleware import _client_ip, _host_name
from tests.helpers import API_BASE, API_HEADERS, app_with_players


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "discovery_cache_ttl": 0,
        "poll_interval": 60,
        "allow_non_private_ips": True,
        "control_rate_limit_seconds": 0,
        "api_rate_limit_seconds": 0,
        "cors_origins": "http://127.0.0.1:8765",
    }
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


@asynccontextmanager
async def _http(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, base_url: str = API_BASE
) -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.middleware.get_settings", lambda: settings)
    app, client, _, _ = await app_with_players(settings, monkeypatch)
    client.pause = AsyncMock(return_value=True)  # type: ignore[method-assign]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=base_url) as http:
            yield http
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_state_change_without_the_request_header_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign page can POST without a preflight, but cannot add this header."""
    async with _http(_settings(), monkeypatch) as http:
        refused = await http.post("/api/v1/fleet/pause")
        assert refused.status_code == 403
        assert refused.json()["code"] == "missing_request_header"
        allowed = await http.post("/api/v1/fleet/pause", headers=API_HEADERS)
        assert allowed.status_code == 200
        # Reads do not need it.
        assert (await http.get("/api/v1/devices")).status_code == 200


@pytest.mark.asyncio
async def test_cross_site_origin_is_refused_on_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _http(_settings(), monkeypatch) as http:
        foreign = await http.post(
            "/api/v1/fleet/pause",
            headers={**API_HEADERS, "Origin": "https://evil.example.com"},
        )
        assert foreign.status_code == 403
        assert foreign.json()["code"] == "origin_not_allowed"
        same = await http.post(
            "/api/v1/fleet/pause", headers={**API_HEADERS, "Origin": "http://127.0.0.1"}
        )
        assert same.status_code == 200
        configured = await http.post(
            "/api/v1/fleet/pause", headers={**API_HEADERS, "Origin": "http://127.0.0.1:8765"}
        )
        assert configured.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("127.0.0.1:8780", True),
        ("[::1]:8780", True),
        ("192.168.1.5", True),
        ("localhost:8780", True),
        ("player-1.local", True),
        ("music.example.net", True),
        ("rebind.example.com", False),
    ],
)
async def test_host_header_is_checked_without_a_token(
    monkeypatch: pytest.MonkeyPatch, host: str, allowed: bool
) -> None:
    """A DNS-rebinding page reaches the server under its own name, which is refused."""
    settings = _settings(allowed_hosts="music.example.net")
    async with _http(settings, monkeypatch) as http:
        response = await http.get("/api/v1/devices", headers={"Host": host})
        if allowed:
            assert response.status_code == 200
        else:
            assert response.status_code == 400
            assert response.json()["code"] == "host_not_allowed"
        # Health checks answer under any name.
        assert (await http.get("/api/v1/healthz", headers={"Host": host})).status_code == 200


@pytest.mark.asyncio
async def test_host_header_is_not_checked_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a token, a rebinding page has no credential, so any name may reach the API."""
    settings = _settings(api_token="secret-token")
    async with _http(settings, monkeypatch) as http:
        response = await http.get(
            "/api/v1/devices",
            headers={"Host": "music.example.com", "Authorization": "Bearer secret-token"},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_api_docs_need_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(api_token="secret-token", enable_openapi=True)
    async with _http(settings, monkeypatch) as http:
        assert (await http.get("/api/openapi.json")).status_code == 401
        authorized = await http.get(
            "/api/openapi.json", headers={"Authorization": "Bearer secret-token"}
        )
        assert authorized.status_code == 200


@pytest.mark.asyncio
async def test_refusals_carry_request_id_and_security_headers_and_are_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings(api_token="secret-token")
    async with _http(settings, monkeypatch) as http:
        with caplog.at_level(logging.INFO, logger="app.middleware"):
            denied = await http.get("/api/v1/devices", headers={"X-Request-ID": "trace-42"})
    assert denied.status_code == 401
    assert denied.headers["x-request-id"] == "trace-42"
    assert denied.json()["request_id"] == "trace-42"
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in denied.headers
    logged = [r for r in caplog.records if r.getMessage() == "http_request"]
    assert logged and getattr(logged[-1], "http_status", None) == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("supplied", ["x" * 65, "bad id", "line\\nbreak", ""])
async def test_unsafe_request_ids_are_replaced(
    monkeypatch: pytest.MonkeyPatch, supplied: str
) -> None:
    async with _http(_settings(), monkeypatch) as http:
        response = await http.get("/api/v1/healthz", headers={"X-Request-ID": supplied})
    echoed = response.headers["x-request-id"]
    assert echoed != supplied
    assert len(echoed) == 36


def test_forwarded_for_uses_the_address_the_proxy_saw() -> None:
    """The client writes the left of X-Forwarded-For; the proxy appends the real address."""
    scope = {"headers": [(b"x-forwarded-for", b"203.0.113.7, 198.51.100.9")]}
    assert _client_ip(scope, "127.0.0.1", {"127.0.0.1"}) == "198.51.100.9"
    chained = {"headers": [(b"x-forwarded-for", b"203.0.113.7, 198.51.100.9, 10.0.0.2")]}
    assert _client_ip(chained, "127.0.0.1", {"127.0.0.1", "10.0.0.2"}) == "198.51.100.9"


def test_host_name_strips_port_and_brackets() -> None:
    assert _host_name("Example.COM:8780") == "example.com"
    assert _host_name("[::1]:8780") == "::1"
    assert _host_name("::1") == "::1"
    assert _host_name("player-1.local.") == "player-1.local"


def test_rate_path_cap() -> None:
    from app.middleware import _RATE_OVERFLOW_PATH, _RATE_PATHS_PER_CLIENT, RequestContextMiddleware

    async def app(_scope: object, _receive: object, _send: object) -> None:
        return None

    middleware = RequestContextMiddleware(app)  # type: ignore[arg-type]
    paths = [middleware._rate_path("198.51.100.1", f"/p{i}") for i in range(80)]
    assert paths[:_RATE_PATHS_PER_CLIENT] == [f"/p{i}" for i in range(_RATE_PATHS_PER_CLIENT)]
    assert set(paths[_RATE_PATHS_PER_CLIENT:]) == {_RATE_OVERFLOW_PATH}
    # A path seen before keeps its own bucket.
    assert middleware._rate_path("198.51.100.1", "/p3") == "/p3"
    # Another client has its own allowance.
    assert middleware._rate_path("198.51.100.2", "/p70") == "/p70"


@pytest.mark.asyncio
async def test_session_accepts_a_non_ascii_token(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "sésame-token"
    settings = _settings(api_token=token)
    async with _http(settings, monkeypatch) as http:
        # httpx sends str headers as ASCII only, so pass the UTF-8 bytes directly.
        response = await http.post(
            "/api/v1/session",
            headers=[(b"authorization", b"Bearer " + token.encode()), *_raw(API_HEADERS)],
        )
    assert response.status_code == 204
    assert SESSION_COOKIE in response.cookies


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trusted", "proto", "secure"),
    [("127.0.0.1", "https", True), ("", "https", False), ("127.0.0.1", "http", False)],
)
async def test_session_cookie_is_secure_behind_a_trusted_tls_proxy(
    monkeypatch: pytest.MonkeyPatch, trusted: str, proto: str, secure: bool
) -> None:
    settings = _settings(api_token="secret-token", trusted_proxies=trusted)
    async with _http(settings, monkeypatch) as http:
        response = await http.post(
            "/api/v1/session",
            headers={
                **API_HEADERS,
                "Authorization": "Bearer secret-token",
                "X-Forwarded-Proto": proto,
            },
        )
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert ("secure" in cookie) is secure


def _raw(headers: dict[str, str]) -> list[tuple[bytes, bytes]]:
    return [(key.lower().encode(), value.encode()) for key, value in headers.items()]
