"""Postcode geocoding via postcodes.io, behind an interface the tests replace."""

import logging
import re
import time
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.exceptions import NotFoundError, ServiceUnavailableError

logger = logging.getLogger(__name__)

_POSTCODE_PATTERN = re.compile(r"^(GIR0AA|[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2})$")
_INWARD_CODE_LENGTH = 3
_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_MAX_ENTRIES = 4096


class PostcodeNotFoundError(NotFoundError):
    code = "postcode_not_found"
    message = "We could not find that postcode."


class GeocodingUnavailableError(ServiceUnavailableError):
    code = "geocoding_unavailable"
    message = "Postcode lookup is temporarily unavailable. Please try again shortly."


@dataclass(frozen=True, slots=True)
class GeocodedPostcode:
    postcode: str
    latitude: float
    longitude: float
    district: str | None
    region: str | None


class Geocoder(Protocol):
    async def lookup(self, postcode: str) -> GeocodedPostcode:
        """Resolve a normalised postcode.

        Raises `PostcodeNotFoundError` or `GeocodingUnavailableError`.
        """
        ...


def normalise_postcode(value: str) -> str | None:
    """Return the postcode as `M1 1AA`, or `None` when it is not a UK postcode format."""
    compact = re.sub(r"\s+", "", value).upper()
    if not _POSTCODE_PATTERN.fullmatch(compact):
        return None
    return f"{compact[:-_INWARD_CODE_LENGTH]} {compact[-_INWARD_CODE_LENGTH:]}"


def outward_code(postcode: str) -> str:
    """The district part of a normalised postcode (`M1 1AA` -> `M1`)."""
    return postcode.split(" ", maxsplit=1)[0]


class PostcodesIOGeocoder:
    """postcodes.io client with a small in-process TTL/LRU cache of successful lookups."""

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url
        self._cache: OrderedDict[str, tuple[float, GeocodedPostcode]] = OrderedDict()

    def prime(self, entries: Iterable[GeocodedPostcode]) -> None:
        """Pre-load lookups that never expire (development only: demo postcodes, offline)."""
        for entry in entries:
            self._cache[entry.postcode] = (float("inf"), entry)

    async def lookup(self, postcode: str) -> GeocodedPostcode:
        cached = self._cached(postcode)
        if cached is not None:
            return cached
        result = await self._fetch(postcode)
        self._store(postcode, result)
        return result

    def _cached(self, postcode: str) -> GeocodedPostcode | None:
        entry = self._cache.get(postcode)
        if entry is None:
            return None
        expires_at, result = entry
        if expires_at < time.monotonic():
            del self._cache[postcode]
            return None
        self._cache.move_to_end(postcode)
        return result

    def _store(self, postcode: str, result: GeocodedPostcode) -> None:
        self._cache[postcode] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
        self._cache.move_to_end(postcode)
        while len(self._cache) > _CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)

    async def _fetch(self, postcode: str) -> GeocodedPostcode:
        url = f"{self._base_url}/postcodes/{postcode.replace(' ', '')}"
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("postcodes.io request failed: %s", exc.__class__.__name__)
            raise GeocodingUnavailableError from exc
        if response.status_code == httpx.codes.NOT_FOUND:
            raise PostcodeNotFoundError
        if response.status_code != httpx.codes.OK:
            logger.warning("postcodes.io returned HTTP %d", response.status_code)
            raise GeocodingUnavailableError
        try:
            result = response.json()["result"]
            latitude, longitude = result["latitude"], result["longitude"]
            if latitude is None or longitude is None:
                # Some postcodes (e.g. Crown Dependencies) are listed without coordinates.
                raise PostcodeNotFoundError
            return GeocodedPostcode(
                postcode=result["postcode"],
                latitude=float(latitude),
                longitude=float(longitude),
                district=result.get("admin_district"),
                region=result.get("region"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("postcodes.io returned an unexpected payload")
            raise GeocodingUnavailableError from exc
