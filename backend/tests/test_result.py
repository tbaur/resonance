# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""How a control reply is judged, and what a failure records."""

from __future__ import annotations

import pytest

from app.bluos.result import (
    CallResult,
    classify_control_body,
    note_control_result,
    take_control_result,
)
from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings()


def test_a_failed_result_is_falsy_so_callers_must_test_for_none() -> None:
    """The bug this guards: ``kind if failure else "failed"`` hid every real kind."""
    failure = CallResult.failure("timeout", "ReadTimeout")
    assert not failure
    assert failure is not None
    assert CallResult.success(b"<ok/>")


def test_failure_detail_is_one_line_and_capped() -> None:
    detail = "line one\nline two " + "x" * 500
    result = CallResult.failure("bluos_error", detail)
    assert "\n" not in result.detail
    assert len(result.detail) == 200


def test_take_control_result_clears_it() -> None:
    note_control_result(CallResult.failure("http_status", "404"))
    taken = take_control_result()
    assert taken is not None and taken.kind == "http_status"
    assert take_control_result() is None


@pytest.mark.parametrize(
    ("body", "kind", "detail"),
    [
        (b"<error>no slave available</error>", "bluos_error", "no slave available"),
        (b"<status><error>busy</error></status>", "bluos_error", "busy"),
        (b"<status><error/></status>", "bluos_error", "status"),
        (b"<syncError/>", "bluos_error", "syncerror"),
        (b"plain text", "bluos_error", "unparsed"),
        (b"<broken", "bluos_error", "unparsed"),
        (b"", "empty", ""),
        (None, "empty", ""),
    ],
)
def test_classify_failures(settings: Settings, body: bytes | None, kind: str, detail: str) -> None:
    result = classify_control_body(body, settings, "test")
    assert not result.ok
    assert (result.kind, result.detail) == (kind, detail)


def test_classify_successes(settings: Settings) -> None:
    assert classify_control_body(b"<volume>20</volume>", settings, "test").ok
    assert classify_control_body(b"", settings, "test", empty_ok=True).ok
    assert classify_control_body(b"ok", settings, "test", allow_plain=True).ok
    # An empty reply is never a success for a missing body.
    assert not classify_control_body(None, settings, "test", empty_ok=True).ok
