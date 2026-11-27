# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Discovery refresh, the live device snapshot, and grace-period MAC checks."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from app.bluos.client import BluOSClient
from app.config import Settings, get_settings
from app.discovery.lsdp import LSDPDevice
from app.discovery.service import DiscoveredEndpoint, DiscoveryService, DiscoverySnapshot
from app.models import PlayerStatus


@pytest.mark.asyncio
async def test_control_devices_is_the_live_snapshot() -> None:
    settings = Settings(allow_non_private_ips=True, discovery_cache_ttl=0)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    online = PlayerStatus(id="a", ip="192.168.1.10", name="A", status="online")
    offline = PlayerStatus(id="b", ip="192.168.1.11", name="B", status="offline")
    service._snapshot.devices = [online, offline]
    assert service.control_devices() == [online]
    assert service.control_devices(["a"]) == [online]
    assert service.control_devices(["b"]) == []
    assert service.control_devices() is not service._snapshot.devices
    await client.aclose()


@pytest.mark.asyncio
async def test_discovery_enrich_uses_client(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(allow_non_private_ips=True, discovery_cache_ttl=0)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)

    async def fake_endpoints(self: DiscoveryService):
        return [DiscoveredEndpoint(ip="192.168.1.20", node_id="n1")], "mdns"

    async def fake_status(target: str, device_id: str | None = None, node_id: str = ""):
        host = target.split(":")[0]
        port = int(target.split(":")[1]) if ":" in target else 11000
        return PlayerStatus(
            id=device_id or "player-x",
            ip=host,
            port=port,
            name="Zone M",
            status="online",
        )

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", fake_endpoints)
    client.get_player_status = AsyncMock(side_effect=fake_status)  # type: ignore[method-assign]

    snapshot = await service.refresh()
    assert len(snapshot.devices) == 1
    assert snapshot.devices[0].name == "Zone M"
    assert service.is_known_id(snapshot.devices[0].id)
    await client.aclose()


@pytest.mark.asyncio
async def test_refresh_keeps_live_player_when_enrich_would_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(allow_non_private_ips=True, discovery_cache_ttl=0)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    live = PlayerStatus(
        id="player-zone-m",
        ip="192.168.1.20",
        name="Zone M",
        status="online",
        volume=40,
        track="Current",
    )
    service._snapshot.devices = [live]
    service._snapshot.endpoints_by_id = {live.id: live.endpoint}
    service._snapshot.ids_by_endpoint = {live.endpoint: live.id}
    service._snapshot.discovered_at = 1.0

    async def fake_endpoints(self: DiscoveryService):
        return [DiscoveredEndpoint(ip="192.168.1.20", port=11000)], "mdns"

    async def fake_status(*_args: object, **_kwargs: object) -> PlayerStatus:
        raise AssertionError("live players are not re-enriched")

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", fake_endpoints)
    client.get_player_status = AsyncMock(side_effect=fake_status)  # type: ignore[method-assign]

    snapshot = await service.refresh()
    assert snapshot.devices[0].volume == 40
    assert snapshot.devices[0].track == "Current"
    assert client.get_player_status.await_count == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_refresh_keeps_poll_that_lands_during_enrich(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poll stored while a new room is being enriched wins over the copy seen before."""
    settings = Settings(allow_non_private_ips=True, discovery_cache_ttl=0)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    known = PlayerStatus(id="n1", ip="192.168.1.20", name="Zone L", status="online", volume=1)
    service._snapshot.devices = [known]
    service._snapshot.endpoints_by_id = {known.id: known.endpoint}
    service._snapshot.ids_by_endpoint = {known.endpoint: known.id}

    async def fake_endpoints(self: DiscoveryService):
        return [
            DiscoveredEndpoint(ip="192.168.1.20", port=11000, node_id="n1"),
            DiscoveredEndpoint(ip="192.168.1.21", port=11000, node_id="n2"),
        ], "mdns"

    async def fake_status(target: str, device_id: str | None = None, node_id: str = ""):
        # The poller publishes a newer volume for the known room meanwhile.
        await service.update_device(known.model_copy(update={"volume": 7}))
        host = target.split(":")[0]
        return PlayerStatus(id=device_id or "n2", ip=host, name="Zone R", status="online")

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", fake_endpoints)
    client.get_player_status = AsyncMock(side_effect=fake_status)  # type: ignore[method-assign]

    snapshot = await service.refresh()
    by_id = {device.id: device for device in snapshot.devices}
    assert set(by_id) == {"n1", "n2"}
    assert by_id["n1"].volume == 7
    await client.aclose()


@pytest.mark.asyncio
async def test_refresh_keeps_a_reachable_room_through_missed_browses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One lost announce must not drop a room the poller still reaches."""
    settings = Settings(allow_non_private_ips=True, discovery_cache_ttl=0)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    room = PlayerStatus(id="n1", ip="192.168.1.20", name="Zone L", status="online")
    service._snapshot.devices = [room]
    service._snapshot.endpoints_by_id = {room.id: room.endpoint}
    service._snapshot.ids_by_endpoint = {room.endpoint: room.id}

    async def nothing_found(self: DiscoveryService):
        return [], "mdns"

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", nothing_found)
    for _ in range(2):
        snapshot = await service.refresh()
        assert [device.id for device in snapshot.devices] == ["n1"]
        assert service.is_in_grace("n1") is False
    # The third miss in a row removes it, into the grace period.
    snapshot = await service.refresh()
    assert snapshot.devices == []
    assert service.is_in_grace("n1") is True
    await client.aclose()


@pytest.mark.asyncio
async def test_refresh_drops_an_unreachable_room_on_the_first_missed_browse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(allow_non_private_ips=True, discovery_cache_ttl=0)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    room = PlayerStatus(id="n1", ip="192.168.1.20", name="Zone L", status="online", stale=True)
    service._snapshot.devices = [room]
    service._snapshot.endpoints_by_id = {room.id: room.endpoint}
    service._snapshot.ids_by_endpoint = {room.endpoint: room.id}

    async def nothing_found(self: DiscoveryService):
        return [], "mdns"

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", nothing_found)
    snapshot = await service.refresh()
    assert snapshot.devices == []
    await client.aclose()


@pytest.mark.asyncio
async def test_grace_mac_mismatch_drops_the_address() -> None:
    from app.api.common import _confirm_grace_mac
    from app.api.errors import AppError
    from app.services.events import EventBus
    from app.services.poller import StatusPoller
    from app.state import AppState

    settings = Settings(allow_non_private_ips=True, control_rate_limit_seconds=0)
    client = BluOSClient(settings)
    discovery = DiscoveryService(settings, client)
    device_id = "player-grace"
    discovery._grace_endpoints[device_id] = "192.168.1.20:11000"
    discovery._grace_until[device_id] = time.time() + 60
    discovery._grace_macs[device_id] = "02:00:00:00:00:11"
    client.get_player_status = AsyncMock(  # type: ignore[method-assign]
        return_value=PlayerStatus(
            id=device_id,
            ip="192.168.1.20",
            status="online",
            mac="02:00:00:00:00:FF",
        )
    )
    state = AppState(
        settings=settings,
        client=client,
        discovery=discovery,
        events=EventBus(),
        poller=StatusPoller(settings, discovery, client, EventBus()),
    )
    with pytest.raises(AppError) as caught:
        await _confirm_grace_mac(state, device_id, "192.168.1.20:11000")
    assert caught.value.status_code == 409
    assert discovery.resolve_endpoint(device_id) is None
    await client.aclose()


@pytest.mark.asyncio
async def test_grace_probe_failure_keeps_the_address() -> None:
    from app.api.common import _confirm_grace_mac
    from app.api.errors import AppError
    from app.services.events import EventBus
    from app.services.poller import StatusPoller
    from app.state import AppState

    settings = Settings(allow_non_private_ips=True, control_rate_limit_seconds=0)
    client = BluOSClient(settings)
    discovery = DiscoveryService(settings, client)
    device_id = "player-grace"
    discovery._grace_endpoints[device_id] = "192.168.1.20:11000"
    discovery._grace_until[device_id] = time.time() + 60
    discovery._grace_macs[device_id] = "02:00:00:00:00:11"
    client.get_player_status = AsyncMock(  # type: ignore[method-assign]
        return_value=PlayerStatus(id=device_id, ip="192.168.1.20", status="offline", mac="")
    )
    state = AppState(
        settings=settings,
        client=client,
        discovery=discovery,
        events=EventBus(),
        poller=StatusPoller(settings, discovery, client, EventBus()),
    )
    with pytest.raises(AppError) as caught:
        await _confirm_grace_mac(state, device_id, "192.168.1.20:11000")
    assert caught.value.status_code == 409
    assert discovery.resolve_endpoint(device_id) == "192.168.1.20:11000"
    await client.aclose()


@pytest.mark.asyncio
async def test_grace_online_without_mac_still_allows_the_command() -> None:
    from app.api.common import _confirm_grace_mac
    from app.services.events import EventBus
    from app.services.poller import StatusPoller
    from app.state import AppState

    settings = Settings(allow_non_private_ips=True, control_rate_limit_seconds=0)
    client = BluOSClient(settings)
    discovery = DiscoveryService(settings, client)
    device_id = "player-grace"
    discovery._grace_endpoints[device_id] = "192.168.1.20:11000"
    discovery._grace_until[device_id] = time.time() + 60
    discovery._grace_macs[device_id] = "02:00:00:00:00:11"
    client.get_player_status = AsyncMock(  # type: ignore[method-assign]
        return_value=PlayerStatus(id=device_id, ip="192.168.1.20", status="online", mac="")
    )
    state = AppState(
        settings=settings,
        client=client,
        discovery=discovery,
        events=EventBus(),
        poller=StatusPoller(settings, discovery, client, EventBus()),
    )
    await _confirm_grace_mac(state, device_id, "192.168.1.20:11000")
    assert discovery.resolve_endpoint(device_id) == "192.168.1.20:11000"
    await client.aclose()


@pytest.mark.asyncio
async def test_known_endpoint_accepts_a_followers_master_and_unexpired_grace() -> None:
    settings = Settings(allow_non_private_ips=True)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    service._snapshot.devices = [
        PlayerStatus(
            id="follower",
            ip="192.168.1.21",
            status="online",
            master="192.168.1.55:11000",
            sync_role="synced",
        )
    ]
    assert service.is_known_endpoint("192.168.1.55:11000")
    assert not service.is_known_endpoint("192.168.1.99:11000")
    service._grace_endpoints["old"] = "192.168.1.77:11000"
    service._grace_until["old"] = time.time() - 5
    assert not service.is_known_endpoint("192.168.1.77:11000")
    service._grace_until["old"] = time.time() + 30
    assert service.is_known_endpoint("192.168.1.77:11000")
    await client.aclose()


@pytest.mark.asyncio
async def test_grace_preserves_ip_after_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        allow_non_private_ips=True,
        discovery_cache_ttl=0,
        discovered_grace_ttl=120,
    )
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    device_id = "player-grace"
    service._snapshot.endpoints_by_id = {device_id: "192.168.1.55:11000"}
    service._snapshot.devices = [
        PlayerStatus(id=device_id, ip="192.168.1.55", name="Zone Q", status="online"),
    ]
    service._snapshot.discovered_at = 1.0

    async def empty_refresh(self: DiscoveryService):
        now = __import__("time").time()
        self._grace_until[device_id] = now + settings.discovered_grace_ttl
        self._grace_endpoints[device_id] = "192.168.1.55:11000"
        self._snapshot = DiscoverySnapshot(
            devices=[],
            discovered_at=now,
            method_used="mdns",
            endpoints_by_id={},
            ids_by_endpoint={},
        )
        return self._snapshot

    monkeypatch.setattr(DiscoveryService, "refresh", empty_refresh)
    await service.refresh()
    assert device_id not in service.snapshot.endpoints_by_id
    assert service.is_known_id(device_id)
    assert service.resolve_endpoint(device_id) == "192.168.1.55:11000"
    await client.aclose()


@pytest.mark.asyncio
async def test_empty_fleet_result_counts_as_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bluos.client import BluOSClient
    from app.discovery.service import DiscoveryService

    get_settings.cache_clear()
    settings = Settings(
        allow_non_private_ips=True,
        discovery_cache_ttl=300,
        empty_fleet_rediscovery_seconds=60,
        discovery_method="mdns",
    )
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    calls = {"n": 0}

    async def fake_discover(self: DiscoveryService):
        calls["n"] += 1
        return [], "mdns"

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", fake_discover)
    first = await service.refresh()
    assert first.devices == []
    assert calls["n"] == 1
    # An empty result stays fresh for empty_fleet_rediscovery_seconds, so the
    # poller does not run a browse on every tick.
    assert service.cache_fresh() is True
    assert calls["n"] == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_discovery_cache_grace_and_enrich_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bluos.client import BluOSClient

    settings = Settings(
        allow_non_private_ips=True,
        discovery_cache_ttl=60,
        discovery_method="both",
    )
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)

    async def endpoints(self: DiscoveryService):
        return [DiscoveredEndpoint(ip="192.168.1.20", node_id="n1")], "mdns"

    async def boom(*_a, **_k):
        raise RuntimeError("enrich fail")

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", endpoints)
    client.get_player_status = AsyncMock(side_effect=boom)  # type: ignore[method-assign]

    snap = await service.refresh()
    # Failed SyncStatus probes are dropped (not kept as error players).
    assert snap.devices == []
    assert snap.discovered_at is not None
    # Empty fleets cache for empty_fleet_rediscovery_seconds (avoid discovery storms).
    assert service.cache_fresh() is True

    # A read for a player outside the fleet is not stored: membership comes
    # from discovery, so a late poll cannot add a removed room back.
    extra = PlayerStatus(id="extra", ip="192.168.1.30", name="X", status="online")
    assert await service.update_device(extra) is False
    assert not any(d.id == "extra" for d in service.snapshot.devices)

    assert service.get_device("missing") is None
    assert service.is_in_grace("extra") is False
    await client.aclose()


@pytest.mark.asyncio
async def test_discover_endpoints_mdns_lsdp_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bluos.client import BluOSClient

    settings = Settings(allow_non_private_ips=False, discovery_method="both")
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)

    monkeypatch.setattr(
        "app.discovery.service.MDNSDiscovery.discover",
        lambda self: ["192.168.1.10", "8.8.8.8"],
    )
    monkeypatch.setattr(
        "app.discovery.service.LSDPDiscovery.discover",
        lambda self: [
            LSDPDevice(node_id="n10", ip="192.168.1.10", class_id=1),
            LSDPDevice(node_id="n11", ip="192.168.1.11", class_id=1),
        ],
    )

    endpoints, method = await service._discover_endpoints()
    ips = {e.ip for e in endpoints}
    assert ips == {"192.168.1.10", "192.168.1.11"}
    assert "mdns" in method and "lsdp" in method
    # node id merged onto mdns-first endpoint
    assert next(e for e in endpoints if e.ip == "192.168.1.10").node_id == "n10"
    await client.aclose()


@pytest.mark.asyncio
async def test_lsdp_secondary_zone_keeps_announced_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bluos.client import BluOSClient
    from app.discovery.lsdp import CLASS_BLUOS_PLAYER_SECONDARY

    settings = Settings(allow_non_private_ips=False, discovery_method="lsdp")
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    monkeypatch.setattr(
        "app.discovery.service.LSDPDiscovery.discover",
        lambda self: [
            LSDPDevice(node_id="0200000000a1", ip="192.168.1.10", class_id=1, port=None),
            LSDPDevice(
                node_id="0200000000a1",
                ip="192.168.1.10",
                class_id=CLASS_BLUOS_PLAYER_SECONDARY,
                port=11010,
            ),
        ],
    )

    endpoints, _method = await service._discover_endpoints()
    assert {e.endpoint: e.node_id for e in endpoints} == {
        "192.168.1.10:11000": "0200000000a1",
        "192.168.1.10:11010": "0200000000a1",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_a_player_found_at_a_new_address_is_not_kept_at_the_old_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DHCP moved the player: one row at the new address, not two."""
    settings = Settings(allow_non_private_ips=True, discovery_cache_ttl=0)
    client = BluOSClient(settings)
    service = DiscoveryService(settings, client)
    old = PlayerStatus(
        id="player-old", ip="192.168.1.20", name="Zone L", status="online", mac="02:00:00:00:00:21"
    )
    service._snapshot.devices = [old]
    service._snapshot.endpoints_by_id = {old.id: old.endpoint}
    service._snapshot.ids_by_endpoint = {old.endpoint: old.id}

    async def moved(self: DiscoveryService):
        return [DiscoveredEndpoint(ip="192.168.1.40")], "mdns"

    async def status(target: str, device_id: str | None = None, node_id: str = ""):
        return PlayerStatus(
            id=device_id or "player-new",
            ip=target.split(":")[0],
            name="Zone L",
            status="online",
            mac="02:00:00:00:00:21",
        )

    monkeypatch.setattr(DiscoveryService, "_discover_endpoints", moved)
    client.get_player_status = AsyncMock(side_effect=status)  # type: ignore[method-assign]

    snapshot = await service.refresh()
    assert [device.ip for device in snapshot.devices] == ["192.168.1.40"]
    await client.aclose()
