# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Who may join whom, legacy /Sync on CI zones, and Break all when one group fails."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.bluos.client import BluOSClient
from app.config import Settings, get_settings
from app.models import PlayerStatus, SyncRole
from tests.helpers import API_BASE, API_HEADERS, app_with_players


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(
        discovery_cache_ttl=0,
        poll_interval=60,
        allow_non_private_ips=True,
        control_rate_limit_seconds=0,
    )


def _rooms() -> list[PlayerStatus]:
    return [
        PlayerStatus(
            id="lead",
            ip="192.168.1.20",
            name="Zone One",
            status="online",
            sync_role=SyncRole.PRIMARY,
            slaves=["192.168.1.21:11000"],
        ),
        PlayerStatus(
            id="follower",
            ip="192.168.1.21",
            name="Zone Two",
            status="online",
            sync_role=SyncRole.SYNCED,
            master="192.168.1.20:11000",
        ),
        PlayerStatus(id="free", ip="192.168.1.22", name="Zone Three", status="online"),
        PlayerStatus(id="free-2", ip="192.168.1.23", name="Zone Four", status="online"),
    ]


@pytest.mark.parametrize(
    ("master_id", "slave_id", "status", "code"),
    [
        ("follower", "free", 409, "master_is_follower"),
        ("free", "follower", 409, "slave_already_grouped"),
        ("free", "lead", 409, "slave_already_grouped"),
        ("lead", "free", 204, None),
        ("free", "free-2", 204, None),
    ],
)
@pytest.mark.asyncio
async def test_sync_add_checks_both_rooms(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    master_id: str,
    slave_id: str,
    status: int,
    code: str | None,
) -> None:
    app, client, _, _ = await app_with_players(settings, monkeypatch, players=_rooms())
    client.add_sync_slave = AsyncMock(return_value=True)  # type: ignore[method-assign]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=API_BASE, headers=API_HEADERS
    ) as http:
        response = await http.post(
            "/api/v1/sync/add", json={"master_id": master_id, "slave_id": slave_id}
        )
    assert response.status_code == status
    if code is not None:
        assert response.json()["code"] == code
        client.add_sync_slave.assert_not_awaited()
    await client.aclose()


@pytest.mark.asyncio
async def test_sync_add_failure_names_the_kind(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, _, poller = await app_with_players(settings, monkeypatch, players=_rooms())
    with respx.mock:
        respx.get(url__regex=r"http://192\.168\.1\.22:11000/AddSlave.*").mock(
            return_value=httpx.Response(200, content=b"<error>busy</error>")
        )
        respx.get(url__regex=r"http://192\.168\.1\.22:11000/Sync\?.*").mock(
            return_value=httpx.Response(200, content=b"<error>busy</error>")
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=API_BASE, headers=API_HEADERS
        ) as http:
            response = await http.post(
                "/api/v1/sync/add", json={"master_id": "free", "slave_id": "free-2"}
            )
    assert response.status_code == 502
    assert poller.last_control_failure_kind == "bluos_error"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_legacy_sync_is_not_used_for_a_secondary_zone(settings: Settings) -> None:
    """/Sync names the follower by address only, which would group its :11000 zone."""
    add = respx.get(url__regex=r"http://192\.168\.1\.20:11000/AddSlave.*").mock(
        return_value=httpx.Response(500)
    )
    legacy = respx.get(url__regex=r"http://192\.168\.1\.20:11000/Sync\?.*").mock(
        return_value=httpx.Response(200, content=b"<sync/>")
    )
    client = BluOSClient(settings)
    try:
        assert await client.add_sync_slave("192.168.1.20", "192.168.1.30:11010") is False
        assert add.called
        assert not legacy.called
        # The primary zone may still use it.
        assert await client.add_sync_slave("192.168.1.20", "192.168.1.30:11000") is True
        assert legacy.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_reparent_stops_after_its_donor_limit(settings: Settings) -> None:
    client = BluOSClient(settings)
    client.add_sync_slave = AsyncMock(return_value=False)  # type: ignore[method-assign]
    donors = [f"192.168.1.{40 + index}:11000" for index in range(6)]
    try:
        assert await client._ungroup_via_reparent("192.168.1.31:11000", donors) is False
        assert client.add_sync_slave.await_count == client._reparent_max_donors
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_break_all_keeps_going_when_one_group_cannot_be_resolved(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A group whose address is refused fails alone; the others still break and stop."""
    rooms = [
        *_rooms(),
        PlayerStatus(
            id="far-lead",
            ip="8.8.8.8",
            name="Zone Five",
            status="online",
            sync_role=SyncRole.PRIMARY,
            slaves=["192.168.1.23:11000"],
        ),
    ]
    rooms[3] = rooms[3].model_copy(update={"sync_role": SyncRole.SYNCED, "master": "8.8.8.8:11000"})
    strict = settings.model_copy(update={"allow_non_private_ips": False})
    app, client, _, _ = await app_with_players(strict, monkeypatch, players=rooms)
    client.remove_sync_slave = AsyncMock(return_value=True)  # type: ignore[method-assign]
    client.stop = AsyncMock(return_value=True)  # type: ignore[method-assign]
    client.get_player_status = AsyncMock(  # type: ignore[method-assign]
        return_value=rooms[0].model_copy(update={"slaves": []})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=API_BASE, headers=API_HEADERS
    ) as http:
        response = await http.post("/api/v1/sync/break")
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert {r["device_id"]: r["ok"] for r in body["results"]} == {
        "follower": True,
        "free-2": False,
    }
    stopped = {call.args[0] for call in client.stop.await_args_list}
    assert "192.168.1.21:11000" in stopped
    await client.aclose()


@pytest.mark.asyncio
async def test_an_unconfirmed_sync_change_logs_failed_not_an_empty_kind(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RemoveSlave answered OK but the follower never left: the last call was a success."""
    from app.bluos.result import CallResult, note_control_result

    app, client, _, poller = await app_with_players(settings, monkeypatch, players=_rooms())

    async def accepted_but_unconfirmed(*_args: object, **_kwargs: object) -> bool:
        note_control_result(CallResult.success(b"<removeSlave/>"))
        return False

    client.remove_sync_slave = accepted_but_unconfirmed  # type: ignore[method-assign]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=API_BASE, headers=API_HEADERS
    ) as http:
        response = await http.post(
            "/api/v1/sync/remove", json={"master_id": "lead", "slave_id": "follower"}
        )
    assert response.status_code == 502
    assert poller.last_control_failure_kind == "failed"
    await client.aclose()
