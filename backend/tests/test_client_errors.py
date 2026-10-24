# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""BluOS client error and edge-path coverage."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.bluos.client import BluOSClient
from app.bluos.result import take_control_result
from app.config import Settings
from tests.fixtures.xml_samples import QUEUE, STATUS, SYNC_STATUS


@pytest.fixture
def settings() -> Settings:
    return Settings(
        allow_non_private_ips=True,
        device_http_timeout=1.0,
        control_rate_limit_seconds=0,
        max_xml_size=1024,
    )


@pytest.mark.asyncio
async def test_get_rejects_invalid_and_blocked_ips() -> None:
    settings = Settings(allow_non_private_ips=False, control_rate_limit_seconds=0)
    client = BluOSClient(settings)
    try:
        assert await client._get("not-an-ip", "/Status") is None
        assert await client._get("8.8.8.8", "/Status") is None
        assert await client._post("bad", "/Reboot") is False
        assert await client._post("8.8.8.8", "/Reboot") is False
        assert await client.add_sync_slave("bad", "192.168.1.2") is False
        assert await client.remove_sync_slave("192.168.1.1", "bad") is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_http_error_and_payload_too_large(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Status").mock(
        return_value=httpx.Response(500, content=b"err")
    )
    respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=b"x" * 2000)
    )
    client = BluOSClient(settings)
    try:
        assert await client._get("192.168.1.20", "/Status") is None
        assert await client._get("192.168.1.20", "/SyncStatus") is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_retries_then_succeeds(settings: Settings) -> None:
    route = respx.get("http://192.168.1.20:11000/Status").mock(
        side_effect=[
            httpx.ConnectError("down"),
            httpx.ConnectError("down"),
            httpx.Response(200, content=STATUS),
        ]
    )
    client = BluOSClient(settings)
    try:
        raw = await client._get("192.168.1.20", "/Status", retries=3)
        assert raw is not None
        assert route.call_count == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_retries_exhausted(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Status").mock(side_effect=httpx.ConnectError("down"))
    client = BluOSClient(settings)
    try:
        assert await client._get("192.168.1.20", "/Status", retries=2) is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_post_transport_error(settings: Settings) -> None:
    respx.post("http://192.168.1.20/reboot").mock(side_effect=httpx.ConnectError("x"))
    client = BluOSClient(settings)
    try:
        assert await client.reboot("192.168.1.20") is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_stays_on_the_player_host(settings: Settings) -> None:
    art = respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(
            200,
            content=b"\xff\xd8\xff",
            headers={"content-type": "image/jpeg"},
        )
    )
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork("192.168.1.20:11000", "/Artwork")
        assert fetched is not None
        assert fetched[1] == "image/jpeg"
        assert art.called
        assert (
            await client.fetch_artwork("192.168.1.20:11000", "http://10.0.0.10:11000/art")
            is None
        )
        assert await client.fetch_artwork("192.168.1.20:11000", "/Volume?level=0") is None
    finally:
        await client.aclose()


_APPLE_ART = "https://is1-ssl.mzstatic.com/image/thumb/Music/cover/600x600bb.jpg"
_JPEG = b"\xff\xd8\xff"


@pytest.mark.asyncio
@respx.mock
async def test_artwork_follows_one_mzstatic_redirect(settings: Settings) -> None:
    player = respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": _APPLE_ART})
    )
    cdn = respx.get(_APPLE_ART).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork(
            "192.168.1.20:11000",
            "/Artwork?service=AppleMusic&songid=AppleMusic%3Acatalog%2Fsongs%2F1",
        )
        assert fetched == (_JPEG, "image/jpeg")
        assert "songid=AppleMusic" in str(player.calls.last.request.url)
        assert cdn.called
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/a.jpg",
        "http://is1-ssl.mzstatic.com/a.jpg",
        "https://is1-ssl.mzstatic.com.evil.example/a.jpg",
        "https://evilmzstatic.com/a.jpg",
        "https://is1-ssl.mzstatic.com:8443/a.jpg",
        "https://resources.tidal.com.evil.example/images/a.jpg",
        "https://notresources.tidal.com/images/a.jpg",
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_artwork_refuses_redirects_off_the_allowlist(
    settings: Settings, location: str
) -> None:
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": location})
    )
    forbidden = respx.get(location).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork("192.168.1.20:11000", "/Artwork") is None
        assert not forbidden.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_does_not_follow_a_second_cdn_hop(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": _APPLE_ART})
    )
    respx.get(_APPLE_ART).mock(
        return_value=httpx.Response(
            302,
            headers={"Location": "https://evil.example/next.jpg"},
        )
    )
    second = respx.get("https://evil.example/next.jpg").mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork("192.168.1.20:11000", "/Artwork") is None
        assert not second.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_follows_a_same_player_redirect(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(
            301,
            headers={"Location": "http://192.168.1.20:11000/images/cover.jpg"},
        )
    )
    respx.get("http://192.168.1.20:11000/images/cover.jpg").mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork("192.168.1.20:11000", "/Artwork")
        assert fetched == (_JPEG, "image/jpeg")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_fetches_a_direct_tidal_url(settings: Settings) -> None:
    tidal = "https://resources.tidal.com/images/cover.jpg"
    cdn = respx.get(tidal).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork("192.168.1.20:11000", tidal)
        assert fetched == (_JPEG, "image/jpeg")
        assert cdn.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_upgrades_tidal_http_to_https(settings: Settings) -> None:
    plain = "http://resources.tidal.com/images/cover.jpg"
    secure = "https://resources.tidal.com/images/cover.jpg"
    http_route = respx.get(plain).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    https_route = respx.get(secure).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": plain})
    )
    client = BluOSClient(settings)
    try:
        direct = await client.fetch_artwork("192.168.1.20:11000", plain)
        redirected = await client.fetch_artwork("192.168.1.20:11000", "/Artwork")
        assert direct == (_JPEG, "image/jpeg")
        assert redirected == (_JPEG, "image/jpeg")
        assert not http_route.called
        assert https_route.call_count == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_fetches_a_direct_allowlisted_url(settings: Settings) -> None:
    cdn = respx.get(_APPLE_ART).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork("192.168.1.20:11000", _APPLE_ART)
        assert fetched == (_JPEG, "image/jpeg")
        assert cdn.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_rejects_a_direct_url_off_the_allowlist(settings: Settings) -> None:
    evil = "https://evil.example/images/a.jpg"
    tidal_api = "https://resources.tidal.com/v1/sessions"
    evil_route = respx.get(evil).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    api_route = respx.get(tidal_api).mock(
        return_value=httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
    )
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork("192.168.1.20:11000", evil) is None
        assert await client.fetch_artwork("192.168.1.20:11000", tidal_api) is None
        assert not evil_route.called
        assert not api_route.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_rejects_an_oversized_cdn_image(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": _APPLE_ART})
    )
    respx.get(_APPLE_ART).mock(
        return_value=httpx.Response(
            200,
            content=b"\xff" * (settings.max_xml_size + 1),
            headers={"content-type": "image/jpeg"},
        )
    )
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork("192.168.1.20:11000", "/Artwork") is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_artwork_cdn_target_rejects_credentials_and_lookalikes(settings: Settings) -> None:
    client = BluOSClient(settings)
    origin = "http://192.168.1.20:11000/Artwork"
    try:
        assert client._artwork_cdn_target(origin, _APPLE_ART) == _APPLE_ART
        assert (
            client._artwork_cdn_target(origin, "https://user:pass@is1-ssl.mzstatic.com/a.jpg")
            is None
        )
        assert client._artwork_cdn_target(origin, "https://mzstatic.com/a.jpg") is not None
        assert (
            client._artwork_cdn_target(origin, "http://resources.tidal.com/images/a.jpg")
            == "https://resources.tidal.com/images/a.jpg"
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_control_redirect_to_mzstatic_stays_blocked(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Status").mock(
        return_value=httpx.Response(301, headers={"Location": _APPLE_ART})
    )
    cdn = respx.get(_APPLE_ART).mock(return_value=httpx.Response(200, content=b"<status/>"))
    client = BluOSClient(settings)
    try:
        assert await client._get("192.168.1.20", "/Status") is None
        assert not cdn.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_play_rejects_bluos_error_document(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Play").mock(
        return_value=httpx.Response(
            200,
            content=b"<error>no slave available as new master</error>",
        )
    )
    client = BluOSClient(settings)
    try:
        assert await client.play("192.168.1.20") is False
        failure = take_control_result()
        assert failure is not None
        assert failure.kind == "bluos_error"
        assert "no slave" in failure.detail
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_play_timeout_is_named(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Play").mock(side_effect=httpx.ConnectTimeout("slow"))
    client = BluOSClient(settings)
    try:
        assert await client.play("192.168.1.20") is False
        failure = take_control_result()
        assert failure is not None
        assert failure.kind == "timeout"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_volume_xml_still_succeeds(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Volume").mock(
        return_value=httpx.Response(200, content=b"<volume>20</volume>")
    )
    client = BluOSClient(settings)
    try:
        assert await client.set_volume("192.168.1.20", 20) is True
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_player_status_offline_and_xml_error(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=b"<not-xml")
    )
    respx.get("http://192.168.1.20:11000/Status").mock(
        return_value=httpx.Response(200, content=b"<not-xml")
    )
    client = BluOSClient(settings)
    try:
        player = await client.get_player_status("192.168.1.20", device_id="p1")
        assert player.status in {"xml_error", "offline"}
        offline = await client.get_player_status("bad-ip")
        assert offline.status == "invalid"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_queue_and_inputs_none_on_empty(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Playlist").mock(
        return_value=httpx.Response(500, content=b"")
    )
    respx.get("http://192.168.1.20:11000/Settings").mock(
        return_value=httpx.Response(500, content=b"")
    )
    respx.get("http://192.168.1.20:11000/Presets").mock(
        return_value=httpx.Response(500, content=b"")
    )
    client = BluOSClient(settings)
    try:
        assert await client.get_queue("192.168.1.20") is None
        assert await client.get_inputs("192.168.1.20") is None
        assert await client.get_presets("192.168.1.20") is None
        assert await client.set_input("192.168.1.20", "") is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_set_input_by_type_index_and_unknown_name(settings: Settings) -> None:
    from tests.fixtures.xml_samples import CAPTURE_SETTINGS

    respx.get("http://192.168.1.20:11000/Settings").mock(
        return_value=httpx.Response(200, content=CAPTURE_SETTINGS)
    )
    respx.get("http://192.168.1.20:11000/Status").mock(
        return_value=httpx.Response(200, content=STATUS)
    )
    play = respx.get("http://192.168.1.20:11000/Play").mock(
        return_value=httpx.Response(200, content=b"<ok/>")
    )
    client = BluOSClient(settings)
    try:
        assert await client.set_input("192.168.1.20", "spdif-1") is True
        assert "inputTypeIndex=spdif-1" in str(play.calls.last.request.url)
        assert await client.set_input("192.168.1.20", "No Such Input") is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_sync_fallback_paths(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/AddSlave").mock(
        return_value=httpx.Response(500, content=b"")
    )
    sync_add = respx.get("http://192.168.1.20:11000/Sync").mock(
        return_value=httpx.Response(200, content=b"<ok/>")
    )
    respx.get("http://192.168.1.20:11000/RemoveSlave").mock(
        return_value=httpx.Response(500, content=b"")
    )
    respx.get("http://192.168.1.21:11000/SyncStatus").mock(
        return_value=httpx.Response(
            200,
            content=b"<SyncStatus id='192.168.1.21:11000' name='Zone R'/>",
        )
    )
    client = BluOSClient(settings)
    try:
        assert await client.add_sync_slave("192.168.1.20", "192.168.1.21") is True
        assert "slave=192.168.1.21" in str(sync_add.calls[0].request.url)
        assert await client.remove_sync_slave("192.168.1.20", "192.168.1.21") is True
        assert "remove=192.168.1.21" in str(sync_add.calls[-1].request.url)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_text_and_absolute_media(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/SyncStatus").mock(
        return_value=httpx.Response(200, content=SYNC_STATUS)
    )
    respx.get("http://192.168.1.20:11000/Status").mock(
        return_value=httpx.Response(200, content=STATUS)
    )
    client = BluOSClient(settings)
    try:
        text = await client._get_text("192.168.1.20", "/Status")
        assert text is not None
        assert client._absolute_media_url("192.168.1.20", "http://cdn/x.png") == "http://cdn/x.png"
        assert client._absolute_media_url("192.168.1.20", "") == ""
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_bluetooth_modes_and_queue_parse(settings: Settings) -> None:
    # max_xml_size bumped for QUEUE fixture path via separate client
    roomy = Settings(allow_non_private_ips=True, control_rate_limit_seconds=0)
    respx.get("http://192.168.1.20:11000/Playlist").mock(
        return_value=httpx.Response(200, content=QUEUE)
    )
    respx.get("http://192.168.1.20:11000/Settings").mock(
        return_value=httpx.Response(
            200,
            content=b"""<?xml version="1.0"?><settings>
              <setting id="bluetoothAutoplay" value="1"/>
            </settings>""",
        )
    )
    client = BluOSClient(roomy)
    try:
        queue = await client.get_queue("192.168.1.20")
        assert queue is not None and queue.count == 1
        assert await client.get_bluetooth_mode("192.168.1.20") == "Automatic"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_uptime_http_error(settings: Settings) -> None:
    respx.get("http://192.168.1.20/diagnostics").mock(
        return_value=httpx.Response(404, text="missing")
    )
    client = BluOSClient(settings)
    try:
        assert await client.get_uptime("192.168.1.20") is None
        blocked = BluOSClient(Settings(allow_non_private_ips=False))
        try:
            assert await blocked.get_uptime("8.8.8.8") is None
        finally:
            await blocked.aclose()
    finally:
        await client.aclose()
