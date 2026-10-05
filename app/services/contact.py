"""Contact form submissions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContactMessage
from app.schemas.contact import ContactCreate
from app.services import email as emails
from app.services.email import Email


async def create_message(session: AsyncSession, data: ContactCreate) -> list[Email]:
    """Store the message; return the support notification and the sender's acknowledgement."""
    message = ContactMessage(
        name=data.name, email=data.email, subject=data.subject, message=data.message
    )
    session.add(message)
    await session.commit()
    return [emails.contact_received(message), emails.contact_ack(message)]
