"""Public contact form."""

from fastapi import APIRouter, Depends, status

from app.api.deps import EmailQueueDep, SessionDep
from app.core.rate_limit import rate_limit
from app.schemas.common import Message
from app.schemas.contact import ContactCreate
from app.services import contact

router = APIRouter(prefix="/contact", tags=["contact"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("contact", "5/hour"))],
)
async def send_message(data: ContactCreate, session: SessionDep, emails: EmailQueueDep) -> Message:
    if not data.website:
        emails.send(await contact.create_message(session, data))
    return Message(message="Thanks for your message. We will get back to you soon.")
