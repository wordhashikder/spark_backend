"""Enumerations shared by the models, schemas and emails, with their human labels."""

from enum import StrEnum
from typing import Self


class LabelledEnum(StrEnum):
    """A string enum whose members also carry the label shown to people (e.g. in emails)."""

    label: str

    def __new__(cls, value: str, label: str) -> Self:
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member


class Role(StrEnum):
    INSTALLER = "installer"
    ADMIN = "admin"


class AuthTokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"  # noqa: S105 - a purpose name, not a credential


class MessageSender(StrEnum):
    INSTALLER = "installer"
    HOMEOWNER = "homeowner"
    TEAM = "team"  # PickASparky staff
    SYSTEM = "system"  # automatic notes, e.g. "Quote accepted"


class OfferStatus(StrEnum):
    """A priced quote an installer sends a homeowner."""

    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class InstallerSource(StrEnum):
    """How a business came to be listed."""

    REGISTERED = "registered"  # signed up through the website
    IMPORTED = "imported"  # added by PickASparky as a free basic listing; claimable


class InstallerStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class SubscriptionStatus(StrEnum):
    NONE = "none"
    INCOMPLETE = "incomplete"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class QuoteStatus(StrEnum):
    NEW = "new"
    MATCHED = "matched"
    UNMATCHED = "unmatched"


class LeadStatus(StrEnum):
    SENT = "sent"
    VIEWED = "viewed"
    CONTACTED = "contacted"
    WON = "won"
    LOST = "lost"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


class BlogPostStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class DirectoryColumn(StrEnum):
    """The four columns of the "Find trusted installers in your area" directory."""

    NEARBY = "nearby"
    POPULAR = "popular"
    MORE_IN_AREA = "more_in_area"
    OTHER = "other"


class Plan(LabelledEnum):
    FREE = "free", "Free"
    PRO = "pro", "Pro"
    PREMIUM = "premium", "Premium"


class AccreditationScheme(LabelledEnum):
    OZEV = "ozev", "OZEV"
    NAPIT = "napit", "NAPIT"
    NICEIC = "niceic", "NICEIC"
    TRUSTMARK = "trustmark", "TrustMark"
    MCS = "mcs", "MCS"
    ELECSA = "elecsa", "ELECSA"


class Service(LabelledEnum):
    EV_CHARGER_INSTALLATION = "ev_charger_installation", "EV charger installation"
    DOMESTIC_ELECTRICAL = "domestic_electrical", "Domestic electrical"
    COMMERCIAL_ELECTRICAL = "commercial_electrical", "Commercial electrical"
    ELECTRICAL_REPAIRS = "electrical_repairs", "Electrical repairs"
    SOLAR_BATTERY = "solar_battery", "Solar and battery storage"
    SMART_HOME = "smart_home", "Smart home"
    EICR_TESTING = "eicr_testing", "EICR and testing"


class InstallationType(LabelledEnum):
    NEW_HOME = "new_home", "New home EV charger"
    REPLACE_EXISTING = "replace_existing", "Replace an existing charger"
    ADDITIONAL = "additional", "Additional charger"
    WORKPLACE_COMMERCIAL = "workplace_commercial", "Workplace/commercial charger"
    NOT_SURE = "not_sure", "Not sure"


class ChargerLocation(LabelledEnum):
    HOUSE_WALL = "house_wall", "House wall"
    GARAGE = "garage", "Garage"
    DETACHED_GARAGE = "detached_garage", "Detached garage/outbuilding"
    POST_PEDESTAL = "post_pedestal", "Post/pedestal by the parking space"
    WORKPLACE_COMMERCIAL = "workplace_commercial", "Workplace/commercial property"
    OTHER = "other", "Other"
    NOT_SURE = "not_sure", "Not sure"


class ExistingCharger(LabelledEnum):
    NO = "no", "No"
    REPLACE = "replace", "Yes - wants to replace it"
    ADD_ANOTHER = "add_another", "Yes - wants to add another charger"


class ChargerFollowup(LabelledEnum):
    ALREADY_BOUGHT = "already_bought", "Has already bought a charger"
    CHOSEN_NOT_BOUGHT = "chosen_not_bought", "Knows which charger, but has not bought it yet"
    INSTALLER_RECOMMEND = "installer_recommend", "Would like the installer to recommend one"
    FIT_CUSTOMER_CHARGER = "fit_customer_charger", "Replace it with a charger already bought"
    SUPPLY_AND_INSTALL = "supply_and_install", "Supply and install a new charger"
    RECOMMEND_REPLACEMENT = "recommend_replacement", "Recommend a suitable replacement"
    NOT_SURE = "not_sure", "Not sure"


class FuseBoxDistance(LabelledEnum):
    VERY_CLOSE = "very_close", "Very close / same garage"
    INSIDE_HOUSE = "inside_house", "Inside the house"
    UNDER_10M = "under_10m", "Less than 10 metres away"
    OVER_10M = "over_10m", "More than 10 metres away"
    NOT_SURE = "not_sure", "Not sure"


class Timing(LabelledEnum):
    ASAP = "asap", "As soon as possible"
    WITHIN_2_WEEKS = "within_2_weeks", "Within 2 weeks"
    WITHIN_MONTH = "within_month", "Within a month"
    ONE_TO_THREE_MONTHS = "one_to_three_months", "Within 1-3 months"
    RESEARCHING = "researching", "Just researching prices"


class ContactSubject(LabelledEnum):
    GETTING_QUOTES = "getting_quotes", "Getting quotes"
    JOINING = "joining", "Joining as an installer"
    ACCOUNT = "account", "My account"
    FEEDBACK = "feedback", "Feedback"
    OTHER = "other", "Something else"


_NEW_CHARGER_FOLLOWUPS = frozenset(
    {
        ChargerFollowup.ALREADY_BOUGHT,
        ChargerFollowup.CHOSEN_NOT_BOUGHT,
        ChargerFollowup.INSTALLER_RECOMMEND,
        ChargerFollowup.NOT_SURE,
    }
)

# Which follow-up answers are valid for each answer to "do you already have a charger?".
CHARGER_FOLLOWUPS: dict[ExistingCharger, frozenset[ChargerFollowup]] = {
    ExistingCharger.NO: _NEW_CHARGER_FOLLOWUPS,
    ExistingCharger.ADD_ANOTHER: _NEW_CHARGER_FOLLOWUPS,
    ExistingCharger.REPLACE: frozenset(
        {
            ChargerFollowup.FIT_CUSTOMER_CHARGER,
            ChargerFollowup.SUPPLY_AND_INSTALL,
            ChargerFollowup.RECOMMEND_REPLACEMENT,
            ChargerFollowup.NOT_SURE,
        }
    ),
}
