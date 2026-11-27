# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Orchestrates mDNS/LSDP discovery and BluOS enrichment."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.bluos.client import BluOSClient
from app.config import Settings
from app.discovery.lsdp import LSDPDevice, LSDPDiscovery
from app.discovery.mdns import BLUOS_MDNS_SERVICES, MDNSDiscovery, StandingMDNS
from app.models import PlayerStatus
from app.services.sync import drop_stale_follower_claims
from app.validators import (
    DEFAULT_BLUOS_PORT,
    format_endpoint,
    make_device_id,
    normalize_bluos_mac,
    parse_endpoint,
    sanitize_endpoint,
)

logger = logging.getLogger(__name__)

# A player that the poller still reaches is kept through this many browses that
# miss it. One lost LSDP reply or mDNS announce must not drop a working room.
_MISSED_BROWSES_BEFORE_REMOVAL = 3


@dataclass
class DiscoveredEndpoint:
    ip: str
    port: int = DEFAULT_BLUOS_PORT
    node_id: str = ""

    @property
    def endpoint(self) -> str:
        return format_endpoint(self.ip, self.port)


@dataclass
class DiscoverySnapshot:
    devices: list[PlayerStatus] = field(default_factory=list)
    endpoints: dict[str, DiscoveredEndpoint] = field(default_factory=dict)
    discovered_at: float | None = None
    method_used: str = ""
    # device_id -> canonical ip:port
    endpoints_by_id: dict[str, str] = field(default_factory=dict)
    # canonical ip:port -> device_id
    ids_by_endpoint: dict[str, str] = field(default_factory=dict)


def _hardware_key(player: PlayerStatus) -> tuple[str, int] | None:
    """Chassis MAC and API port: the same player wherever DHCP puts it."""
    mac = normalize_bluos_mac(player.mac)
    return (mac, player.port) if mac else None


class DiscoveryService:
    def __init__(self, settings: Settings, client: BluOSClient) -> None:
        self.settings = settings
        self.client = client
        self._data_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._snapshot = DiscoverySnapshot()
        self._grace_until: dict[str, float] = {}
        self._grace_endpoints: dict[str, str] = {}
        self._grace_macs: dict[str, str] = {}
        self._grace_confirmed_until: dict[str, float] = {}
        self._state_rev: dict[str, int] = {}
        self._missed_browses: dict[str, int] = {}
        self.mdns = StandingMDNS()

    @property
    def snapshot(self) -> DiscoverySnapshot:
        return self._snapshot

    def is_known_id(self, device_id: str) -> bool:
        if device_id in self._snapshot.endpoints_by_id:
            return True
        return time.time() < self._grace_until.get(device_id, 0.0)

    def is_in_grace(self, device_id: str) -> bool:
        """True when the id is only reachable via discovered-grace TTL."""
        if device_id in self._snapshot.endpoints_by_id:
            return False
        return time.time() < self._grace_until.get(device_id, 0.0)

    def is_known_endpoint(self, endpoint: str) -> bool:
        """True for a live endpoint, unexpired grace, or a master a live player names.

        After a restart the grace table is empty. A follower that still reports its
        primary is enough to ungroup that orphan. An address nobody in the fleet
        names is not.
        """
        canonical = sanitize_endpoint(endpoint, default_port=self.settings.bluos_port)
        if not canonical:
            return False
        if canonical in self._snapshot.ids_by_endpoint:
            return True
        now = time.time()
        for device_id, grace_ep in self._grace_endpoints.items():
            if grace_ep == canonical and now < self._grace_until.get(device_id, 0.0):
                return True
        for device in self._snapshot.devices:
            claimed = sanitize_endpoint(device.master, default_port=self.settings.bluos_port)
            if claimed == canonical:
                return True
        return False

    def grace_mac(self, device_id: str) -> str:
        if not self.is_in_grace(device_id):
            return ""
        return self._grace_macs.get(device_id, "")

    def grace_recently_confirmed(self, device_id: str) -> bool:
        return time.monotonic() < self._grace_confirmed_until.get(device_id, 0.0)

    def note_grace_confirmed(self, device_id: str) -> None:
        self._grace_confirmed_until[device_id] = time.monotonic() + 30.0

    def state_revision(self, device_id: str) -> int:
        """Bumps when a newer status is stored. A failed poll must not overwrite it."""
        return self._state_rev.get(device_id, 0)

    def clear_grace(self, device_id: str) -> None:
        self._grace_until.pop(device_id, None)
        self._grace_endpoints.pop(device_id, None)
        self._grace_macs.pop(device_id, None)
        self._grace_confirmed_until.pop(device_id, None)

    def same_endpoint(self, left: str | None, right: str | None) -> bool:
        if not left or not right:
            return False
        port = self.settings.bluos_port
        return sanitize_endpoint(left, default_port=port) == sanitize_endpoint(
            right, default_port=port
        )

    def resolve_endpoint(self, device_id: str) -> str | None:
        endpoint = self._snapshot.endpoints_by_id.get(device_id)
        if endpoint:
            return endpoint
        if time.time() < self._grace_until.get(device_id, 0.0):
            return self._grace_endpoints.get(device_id)
        return None

    def get_device(self, device_id: str) -> PlayerStatus | None:
        for device in self._snapshot.devices:
            if device.id == device_id:
                return device
        return None

    def control_devices(self, device_ids: list[str] | None = None) -> list[PlayerStatus]:
        """Online players from the live snapshot. Never browses or re-enriches.

        Offline rooms are omitted so a dead player cannot stall mute-all
        behind ``RESONANCE_DEVICE_HTTP_TIMEOUT``.
        """
        devices = list(self._snapshot.devices)
        if device_ids is not None:
            by_id = {device.id: device for device in devices}
            devices = [by_id[device_id] for device_id in device_ids if device_id in by_id]
        return [device for device in devices if device.status == "online"]

    def cache_fresh(self) -> bool:
        """True when the last discovery result (including empty) is still within TTL.

        Empty fleets use ``empty_fleet_rediscovery_seconds`` so API/REST-fallback
        paths do not re-run a full mDNS+LSDP window on every request.
        """
        if self._snapshot.discovered_at is None:
            return False
        age = time.time() - self._snapshot.discovered_at
        if not self._snapshot.devices:
            return age < self.settings.empty_fleet_rediscovery_seconds
        return age < self.settings.discovery_cache_ttl

    async def refresh(self) -> DiscoverySnapshot:
        """Run discovery and enrich (poller clock and explicit rescan).

        Discover and enrich run outside the data lock, and the snapshot is
        swapped in one step.
        """
        async with self._refresh_lock:
            async with self._data_lock:
                previous_ids = set(self._snapshot.endpoints_by_id)
                previous_endpoints = dict(self._snapshot.endpoints_by_id)
                previous_macs = {device.id: device.mac for device in self._snapshot.devices}

            endpoints, method_used = await self._discover_endpoints()
            # Membership comes from the browse. Playback state stays with the
            # poller, so a short /Status during a held long-poll cannot delete
            # a room or rewind a volume the poller already published.
            async with self._data_lock:
                live_endpoints = {device.endpoint for device in self._snapshot.devices}
            to_enrich = [
                endpoint for endpoint in endpoints if endpoint.endpoint not in live_endpoints
            ]
            enriched = await self._enrich(to_enrich)
            enriched_by_endpoint = {player.endpoint: player for player in enriched}
            now = time.time()

            async with self._data_lock:
                live_by_endpoint = {device.endpoint: device for device in self._snapshot.devices}
                players: list[PlayerStatus] = []
                for endpoint in endpoints:
                    current = live_by_endpoint.get(endpoint.endpoint)
                    if current is not None:
                        # A poll that landed during enrich wins over the copy we saw earlier.
                        players.append(current)
                        continue
                    created = enriched_by_endpoint.get(endpoint.endpoint)
                    if created is not None:
                        players.append(created)

                players.extend(self._retained_players(players, live_by_endpoint))
                players = drop_stale_follower_claims(players)
                new_ids = {player.id for player in players}
                for missing in previous_ids - new_ids:
                    self._grace_until[missing] = now + self.settings.discovered_grace_ttl
                    grace_ep = previous_endpoints.get(missing)
                    if grace_ep:
                        self._grace_endpoints[missing] = grace_ep
                    mac = previous_macs.get(missing, "")
                    if mac:
                        self._grace_macs[missing] = mac
                    else:
                        self._grace_macs.pop(missing, None)
                for present in new_ids:
                    self._grace_until.pop(present, None)
                    self._grace_endpoints.pop(present, None)
                    self._grace_macs.pop(present, None)

                endpoints_by_id = {player.id: player.endpoint for player in players}
                ids_by_endpoint = {player.endpoint: player.id for player in players}
                self._snapshot = DiscoverySnapshot(
                    devices=players,
                    endpoints={endpoint.endpoint: endpoint for endpoint in endpoints},
                    discovered_at=now,
                    method_used=method_used,
                    endpoints_by_id=endpoints_by_id,
                    ids_by_endpoint=ids_by_endpoint,
                )
                logger.info(
                    "discovery_complete count=%s method=%s",
                    len(players),
                    method_used,
                )
                return self._snapshot

    def _retained_players(
        self,
        found: list[PlayerStatus],
        live_by_endpoint: dict[str, PlayerStatus],
    ) -> list[PlayerStatus]:
        """Players this browse missed that the poller still reaches.

        Each one is kept until it has been missed ``_MISSED_BROWSES_BEFORE_REMOVAL``
        times in a row. A player the poller cannot reach is dropped at once, and
        so is one that this browse found at a new address (same MAC and port):
        its old row would otherwise stay up next to the new one while the held
        read on the old address waits out its timeout.
        Call with the data lock held.
        """
        found_ids = {player.id for player in found}
        found_endpoints = {player.endpoint for player in found}
        found_hardware = {_hardware_key(player) for player in found} - {None}
        kept: list[PlayerStatus] = []
        for endpoint, device in live_by_endpoint.items():
            if device.id in found_ids or endpoint in found_endpoints:
                self._missed_browses.pop(device.id, None)
                continue
            if _hardware_key(device) in found_hardware:
                self._missed_browses.pop(device.id, None)
                continue
            misses = self._missed_browses.get(device.id, 0) + 1
            reachable = device.status == "online" and not device.stale
            if reachable and misses < _MISSED_BROWSES_BEFORE_REMOVAL:
                self._missed_browses[device.id] = misses
                kept.append(device)
                logger.info(
                    "discovery_kept_unannounced",
                    extra={"device_id": device.id, "device_ip": endpoint},
                )
            else:
                self._missed_browses.pop(device.id, None)
        return kept

    async def _discover_endpoints(self) -> tuple[list[DiscoveredEndpoint], str]:
        method = self.settings.discovery_method
        by_endpoint: dict[str, DiscoveredEndpoint] = {}
        methods_run: list[str] = []

        run_mdns = method in ("mdns", "both")
        run_lsdp = method in ("lsdp", "both")
        standing = self.mdns.endpoints() if run_mdns and self.mdns.running else []

        mdns_task = (
            asyncio.to_thread(
                MDNSDiscovery(BLUOS_MDNS_SERVICES, self.settings.discovery_timeout).discover
            )
            if run_mdns and not standing
            else None
        )
        lsdp_task = (
            asyncio.to_thread(LSDPDiscovery(self.settings.discovery_timeout).discover)
            if run_lsdp
            else None
        )

        mdns_endpoints: list[str] = list(standing)
        lsdp_devices: list[LSDPDevice] = []
        if mdns_task is not None and lsdp_task is not None:
            mdns_endpoints, lsdp_devices = await asyncio.gather(mdns_task, lsdp_task)
        elif mdns_task is not None:
            mdns_endpoints = await mdns_task
        elif lsdp_task is not None:
            lsdp_devices = await lsdp_task

        if run_mdns:
            mdns_added = False
            for raw in mdns_endpoints:
                cleaned = sanitize_endpoint(raw, default_port=self.settings.bluos_port)
                if not cleaned:
                    continue
                ip, port = parse_endpoint(cleaned, default_port=self.settings.bluos_port)
                if not ip or not self.settings.is_allowed_device_ip(ip):
                    continue
                by_endpoint[cleaned] = DiscoveredEndpoint(ip=ip, port=port)
                mdns_added = True
            if mdns_added:
                methods_run.append("mdns")

        if run_lsdp:
            lsdp_added = False
            for device in lsdp_devices:
                if not self.settings.is_allowed_device_ip(device.ip):
                    continue
                port = device.port if device.port is not None else self.settings.bluos_port
                endpoint = format_endpoint(device.ip, port)
                existing = by_endpoint.get(endpoint)
                if existing is None or (device.node_id and not existing.node_id):
                    by_endpoint[endpoint] = DiscoveredEndpoint(
                        ip=device.ip,
                        port=port,
                        node_id=device.node_id,
                    )
                lsdp_added = True
            if lsdp_added:
                methods_run.append("lsdp")

        method_used = "+".join(methods_run) if methods_run else method
        return sorted(by_endpoint.values(), key=lambda e: e.endpoint), method_used

    async def _enrich(self, endpoints: list[DiscoveredEndpoint]) -> list[PlayerStatus]:
        """Keep only endpoints that answer SyncStatus successfully."""

        async def one(endpoint: DiscoveredEndpoint) -> PlayerStatus | None:
            device_id = make_device_id(
                endpoint.ip,
                node_id=endpoint.node_id,
                port=endpoint.port,
            )
            try:
                player = await self.client.get_player_status(
                    endpoint.endpoint,
                    device_id=device_id,
                    node_id=endpoint.node_id,
                )
            except Exception as exc:  # noqa: BLE001 — isolate per device
                # A discovered address that is not added to the fleet is the first
                # thing to look for when a room is missing, so log at INFO.
                logger.info(
                    "enrich_failed",
                    extra={"device_ip": endpoint.endpoint, "failure_kind": type(exc).__name__},
                )
                return None
            if player.status != "online":
                logger.info(
                    "enrich_unverified",
                    extra={"device_ip": endpoint.endpoint, "failure_kind": player.status},
                )
                return None
            return player

        results = await asyncio.gather(*(one(e) for e in endpoints))
        return [p for p in results if p is not None]

    async def update_device(
        self,
        player: PlayerStatus,
        *,
        expect_revision: int | None = None,
    ) -> bool:
        """Store a newer status for a player that is in the fleet.

        Returns False, and stores nothing, when ``expect_revision`` is stale or
        the player is no longer in the fleet. A read that finishes after a
        rescan removed its player must not add the player back: membership
        comes from discovery.
        """
        async with self._data_lock:
            current_rev = self._state_rev.get(player.id, 0)
            if expect_revision is not None and current_rev != expect_revision:
                return False
            if player.id not in self._snapshot.endpoints_by_id:
                return False
            self._state_rev[player.id] = current_rev + 1
            devices = [player if d.id == player.id else d for d in self._snapshot.devices]
            self._snapshot.devices = drop_stale_follower_claims(devices)
            self._snapshot.endpoints_by_id[player.id] = player.endpoint
            self._snapshot.ids_by_endpoint[player.endpoint] = player.id
            existing = self._snapshot.endpoints.get(
                player.endpoint,
                DiscoveredEndpoint(player.ip, player.port),
            )
            self._snapshot.endpoints[player.endpoint] = DiscoveredEndpoint(
                ip=player.ip,
                port=player.port,
                node_id=existing.node_id,
            )
            return True
