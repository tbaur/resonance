# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Where a cover request may go, and which responses count as a cover.

Any host that BluOS names is accepted, so no list of streaming services needs
upkeep. The player itself may be reached over plain HTTP, but only on paths
that look like artwork, because a GET such as ``/Volume?level=0`` is a command.
Every other host must use HTTPS, and an ``http`` link is upgraded. That keeps
stream metadata from making the server call routers and other devices on the
home network: they have no valid certificate for the name, so the TLS
handshake fails before any request is sent. The same check runs on every
redirect.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

from app.validators import sanitize_ip

# Covers are rarely over 1 MB. Anything past this is refused while it downloads.
MAX_ARTWORK_BYTES = 10 * 1024 * 1024

_ART_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif")
_ART_HINTS = ("/artwork", "/images/", "/image/", "/var/data/")
_PLAIN_HTTP_PORT = 80
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"})


def is_artwork_path(path: str) -> bool:
    """Reject control verbs disguised as a cover URL. GET /Volume?level=0 is a command."""
    lowered = (path or "").lower()
    if any(hint in lowered for hint in _ART_HINTS):
        return True
    return lowered.endswith(_ART_SUFFIXES)


def is_player_url(player_ip: str, url: str) -> bool:
    return sanitize_ip(urlparse(url).hostname or "") == player_ip


def artwork_target(player_ip: str, current_url: str, location: str) -> str | None:
    """The URL to request for ``location`` (relative to ``current_url``), or None to refuse it."""
    next_url = urljoin(current_url, location)
    parsed = urlparse(next_url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if sanitize_ip(host) == player_ip:
        return next_url if is_artwork_path(parsed.path) else None
    if parsed.scheme == "https":
        return next_url
    name = f"[{host}]" if ":" in host else host
    netloc = name if port in (None, _PLAIN_HTTP_PORT) else f"{name}:{port}"
    return urlunparse(parsed._replace(scheme="https", netloc=netloc))


def image_media_type(body: bytes) -> str | None:
    """The media type of a JPEG, PNG, WebP or HEIC/HEIF cover, judged from its bytes.

    The server's content type is ignored, so a response such as an SVG document
    is never served from this origin as a cover.
    """
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body[4:8] == b"ftyp" and body[8:12] in _HEIF_BRANDS:
        return "image/heic" if body[8:12].startswith(b"he") else "image/heif"
    return None
