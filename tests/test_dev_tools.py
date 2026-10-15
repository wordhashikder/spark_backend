"""Development helpers: the unsent-email outbox and the demo accounts."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Installer
from app.services import email as emails
from app.services import seeding


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


async def test_demo_seed_gives_only_three_installers_a_login(db: AsyncSession):
    created = await seeding.seed_demo(db)
    assert created == 3
    claimed = list(
        await db.scalars(
            select(Installer.business_name)
            .where(Installer.user_id.is_not(None))
            .order_by("business_name")
        )
    )
    assert claimed == sorted(seeding.DEMO_ACTIVE_INSTALLERS)
    # Running it again changes nothing.
    assert await seeding.seed_demo(db) == 3


def _customer():
    from app.models import Customer

    return Customer(email="a@example.com", first_name="Sam")
