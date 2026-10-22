"""API token and session cookie values."""

from __future__ import annotations

import hashlib
import hmac

SESSION_COOKIE = "resonance_session"
# Lowercase: ASGI delivers header names lowercased.
REQUEST_HEADER = b"x-resonance-request"
_SESSION_LABEL = b"resonance session v1"


def session_cookie_value(token: bytes) -> bytes:
    """Cookie value for a session opened with ``token``.

    Derived rather than the token itself, so cookie storage never holds the
    credential. Changing RESONANCE_API_TOKEN invalidates every cookie.
    """
    return hmac.new(token, _SESSION_LABEL, hashlib.sha256).hexdigest().encode("ascii")
