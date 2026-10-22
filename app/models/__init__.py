"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.billing import BillingActivity, BillingInvoice, StripeEvent
from app.models.blog import BlogPost
from app.models.contact import ContactMessage
from app.models.conversation import Conversation, ConversationMessage, Offer
from app.models.customer import Customer, CustomerLoginLink, CustomerSession
from app.models.enquiry import InstallerEnquiry
from app.models.installer import Installer, InstallerAccreditation, InstallerPhoto
from app.models.location import Location
from app.models.plan import Plan, PlanPrice
from app.models.quote import QuoteMatch, QuoteRequest
from app.models.review import Review
from app.models.seed import SeedBatch
from app.models.settings import (
    PlatformSetting,
    RolePermission,
    SiteContent,
    SiteContentRevision,
)
from app.models.user import AuthToken, RefreshToken, User

__all__ = [
    "AuthToken",
    "Base",
    "BillingActivity",
    "BillingInvoice",
    "BlogPost",
    "ContactMessage",
    "Conversation",
    "ConversationMessage",
    "Customer",
    "CustomerLoginLink",
    "CustomerSession",
    "Installer",
    "InstallerAccreditation",
    "InstallerEnquiry",
    "InstallerPhoto",
    "Location",
    "Offer",
    "Plan",
    "PlanPrice",
    "PlatformSetting",
    "QuoteMatch",
    "QuoteRequest",
    "RefreshToken",
    "Review",
    "RolePermission",
    "SeedBatch",
    "SiteContent",
    "SiteContentRevision",
    "StripeEvent",
    "User",
]
