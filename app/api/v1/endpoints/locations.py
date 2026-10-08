"""Locations and postcode lookup."""

from fastapi import APIRouter, Depends

from app.api.deps import GeocoderDep, SessionDep
from app.core.exceptions import FieldValidationError
from app.core.rate_limit import rate_limit
from app.schemas.location import (
    LocationDetail,
    LocationDirectory,
    LocationSummary,
    PostcodeLookup,
)
from app.services import locations, matching
from app.services.geocoding import normalise_postcode

router = APIRouter(tags=["locations"])


@router.get("/locations")
async def list_locations(session: SessionDep) -> list[LocationSummary]:
    return await locations.list_with_counts(session)


@router.get("/locations/directory")
async def directory(session: SessionDep) -> LocationDirectory:
    """The "Find trusted installers in your area" columns, shown on every page."""
    return await locations.get_directory(session)


@router.get("/locations/{slug}")
async def get_location(slug: str, session: SessionDep) -> LocationDetail:
    return await locations.get_detail(session, slug)


@router.get(
    "/postcodes/{postcode}", dependencies=[Depends(rate_limit("postcode-lookup", "60/minute"))]
)
async def lookup_postcode(
    postcode: str, session: SessionDep, geocoder: GeocoderDep
) -> PostcodeLookup:
    normalised = normalise_postcode(postcode)
    if normalised is None:
        raise FieldValidationError({"postcode": "Enter a valid UK postcode."})
    place = await geocoder.lookup(normalised)
    return PostcodeLookup(
        postcode=place.postcode,
        district=place.district,
        region=place.region,
        installers_in_range=await matching.count_in_range(session, place.latitude, place.longitude),
    )
