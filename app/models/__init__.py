"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.billing import StripeEvent
from app.models.blog import BlogPost
from app.models.contact import ContactMessage
from app.models.enquiry import InstallerEnquiry
from app.models.installer import Installer, InstallerAccreditation, InstallerPhoto
from app.models.location import Location
from app.models.quote import QuoteMatch, QuoteRequest
from app.models.review import Review
from app.models.user import AuthToken, RefreshToken, User

__all__ = [
    "AuthToken",
    "Base",
    "BlogPost",
    "ContactMessage",
    "Installer",
    "InstallerAccreditation",
    "InstallerEnquiry",
    "InstallerPhoto",
    "Location",
    "QuoteMatch",
    "QuoteRequest",
    "RefreshToken",
    "Review",
    "StripeEvent",
    "User",
]
