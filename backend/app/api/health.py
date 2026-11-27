# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Health, readiness, version, and companion app endpoints."""

from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Request, Response

from app import __version__
from app.api.common import StateDep
from app.api.errors import AppError
from app.auth import SESSION_COOKIE, session_cookie_value
from app.config import Settings
from app.models import AppLinks, HealthResponse, VersionInfo

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz(state: StateDep) -> HealthResponse:
    poller_running = state.poller.running and not state.poller.is_wedged()
    return HealthResponse(
        status="ok" if poller_running else "degraded",
        details={"poller_running": poller_running},
    )


@router.get("/readyz", response_model=HealthResponse)
async def readyz(state: StateDep) -> HealthResponse:
    if not state.poller.running or state.poller.is_wedged():
        raise AppError(503, "not_ready", "Status poller is not running")
    devices = state.discovery.snapshot.devices
    stale_count, slow_poll_count = state.poller.presence_counts()
    discovered_at = state.discovery.snapshot.discovered_at
    age = None if discovered_at is None else round(time.time() - discovered_at, 1)
    return HealthResponse(
        status="ok",
        details={
            "device_count": len(devices),
            "last_poll_at": state.poller.last_poll_at,
            # Class name only. /readyz is auth-exempt, so no exception text,
            # names, or addresses. The player LAN already announces those.
            "last_error_kind": state.poller.last_error_kind,
            "last_control_failure_kind": state.poller.last_control_failure_kind,
            "discovery_age_seconds": age,
            "stale_count": stale_count,
            "slow_poll_count": slow_poll_count,
            "sse_dropped_events": state.events.dropped_events,
            "sse_subscribers": state.events.subscriber_count,
        },
    )


@router.get("/version", response_model=VersionInfo)
async def version() -> VersionInfo:
    return VersionInfo(version=__version__)


@router.get("/links", response_model=AppLinks)
async def links(state: StateDep) -> AppLinks:
    return AppLinks(valence_url=state.settings.valence_url)


@router.post("/session", status_code=204)
async def open_session(request: Request) -> Response:
    """Trade a bearer token for an HttpOnly session cookie.

    The cookie is for a Resonance server reached from a network that cannot
    reach the players. On the player LAN the players are already open.
    """
    # Raw header bytes, the same way the middleware compares them. Decoding as
    # latin-1 and re-encoding as UTF-8 would reject a correct non-ASCII token.
    header = next(
        (value for key, value in request.scope.get("headers") or [] if key == b"authorization"),
        b"",
    )
    token = header[7:].strip() if header[:7].lower() == b"bearer " else b""
    configured = ""
    app_state = getattr(request.app.state, "app_state", None)
    if app_state is not None:
        configured = app_state.settings.api_token.strip()
    expected = configured.encode("utf-8")
    if not expected or not hmac.compare_digest(token, expected):
        raise AppError(401, "unauthorized", "Valid API token required")
    response = Response(status_code=204)
    response.set_cookie(
        SESSION_COOKIE,
        session_cookie_value(expected).decode("ascii"),
        httponly=True,
        samesite="strict",
        secure=_is_https(request, app_state.settings if app_state is not None else None),
        path="/",
    )
    return response


def _is_https(request: Request, settings: Settings | None) -> bool:
    """True when the browser reached us over HTTPS, directly or through a trusted proxy."""
    if request.url.scheme == "https":
        return True
    if settings is None:
        return False
    peer = request.client.host if request.client else ""
    if peer not in settings.trusted_proxy_set():
        return False
    proto = request.headers.get("x-forwarded-proto", "")
    # A chain of proxies appends; the right-most value came from the nearest one.
    nearest = proto.split(",")[-1].strip().lower()
    return nearest == "https"
