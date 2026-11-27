# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Fixtures shared by every test module."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def short_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep device retry backoff short. Its length matters only to the tests that check it."""
    monkeypatch.setattr("app.bluos.transport._backoff_seconds", lambda _attempt: 0.001)


@pytest.fixture(autouse=True)
def cover_hosts_resolve_to_themselves(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cover tests mock hosts by name and must not use real DNS.

    A test marked ``real_cover_dns`` keeps the real check, with its own resolver stub.
    """
    if request.node.get_closest_marker("real_cover_dns"):
        return

    async def passthrough(_self: object, host: str) -> str:
        return host

    monkeypatch.setattr("app.bluos.transport.BluOSTransport._artwork_address", passthrough)
