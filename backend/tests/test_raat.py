# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Roon stream URL parsing: trust only the exact known shape."""

from __future__ import annotations

import pytest

from app.bluos.raat import RaatFormat, parse_raat_stream_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("Raat:raat_pcm01:pcm/44100/16/2/mqaCore=-1/3", RaatFormat("PCM 16/44.1", 0)),
        ("Raat:raat_pcm01:pcm/96000/24/2/mqaCore=-1/3", RaatFormat("PCM 24/96", 0)),
        ("Raat:raat_pcm01:pcm/48000/24/2/mqa=192000/3", RaatFormat("PCM 24/48", 192000)),
        ("Raat:raat_pcm01:pcm/44100/24/2/mqa=44100", RaatFormat("PCM 24/44.1", 44100)),
    ],
)
def test_parses_known_shapes(url: str, expected: RaatFormat) -> None:
    assert parse_raat_stream_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "Raat:raat_pcm01:dsd/2822400/1/2/mqaCore=-1/3",
        "Raat:raat_pcm01:pcm/44100/16/2",
        "Raat:raat_pcm01:pcm/100/16/2/mqaCore=-1/3",
        "Raat:raat_pcm01:pcm/44100/64/2/mqaCore=-1/3",
        "http://example.com/stream.flac",
    ],
)
def test_rejects_unknown_shapes(url: str) -> None:
    assert parse_raat_stream_url(url) is None


def test_drops_an_out_of_range_mqa_rate() -> None:
    assert parse_raat_stream_url("Raat:raat_pcm01:pcm/48000/24/2/mqa=1000/3") == RaatFormat(
        "PCM 24/48", 0
    )
