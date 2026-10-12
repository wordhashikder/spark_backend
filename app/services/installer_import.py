"""Adding many listings at once from a CSV file (Installers → Import CSV).

The file needs a header row. Required columns: `business_name`, `contact_email`, `phone`,
`postcode`. Optional: `contact_name`, `description`, `accreditations` (separated by `;`
or `,`, e.g. "NICEIC; OZEV"), `coverage_radius_miles`, `services` (separated likewise).

Rows are checked one by one. A row whose business or email is already listed (or appears
earlier in the file) is skipped; a row with a problem is reported with its line number
and the rest still import. A dry run checks everything and saves nothing.
"""

import csv
import io
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccreditationScheme, InstallerStatus, Plan, Service
from app.core.exceptions import FieldValidationError
from app.schemas.admin import AdminInstallerCreate, ImportReport, ImportRowError
from app.services import admin
from app.services.geocoding import Geocoder

MAX_ROWS = 500
MAX_BYTES = 1024 * 1024
REQUIRED_COLUMNS = ("business_name", "contact_email", "phone", "postcode")
OPTIONAL_COLUMNS = (
    "contact_name",
    "description",
    "accreditations",
    "coverage_radius_miles",
    "services",
)
_ALIASES = {
    "business": "business_name",
    "name": "business_name",
    "company": "business_name",
    "email": "contact_email",
    "telephone": "phone",
    "phone_number": "phone",
    "base_postcode": "postcode",
    "radius": "coverage_radius_miles",
    "coverage": "coverage_radius_miles",
    "contact": "contact_name",
}


def _column(name: str) -> str:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(key, key)


def _choices(value: str, enum: type[AccreditationScheme] | type[Service]) -> list[str]:
    """Match `NICEIC; ozev` style lists against an enum's values and labels."""
    lookup: dict[str, str] = {}
    for member in enum:
        lookup[member.value.lower()] = member.value
        lookup[member.label.lower()] = member.value
    items = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    unknown = [item for item in items if item.lower() not in lookup]
    if unknown:
        raise ValueError(f"Unknown value: {', '.join(unknown)}.")
    return [lookup[item.lower()] for item in items]


def _decode(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise FieldValidationError({"file": "The file is larger than 1 MB."})
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise FieldValidationError({"file": "Save the file as CSV (UTF-8) and try again."})


def _row_payload(row: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "business_name": row.get("business_name", ""),
        "contact_email": row.get("contact_email", ""),
        "phone": row.get("phone", ""),
        "base_postcode": row.get("postcode", ""),
        "contact_name": row.get("contact_name") or None,
        "description": row.get("description") or None,
        "status": InstallerStatus.APPROVED,
        "plan": Plan.FREE,
    }
    if row.get("accreditations"):
        payload["accreditations"] = _choices(row["accreditations"], AccreditationScheme)
    if row.get("services"):
        payload["services"] = _choices(row["services"], Service)
    if row.get("coverage_radius_miles"):
        payload["coverage_radius_miles"] = row["coverage_radius_miles"]
    return payload


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error.get("loc", ()))
    message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
    return f"{field.replace('base_postcode', 'postcode')}: {message}" if field else message


async def import_csv(
    session: AsyncSession, data: bytes, geocoder: Geocoder, *, dry_run: bool
) -> ImportReport:
    text = _decode(data)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise FieldValidationError({"file": "The file is empty."})
    columns = [_column(name) for name in reader.fieldnames]
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise FieldValidationError({"file": f"Missing columns: {', '.join(missing)}."})

    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise FieldValidationError({"file": f"Import at most {MAX_ROWS} rows at a time."})

    created = 0
    skipped: list[ImportRowError] = []
    errors: list[ImportRowError] = []
    seen_names: set[str] = set()
    seen_emails: set[str] = set()
    for line, raw in enumerate(rows, start=2):
        row = {
            column: (value or "").strip()
            for column, value in zip(columns, raw.values(), strict=False)
            if isinstance(value, str)
        }
        name = row.get("business_name") or None
        if not any(row.values()):
            continue
        try:
            listing = AdminInstallerCreate.model_validate(_row_payload(row))
        except ValidationError as exc:
            errors.append(ImportRowError(row=line, business_name=name, message=_first_error(exc)))
            continue
        except ValueError as exc:
            errors.append(ImportRowError(row=line, business_name=name, message=str(exc)))
            continue

        key_name, key_email = listing.business_name.lower(), listing.contact_email.lower()
        if (
            key_name in seen_names
            or key_email in seen_emails
            or await admin.find_duplicate(session, listing.business_name, listing.contact_email)
        ):
            skipped.append(
                ImportRowError(
                    row=line,
                    business_name=listing.business_name,
                    message="Already listed (same business name or email).",
                )
            )
            continue
        try:
            async with session.begin_nested():
                await admin.build_listing(session, listing, geocoder)
        except FieldValidationError as exc:
            errors.append(
                ImportRowError(
                    row=line,
                    business_name=listing.business_name,
                    message=next(iter((exc.fields or {}).values()), "Invalid row."),
                )
            )
            continue
        seen_names.add(key_name)
        seen_emails.add(key_email)
        created += 1

    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return ImportReport(
        dry_run=dry_run, rows=len(rows), created=created, skipped=skipped, errors=errors
    )
