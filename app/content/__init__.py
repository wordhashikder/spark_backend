"""Editable website content: the registry of every page the Dashboard can edit.

Add a page by defining a `Document` in `app/content/pages/` and listing it here, then
run `python -m app.content --output ...` so the website's offline fallback
(`frontend/src/content/site-content.json`) carries the same original wording.
"""

from dataclasses import replace

from app.content.fields import ContentValidationError, Document, FieldType, closing_section
from app.content.pages.company import ABOUT, CONTACT, HOW_IT_WORKS
from app.content.pages.guides import ACCREDITATIONS, SAFETY, VETTING
from app.content.pages.help import FAQ, JOIN
from app.content.pages.home import HOME
from app.content.pages.hub import HUB
from app.content.pages.journeys import BLOG, GET_QUOTES, LOCATION
from app.content.pages.legal import COOKIES, PRIVACY, TERMS
from app.content.pages.site import SITE

# Pages that end with the "Find installers" footer also get an optional closing section.
_WITH_CLOSING = {
    "home",
    "installers-hub",
    "location",
    "about",
    "how-it-works",
    "contact",
    "faq",
    "join",
    "blog",
    "how-we-vet",
    "accreditations",
    "safety",
}


def _with_closing(document: Document) -> Document:
    if document.key not in _WITH_CLOSING:
        return document
    return replace(document, sections=(*document.sections, closing_section()))


# Shown in the Dashboard in this order.
DOCUMENTS: dict[str, Document] = {
    document.key: document
    for document in map(
        _with_closing,
        (
            SITE,
            HOME,
            HUB,
            LOCATION,
            GET_QUOTES,
            ABOUT,
            HOW_IT_WORKS,
            CONTACT,
            FAQ,
            JOIN,
            BLOG,
            VETTING,
            ACCREDITATIONS,
            SAFETY,
            PRIVACY,
            TERMS,
            COOKIES,
        ),
    )
}

# Words the website replaces when it shows the content.
TOKENS: dict[str, str] = {
    "{brand}": "The platform name (Settings › Organisation).",
    "{email}": "The support email (Settings › Organisation).",
    "{privacy_email}": "The privacy email (Site-wide content).",
    "{city}": "The town or city's name (location pages only).",
    "{price_free}": 'The Free plan\'s price, e.g. "£0 per month".',
    "{price_pro}": "The Pro plan's price.",
    "{price_premium}": "The Premium plan's price.",
    "{lowest_price}": 'The cheapest paid plan\'s price, e.g. "£29".',
}


def defaults() -> dict[str, dict]:
    """Every page's original wording, keyed by page."""
    return {key: document.defaults() for key, document in DOCUMENTS.items()}


__all__ = [
    "DOCUMENTS",
    "TOKENS",
    "ContentValidationError",
    "Document",
    "FieldType",
    "defaults",
]
