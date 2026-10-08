"""Transactional email: Jinja2 templates rendered to multipart messages, sent over SMTP.

Use cases build `Email` values; endpoints queue them on `BackgroundTasks` once the
transaction has committed. Sending never raises into a request.
"""

import logging
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
from app.models import ContactMessage, Installer, InstallerEnquiry, QuoteRequest

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
        message["From"] = formataddr((settings.email_from_name, settings.email_from))
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
        logger.info(
            "SMTP is not configured; email not sent.\nTo: %s\nSubject: %s\n\n%s",
            email.to,
            email.subject,
            body.get_content() if body else "",
        )


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


def quote_confirmation(quote: QuoteRequest, installer_names: Sequence[str]) -> Email:
    return Email(
        to=quote.email,
        subject=f"We've received your quote request ({quote.reference})",
        template="quote_confirmation",
        context={
            "first_name": quote.first_name,
            "reference": quote.reference,
            "answers": quote_summary(quote),
            "installer_names": list(installer_names),
        },
    )


def new_lead(quote: QuoteRequest, installer: Installer, to: str) -> Email:
    return Email(
        to=to,
        subject=f"New enquiry in {quote.district or quote.postcode} ({quote.reference})",
        template="new_lead",
        context={
            "business_name": installer.business_name,
            "reference": quote.reference,
            "answers": quote_summary(quote),
            "customer": {
                "first_name": quote.first_name,
                "email": quote.email,
                "phone": quote.phone,
            },
            "account_url": _account_url(),
        },
        reply_to=quote.email,
    )


def quote_unmatched(quote: QuoteRequest) -> Email:
    return Email(
        to=get_settings().support_email,
        subject=f"Unmatched quote request {quote.reference}",
        template="quote_unmatched",
        context={
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
    enquiry: InstallerEnquiry, installer: Installer, installer_email: str
) -> Email:
    """A request to a Free-plan (listed-only) installer, sent to the PickASparky team.

    The installer's plan does not include enquiries, so the team replies to the customer.
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
            "profile_url": _profile_url(installer),
            "customer": {"name": enquiry.name, "email": enquiry.email, "phone": enquiry.phone},
            "message": enquiry.message,
        },
        reply_to=enquiry.email,
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
