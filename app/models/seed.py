"""Record of the content batches the seed has applied (see `services/seeding.py`)."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SeedBatch(Base):
    """A named set of content that is inserted once, like a data migration.

    Once applied it is never applied again, so records the admin edits or deletes
    afterwards stay as the admin left them.
    """

    __tablename__ = "seed_batches"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
