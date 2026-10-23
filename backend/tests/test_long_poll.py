"""Status etag long-poll (Custom Integration API v1.7)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx

from app.bluos.client import BluOSClient
from app.config import Settings
from app.discovery.service import DiscoveryService
from app.models import PlayerStatus, SyncRole
from app.services.events import EventBus
from app.services.poller import StatusPoller
from tests.fixtures.xml_samples import (
    STATUS,
    STATUS_GROUP_VOLUME,
    STATUS_MUTED,
    SYNC_STATUS,
    SYNC_STATUS_MUTED,
    SYNC_STATUS_SLAVE,
)

STATUS_SKIP = STATUS.replace(b'etag="2"', b'etag="3"').replace(b"Song Title", b"Next Song")
STATUS_SYNC_CHANGED = STATUS.replace(b'etag="2"', b'etag="4"').replace(
    b"<syncStat>ss-1</syncStat>", b"<syncStat>ss-2</syncStat>"
)
SYNC_AFTER_VOLUME = SYNC_STATUS.replace(b'volume="22"', b'volume="31"').replace(
    b'syncStat="ss-1"', b'syncStat="ss-2"'
)
SLAVE_STATUS = STATUS_GROUP_VOLUME.replace(
    b"<status etag=\"g1\">", b'<status etag="g1">\n  <syncStat>ss-slave</syncStat>'
)
SLAVE_SYNC = SYNC_STATUS_SLAVE.replace(b'etag="252"', b'etag="252" syncStat="ss-slave"')


@pytest.fixture
def settings() -> Settings:
    return Settings(
        allow_non_private_ips=True,
        device_http_timeout=1.0,
        control_rate_limit_seconds=0,
        long_poll_gap_seconds=0,
        status_long_poll_seconds=10,
        long_poll_read_slack_seconds=1,
        max_concurrent_device_calls=1,
        poll_interval=1,
        circuit_failure_threshold=5,
    )


def _poller(settings: Settings, client: BluOSClient) -> tuple[StatusPoller, DiscoveryService]:
    discovery = DiscoveryService(settings, client)
    player = PlayerStatus(id="p1", ip="192.168.1.20", name="K", status="online")
    discovery._snapshot.devices = [player]
    discovery._snapshot.ips_by_id = {"p1": "192.168.1.20:11000"}
    discovery._snapshot.discovered_at = time.time()
    return StatusPoller(settings, discovery, client, EventBus()), discovery


@pytest.mark.asyncio
@respx.mock
async def test_long_poll_uses_timeout_and_etag(settings: Settings) -> None:
    status_route = respx.get(url__regex=r"http://192\.168\.1\.20:11000/Status.*").mock(
        return_value=httpx.Response(200, content=STATUS)
    )
    sync_route = respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=SYNC_STATUS)
    )
    client = BluOSClient(settings)
    try:
        first = await client.load_player("192.168.1.20", device_id="p1")
        assert first.player.track == "Song Title"
        assert first.status_etag == "2"
        assert first.sync_stat == "ss-1"
        assert sync_route.call_count == 1

        second = await client.load_player(
            "192.168.1.20",
            device_id="p1",
            status_etag=first.status_etag,
            sync_stat=first.sync_stat,
            previous=first.player,
            long_poll_seconds=10,
        )
        assert second.player.track == "Song Title"
        assert sync_route.call_count == 1
        long_poll = status_route.calls.last.request
        assert long_poll.url.params["timeout"] == "10"
        assert long_poll.url.params["etag"] == "2"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_syncstat_change_refetches_syncstatus(settings: Settings) -> None:
    respx.get(url__regex=r"http://192\.168\.1\.20:11000/Status.*").mock(
        return_value=httpx.Response(200, content=STATUS_SYNC_CHANGED)
    )
    sync_route = respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=SYNC_AFTER_VOLUME)
    )
    previous = PlayerStatus(
        id="p1",
        ip="192.168.1.20",
        name="Zone M",
        status="online",
        volume=22,
        track="Song Title",
    )
    client = BluOSClient(settings)
    try:
        snap = await client.load_player(
            "192.168.1.20",
            device_id="p1",
            status_etag="2",
            sync_stat="ss-1",
            previous=previous,
            long_poll_seconds=10,
        )
        assert sync_route.call_count == 1
        assert snap.sync_stat == "ss-2"
        assert snap.player.volume == 31
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_status_only_poll_picks_up_mute_and_unmute_level(settings: Settings) -> None:
    respx.get(url__regex=r"http://192\.168\.1\.30:11010/Status.*").mock(
        return_value=httpx.Response(200, content=STATUS_MUTED)
    )
    sync_route = respx.get("http://192.168.1.30:11010/SyncStatus").mock(
        return_value=httpx.Response(200, content=SYNC_STATUS_MUTED)
    )
    previous = PlayerStatus(
        id="p1", ip="192.168.1.30", port=11010, name="Zone One", status="online", volume=50
    )
    client = BluOSClient(settings)
    try:
        snap = await client.load_player(
            "192.168.1.30:11010",
            device_id="p1",
            status_etag="e0",
            sync_stat="281",
            previous=previous,
            long_poll_seconds=10,
        )
        assert sync_route.call_count == 0
        assert snap.player.muted is True
        assert snap.player.volume == 0
        assert snap.player.mute_volume == 50
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_synced_follower_keeps_syncstatus_volume_on_status_only(
    settings: Settings,
) -> None:
    respx.get(url__regex=r"http://192\.168\.1\.80:11000/Status.*").mock(
        return_value=httpx.Response(200, content=SLAVE_STATUS)
    )
    sync_route = respx.get("http://192.168.1.80:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=SLAVE_SYNC)
    )
    previous = PlayerStatus(
        id="p1",
        ip="192.168.1.80",
        name="Zone C",
        status="online",
        volume=64,
        sync_role=SyncRole.SYNCED,
        master="192.168.1.74:11000",
        state="stream",
        track="Old",
    )
    client = BluOSClient(settings)
    try:
        snap = await client.load_player(
            "192.168.1.80",
            device_id="p1",
            status_etag="g1",
            sync_stat="ss-slave",
            previous=previous,
            long_poll_seconds=10,
        )
        assert sync_route.call_count == 0
        assert snap.player.volume == 64
        assert snap.player.track == "Track"
        assert snap.player.sync_role == SyncRole.SYNCED
    finally:
        await client.aclose()


FOLLOWER = "http://192.168.1.30:11010"
FOLLOWER_SYNC = SYNC_STATUS_MUTED.replace(b'volume="0" muteVolume="50"', b'volume="50"').replace(
    b'etag="281" syncStat="281"', b'etag="280" syncStat="280"'
).replace(b"></SyncStatus>", b'><master port="11000">192.168.1.74</master></SyncStatus>')
FOLLOWER_SYNC_MUTED = SYNC_STATUS_MUTED.replace(
    b"></SyncStatus>", b'><master port="11000">192.168.1.74</master></SyncStatus>'
)
# Seen live: a follower's /Status shows the group and its lead's syncStat, so it
# stays the same when the follower alone is muted.
FOLLOWER_STATUS = STATUS_GROUP_VOLUME.replace(
    b'<status etag="g1">', b'<status etag="g1">\n  <syncStat>lead-1</syncStat>'
)


def _follower(volume: int = 50) -> PlayerStatus:
    return PlayerStatus(
        id="p1",
        ip="192.168.1.30",
        port=11010,
        name="Zone One",
        status="online",
        volume=volume,
        sync_role=SyncRole.SYNCED,
        master="192.168.1.74:11000",
    )


def _route(
    path: str, *, held: bytes | None, now: bytes, waiting: asyncio.Event | None = None
) -> respx.Route:
    """A route whose long-poll answers ``held`` at once, or never when ``held`` is None."""

    async def answer(request: httpx.Request) -> httpx.Response:
        if "timeout" not in request.url.params:
            return httpx.Response(200, content=now)
        if held is None:
            if waiting is not None:
                waiting.set()
            await asyncio.sleep(30)
        return httpx.Response(200, content=held or now)

    return respx.get(url__regex=rf"{FOLLOWER}{path}.*").mock(side_effect=answer)


@pytest.mark.asyncio
@respx.mock
async def test_a_follower_muted_on_its_own_shows_muted_at_once(settings: Settings) -> None:
    status_route = _route("/Status", held=None, now=FOLLOWER_STATUS)
    sync_route = _route("/SyncStatus", held=FOLLOWER_SYNC_MUTED, now=FOLLOWER_SYNC_MUTED)
    client = BluOSClient(settings)
    try:
        snap = await asyncio.wait_for(
            client.load_player(
                "192.168.1.30:11010",
                device_id="p1",
                status_etag="g1",
                sync_stat="lead-1",
                sync_etag="280",
                previous=_follower(),
                long_poll_seconds=10,
            ),
            timeout=3,
        )
        assert (snap.player.muted, snap.player.volume, snap.player.mute_volume) == (True, 0, 50)
        assert snap.player.sync_role == SyncRole.SYNCED
        assert snap.sync_etag == "281"
        assert sync_route.calls.last.request.url.params["etag"] == "280"
        assert "timeout" not in status_route.calls.last.request.url.params
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_a_syncstatus_answer_with_no_change_keeps_waiting_on_status(
    settings: Settings,
) -> None:
    status_route = _route("/Status", held=STATUS_SKIP, now=STATUS)
    _route("/SyncStatus", held=FOLLOWER_SYNC, now=FOLLOWER_SYNC)
    client = BluOSClient(settings)
    try:
        snap = await client.load_player(
            "192.168.1.30:11010",
            device_id="p1",
            status_etag="2",
            sync_stat="ss-1",
            sync_etag="280",
            previous=_follower(),
            long_poll_seconds=10,
        )
        assert snap.player.track == "Next Song"
        assert status_route.call_count == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_cancelling_a_load_releases_both_holds(settings: Settings) -> None:
    status_waiting, sync_waiting = asyncio.Event(), asyncio.Event()
    _route("/Status", held=None, now=FOLLOWER_STATUS, waiting=status_waiting)
    _route("/SyncStatus", held=None, now=FOLLOWER_SYNC, waiting=sync_waiting)
    client = BluOSClient(settings)
    try:
        before = asyncio.all_tasks()
        load = asyncio.create_task(
            client.load_player(
                "192.168.1.30:11010",
                device_id="p1",
                status_etag="g1",
                sync_stat="lead-1",
                sync_etag="280",
                previous=_follower(),
                long_poll_seconds=10,
            )
        )
        await asyncio.wait_for(asyncio.gather(status_waiting.wait(), sync_waiting.wait()), 3)
        load.cancel()
        with pytest.raises(asyncio.CancelledError):
            await load
        assert asyncio.all_tasks() == before
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_skip_not_blocked_by_held_status_long_poll(settings: Settings) -> None:
    held = asyncio.Event()
    release = asyncio.Event()

    async def delayed_status(_request: httpx.Request) -> httpx.Response:
        held.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return httpx.Response(200, content=STATUS)

    respx.get(url__regex=r"http://192\.168\.1\.20:11000/Status.*").mock(side_effect=delayed_status)
    respx.get("http://192.168.1.20:11000/Skip").mock(
        return_value=httpx.Response(200, content=b"<ok/>")
    )
    respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=SYNC_STATUS)
    )
    previous = PlayerStatus(id="p1", ip="192.168.1.20", name="K", status="online")
    client = BluOSClient(settings)
    try:
        task = asyncio.create_task(
            client.load_player(
                "192.168.1.20",
                device_id="p1",
                status_etag="2",
                sync_stat="ss-1",
                previous=previous,
                long_poll_seconds=10,
            )
        )
        await asyncio.wait_for(held.wait(), timeout=2)
        assert await asyncio.wait_for(client.skip("192.168.1.20"), timeout=2)
        release.set()
        snap = await asyncio.wait_for(task, timeout=2)
        assert snap.player.status == "online"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_poller_second_cycle_long_polls_status(settings: Settings) -> None:
    status_route = respx.get(url__regex=r"http://192\.168\.1\.20:11000/Status.*").mock(
        side_effect=[
            httpx.Response(200, content=STATUS),
            httpx.Response(200, content=STATUS_SKIP),
        ]
    )
    sync_route = respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=SYNC_STATUS)
    )
    client = BluOSClient(settings)
    poller, discovery = _poller(settings, client)
    try:
        await poller._poll_once()
        assert discovery.snapshot.devices[0].track == "Song Title"
        assert poller._status_etags["p1"] == "2"
        await poller._poll_once()
        assert discovery.snapshot.devices[0].track == "Next Song"
        assert poller._status_etags["p1"] == "3"
        assert status_route.calls[1].request.url.params["etag"] == "2"
        assert status_route.calls[1].request.url.params["timeout"] == "10"
        assert poller._sync_etags["p1"] == "1"
        held_sync = sync_route.calls.last.request.url.params
        assert (held_sync["etag"], held_sync["timeout"]) == ("1", "10")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_poller_rereads_syncstatus_when_syncstat_never_moves(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A follower's /Status carries its lead's syncStat, so joining a group can
    leave that value unchanged. The poller must still notice the new master."""
    respx.get(url__regex=r"http://192\.168\.1\.20:11000/Status.*").mock(
        return_value=httpx.Response(200, content=STATUS)
    )
    standalone = (
        b'<SyncStatus name="K" brand="Bluesound" volume="22" etag="7" syncStat="own-7">'
        b"</SyncStatus>"
    )
    joined = standalone.replace(
        b"</SyncStatus>", b'<master port="11000">192.168.1.30</master></SyncStatus>'
    )
    reads: list[bytes] = [standalone, joined]
    plain_reads = 0

    def sync_answer(request: httpx.Request) -> httpx.Response:
        # The etag never moves here, so a held read only ever answers "no change".
        nonlocal plain_reads
        if "timeout" in request.url.params:
            return httpx.Response(200, content=standalone)
        plain_reads += 1
        return httpx.Response(200, content=reads[plain_reads - 1])

    respx.get(url__regex=r"http://192\.168\.1\.20:11000/SyncStatus.*").mock(
        side_effect=sync_answer
    )
    client = BluOSClient(settings)
    poller, discovery = _poller(settings, client)
    clock = {"now": 1000.0}
    monkeypatch.setattr("app.services.poller.time.monotonic", lambda: clock["now"])
    try:
        await poller._poll_once()
        assert discovery.snapshot.devices[0].sync_role == SyncRole.STANDALONE

        # Same syncStat soon after: the cached SyncStatus is reused.
        clock["now"] += 5
        await poller._poll_once()
        assert plain_reads == 1
        assert discovery.snapshot.devices[0].sync_role == SyncRole.STANDALONE

        # Same syncStat, but the last read is old: read it again.
        clock["now"] += 60
        await poller._poll_once()
        assert plain_reads == 2
        follower = discovery.snapshot.devices[0]
        assert follower.sync_role == SyncRole.SYNCED
        assert follower.master == "192.168.1.30:11000"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_poller_clears_etag_when_player_goes_offline(settings: Settings) -> None:
    status_calls = {"n": 0}

    def status_response(_request: httpx.Request) -> httpx.Response:
        status_calls["n"] += 1
        if status_calls["n"] == 1:
            return httpx.Response(200, content=STATUS)
        raise httpx.ConnectError("down")

    respx.get(url__regex=r"http://192\.168\.1\.20:11000/Status.*").mock(
        side_effect=status_response
    )
    respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=SYNC_STATUS)
    )
    client = BluOSClient(settings)
    poller, discovery = _poller(settings, client)
    try:
        await poller._poll_once()
        assert "p1" in poller._status_etags
        await poller._poll_once()
        missed = discovery.snapshot.devices[0]
        assert missed.status == "online"
        assert missed.stale is True
        assert missed.track == "Song Title"
        assert "p1" not in poller._status_etags
        for _ in range(settings.circuit_failure_threshold - 1):
            await poller._poll_once()
        assert discovery.snapshot.devices[0].status == "offline"
        assert "p1" not in poller._status_etags
        drops = poller.health.snapshot().drops
        assert len(drops) == 1
        assert drops[0].device_id == "p1"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_long_poll_malformed_status_is_xml_error(settings: Settings) -> None:
    respx.get(url__regex=r"http://192\.168\.1\.20:11000/Status.*").mock(
        return_value=httpx.Response(200, content=b"<not-xml")
    )
    client = BluOSClient(settings)
    try:
        snap = await client.load_player(
            "192.168.1.20",
            device_id="p1",
            status_etag="2",
            long_poll_seconds=10,
        )
        assert snap.player.status == "xml_error"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_poller_starts_per_device_watchers(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BluOSClient(settings)
    poller, _discovery = _poller(settings, client)

    async def hang(_device: PlayerStatus) -> None:
        await poller._stop.wait()

    monkeypatch.setattr(poller, "_cycle_device", hang)
    try:
        await poller._reconcile()
        assert "p1" in poller._watchers
        await poller.stop()
        assert poller._watchers == {}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_reconcile_forgets_removed_devices(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BluOSClient(settings)
    poller, discovery = _poller(settings, client)
    poller._status_etags["p1"] = "e1"
    poller._sync_stats["p1"] = "s1"

    async def hang(_device: PlayerStatus) -> None:
        await poller._stop.wait()

    monkeypatch.setattr(poller, "_cycle_device", hang)

    async def no_refresh(_self: DiscoveryService) -> object:
        return discovery._snapshot

    monkeypatch.setattr(DiscoveryService, "refresh", no_refresh)
    try:
        await poller._reconcile()
        assert "p1" in poller._watchers
        discovery._snapshot.devices = []
        await poller._reconcile()
        assert poller._watchers == {}
        assert "p1" not in poller._status_etags
        await poller.stop()
    finally:
        await client.aclose()
