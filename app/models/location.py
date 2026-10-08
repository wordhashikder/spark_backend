"""Towns and cities that have a landing page."""

from sqlalchemy import Float, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DirectoryColumn
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class Location(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (
        # One location per slot, so a column never lists two towns at the same position.
        # Checked at commit, so the seed can reorder a whole column in one statement.
        UniqueConstraint(
            "directory_column",
            "directory_position",
            name="uq_locations_directory_slot",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    region: Mapped[str] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    # Place in the "Find trusted installers in your area" directory shown on every page:
    # the column and the 1-based position within it. A location sits in at most one column,
    # so no town is listed twice; locations without a column are not listed.
    directory_column: Mapped[DirectoryColumn | None] = mapped_column(
        pg_enum(DirectoryColumn, "directory_column")
    )
    directory_position: Mapped[int | None] = mapped_column(SmallInteger)
    # Content managed by the admin (see `PATCH /admin/locations/{slug}`); the seed file
    # never overwrites an admin's intro or uploaded photo.
    intro: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    image_alt: Mapped[str | None] = mapped_column(String(160))
    image_credit: Mapped[str | None] = mapped_column(String(160))
    # Set only for images uploaded to Cloudinary, so a replaced image can be deleted there.
    image_public_id: Mapped[str | None] = mapped_column(String(255))
