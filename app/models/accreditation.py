"""
The accreditation schemes an installer can list (NICEIC, NAPIT, ...), managed in the Dashboard.
"""

from sqlalchemy import Boolean, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AccreditationScheme(TimestampMixin, Base):
    __tablename__ = "accreditation_schemes"

    # Lower-case letters, numbers and hyphens; it never changes (installers refer to it and it
    # is the last part of the scheme's page address, /uk/accreditations/<key>/).
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    # Small label on the card: "Recognised Standard", "Gov. Endorsed", ...
    badge: Mapped[str | None] = mapped_column(String(40))
    card_title: Mapped[str] = mapped_column(String(80))
    card_text: Mapped[str] = mapped_column(String(400))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # A scheme that is off is not offered to installers; those who already list it keep it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
