# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""HTTP transport for BluOS and device web-UI calls."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import ParseResult, urljoin, urlparse, urlunparse

import httpx

from app.bluos.artwork import MAX_ARTWORK_BYTES, artwork_target
from app.bluos.rate_limit import RateLimiter
from app.bluos.result import CallResult, classify_control_body, note_control_result
from app.config import Settings
from app.validators import format_endpoint, parse_endpoint, sanitize_ip

logger = logging.getLogger(__name__)


def _failure_kind(result: CallResult) -> str:
    """A short label for logs. Transport failures keep the exception name."""
    if result.kind in {"timeout", "transport"} and result.detail:
        return result.detail
    if result.detail and result.detail != result.kind:
        return f"{result.kind}:{result.detail}"
    return result.kind or "unreachable"


async def _read_capped(response: httpx.Response, limit: int) -> bytes | None:
    """The whole body, or None once it passes ``limit`` bytes."""
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body) or None


async def _read_limited(response: httpx.Response, limit: int) -> bytes | None:
    """The whole body (empty allowed), or None once it passes ``limit`` bytes.

    Reads in chunks so an oversized reply is refused before it is all in memory.
    """
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


@dataclass(frozen=True)
class FetchedResponse:
    """Status and size-capped body of a device reply. ``too_large`` means no body was kept."""

    status_code: int
    content: bytes = b""
    too_large: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_public(address: str) -> bool:
    parsed = _parse_ip(address.split("%", 1)[0])
    return parsed is not None and parsed.is_global


def _pinned(
    parsed: ParseResult, host: str, address: str
) -> tuple[str, dict[str, str], dict[str, str]]:
    """The URL with ``address`` in place of ``host``, plus the Host header and TLS name.

    ``Connection: close`` keeps the connection out of the pool. The pool keys
    connections by address, not by TLS name, so a pooled one could carry a
    request for another host that shares the address, over TLS checked for
    the first name.
    """
    name = f"[{address}]" if ":" in address else address
    netloc = name if parsed.port is None else f"{name}:{parsed.port}"
    original = parsed.netloc.rsplit("@", 1)[-1]
    return (
        urlunparse(parsed._replace(netloc=netloc)),
        {"Host": original, "Connection": "close"},
        {"sni_hostname": host},
    )


def _backoff_seconds(attempt: int) -> float:
    """Jittered backoff before retry ``attempt + 1``.

    A LAN blip fails every device at once, and a fixed delay would march them
    all back in lockstep.
    """
    base = min(10.0, (2**attempt) + 0.1)
    return float(base * (0.5 + random.random() / 2))


_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
# Idle control sockets stay warm across a mute/volume session. Long-polls are
# in-use and do not use this expiry.
_CONTROL_KEEPALIVE_EXPIRY_SECONDS = 60.0
# A BluOS player answers only a few HTTP calls at once. Two held long-polls
# fill that, and the player keeps streaming while Status, art, and queue
# all time out. One hold plus one other call is the cap.
_MAX_HTTP_PER_ENDPOINT = 2


class BluOSTransport:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._owns_client = client is None
        # Manual redirects so each Location host is re-validated (BluOS may
        # 301 /Settings from :11000 -> :11001 on the same device IP).
        # Keepalive room for per-player Status long-polls plus control calls.
        pool = max(48, settings.max_concurrent_device_calls + 24)
        self._client = client or httpx.AsyncClient(
            timeout=settings.device_http_timeout,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=pool + 16,
                max_keepalive_connections=pool,
                keepalive_expiry=_CONTROL_KEEPALIVE_EXPIRY_SECONDS,
            ),
        )
        self._rate = RateLimiter(settings.control_rate_limit_seconds)
        self._sem = asyncio.Semaphore(settings.max_concurrent_device_calls)
        self._endpoint_slots: dict[str, asyncio.Semaphore] = {}
        # Short-lived settings page cache so unresolved writes do not double-fetch.
        self._settings_page_cache: dict[tuple[str, str], tuple[float, object]] = {}
        self._settings_page_cache_ttl = 5.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _resolve_target(self, target: str) -> tuple[str, int] | None:
        """Parse ``ip`` or ``ip:port`` into a validated ``(ip, port)`` pair."""
        ip, port = parse_endpoint(target, default_port=self.settings.bluos_port)
        if not ip:
            return None
        return ip, port

    def _url(self, ip: str, path: str, query: str = "", *, port: int | None = None) -> str:
        api_port = self.settings.bluos_port if port is None else port
        base = f"http://{ip}:{api_port}{path}"
        return f"{base}?{query}" if query else base

    def _redirect_target_allowed(
        self,
        origin_ip: str,
        current_url: str,
        location: str,
        *,
        warn: bool = True,
    ) -> str | None:
        """Return absolute next URL if redirect stays on the same allowed device IP."""
        next_url = urljoin(current_url, location)
        parsed = urlparse(next_url)
        if parsed.scheme not in {"http", "https"}:
            return None
        host = parsed.hostname
        if not host:
            return None
        sanitized_host = sanitize_ip(host)
        if not sanitized_host or sanitized_host != origin_ip:
            if warn:
                logger.warning(
                    "blocked_redirect_host",
                    extra={"device_ip": origin_ip, "redirect_host": host},
                )
            return None
        if not self.settings.is_allowed_device_ip(sanitized_host):
            if warn:
                logger.warning("blocked_non_private_ip", extra={"device_ip": sanitized_host})
            return None
        return next_url

    def _endpoint_slot(self, endpoint_key: str) -> asyncio.Semaphore:
        slot = self._endpoint_slots.get(endpoint_key)
        if slot is None:
            slot = asyncio.Semaphore(_MAX_HTTP_PER_ENDPOINT)
            self._endpoint_slots[endpoint_key] = slot
        return slot

    @asynccontextmanager
    async def _call_slot(self, hold_slot: bool) -> AsyncIterator[None]:
        if hold_slot:
            async with self._sem:
                yield
            return
        yield

    async def _fetch_capped(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> tuple[FetchedResponse, str | None]:
        """One request. Returns the capped reply and its Location header, if any."""
        request_timeout = httpx.USE_CLIENT_DEFAULT if timeout is None else timeout
        async with self._client.stream(method, url, data=data, timeout=request_timeout) as response:
            location = response.headers.get("Location")
            if response.status_code in _REDIRECT_STATUSES and location:
                return FetchedResponse(response.status_code), location
            body = await _read_limited(response, self.settings.max_xml_size)
            if body is None:
                return FetchedResponse(response.status_code, too_large=True), None
            return FetchedResponse(response.status_code, body), None

    async def _follow_get(
        self,
        origin_ip: str,
        url: str,
        *,
        timeout: float | httpx.Timeout | None = None,
    ) -> FetchedResponse | None:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            response, location = await self._fetch_capped("GET", current, timeout=timeout)
            if location is None:
                return response
            nxt = self._redirect_target_allowed(origin_ip, current, location)
            if nxt is None:
                return None
            current = nxt
        logger.warning("redirect_limit_exceeded", extra={"device_ip": origin_ip, "url": url})
        return None

    async def _artwork_addresses(self, host: str) -> list[str] | None:
        """The public addresses of a cover host, IPv4 first, or None to refuse the host.

        Every address the name resolves to must be public. A name that points
        inside the home network (a NAS or router with a real certificate, or a
        split-horizon DNS answer) is refused. The caller connects only to
        addresses returned here, so a second, different DNS answer cannot move
        the request after the check.
        """
        literal = _parse_ip(host)
        if literal is not None:
            return [host] if literal.is_global else None
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM),
                timeout=self.settings.device_http_timeout,
            )
        except (OSError, TimeoutError):
            return None
        addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
        if not addresses or not all(_is_public(address) for address in addresses):
            return None
        # The rest of the app is IPv4. Try those first, so a network whose IPv6
        # does not route still gets its covers.
        return sorted(addresses, key=lambda address: ":" in address)

    async def _artwork_hop(
        self,
        url: str,
        headers: dict[str, str],
        extensions: dict[str, str],
        timeout: float | httpx.Timeout | None,
    ) -> tuple[int, str, bytes | None]:
        """One cover request: its status, its Location, and its capped body on a 200."""
        stream = (
            self._client.stream("GET", url, headers=headers, extensions=extensions)
            if timeout is None
            else self._client.stream(
                "GET", url, headers=headers, extensions=extensions, timeout=timeout
            )
        )
        async with stream as response:
            if response.status_code in _REDIRECT_STATUSES:
                return response.status_code, response.headers.get("Location", ""), None
            if response.status_code != 200:
                return response.status_code, "", None
            return 200, "", await _read_capped(response, MAX_ARTWORK_BYTES)

    async def _follow_artwork_get(
        self,
        origin_ip: str,
        url: str,
        *,
        timeout: float | httpx.Timeout | None = None,
    ) -> bytes | None:
        """The body of a cover, following redirects that ``artwork_target`` allows.

        A host other than the player is reached only at public addresses that
        were checked first, with TLS still verified for its name. When one
        address does not connect, the next one is tried.
        Control calls use ``_follow_get`` and still refuse every off-player host.
        """
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            host = parsed.hostname or ""
            attempts: list[tuple[str, dict[str, str], dict[str, str]]] = [(current, {}, {})]
            if sanitize_ip(host) != origin_ip:
                addresses = await self._artwork_addresses(host)
                if addresses is None:
                    logger.warning(
                        "blocked_artwork_host",
                        extra={"device_ip": origin_ip, "redirect_host": host},
                    )
                    return None
                attempts = [
                    _pinned(parsed, host, address) if address != host else (current, {}, {})
                    for address in addresses
                ]
            status, location, body = await self._first_answer(attempts, timeout)
            if status not in _REDIRECT_STATUSES:
                return body
            target = artwork_target(origin_ip, current, location) if location else None
            if target is None:
                logger.warning(
                    "blocked_redirect_host",
                    extra={"device_ip": origin_ip, "redirect_host": urlparse(location).hostname},
                )
                return None
            current = target
        logger.warning("redirect_limit_exceeded", extra={"device_ip": origin_ip, "url": url})
        return None

    async def _first_answer(
        self,
        attempts: list[tuple[str, dict[str, str], dict[str, str]]],
        timeout: float | httpx.Timeout | None,
    ) -> tuple[int, str, bytes | None]:
        """The first of ``attempts`` that connects. The last connect error is raised."""
        for index, (request_url, headers, extensions) in enumerate(attempts):
            try:
                return await self._artwork_hop(request_url, headers, extensions, timeout)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if index + 1 >= len(attempts):
                    raise
        raise httpx.ConnectError("no address to try")

    async def _follow_post(
        self,
        origin_ip: str,
        url: str,
        data: dict[str, str],
    ) -> FetchedResponse | None:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            response, location = await self._fetch_capped("POST", current, data=data)
            if location is None:
                return response
            nxt = self._redirect_target_allowed(origin_ip, current, location)
            if nxt is None:
                return None
            current = nxt
            # 301/302/303 switch to GET without a body; 307/308 repeat the POST.
            if response.status_code in {301, 302, 303}:
                return await self._follow_get(origin_ip, current)
        logger.warning("redirect_limit_exceeded", extra={"device_ip": origin_ip, "url": url})
        return None

    async def _transport_get(
        self,
        target: str,
        path: str,
        *,
        query: str = "",
        retries: int = 3,
        control: bool = False,
        timeout: float | httpx.Timeout | None = None,
        hold_slot: bool = True,
    ) -> CallResult:
        resolved = self._resolve_target(target)
        if not resolved:
            return CallResult.failure("rejected", "invalid target")
        sanitized, port = resolved
        endpoint_key = format_endpoint(sanitized, port)
        if not self.settings.is_allowed_device_ip(sanitized):
            logger.warning("blocked_non_private_ip", extra={"device_ip": sanitized})
            return CallResult.failure("rejected", "ip not allowed")
        if control:
            await self._rate.wait(endpoint_key)
        url = self._url(sanitized, path, query, port=port)
        last_error: Exception | None = None
        attempts = 1 if control else retries
        for attempt in range(attempts):
            try:
                async with self._call_slot(hold_slot):
                    async with self._endpoint_slot(endpoint_key):
                        response = await self._follow_get(sanitized, url, timeout=timeout)
                if response is None:
                    return CallResult.failure("rejected", "redirect blocked")
                if response.status_code >= 400:
                    logger.debug(
                        "bluos_http_error endpoint=%s path=%s status=%s",
                        endpoint_key,
                        path,
                        response.status_code,
                    )
                    return CallResult.failure("http_status", str(response.status_code))
                if response.too_large:
                    logger.warning(
                        "payload_too_large endpoint=%s path=%s",
                        endpoint_key,
                        path,
                    )
                    return CallResult.failure("rejected", "payload too large")
                return CallResult.success(response.content)
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    return CallResult.failure("timeout", type(exc).__name__)
                await asyncio.sleep(_backoff_seconds(attempt))
            except (httpx.TransportError, OSError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                await asyncio.sleep(_backoff_seconds(attempt))
        detail = type(last_error).__name__ if last_error else "transport"
        if last_error:
            logger.debug(
                "bluos_request_failed endpoint=%s path=%s err=%s",
                endpoint_key,
                path,
                last_error,
            )
        return CallResult.failure("transport", detail)

    async def _read(
        self,
        target: str,
        path: str,
        *,
        query: str = "",
        retries: int = 3,
        control: bool = False,
        timeout: float | httpx.Timeout | None = None,
        hold_slot: bool = True,
    ) -> tuple[bytes | None, str]:
        """Return ``(body, failure_kind)``. ``failure_kind`` is empty on success."""
        result = await self._transport_get(
            target,
            path,
            query=query,
            retries=retries,
            control=control,
            timeout=timeout,
            hold_slot=hold_slot,
        )
        if not result.ok:
            return None, _failure_kind(result)
        return result.body, ""

    async def _get(
        self,
        target: str,
        path: str,
        *,
        query: str = "",
        retries: int = 3,
        control: bool = False,
        timeout: float | httpx.Timeout | None = None,
        hold_slot: bool = True,
    ) -> bytes | None:
        body, _kind = await self._read(
            target,
            path,
            query=query,
            retries=retries,
            control=control,
            timeout=timeout,
            hold_slot=hold_slot,
        )
        return body

    async def _control_get(
        self,
        target: str,
        path: str,
        *,
        query: str = "",
        allow_plain: bool = False,
    ) -> CallResult:
        transport = await self._transport_get(target, path, query=query, control=True)
        if not transport.ok:
            note_control_result(transport)
            return transport
        classified = classify_control_body(
            transport.body,
            self.settings,
            target,
            allow_plain=allow_plain,
            empty_ok=True,
        )
        note_control_result(classified)
        return classified

    def _ok(self, result: CallResult) -> bool:
        """Bool so existing ``is True`` / ``is False`` checks keep working."""
        note_control_result(result)
        return True if result.ok else False
