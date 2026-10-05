"""Customer reviews of installers."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ReviewStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.installer import Installer


class Review(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        Index("ix_reviews_installer_id_status_created_at", "installer_id", "status", "created_at"),
        Index("ix_reviews_status_created_at", "status", "created_at"),
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    # Present when the review came from a review invitation, which makes it "verified".
    quote_match_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quote_matches.id", ondelete="SET NULL"), unique=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger)
    title: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str] = mapped_column(String(60))
    author_location: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[ReviewStatus] = mapped_column(
        pg_enum(ReviewStatus, "review_status"),
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    installer: Mapped[Installer] = relationship(lazy="raise")

    @property
    def verified(self) -> bool:
        return self.quote_match_id is not None
