"""Settings validation and derived values."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_config_validators() -> None:
    assert Settings(host="0.0.0.0").host == "0.0.0.0"
    assert Settings(log_level="debug").log_level == "DEBUG"
    with pytest.raises(ValidationError):
        Settings(host="")
    with pytest.raises(ValidationError):
        Settings(host="not a host!!")
    with pytest.raises(ValidationError):
        Settings(log_level="VERBOSE")
    s = Settings(host="127.0.0.1", enable_openapi=None)
    assert s.openapi_enabled() is True
    s2 = Settings(host="0.0.0.0", enable_openapi=None)
    assert s2.openapi_enabled() is False
    s3 = Settings(enable_openapi=True, host="0.0.0.0")
    assert s3.openapi_enabled() is True
    assert Settings(cors_origins="a, b ,").cors_origin_list() == ["a", "b"]
    assert Settings(allow_non_private_ips=True).is_allowed_device_ip("8.8.8.8") is True
    assert Settings().is_allowed_device_ip("not-ip") is False
    assert Settings().is_allowed_device_ip("::1") is False


def test_settings_read_resonance_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESONANCE_PORT", "9123")
    monkeypatch.setenv("RESONANCE_LOG_LEVEL", "debug")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.delenv("RESONANCE_HOST", raising=False)
    settings = Settings(_env_file=None)
    assert settings.port == 9123
    assert settings.log_level == "DEBUG"
    assert settings.host == "127.0.0.1"
