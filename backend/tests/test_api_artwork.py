# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""The cover route fetches other hosts only for images that a player reported."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.models import PlayerStatus
from tests.helpers import app_with_players

_LEAD_ART = "https://m.media-amazon.com/images/I/lead._SL500_.jpg"
_MEMBER_ART = "https://images.example.com/member.jpg"


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(
        discovery_cache_ttl=0,
        poll_interval=60,
        allow_non_private_ips=True,
        control_rate_limit_seconds=0,
    )


def _players() -> list[PlayerStatus]:
    return [
        PlayerStatus(
            id="lead", ip="192.168.1.20", name="Zone One", status="online", image=_LEAD_ART
        ),
        PlayerStatus(
            id="member", ip="192.168.1.21", name="Zone Two", status="online", image=_MEMBER_ART
        ),
    ]


@pytest.mark.parametrize(
    ("image", "named_by_player"),
    [
        (_LEAD_ART, True),
        (_MEMBER_ART, True),
        ("", True),
        ("https://images.example.com/other.jpg", False),
        ("/Artwork?id=1", False),
    ],
)
@pytest.mark.asyncio
async def test_art_route_marks_images_that_a_player_reported(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, image: str, named_by_player: bool
) -> None:
    app, client, _, poller = await app_with_players(settings, monkeypatch, players=_players())
    fetch = AsyncMock(return_value=(b"\xff\xd8\xff", "image/jpeg"))
    client.fetch_artwork = fetch  # type: ignore[method-assign]
    poller.interrupt = AsyncMock()  # type: ignore[method-assign]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/v1/devices/lead/art", params={"image": image})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert fetch.await_args is not None
    assert fetch.await_args.kwargs == {"named_by_player": named_by_player}
    await client.aclose()


@pytest.mark.asyncio
async def test_art_route_is_404_when_the_cover_is_refused(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, _, poller = await app_with_players(settings, monkeypatch, players=_players())
    client.fetch_artwork = AsyncMock(return_value=None)  # type: ignore[method-assign]
    poller.interrupt = AsyncMock()  # type: ignore[method-assign]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/v1/devices/lead/art", params={"image": _LEAD_ART})
    assert response.status_code == 404
    assert response.json()["code"] == "artwork_not_found"
    await client.aclose()
