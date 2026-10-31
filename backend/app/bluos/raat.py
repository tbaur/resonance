# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""Audio format that Roon (RAAT) reports only inside ``streamUrl``.

Roon decodes on its server and sends the player PCM, so BluOS leaves
``streamFormat`` empty. The PCM shape is in the stream URL instead, for example
``Raat:raat_pcm01:pcm/48000/24/2/mqa=192000/18``. The layout is undocumented,
so only an exact match is trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RAAT_PCM = re.compile(
    r"^Raat:[A-Za-z0-9_]+:pcm/(?P<rate>\d{4,6})/(?P<bits>\d{1,2})/\d{1,2}"
    r"/(?:mqaCore=-?\d+|mqa=(?P<mqa>\d{4,6}))(?:/\d+)?$"
)
_MIN_RATE_HZ = 8_000
_MAX_RATE_HZ = 768_000
_MIN_BITS = 8
_MAX_BITS = 32


@dataclass(frozen=True)
class RaatFormat:
    """``stream_format`` in BluOS ``bits/kHz`` form, plus the MQA original rate (0 if none)."""

    stream_format: str
    mqa_original_rate: int


def _valid_rate(hz: int) -> bool:
    return _MIN_RATE_HZ <= hz <= _MAX_RATE_HZ


def parse_raat_stream_url(stream_url: str) -> RaatFormat | None:
    """Return the PCM format of a Roon stream, or None when the URL is not the known shape."""
    match = _RAAT_PCM.match(stream_url.strip())
    if match is None:
        return None
    rate = int(match["rate"])
    bits = int(match["bits"])
    mqa = int(match["mqa"]) if match["mqa"] else 0
    if not _valid_rate(rate) or not _MIN_BITS <= bits <= _MAX_BITS:
        return None
    if mqa and not _valid_rate(mqa):
        mqa = 0
    return RaatFormat(stream_format=f"PCM {bits}/{rate / 1000:g}", mqa_original_rate=mqa)
