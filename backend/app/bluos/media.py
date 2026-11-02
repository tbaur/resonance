# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Queue, capture inputs, Bluetooth, and presets."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.bluos.artwork import artwork_target, image_media_type, is_player_url
from app.bluos.result import CallResult
from app.bluos.status import BluOSStatusMixin
from app.bluos.xml import safe_parse_xml, text
from app.models import AudioInput, BluetoothResponse, Preset, QueueItem, QueueResponse
from app.validators import format_endpoint


class BluOSMediaMixin(BluOSStatusMixin):
    _INPUT_HINTS = (
        ("hdmi arc", "arc"),
        ("earc", "earc"),
        ("optical", "spdif"),
        ("analog", "analog"),
        ("line in", "analog"),
        ("coax", "coax"),
        ("phono", "phono"),
        ("vinyl", "phono"),
        ("computer", "computer"),
        ("aes", "aesebu"),
        ("balanced", "balanced"),
        ("microphone", "microphone"),
        ("bluetooth", "bluetooth"),
    )
    _ICON_HINTS = (
        ("ic_optical", "spdif"),
        ("ic_analog", "analog"),
        ("ic_tv", "arc"),
        ("ic_hdmi", "arc"),
        ("ic_phono", "phono"),
        ("ic_coax", "coax"),
        ("ic_bluetooth", "bluetooth"),
    )
    _BT_MODE_MAP = {"0": "Manual", "1": "Automatic", "2": "Guest", "3": "Disabled"}

    @classmethod
    def _input_type_from_capture(cls, display_name: str, icon: str) -> str:
        """Map capture menu labels/icons to inputTypeIndex type tokens."""
        name = (display_name or "").lower()
        for needle, type_name in cls._INPUT_HINTS:
            if needle in name:
                return type_name
        icon_l = (icon or "").lower()
        for needle, type_name in cls._ICON_HINTS:
            if needle in icon_l:
                return type_name
        return "analog"

    async def get_queue(self, ip: str) -> QueueResponse | None:
        """Play queue via GET /Playlist."""
        raw = await self._get(ip, "/Playlist", query="start=0&end=500")
        if not raw:
            return None
        root = safe_parse_xml(raw, self.settings, ip)
        if root is None:
            return None
        items = [
            QueueItem(
                title=text(song, "title"),
                artist=text(song, "art") or text(song, "artist"),
                album=text(song, "alb") or text(song, "album"),
                image=text(song, "image"),
                service=text(song, "service"),
            )
            for song in root.findall("song")
        ]
        length_attr = root.attrib.get("length")
        length_el = root.findtext("length")
        try:
            count = int(
                length_attr
                if length_attr is not None
                else (length_el if length_el is not None else len(items))
            )
        except ValueError:
            count = len(items)
        return QueueResponse(items=items, count=count)

    async def clear_queue(self, ip: str) -> bool:
        """Clear play queue via GET /Clear."""
        return self._ok(await self._control_get(ip, "/Clear"))

    async def move_queue_item(self, ip: str, from_index: int, to_index: int) -> bool:
        """Move queue track via GET /Move?old=&new=."""
        return self._ok(
            await self._control_get(ip, "/Move", query=f"old={from_index}&new={to_index}")
        )

    async def get_inputs(self, ip: str) -> list[AudioInput] | None:
        """List capture inputs via Settings?id=capture."""
        raw = await self._get(ip, "/Settings", query="id=capture&schemaVersion=32")
        if not raw:
            return None
        root = safe_parse_xml(raw, self.settings, ip)
        if root is None:
            return None

        active_type_index = ""
        active_input_id = ""
        active_name = ""
        status_raw = await self._get(ip, "/Status")
        if status_raw:
            status = self._parse_status(status_raw, ip)
            if status.get("service_id") == "Capture":
                active_type_index = str(status.get("input_type_index") or "")
                active_input_id = str(status.get("input_id") or "")
                active_name = str(status.get("track") or "")

        inputs: list[AudioInput] = []
        type_counts: dict[str, int] = {}
        for group in root.iter("menuGroup"):
            group_id = group.get("id", "")
            if not group_id.startswith("capture-") or group_id == "capture":
                continue
            if "bluetooth" in group_id.lower():
                continue
            name = group.get("displayName", "") or group_id
            icon = group.get("icon", "")
            type_name = self._input_type_from_capture(name, icon)
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
            type_index = f"{type_name}-{type_counts[type_name]}"
            capture_key = group_id.removeprefix("capture-")
            selected = bool(
                (active_type_index and type_index == active_type_index)
                or (active_input_id and capture_key == active_input_id)
                or (active_name and name.lower() == active_name.lower())
            )
            inputs.append(
                AudioInput(
                    name=name,
                    type=type_name,
                    id=type_index,
                    selected=selected,
                )
            )
        return inputs

    async def set_input(self, ip: str, input_name: str) -> bool:
        """Select input by display name or inputTypeIndex (fw >= 4.2)."""
        target = (input_name or "").strip()
        if not target:
            return False
        type_index = target
        if "-" not in target or not any(ch.isdigit() for ch in target.split("-")[-1]):
            inputs = await self.get_inputs(ip) or []
            lowered = target.lower()
            match = next(
                (
                    inp
                    for inp in inputs
                    if inp.id.lower() == lowered
                    or inp.name.lower() == lowered
                    or inp.type.lower() == lowered
                ),
                None,
            )
            if match is None:
                return False
            type_index = match.id
        encoded = quote(type_index, safe="-")
        return self._ok(await self._control_get(ip, "/Play", query=f"inputTypeIndex={encoded}"))

    async def get_bluetooth_info(self, ip: str) -> BluetoothResponse | None:
        """Probe Bluetooth from capture settings (no /AudioModes GET).

        Returns ``None`` on hard failure (unreachable / unparseable). When capture
        settings load but omit ``bluetoothAutoplay``, returns ``supported=False``
        (e.g. NAD CI S2 and other players without a Bluetooth radio).
        """
        raw = await self._get(ip, "/Settings", query="id=capture&schemaVersion=32")
        if not raw:
            return None
        root = safe_parse_xml(raw, self.settings, ip)
        if root is None:
            return None
        for setting in root.iter("setting"):
            setting_id = setting.get("id") or setting.get("name")
            if setting_id == "bluetoothAutoplay":
                mode = setting.get("value", "")
                return BluetoothResponse(
                    supported=True,
                    mode=self._BT_MODE_MAP.get(mode, "Unknown"),
                )
        return BluetoothResponse(supported=False, mode=None)

    async def get_bluetooth_mode(self, ip: str) -> str | None:
        """Read Bluetooth mode label, or ``None`` when unsupported / unreachable."""
        info = await self.get_bluetooth_info(ip)
        if info is None or not info.supported:
            return None
        return info.mode

    async def set_bluetooth_mode(self, ip: str, mode: int) -> bool:
        if mode not in (0, 1, 2, 3):
            return self._ok(CallResult.failure("rejected", "invalid bluetooth mode"))
        return self._ok(
            await self._control_get(ip, "/audiomodes", query=f"bluetoothAutoplay={mode}")
        )

    async def get_presets(self, ip: str) -> list[Preset] | None:
        # Read path: do not burn the control rate slot / single-attempt budget.
        raw = await self._get(ip, "/Presets", control=False)
        if not raw:
            return None
        root = safe_parse_xml(raw, self.settings, ip)
        if root is None:
            return None
        return [
            Preset(
                id=preset.get("id", ""),
                name=text(preset, "name"),
                image=text(preset, "image"),
            )
            for preset in root.findall("preset")
        ]

    async def play_preset(self, ip: str, preset_id: int) -> bool:
        if preset_id < 1:
            return self._ok(CallResult.failure("rejected", "invalid preset"))
        return self._ok(await self._control_get(ip, "/Preset", query=f"id={preset_id}"))

    def _artwork_fetch_url(
        self, ip: str, port: int, raw: str, *, named_by_player: bool
    ) -> str | None:
        """The first URL to request for a cover, under the rule in ``app.bluos.artwork``.

        A URL that no player reported may only point at the player itself, so a
        client can't make the server fetch from any host it likes.
        """
        if not raw or raw.startswith("data:"):
            return None
        url = artwork_target(ip, f"http://{ip}:{port}/", raw)
        if url is None or (not named_by_player and not is_player_url(ip, url)):
            return None
        return url

    async def fetch_artwork(
        self, endpoint: str, image_url: str, *, named_by_player: bool = False
    ) -> tuple[bytes, str] | None:
        """Fetch cover art for a player, as bytes and the media type judged from them.

        The browser never opens the cover URL. Set ``named_by_player`` only when
        ``image_url`` is the image that a player reported.
        """
        resolved = self._resolve_target(endpoint)
        if not resolved:
            return None
        ip, port = resolved
        if not self.settings.is_allowed_device_ip(ip):
            return None
        url = self._artwork_fetch_url(
            ip, port, (image_url or "").strip(), named_by_player=named_by_player
        )
        if url is None:
            return None
        try:
            async with self._sem:
                async with self._endpoint_slot(format_endpoint(ip, port)):
                    body = await self._follow_artwork_get(
                        ip,
                        url,
                        timeout=self.settings.device_http_timeout,
                    )
        except (httpx.TimeoutException, httpx.TransportError, OSError):
            return None
        media = image_media_type(body) if body else None
        if body is None or media is None:
            return None
        return body, media
