# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Where a cover request may go, and which bytes count as a cover."""

from __future__ import annotations

import pytest

from app.bluos.artwork import artwork_target, image_media_type, is_player_url

_PLAYER_IP = "192.168.1.20"
_BASE = "http://192.168.1.20:11000/"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("/Artwork?id=1", "http://192.168.1.20:11000/Artwork?id=1"),
        ("http://192.168.1.20:11001/images/a.jpg", "http://192.168.1.20:11001/images/a.jpg"),
        ("https://m.media-amazon.com/images/I/a.jpg", "https://m.media-amazon.com/images/I/a.jpg"),
        ("https://images.example.com/any/path", "https://images.example.com/any/path"),
        ("http://images.example.com/a.jpg", "https://images.example.com/a.jpg"),
        ("http://images.example.com:80/a.jpg", "https://images.example.com/a.jpg"),
        ("http://images.example.com:8080/a.jpg", "https://images.example.com:8080/a.jpg"),
        ("http://Images.Example.COM/a.jpg", "https://images.example.com/a.jpg"),
        ("http://[2001:db8::1]/a.jpg", "https://[2001:db8::1]/a.jpg"),
        ("http://10.0.0.10:11000/Volume?level=0", "https://10.0.0.10:11000/Volume?level=0"),
    ],
)
def test_artwork_target_allows_and_upgrades(location: str, expected: str) -> None:
    assert artwork_target(_PLAYER_IP, _BASE, location) == expected


@pytest.mark.parametrize(
    "location",
    [
        "/Volume?level=0",
        "http://192.168.1.20:11000/Reboot",
        "https://user:pass@images.example.com/a.jpg",
        "https://user@images.example.com/a.jpg",
        "ftp://images.example.com/a.jpg",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https:///a.jpg",
        "https://images.example.com:99999/a.jpg",
    ],
)
def test_artwork_target_refuses(location: str) -> None:
    assert artwork_target(_PLAYER_IP, _BASE, location) is None


def test_is_player_url_compares_the_host() -> None:
    assert is_player_url(_PLAYER_IP, "http://192.168.1.20:11001/Artwork")
    assert not is_player_url(_PLAYER_IP, "https://10.0.0.10/Artwork")
    assert not is_player_url(_PLAYER_IP, "https://images.example.com/Artwork")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n\x00", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00", "image/heic"),
        (b"\x00\x00\x00\x18ftypmif1\x00\x00", "image/heif"),
        (b"\x00\x00\x00\x1cftypavif\x00\x00", None),
        (b"GIF89a", None),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", None),
        (b"", None),
    ],
)
def test_image_media_type_reads_the_bytes(body: bytes, expected: str | None) -> None:
    assert image_media_type(body) == expected
