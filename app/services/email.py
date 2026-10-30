"""Transactional email: Jinja2 templates rendered to multipart messages, sent over SMTP.

Use cases build `Email` values; endpoints queue them on `BackgroundTasks` once the
transaction has committed. Sending never raises into a request.
"""

import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from pathlib import Path
from typing import Any, Protocol

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import Settings, get_settings
from app.core.enums import Service
from app.models import (
    ContactMessage,
    Conversation,
    Customer,
    Installer,
    InstallerEnquiry,
    Offer,
    QuoteRequest,
    User,
)
from app.services.geocoding import outward_code

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_SMTP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class Email:
    """A message to render from `templates/email/{template}.html|.txt` and send."""

    to: str
    subject: str
    template: str
    context: Mapping[str, Any] = field(default_factory=dict)
    reply_to: str | None = None
    # An alert for the PickASparky team: sent to the support address in Settings, and only
    # while email alerts are on (see `EmailQueue` in `app/api/deps.py`).
    team: bool = False
    # Overrides EMAIL_FROM_NAME (the platform name in Settings).
    from_name: str | None = None


class EmailSender(Protocol):
    async def send(self, email: Email) -> None: ...


class SmtpEmailSender:
    """Renders and sends email; logs the message instead when SMTP is not configured."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._templates = Environment(
            loader=FileSystemLoader(_TEMPLATE_DIR),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, email: Email) -> EmailMessage:
        settings = self._settings
        context = {
            "frontend_url": settings.frontend_url,
            "support_email": settings.support_email,
            "subject": email.subject,
            **email.context,
        }
        message = EmailMessage()
        message["From"] = formataddr(
            (email.from_name or settings.email_from_name, settings.email_from)
        )
        message["To"] = email.to
        message["Subject"] = email.subject
        message["Date"] = format_datetime(datetime.now(UTC))
        message["Message-ID"] = make_msgid(domain=settings.email_from.rpartition("@")[2])
        if email.reply_to:
            message["Reply-To"] = email.reply_to
        message.set_content(self._templates.get_template(f"{email.template}.txt").render(context))
        message.add_alternative(
            self._templates.get_template(f"{email.template}.html").render(context), subtype="html"
        )
        return message

    async def send(self, email: Email) -> None:
        try:
            message = self.render(email)
            if not self._settings.smtp_configured:
                self._log_unsent(email, message)
                return
            await aiosmtplib.send(
                message,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_username,
                password=self._settings.smtp_password,
                use_tls=self._settings.smtp_use_tls,
                start_tls=self._settings.smtp_start_tls,
                timeout=_SMTP_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Could not send %r email", email.template)
        else:
            logger.info("Sent %r email", email.template)

    def _log_unsent(self, email: Email, message: EmailMessage) -> None:
        if self._settings.is_production:
            # Bodies carry sign-in links, so production logs record only that it was dropped.
            logger.error("SMTP is not configured; dropped %r email", email.template)
            return
        body = message.get_body(preferencelist=("plain",))
        saved = self._save_to_dev_outbox(email, message)
        logger.info(
            "SMTP is not configured; email not sent%s.\nTo: %s\nSubject: %s\n\n%s",
            f" (open {saved} in a browser to read it)" if saved else "",
            email.to,
            email.subject,
            body.get_content() if body else "",
        )

    @staticmethod
    def _save_to_dev_outbox(email: Email, message: EmailMessage) -> Path | None:
        """Development only: keep an unsent email as an HTML file in `dev-outbox/`.

        Without an SMTP server nothing reaches a real inbox; this lets a developer open the
        email (magic link, claim invitation...) and click its buttons. Never used in
        production, where bodies carry sign-in links and are not stored.
        """
        html = message.get_body(preferencelist=("html",))
        if html is None:
            return None
        try:
            folder = Path("dev-outbox")
            folder.mkdir(exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            recipient = re.sub(r"[^a-z0-9]+", "-", email.to.lower()).strip("-")
            path = folder / f"{stamp}-{email.template}-{recipient}.html"
            path.write_text(html.get_content(), encoding="utf-8")
        except OSError:
            logger.warning("Could not write the development outbox", exc_info=True)
            return None
        return path.resolve()


def quote_summary(quote: QuoteRequest) -> list[tuple[str, str]]:
    """The customer's answers as `(question, answer)` rows for emails."""
    if quote.vehicle:
        vehicle = quote.vehicle
    elif quote.vehicle_undecided:
        vehicle = "Not chosen yet"
    else:
        vehicle = "Not provided"
    rows = [
        ("Postcode", quote.postcode),
        ("Installation type", quote.installation_type.label),
        ("Charger location", quote.charger_location.label),
        ("Existing charger", quote.existing_charger.label),
        ("Charger choice", quote.charger_followup.label),
        ("Fuse box", quote.fuse_box_distance.label),
        ("Vehicle", vehicle),
        ("Timing", quote.timing.label),
    ]
    if quote.notes:
        rows.append(("Notes", quote.notes))
    return rows


def _account_url() -> str:
    return f"{get_settings().frontend_url}/installer/account"


def verify_email(to: str, contact_name: str, token: str) -> Email:
    link = f"{get_settings().frontend_url}/installer/verify-email?token={token}"
    return Email(
        to=to,
        subject="Confirm your email address",
        template="verify_email",
        context={"contact_name": contact_name, "link": link},
    )


def account_exists(to: str) -> Email:
    return Email(
        to=to,
        subject="You already have a PickASparky account",
        template="account_exists",
        context={"account_url": _account_url()},
    )


def password_reset(to: str, token: str) -> Email:
    link = f"{get_settings().frontend_url}/installer/reset-password?token={token}"
    return Email(
        to=to, subject="Reset your password", template="password_reset", context={"link": link}
    )


def _profile_url(installer: Installer) -> str:
    # The installer's one public profile URL. It depends on the installer alone, never on
    # a location, and must match `installerPath` in the frontend (src/lib/site.ts).
    return f"{get_settings().frontend_url}/uk/installer/{installer.slug}/"


def installer_approved(installer: Installer, to: str) -> Email:
    return Email(
        to=to,
        subject="Your PickASparky listing is live",
        template="installer_approved",
        context={
            "business_name": installer.business_name,
            "profile_url": _profile_url(installer),
            "account_url": _account_url(),
        },
    )


def installer_rejected(installer: Installer, to: str) -> Email:
    return Email(
        to=to,
        subject="An update on your PickASparky application",
        template="installer_rejected",
        context={"business_name": installer.business_name},
    )


def payment_failed(installer: Installer, to: str, *, previous_plan: str) -> Email:
    """A subscription payment was declined; the paid plan is paused until it is paid."""
    return Email(
        to=to,
        subject="Your PickASparky payment didn't go through",
        template="payment_failed",
        context={
            "business_name": installer.business_name,
            "plan_name": previous_plan,
            "billing_url": _dashboard_url("/billing"),
        },
    )


def magic_link(customer: Customer, link: str) -> Email:
    """Passwordless sign-in to the customer's quote dashboard."""
    return Email(
        to=customer.email,
        subject="Your secure link to view your quotes",
        template="magic_link",
        context={
            "first_name": customer.first_name,
            "link": link,
            "hours": get_settings().magic_link_expire_minutes // 60,
        },
    )


def quote_confirmation(
    quote: QuoteRequest,
    installer_names: Sequence[str],
    *,
    held: bool = False,
    link: str | None = None,
) -> Email:
    """Sent on every request. One wording for all cases: it never says who got the request.

    `installer_names` and `held` stay in the context for the team's tools and tests only.
    """
    return Email(
        to=quote.email,
        subject=f"We've received your quote request ({quote.reference})",
        template="quote_confirmation",
        context={
            "first_name": quote.first_name,
            "reference": quote.reference,
            "answers": quote_summary(quote),
            "installer_names": list(installer_names),
            "held": held,
            "shared": False,
            "link": link,
            "hours": get_settings().magic_link_expire_minutes // 60,
        },
    )


def quote_shared(
    quote: QuoteRequest, installer_names: Sequence[str], *, link: str | None = None
) -> Email:
    """The team sent a held or unmatched request to installers (same wording as above)."""
    return Email(
        to=quote.email,
        subject=f"Installers are ready to quote for your EV charger ({quote.reference})",
        template="quote_confirmation",
        context={
            "first_name": quote.first_name,
            "reference": quote.reference,
            "answers": quote_summary(quote),
            "installer_names": list(installer_names),
            "held": False,
            "shared": True,
            "link": link,
            "hours": get_settings().magic_link_expire_minutes // 60,
        },
    )


def _dashboard_url(path: str) -> str:
    return f"{get_settings().dashboard_url}{path}"


# How an enquiry reads in a sentence ("... to install an EV charger"), per service. A service
# without an entry still reads correctly from its label, so adding one never breaks the email.
_JOB_PHRASES: dict[Service, str] = {Service.EV_CHARGER_INSTALLATION: "install an EV charger"}


def _job_phrase(service: Service) -> str:
    return _JOB_PHRASES.get(service, f"help with {service.label.lower()}")


def new_lead(
    quote: QuoteRequest, installer: Installer, to: str, lead_id: uuid.UUID, max_quotes: int
) -> Email:
    """Tell an installer about an enquiry in their area (every plan, Free included).

    Deliberately thin: first name, town, service and timeframe only. No phone, email or
    answers, and no Reply-To of the customer, so the details are only reached by opening
    the enquiry, which asks Free installers to upgrade first.
    """
    service = quote.service
    location = quote.district or outward_code(quote.postcode)
    return Email(
        to=to,
        subject=f"New Customer Enquiry : {service.label} in {location}",
        template="new_lead",
        context={
            "first_name": quote.first_name,
            "location": location,
            "service": service.label,
            "job": _job_phrase(service),
            "timeframe": quote.timing.label,
            "max_quotes": max_quotes,
            "url": _dashboard_url(f"/leads/{lead_id}"),
        },
    )


def quote_unmatched(quote: QuoteRequest, *, held: bool = False) -> Email:
    """Team alert: a request matched nobody, or (`held`) waits for the team to choose."""
    return Email(
        to=get_settings().support_email,
        subject=(
            f"Quote request {quote.reference} is waiting for installers"
            if held
            else f"Unmatched quote request {quote.reference}"
        ),
        template="quote_unmatched",
        context={
            "held": held,
            "link": _dashboard_url(f"/leads?open={quote.id}"),
            "reference": quote.reference,
            "answers": quote_summary(quote),
            "geocoded": quote.latitude is not None,
            "customer": {
                "first_name": quote.first_name,
                "email": quote.email,
                "phone": quote.phone,
            },
        },
        reply_to=quote.email,
        team=True,
    )


def installer_enquiry(enquiry: InstallerEnquiry, installer: Installer, to: str) -> Email:
    """A customer's direct request, sent to the installer; replies go straight to them."""
    return Email(
        to=to,
        subject=f"New quote request from {enquiry.name}",
        template="installer_enquiry",
        context={
            "business_name": installer.business_name,
            "customer": {"name": enquiry.name, "email": enquiry.email, "phone": enquiry.phone},
            "message": enquiry.message,
            "account_url": _account_url(),
        },
        reply_to=enquiry.email,
    )


def enquiry_for_team(
    enquiry: InstallerEnquiry, installer: Installer, installer_email: str | None
) -> Email:
    """A request to a Free-plan or unclaimed listing, sent to the PickASparky team.

    The business does not receive enquiries yet, so the team replies to the customer.
    Replies go straight to the customer.
    """
    return Email(
        to=get_settings().support_email,
        subject=f"Quote request for {installer.business_name} (Free plan)",
        template="enquiry_for_team",
        context={
            "business_name": installer.business_name,
            "installer_email": installer_email,
            "installer_phone": installer.phone,
            "claimed": installer.is_claimed,
            "profile_url": _profile_url(installer),
            "customer": {"name": enquiry.name, "email": enquiry.email, "phone": enquiry.phone},
            "message": enquiry.message,
        },
        reply_to=enquiry.email,
        team=True,
    )


def enquiry_ack(enquiry: InstallerEnquiry, installer: Installer) -> Email:
    """The customer's copy of the request they sent from an installer's profile."""
    sent_to_installer = enquiry.sent_to_installer
    return Email(
        to=enquiry.email,
        subject=(
            f"Your quote request has been sent to {installer.business_name}"
            if sent_to_installer
            else f"We've received your quote request for {installer.business_name}"
        ),
        template="enquiry_ack",
        context={
            "name": enquiry.name,
            "business_name": installer.business_name,
            "sent_to_installer": sent_to_installer,
            "profile_url": _profile_url(installer),
            "email": enquiry.email,
            "phone": enquiry.phone,
            "message": enquiry.message,
        },
    )


def contact_received(message: ContactMessage) -> Email:
    return Email(
        to=get_settings().support_email,
        subject=f"Contact form: {message.subject.label}",
        template="contact_received",
        context={
            "name": message.name,
            "email": message.email,
            "subject_label": message.subject.label,
            "message": message.message,
        },
        reply_to=message.email,
        team=True,
    )


def contact_ack(message: ContactMessage) -> Email:
    return Email(
        to=message.email,
        subject="We've received your message",
        template="contact_ack",
        context={"name": message.name, "subject_label": message.subject.label},
    )


def review_invitation(quote: QuoteRequest, installer: Installer, token: str) -> Email:
    link = f"{get_settings().frontend_url}/review?token={token}"
    return Email(
        to=quote.email,
        subject=f"How did {installer.business_name} do?",
        template="review_invitation",
        context={
            "first_name": quote.first_name,
            "business_name": installer.business_name,
            "link": link,
        },
    )


# ---- Claiming a listing ----------------------------------------------------------------


def _dashboard_url(path: str = "") -> str:
    return f"{get_settings().dashboard_url}{path}"


def listing_claim_link(
    installer: Installer, to: str, token: str, *, invited: bool = False
) -> Email:
    """The link that lets a business take over its free listing."""
    return Email(
        to=to,
        subject=(
            f"{installer.business_name} is listed on PickASparky"
            if invited
            else f"Claim your PickASparky listing: {installer.business_name}"
        ),
        template="listing_claim",
        context={
            "business_name": installer.business_name,
            "name": installer.contact_name or installer.business_name,
            "profile_url": _profile_url(installer),
            "link": f"{get_settings().frontend_url}/installer/claim/?token={token}",
            "invited": invited,
        },
    )


def claim_already_claimed(installer: Installer, to: str) -> Email:
    return Email(
        to=to,
        subject=f"About your request to claim {installer.business_name}",
        template="claim_already_claimed",
        context={
            "business_name": installer.business_name,
            "login_url": f"{get_settings().frontend_url}/installer/login/",
            "reset_url": f"{get_settings().frontend_url}/installer/forgot-password/",
        },
    )


def claim_needs_review(installer: Installer, requester_email: str) -> Email:
    """A claim from an address that is not the one on file: the team checks it by hand."""
    return Email(
        to=get_settings().support_email,
        subject=f"Listing claim to check: {installer.business_name}",
        template="claim_needs_review",
        context={
            "business_name": installer.business_name,
            "profile_url": _profile_url(installer),
            "requester_email": requester_email,
            "email_on_file": installer.contact_email,
            "phone_on_file": installer.phone,
        },
        reply_to=requester_email,
        team=True,
    )


# ---- Conversations ---------------------------------------------------------------------


def installer_conversation_url(conversation_id: uuid.UUID) -> str:
    return _dashboard_url(f"/messages/{conversation_id}")


def conversation_link(token: str) -> str:
    """The homeowner's private page for a conversation (see `/messages/` in the frontend)."""
    return f"{get_settings().frontend_url}/messages/?token={token}"


def customer_conversation_path(conversation_id: uuid.UUID) -> str:
    """The conversation inside the homeowner's quote dashboard (`/uk/my-quotes/messages/`)."""
    return f"/uk/my-quotes/messages/?c={conversation_id}"


def conversation_message_to_homeowner(
    conversation: Conversation, installer: Installer, body: str, link: str
) -> Email:
    return Email(
        to=conversation.homeowner_email,
        subject=f"New message from {installer.business_name}",
        template="conversation_message",
        context={
            "name": conversation.homeowner_name,
            "business_name": installer.business_name,
            "body": body,
            "link": link,
        },
        reply_to=installer.user.email if installer.user else None,
    )


def conversation_offer_to_homeowner(
    conversation: Conversation,
    installer: Installer,
    offer: Offer,
    note: str | None,
    link: str,
) -> Email:
    return Email(
        to=conversation.homeowner_email,
        subject=f"Your quote from {installer.business_name} ({offer.reference})",
        template="conversation_offer",
        context={
            "name": conversation.homeowner_name,
            "business_name": installer.business_name,
            "reference": offer.reference,
            "amount": f"£{offer.amount:,.2f}",
            "vat": "including VAT" if offer.includes_vat else "excluding VAT",
            "description": offer.description,
            "valid_until": offer.valid_until.strftime("%-d %B %Y") if offer.valid_until else None,
            "note": note,
            "link": link,
        },
        reply_to=installer.user.email if installer.user else None,
    )


def conversation_reply_to_installer(conversation: Conversation, body: str, to: str) -> Email:
    return Email(
        to=to,
        subject=f"New message from {conversation.homeowner_name}",
        template="conversation_reply",
        context={
            "business_name": conversation.installer.business_name,
            "name": conversation.homeowner_name,
            "body": body,
            "link": installer_conversation_url(conversation.id),
        },
        reply_to=conversation.homeowner_email,
    )


def offer_response_to_installer(conversation: Conversation, offer: Offer, to: str) -> Email:
    accepted = offer.status.value == "accepted"
    return Email(
        to=to,
        subject=(
            f"{conversation.homeowner_name} {'accepted' if accepted else 'declined'} "
            f"quote {offer.reference}"
        ),
        template="offer_response",
        context={
            "business_name": conversation.installer.business_name,
            "name": conversation.homeowner_name,
            "accepted": accepted,
            "reference": offer.reference,
            "amount": f"£{offer.amount:,.2f}",
            "note": offer.response_note,
            "email": conversation.homeowner_email,
            "link": installer_conversation_url(conversation.id),
        },
        reply_to=conversation.homeowner_email,
    )


def conversation_team_message(
    conversation: Conversation, body: str, *, to: str, audience: str, link: str
) -> Email:
    """The PickASparky team added a message to a conversation (sent to both sides)."""
    homeowner = audience == "homeowner"
    return Email(
        to=to,
        subject=(
            "A message from PickASparky about your quote from "
            f"{conversation.installer.business_name}"
            if homeowner
            else f"A message from PickASparky about {conversation.homeowner_name}'s request"
        ),
        template="conversation_team_message",
        context={
            "name": conversation.homeowner_name
            if homeowner
            else conversation.installer.business_name,
            "other_party": conversation.installer.business_name
            if homeowner
            else conversation.homeowner_name,
            "body": body,
            "link": link,
        },
    )


# ---- Team ---------------------------------------------------------------------------------


def staff_invite(user: User, invited_by: User, token: str) -> Email:
    inviter = invited_by.full_name or invited_by.email
    return Email(
        to=user.email,
        subject="You're invited to the PickASparky dashboard",
        template="staff_invite",
        context={
            "name": user.full_name,
            "inviter": inviter,
            "role": (user.staff_role.value if user.staff_role else "").capitalize(),
            "link": _dashboard_url(f"/accept-invite?token={token}"),
        },
    )
