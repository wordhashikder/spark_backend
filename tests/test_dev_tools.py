"""Development helper: the unsent-email outbox."""

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import email as emails


async def test_unsent_email_is_saved_for_development(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    sender = emails.SmtpEmailSender(Settings(environment="development", smtp_host=None))
    mail = emails.magic_link(_customer(), "https://site.test/uk/my-quotes/verify/?token=abc")
    await sender.send(mail)
    files = list((tmp_path / "dev-outbox").glob("*.html"))
    assert len(files) == 1
    assert "token=abc" in files[0].read_text()


def _customer():
    from app.models import Customer

    return Customer(email="a@example.com", first_name="Sam")
