# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Shared fixtures for API route tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest

from app.bluos.client import BluOSClient
from app.config import Settings, get_settings
from app.discovery.service import DiscoveryService
from app.main import create_app
from app.models import PlayerStatus
from app.services.events import EventBus
from app.services.poller import StatusPoller
from app.state import AppState

# What the UI sends: a loopback Host and the header that every state change needs.
API_BASE = "http://127.0.0.1"
API_HEADERS = {"X-Resonance-Request": "1"}


async def app_with_players(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    players: list[PlayerStatus] | None = None,
) -> tuple:
    async def seeded(self: DiscoveryService, *args, **kwargs):
        return self._snapshot

    monkeypatch.setattr(DiscoveryService, "refresh", seeded)

    # Default production spacing is 50ms; tests fire many requests back-to-back.
    # Opt in to 429 behavior by passing api_rate_limit_seconds other than the default.
    default_api_rate = Settings.model_fields["api_rate_limit_seconds"].default
    if settings.api_rate_limit_seconds == default_api_rate:
        settings = settings.model_copy(update={"api_rate_limit_seconds": 0.0})

    def _settings() -> Settings:
        return settings

    get_settings.cache_clear()
    monkeypatch.setattr("app.config.get_settings", _settings)
    monkeypatch.setattr("app.main.get_settings", _settings)
    monkeypatch.setattr("app.middleware.get_settings", _settings)

    app = create_app()
    client = BluOSClient(settings)
    # Fleet volume reads each player's live mute; route tests have no players.
    client.player_is_muted = AsyncMock(return_value=False)  # type: ignore[method-assign]
    events = EventBus()
    discovery = DiscoveryService(settings, client)
    devices = players or [
        PlayerStatus(
            id="player-zone-m",
            ip="192.168.1.20",
            name="Zone M",
            status="online",
            volume=22,
            state="play",
        )
    ]
    discovery._snapshot.devices = devices
    discovery._snapshot.endpoints_by_id = {p.id: p.endpoint for p in devices}
    discovery._snapshot.ids_by_endpoint = {p.endpoint: p.id for p in devices}
    discovery._snapshot.discovered_at = 1.0
    discovery._snapshot.method_used = "mdns"
    poller = StatusPoller(settings, discovery, client, events)
    poller.refresh_one = AsyncMock(return_value=None)  # type: ignore[method-assign]
    poller.running = True
    app.state.app_state = AppState(
        settings=settings,
        client=client,
        discovery=discovery,
        events=events,
        poller=poller,
    )
    return app, client, discovery, poller


async def poll_once(poller: StatusPoller) -> None:
    """One sequential status pass over the fleet. Production runs a watcher per player."""
    for device in list(poller.discovery.snapshot.devices):
        await poller._cycle_device(device)


async def bluetooth_mode(client: BluOSClient, ip: str) -> str | None:
    """The Bluetooth mode label, or None when unsupported or unreachable."""
    info = await client.get_bluetooth_info(ip)
    return info.mode if info is not None and info.supported else None


async def uptime(client: BluOSClient, ip: str) -> str | None:
    """Uptime from the device web UI diagnostics page."""
    parsed = await client.get_diagnostics(ip)
    return None if parsed is None else parsed.get("uptime")


async def wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait for ``predicate`` to hold, checking each loop turn. Fails after ``timeout``."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)
