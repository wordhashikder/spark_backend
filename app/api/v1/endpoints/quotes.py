"""Public quote requests."""

from fastapi import APIRouter, Depends, status

from app.api.deps import ClientIpDep, EmailQueueDep, GeocoderDep, SessionDep
from app.core.rate_limit import rate_limit
from app.schemas.quote import QuoteCreate, QuoteCreated
from app.services import quotes

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("quotes", "10/hour"))],
)
async def create_quote(
    data: QuoteCreate,
    session: SessionDep,
    geocoder: GeocoderDep,
    client_ip: ClientIpDep,
    emails: EmailQueueDep,
) -> QuoteCreated:
    if data.website:
        return quotes.decoy_response(data)
    created, outbox = await quotes.create_quote(session, data, geocoder, client_ip)
    emails.send(outbox)
    return created
