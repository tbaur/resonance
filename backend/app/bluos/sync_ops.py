# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Multi-room sync add/remove and orphan reparent-ungroup."""

from __future__ import annotations

import asyncio
import logging
import time

from app.bluos.result import CallResult, classify_control_body, note_control_result
from app.bluos.status import BluOSStatusMixin
from app.validators import DEFAULT_BLUOS_PORT, format_endpoint

logger = logging.getLogger(__name__)


class BluOSSyncMixin(BluOSStatusMixin):
    # Orphan ungroup verification (BluOS may need a short settle after RemoveSlave).
    _ungroup_verify_attempts = 6
    _ungroup_verify_delay = 0.25
    # Reparenting an orphan tries one donor after another. Bound the whole
    # attempt so one ungroup request cannot hold the HTTP request for minutes.
    _reparent_max_donors = 3
    _reparent_budget_seconds = 30.0

    async def _sync_call(self, endpoint: str, path: str, query: str) -> CallResult:
        """A sync control GET, judged like a status read: an empty reply is a failure.

        The outcome is recorded for the API log, like every other control call.
        """
        transport = await self._transport_get(endpoint, path, query=query, control=True)
        if not transport.ok:
            note_control_result(transport)
            return transport
        result = classify_control_body(transport.body, self.settings, endpoint)
        note_control_result(result)
        return result

    def _bluos_response_ok(self, content: bytes | None, context: str = "") -> bool:
        """True when BluOS returned a non-error XML body (structure-capped parse)."""
        return classify_control_body(
            content,
            self.settings,
            context or "bluos",
        ).ok

    async def player_is_ungrouped(self, endpoint: str) -> bool | None:
        """Return True if standalone, False if still has a master, None if unreachable."""
        resolved = self._resolve_target(endpoint)
        if not resolved:
            return None
        ep = format_endpoint(*resolved)
        raw = await self._get(ep, "/SyncStatus")
        if not self._bluos_response_ok(raw, ep):
            return None
        assert raw is not None
        sync = self._parse_sync(raw, ep)
        return not bool(sync.get("master"))

    async def player_is_muted(self, endpoint: str) -> bool | None:
        """Live mute from /SyncStatus. None when the player did not answer."""
        resolved = self._resolve_target(endpoint)
        if not resolved:
            return None
        ep = format_endpoint(*resolved)
        raw = await self._get(ep, "/SyncStatus")
        if not self._bluos_response_ok(raw, ep):
            return None
        assert raw is not None
        muted = self._parse_sync(raw, ep).get("muted")
        return muted if isinstance(muted, bool) else None

    async def _wait_until_ungrouped(self, slave_ep: str) -> bool:
        attempts = max(1, self._ungroup_verify_attempts)
        delay = max(0.0, self._ungroup_verify_delay)
        for _ in range(attempts):
            state = await self.player_is_ungrouped(slave_ep)
            if state is True:
                return True
            if delay:
                await asyncio.sleep(delay)
        return (await self.player_is_ungrouped(slave_ep)) is True

    async def _ungroup_via_reparent(
        self,
        slave_ep: str,
        donor_endpoints: list[str],
    ) -> bool:
        """Clear orphaned ``master reconnecting`` by briefly attaching to a live donor."""
        slave = self._resolve_target(slave_ep)
        if not slave:
            return False
        slave_host, slave_port = slave
        slave_ep = format_endpoint(slave_host, slave_port)
        remove_query = f"slave={slave_host}&port={slave_port}"
        deadline = time.monotonic() + self._reparent_budget_seconds
        tried = 0

        for donor in donor_endpoints:
            if tried >= self._reparent_max_donors or time.monotonic() >= deadline:
                logger.warning("reparent_ungroup_gave_up slave=%s donors_tried=%s", slave_ep, tried)
                break
            donor_resolved = self._resolve_target(donor)
            if not donor_resolved:
                continue
            donor_ep = format_endpoint(*donor_resolved)
            if donor_ep == slave_ep:
                continue
            tried += 1
            if not await self.add_sync_slave(donor_ep, slave_ep):
                continue
            for _ in range(3):
                res = await self._sync_call(donor_ep, "/RemoveSlave", remove_query)
                if res.ok and await self._wait_until_ungrouped(slave_ep):
                    return True
                if time.monotonic() >= deadline:
                    break
            logger.error(
                "reparent_ungroup_failed slave=%s donor=%s",
                slave_ep,
                donor_ep,
            )
            # Best-effort leave this donor, verify clear, then try the next.
            await self._sync_call(donor_ep, "/RemoveSlave", remove_query)
            if slave_port == DEFAULT_BLUOS_PORT:
                await self._sync_call(donor_ep, "/Sync", f"remove={slave_host}")
            await self._wait_until_ungrouped(slave_ep)
        return False

    async def add_sync_slave(self, master_target: str, slave_target: str) -> bool:
        master = self._resolve_target(master_target)
        slave = self._resolve_target(slave_target)
        if not master or not slave:
            return False
        master_ip, master_port = master
        slave_ip, slave_port = slave
        master_ep = format_endpoint(master_ip, master_port)
        added = await self._sync_call(master_ep, "/AddSlave", f"slave={slave_ip}&port={slave_port}")
        if added.ok:
            return True
        # The legacy /Sync call names the follower by address alone, which means
        # its primary zone on :11000. For any other zone it would group the wrong one.
        if slave_port != DEFAULT_BLUOS_PORT:
            return False
        legacy = await self._sync_call(master_ep, "/Sync", f"slave={slave_ip}")
        return legacy.ok

    async def remove_sync_slave(
        self,
        master_target: str,
        slave_target: str,
        *,
        donor_endpoints: list[str] | None = None,
    ) -> bool:
        """Remove slave from a sync group.

        Prefer ``RemoveSlave`` on the primary. If the primary is offline (orphaned
        reconnecting group), try the slave, then reparent onto a live donor and remove.
        """
        master = self._resolve_target(master_target)
        slave = self._resolve_target(slave_target)
        if not master or not slave:
            return False
        master_ip, master_port = master
        slave_ip, slave_port = slave
        master_ep = format_endpoint(master_ip, master_port)
        slave_ep = format_endpoint(slave_ip, slave_port)
        calls = [("/RemoveSlave", f"slave={slave_ip}&port={slave_port}")]
        # Legacy /Sync names the follower by address only (its :11000 zone).
        if slave_port == DEFAULT_BLUOS_PORT:
            calls.append(("/Sync", f"remove={slave_ip}"))

        async def _try_remove(on_ep: str) -> bool:
            for path, query in calls:
                res = await self._sync_call(on_ep, path, query)
                if res.ok and await self._wait_until_ungrouped(slave_ep):
                    return True
            return False

        if await _try_remove(master_ep) or await _try_remove(slave_ep):
            return True

        # Dead primary leaves slaves stuck with reconnecting=true; API self-unjoin
        # returns <error>no slave available as new master</error>.
        donors = list(donor_endpoints or [])
        if await self._ungroup_via_reparent(slave_ep, donors):
            return True
        return False
