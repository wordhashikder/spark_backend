"""Shared request/response building blocks and validated field types."""

import math
import re
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, EmailStr, StringConstraints

from app.services.geocoding import normalise_postcode

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
_PHONE_FORMATTING = re.compile(r"[\s()+-]")
_PHONE_MIN_DIGITS = 10
_PHONE_MAX_DIGITS = 15


def _validate_postcode(value: str) -> str:
    normalised = normalise_postcode(value)
    if normalised is None:
        raise ValueError("Enter a valid UK postcode.")
    return normalised


def _validate_phone(value: str) -> str:
    digits = _PHONE_FORMATTING.sub("", value)
    if not digits.isdigit() or not _PHONE_MIN_DIGITS <= len(digits) <= _PHONE_MAX_DIGITS:
        raise ValueError("Enter a valid phone number.")
    return " ".join(value.split())


def _validate_image_url(value: str) -> str:
    """An absolute `https://` URL, or a path on the website itself such as `/images/x.jpg`."""
    is_site_path = value.startswith("/") and not value.startswith("//")
    if not (value.startswith("https://") or is_site_path) or any(c.isspace() for c in value):
        raise ValueError("Enter an https:// image URL or a site path starting with /.")
    return value


def validate_password(value: str) -> str:
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Password must be between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters."
        )
    if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise ValueError("Password must contain at least one letter and one digit.")
    return value


def _lowercase(value: str) -> str:
    return value.lower()


def _blank_to_none(value: object) -> object:
    """Treat an empty or whitespace-only optional text field as "not provided"."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def text(min_length: int, max_length: int) -> StringConstraints:
    """Constraint for a whitespace-trimmed string: `Annotated[str, text(2, 80)]`."""
    return StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)


# Marks an optional text field where blank input means "not provided":
# `Annotated[Annotated[str, text(1, 120)] | None, blank_as_none]`.
blank_as_none = BeforeValidator(_blank_to_none)

Postcode = Annotated[str, StringConstraints(max_length=12), AfterValidator(_validate_postcode)]
Phone = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=30), AfterValidator(_validate_phone)
]
Password = Annotated[str, AfterValidator(validate_password)]
ImageUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=500),
    AfterValidator(_validate_image_url),
]
Email = Annotated[EmailStr, StringConstraints(max_length=254), AfterValidator(_lowercase)]
OpaqueToken = Annotated[str, StringConstraints(min_length=1, max_length=2048)]


class Message(BaseModel):
    message: str


class Paginated[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], *, total: int, page: int, page_size: int) -> Self:
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size),
        )
