# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""mDNS discovery unit tests with Zeroconf mocked."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.discovery.mdns import MDNSDiscovery, StandingMDNS


def test_mdns_discover_collects_ipv4_addresses() -> None:
    fake_info = MagicMock()
    fake_info.addresses = [bytes((192, 168, 1, 50))]
    fake_info.port = 11000

    with (
        patch("app.discovery.mdns.Zeroconf") as zc_cls,
        patch("app.discovery.mdns.ServiceBrowser") as browser_cls,
        patch("app.discovery.mdns.time.sleep", return_value=None),
    ):
        zc = zc_cls.return_value
        zc.get_service_info.return_value = fake_info

        def fake_browser(_zc, _service, handlers):
            handler = handlers[0]
            from zeroconf import ServiceStateChange

            handler(_zc, "_musc._tcp.local.", "Node._musc._tcp.local.", ServiceStateChange.Added)
            return MagicMock(cancel=MagicMock())

        browser_cls.side_effect = fake_browser
        endpoints = MDNSDiscovery(timeout=0.01).discover()

    assert endpoints == ["192.168.1.50:11000"]
    assert browser_cls.call_count == 2  # _musc + _musp
    zc.close.assert_called_once()


def test_mdns_discover_keeps_musp_srv_port() -> None:
    fake_info = MagicMock()
    fake_info.addresses = [bytes((192, 168, 1, 30))]
    fake_info.port = 11010

    with (
        patch("app.discovery.mdns.Zeroconf") as zc_cls,
        patch("app.discovery.mdns.ServiceBrowser") as browser_cls,
        patch("app.discovery.mdns.time.sleep", return_value=None),
    ):
        zc = zc_cls.return_value
        zc.get_service_info.return_value = fake_info

        def fake_browser(_zc, service, handlers):
            handler = handlers[0]
            from zeroconf import ServiceStateChange

            if service == "_musp._tcp.local.":
                handler(_zc, service, "Zone._musp._tcp.local.", ServiceStateChange.Added)
            return MagicMock(cancel=MagicMock())

        browser_cls.side_effect = fake_browser
        endpoints = MDNSDiscovery(timeout=0.01).discover()

    assert "192.168.1.30:11010" in endpoints


def test_standing_browser_resolves_off_the_callback() -> None:
    from zeroconf import ServiceStateChange

    fake_info = MagicMock()
    fake_info.addresses = [bytes((192, 168, 1, 50))]
    fake_info.port = 11000

    with (
        patch("app.discovery.mdns.Zeroconf") as zc_cls,
        patch("app.discovery.mdns.ServiceBrowser") as browser_cls,
    ):
        zc = zc_cls.return_value
        zc.get_service_info.return_value = fake_info

        def fake_browser(_zc, service, handlers):
            handler = handlers[0]
            handler(_zc, service, "Node._musc._tcp.local.", ServiceStateChange.Added)
            return MagicMock(cancel=MagicMock())

        browser_cls.side_effect = fake_browser
        browser = StandingMDNS()
        browser.start()
        try:
            found = []
            for _ in range(40):
                found = browser.endpoints()
                if found:
                    break
                time.sleep(0.05)
            assert found == ["192.168.1.50:11000"]
            browser._on_change(
                zeroconf=zc,
                service_type="_musc._tcp.local.",
                name="Node._musc._tcp.local.",
                state_change=ServiceStateChange.Removed,
            )
            assert browser.endpoints() == []
        finally:
            browser.stop()


def test_endpoint_from_service_info_skips_empty() -> None:
    from app.discovery.mdns import endpoint_from_service_info

    assert endpoint_from_service_info(None) is None


def test_stale_retry_generation_is_dropped() -> None:
    browser = StandingMDNS()
    browser.running = True
    browser._note_retry("_musc._tcp.local.", "node", 0)
    browser._generation["node"] = 1
    browser._retry_after["node"] = 0
    assert browser._due_retries() == []


def test_failed_lookup_is_queued_again() -> None:
    browser = StandingMDNS()
    browser.running = True
    browser._note_retry("_musc._tcp.local.", "node", 0)
    assert browser._due_retries() == []
    browser._retry_after["node"] = 0
    assert browser._due_retries() == [("_musc._tcp.local.", "node", 0)]
    browser._note_retry("_musc._tcp.local.", "node", 0)
    browser._retry_after["node"] = 0
    browser._bump("node")
    assert browser._due_retries() == []


def test_removed_service_is_not_restored_by_a_late_lookup() -> None:
    browser = StandingMDNS()
    browser.running = True
    browser._apply_resolved("node", "192.168.1.50:11000", 0)
    assert browser.endpoints() == ["192.168.1.50:11000"]
    browser._bump("node")
    browser.forget("node")
    browser._apply_resolved("node", "192.168.1.50:11000", 0)
    assert browser.endpoints() == []


def test_standing_mdns_membership_updates_without_a_new_browser() -> None:
    browser = StandingMDNS()
    browser.running = True
    browser._apply_resolved("node", "192.168.1.50:11000", 0)
    browser._apply_resolved("zone", "192.168.1.30:11010", 0)
    assert browser.endpoints() == ["192.168.1.30:11010", "192.168.1.50:11000"]
    browser.forget("zone")
    assert browser.endpoints() == ["192.168.1.50:11000"]


def test_standing_mdns_restarts_its_resolve_thread_after_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop() sets the stop event. start() must clear it, or the new thread exits at once."""

    class FakeZeroconf:
        def close(self) -> None:
            return None

    monkeypatch.setattr("app.discovery.mdns.Zeroconf", FakeZeroconf)
    monkeypatch.setattr("app.discovery.mdns.ServiceBrowser", lambda *a, **k: _NoBrowser())
    browser = StandingMDNS()
    browser.start()
    browser.stop()
    browser.start()
    try:
        assert not browser._stop.is_set()
        assert browser._thread is not None and browser._thread.is_alive()
    finally:
        browser.stop()


class _NoBrowser:
    def cancel(self) -> None:
        return None


@pytest.mark.parametrize(
    ("addresses", "port", "expected"),
    [
        ([], 11000, []),
        ([bytes((192, 168, 1, 50))], 0, ["192.168.1.50:11000"]),
        ([bytes((192, 168, 1, 50))], 80, ["192.168.1.50:11000"]),
        ([bytes(16), bytes((192, 168, 1, 51))], 11020, ["192.168.1.51:11020"]),
    ],
)
def test_endpoints_from_service_info(
    addresses: list[bytes], port: int, expected: list[str]
) -> None:
    """Bad ports fall back to 11000, and IPv6 or malformed addresses are skipped."""
    from app.discovery.mdns import endpoint_from_service_info, endpoints_from_service_info

    info = MagicMock(addresses=addresses, port=port)
    assert endpoints_from_service_info(info) == expected
    assert endpoint_from_service_info(info) == (expected[0] if expected else None)
    assert endpoints_from_service_info(None) == []


def test_mdns_discover_ignores_removed_services() -> None:
    from zeroconf import ServiceStateChange

    with (
        patch("app.discovery.mdns.Zeroconf") as zc_cls,
        patch("app.discovery.mdns.ServiceBrowser") as browser_cls,
        patch("app.discovery.mdns.time.sleep", return_value=None),
    ):
        zc = zc_cls.return_value

        def fake_browser(_zc, service, handlers):
            handlers[0](_zc, service, "Gone._musc._tcp.local.", ServiceStateChange.Removed)
            return MagicMock(cancel=MagicMock())

        browser_cls.side_effect = fake_browser
        assert MDNSDiscovery(timeout=0.01).discover() == []
        zc.get_service_info.assert_not_called()


def test_standing_mdns_stays_off_when_zeroconf_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> None:
        raise OSError("no multicast")

    monkeypatch.setattr("app.discovery.mdns.Zeroconf", broken)
    browser = StandingMDNS()
    browser.start()
    assert browser.running is False
    assert browser._thread is None


def test_a_failed_lookup_is_retried_later_with_a_growing_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr("app.discovery.mdns.time.monotonic", lambda: clock["now"])
    browser = StandingMDNS()
    browser.running = True
    browser._note_retry("_musc._tcp.local.", "node", 0)
    assert browser._due_retries() == []
    clock["now"] += 1.0
    assert browser._due_retries() == [("_musc._tcp.local.", "node", 0)]
    browser._note_retry("_musc._tcp.local.", "node", 0)
    clock["now"] += 1.0
    assert browser._due_retries() == []
    clock["now"] += 1.0
    assert browser._due_retries() == [("_musc._tcp.local.", "node", 0)]


def test_a_retry_for_a_service_that_left_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr("app.discovery.mdns.time.monotonic", lambda: clock["now"])
    browser = StandingMDNS()
    browser.running = True
    browser._note_retry("_musc._tcp.local.", "node", 0)
    # The service left before the retry came due; the old generation is stale.
    with browser._lock:
        browser._generation["node"] = 1
    clock["now"] += 5.0
    assert browser._due_retries() == []
    # A stopped browser schedules nothing.
    browser.running = False
    browser._note_retry("_musc._tcp.local.", "node", 1)
    assert browser._retry_after == {}


def test_the_resolve_loop_retries_a_lookup_that_raises() -> None:
    browser = StandingMDNS()
    browser.running = True
    zc = MagicMock()
    zc.get_service_info.side_effect = RuntimeError("lookup failed")
    browser._zc = zc
    noted: list[tuple[str, str, int]] = []

    def note(service_type: str, name: str, generation: int) -> None:
        noted.append((service_type, name, generation))
        browser._stop.set()

    browser._note_retry = note  # type: ignore[method-assign]
    browser._queue.put(("_musc._tcp.local.", "node", 0))
    browser._resolve_loop()
    assert noted == [("_musc._tcp.local.", "node", 0)]
