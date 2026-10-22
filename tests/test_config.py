"""Start-up checks on the settings."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_port_465_without_implicit_tls_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SMTP_PORT=465 needs SMTP_USE_TLS=true"):
        _settings(smtp_host="smtp.hostinger.com", smtp_port=465, smtp_start_tls=True)


def test_the_two_working_smtp_setups_are_accepted() -> None:
    implicit = _settings(
        smtp_host="smtp.hostinger.com", smtp_port=465, smtp_use_tls=True, smtp_start_tls=False
    )
    starttls = _settings(
        smtp_host="smtp.hostinger.com", smtp_port=587, smtp_use_tls=False, smtp_start_tls=True
    )
    assert implicit.smtp_use_tls
    assert starttls.smtp_start_tls


def test_both_tls_modes_together_are_rejected() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _settings(smtp_host="smtp.example.com", smtp_use_tls=True, smtp_start_tls=True)
