# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""BluOS client error and edge-path coverage."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.bluos.artwork import MAX_ARTWORK_BYTES
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


_PLAYER = "192.168.1.20:11000"
_APPLE_ART = "https://is1-ssl.mzstatic.com/image/thumb/Music/cover/600x600bb.jpg"
_AMAZON_ART = "https://m.media-amazon.com/images/I/cover._SL500_.jpg"
_JPEG = b"\xff\xd8\xff"


def _image(content: bytes = _JPEG, media: str = "image/jpeg") -> httpx.Response:
    return httpx.Response(200, content=content, headers={"content-type": media})


@pytest.mark.asyncio
@respx.mock
async def test_artwork_stays_on_the_player_host_unless_a_player_named_it(
    settings: Settings,
) -> None:
    art = respx.get("http://192.168.1.20:11000/Artwork").mock(return_value=_image())
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork(_PLAYER, "/Artwork") == (_JPEG, "image/jpeg")
        assert art.called
        assert await client.fetch_artwork(_PLAYER, "http://10.0.0.10:11000/art") is None
        assert await client.fetch_artwork(_PLAYER, _AMAZON_ART) is None
        assert await client.fetch_artwork(_PLAYER, "/Volume?level=0") is None
        assert await client.fetch_artwork(_PLAYER, "", named_by_player=True) is None
        inline = "data:image/png;base64,AAAA"
        assert await client.fetch_artwork(_PLAYER, inline, named_by_player=True) is None
    finally:
        await client.aclose()


@pytest.mark.parametrize("cover", [_AMAZON_ART, _APPLE_ART, "https://images.example.com/c"])
@pytest.mark.asyncio
@respx.mock
async def test_artwork_fetches_any_https_host_a_player_names(
    settings: Settings, cover: str
) -> None:
    route = respx.get(cover).mock(return_value=_image())
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork(_PLAYER, cover, named_by_player=True)
        assert fetched == (_JPEG, "image/jpeg")
        assert route.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_follows_a_player_redirect_to_a_cover_host(settings: Settings) -> None:
    player = respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": _APPLE_ART})
    )
    cdn = respx.get(_APPLE_ART).mock(return_value=_image())
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork(
            _PLAYER, "/Artwork?service=AppleMusic&songid=AppleMusic%3Acatalog%2Fsongs%2F1"
        )
        assert fetched == (_JPEG, "image/jpeg")
        assert "songid=AppleMusic" in str(player.calls.last.request.url)
        assert cdn.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_checks_every_redirect_with_the_same_rule(settings: Settings) -> None:
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(302, headers={"Location": _APPLE_ART})
    )
    respx.get(_APPLE_ART).mock(
        return_value=httpx.Response(302, headers={"Location": "http://images.example.com/c.jpg"})
    )
    plain = respx.get("http://images.example.com/c.jpg").mock(return_value=_image())
    secure = respx.get("https://images.example.com/c.jpg").mock(return_value=_image())
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork(_PLAYER, "/Artwork") == (_JPEG, "image/jpeg")
        assert secure.called
        assert not plain.called
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "location",
    [
        "http://192.168.1.20:11000/Volume?level=0",
        "https://user:pass@images.example.com/a.jpg",
        "ftp://images.example.com/a.jpg",
        "https://images.example.com:99999/a.jpg",
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_artwork_refuses_redirects_the_rule_does_not_allow(
    settings: Settings, location: str
) -> None:
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": location})
    )
    volume = respx.get("http://192.168.1.20:11000/Volume").mock(return_value=_image())
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork(_PLAYER, "/Artwork") is None
        assert not volume.called
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_upgrades_plain_http_cover_hosts(settings: Settings) -> None:
    plain = "http://resources.tidal.com/images/cover.jpg"
    secure = "https://resources.tidal.com/images/cover.jpg"
    http_route = respx.get(plain).mock(return_value=_image())
    https_route = respx.get(secure).mock(return_value=_image())
    respx.get("http://192.168.1.20:11000/Artwork").mock(
        return_value=httpx.Response(301, headers={"Location": plain})
    )
    client = BluOSClient(settings)
    try:
        direct = await client.fetch_artwork(_PLAYER, plain, named_by_player=True)
        redirected = await client.fetch_artwork(_PLAYER, "/Artwork")
        assert direct == (_JPEG, "image/jpeg")
        assert redirected == (_JPEG, "image/jpeg")
        assert not http_route.called
        assert https_route.call_count == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_stops_after_too_many_redirects(settings: Settings) -> None:
    respx.get("https://images.example.com/loop.jpg").mock(
        return_value=httpx.Response(302, headers={"Location": "/loop.jpg"})
    )
    client = BluOSClient(settings)
    try:
        cover = "https://images.example.com/loop.jpg"
        assert await client.fetch_artwork(_PLAYER, cover, named_by_player=True) is None
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, content=_JPEG, headers={"content-type": "image/jpeg"}),
        httpx.Response(204),
        _image(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        _image(b"GIF89a", "image/gif"),
        _image(b"\xff" * (MAX_ARTWORK_BYTES + 1)),
        httpx.Response(200, stream=httpx.ByteStream(_JPEG + b"\xff" * MAX_ARTWORK_BYTES)),
        httpx.Response(
            200,
            headers={"content-length": str(MAX_ARTWORK_BYTES + 1)},
            stream=httpx.ByteStream(_JPEG),
        ),
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_artwork_refuses_responses_that_are_not_a_cover(
    settings: Settings, response: httpx.Response
) -> None:
    respx.get(_APPLE_ART).mock(return_value=response)
    client = BluOSClient(settings)
    try:
        assert await client.fetch_artwork(_PLAYER, _APPLE_ART, named_by_player=True) is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_artwork_type_comes_from_the_bytes(settings: Settings) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    respx.get(_APPLE_ART).mock(return_value=_image(png, "text/html"))
    client = BluOSClient(settings)
    try:
        fetched = await client.fetch_artwork(_PLAYER, _APPLE_ART, named_by_player=True)
        assert fetched == (png, "image/png")
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
