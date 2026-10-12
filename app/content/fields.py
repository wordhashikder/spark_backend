"""The building blocks of editable page content: documents, sections and typed fields.

Each public page is a `Document` made of `Section`s of `Field`s. A field carries its
label, help text, limits and the page's original wording (its default). From one
definition we get:

- the JSON schema the Dashboard renders its editor from (`Document.schema`);
- the original wording, served when the admin has not edited a page and exported for
  the website's offline fallback (`Document.defaults`);
- validation of what the admin saves (`Document.clean`).

Content is plain data: text, Markdown for long-form copy, links and image addresses.
Icons, colours and layout stay in the website's code, so an edit can never break the
design.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FieldType(StrEnum):
    TEXT = "text"  # one line
    TEXTAREA = "textarea"  # plain paragraphs; blank lines separate them
    MARKDOWN = "markdown"  # headings, lists, bold, italics and links
    URL = "url"  # a link: a site path (/contact/) or an https:// address
    IMAGE = "image"  # an image: a site path (/images/x.jpg) or an uploaded (Cloudinary) image
    EMAIL = "email"
    LIST = "list"  # repeatable group of fields


class ContentValidationError(Exception):
    """What the admin saved does not fit the page's schema; `fields` maps paths to messages."""

    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = fields
        super().__init__("; ".join(f"{path}: {message}" for path, message in fields.items()))


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str
    type: FieldType
    default: Any
    help: str | None = None
    max_length: int | None = None
    required: bool = True
    rows: int | None = None
    # Lists only.
    item_label: str | None = None
    fields: tuple[Field, ...] = ()
    min_items: int = 0
    max_items: int | None = None
    fixed: bool = False  # exactly as many items as the default (they pair with icons/images)

    def schema(self) -> dict[str, Any]:
        data: dict[str, Any] = {"key": self.key, "label": self.label, "type": self.type.value}
        for name in ("help", "max_length", "rows", "item_label"):
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        data["required"] = self.required
        if self.type is FieldType.LIST:
            count = len(self.default)
            data["fields"] = [item.schema() for item in self.fields]
            data["min_items"] = count if self.fixed else self.min_items
            data["max_items"] = count if self.fixed else self.max_items
            data["fixed"] = self.fixed
        return data

    def clean(self, value: Any, path: str, errors: dict[str, str]) -> Any:
        if self.type is FieldType.LIST:
            return self._clean_list(value, path, errors)
        if value is None:
            value = ""
        if not isinstance(value, str):
            errors[path] = "Must be text."
            return self.default
        # Normalise line endings; single-line fields lose stray newlines.
        value = value.replace("\r\n", "\n").strip()
        if self.type in (FieldType.TEXT, FieldType.URL, FieldType.IMAGE, FieldType.EMAIL):
            value = " ".join(value.split())
        if not value:
            if self.required:
                errors[path] = "This field is required."
            return value
        if self.max_length is not None and len(value) > self.max_length:
            errors[path] = f"Must be at most {self.max_length} characters."
        elif self.type is FieldType.URL and not _is_safe_link(value):
            errors[path] = "Use a site path starting with / or an https:// address."
        elif self.type is FieldType.IMAGE and not _is_image_source(value):
            errors[path] = "Upload an image, or use a site path such as /images/photo.jpg."
        elif self.type is FieldType.EMAIL and not _EMAIL.match(value):
            errors[path] = "Enter a valid email address."
        elif self.type is FieldType.MARKDOWN and not all(
            _is_safe_link(target) for target in _MARKDOWN_LINK.findall(value)
        ):
            errors[path] = "Links must go to a site path (/page/), an https:// address or mailto:."
        return value

    def _clean_list(self, value: Any, path: str, errors: dict[str, str]) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            errors[path] = "Must be a list."
            return list(self.default)
        minimum = len(self.default) if self.fixed else self.min_items
        maximum = len(self.default) if self.fixed else self.max_items
        if len(value) < minimum:
            errors[path] = f"Add at least {minimum} {self.item_label or 'item'}s."
        if maximum is not None and len(value) > maximum:
            errors[path] = f"Use at most {maximum} {self.item_label or 'item'}s."
        cleaned = []
        for index, item in enumerate(value[: maximum or None]):
            item = item if isinstance(item, dict) else {}
            cleaned.append(
                {
                    sub.key: sub.clean(item.get(sub.key), f"{path}.{index}.{sub.key}", errors)
                    for sub in self.fields
                }
            )
        return cleaned


def _is_safe_link(value: str) -> bool:
    """A path on this site, a page anchor, a mailto/tel link or an https:// address.

    `javascript:`, protocol-relative (`//host`) and plain `http://` links are refused.
    """
    if any(char.isspace() for char in value):
        return False
    if value.startswith("/") and not value.startswith("//"):
        return True
    return value.startswith(("https://", "#", "mailto:", "tel:"))


# Targets of Markdown links and images: [text](target) or ![alt](target).
_MARKDOWN_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)")

# The website only loads images from itself and from Cloudinary (its Content-Security-Policy
# and image optimiser allow nothing else), where Dashboard uploads are stored.
_IMAGE_HOSTS = ("https://res.cloudinary.com/",)


def _is_image_source(value: str) -> bool:
    if any(char.isspace() for char in value):
        return False
    if value.startswith("/") and not value.startswith("//"):
        return True
    return value.startswith(_IMAGE_HOSTS)


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    label: str
    fields: tuple[Field, ...]
    help: str | None = None

    def schema(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "fields": [item.schema() for item in self.fields],
        }
        if self.help:
            data["help"] = self.help
        return data

    def defaults(self) -> dict[str, Any]:
        return {item.key: _copy(item.default) for item in self.fields}


@dataclass(frozen=True, slots=True)
class Document:
    """One editable page (or site-wide block such as the footer)."""

    key: str
    label: str
    group: str
    description: str
    sections: tuple[Section, ...]
    # The public page it controls; None for site-wide content.
    path: str | None = None
    tokens: tuple[str, ...] = field(default=())

    def schema(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "description": self.description,
            "path": self.path,
            "sections": [section.schema() for section in self.sections],
        }

    def defaults(self) -> dict[str, Any]:
        return {section.key: section.defaults() for section in self.sections}

    def clean(self, data: Any) -> dict[str, Any]:
        """Validate a whole document; unknown sections and fields are dropped."""
        if not isinstance(data, dict):
            raise ContentValidationError({"content": "Must be an object of sections."})
        errors: dict[str, str] = {}
        cleaned: dict[str, Any] = {}
        for section in self.sections:
            values = data.get(section.key)
            values = values if isinstance(values, dict) else {}
            cleaned[section.key] = {
                item.key: item.clean(
                    values.get(item.key, _copy(item.default)),
                    f"{section.key}.{item.key}",
                    errors,
                )
                for item in section.fields
            }
        if errors:
            raise ContentValidationError(errors)
        return cleaned

    def merge(self, stored: dict[str, Any] | None) -> dict[str, Any]:
        """The stored document over the defaults, field by field.

        Fields added to a page after the admin last saved it show their original
        wording; anything no longer in the schema is ignored.
        """
        merged = self.defaults()
        if not stored:
            return merged
        for section in self.sections:
            values = stored.get(section.key)
            if not isinstance(values, dict):
                continue
            for item in section.fields:
                if item.key in values and _same_shape(item, values[item.key]):
                    merged[section.key][item.key] = values[item.key]
        return merged


def _same_shape(item: Field, value: Any) -> bool:
    if item.type is FieldType.LIST:
        return isinstance(value, list) and all(isinstance(entry, dict) for entry in value)
    return isinstance(value, str)


def _copy(value: Any) -> Any:
    if isinstance(value, list):
        return [dict(entry) for entry in value]
    return value


# ---- Shorthand used by the page definitions --------------------------------------------


def text(
    key: str,
    label: str,
    default: str,
    *,
    max_length: int = 160,
    help: str | None = None,
    required: bool = True,
) -> Field:
    return Field(key, label, FieldType.TEXT, default, help, max_length, required)


def paragraph(
    key: str,
    label: str,
    default: str,
    *,
    max_length: int = 1000,
    rows: int = 3,
    help: str | None = None,
    required: bool = True,
) -> Field:
    return Field(key, label, FieldType.TEXTAREA, default, help, max_length, required, rows)


def markdown(
    key: str,
    label: str,
    default: str,
    *,
    max_length: int = 20_000,
    rows: int = 8,
    help: str | None = None,
    required: bool = True,
) -> Field:
    return Field(key, label, FieldType.MARKDOWN, default, help, max_length, required, rows)


def link(
    key: str,
    label: str,
    default: str,
    *,
    help: str | None = None,
    required: bool = True,
) -> Field:
    return Field(key, label, FieldType.URL, default, help, 500, required)


def image(
    key: str,
    label: str,
    default: str,
    *,
    help: str | None = None,
    required: bool = True,
) -> Field:
    return Field(key, label, FieldType.IMAGE, default, help, 500, required)


def email(
    key: str,
    label: str,
    default: str,
    *,
    help: str | None = None,
    required: bool = True,
) -> Field:
    return Field(key, label, FieldType.EMAIL, default, help, 254, required)


def items(
    key: str,
    label: str,
    item_label: str,
    fields: list[Field],
    default: list[dict[str, Any]],
    *,
    fixed: bool = False,
    min_items: int = 1,
    max_items: int | None = 30,
    help: str | None = None,
) -> Field:
    return Field(
        key,
        label,
        FieldType.LIST,
        default,
        help,
        item_label=item_label,
        fields=tuple(fields),
        min_items=min_items,
        max_items=max_items,
        fixed=fixed,
    )


def section(key: str, label: str, *fields: Field, help: str | None = None) -> Section:
    return Section(key, label, tuple(fields), help)


def seo(title: str, description: str, *, full_title: bool = False) -> Section:
    """The page's search snippet: shown in Google and when the page is shared.

    With `full_title` the title is used exactly as written (the home page); otherwise
    the site name is added after it.
    """
    title_help = (
        "Shown in search results and browser tabs, exactly as written."
        if full_title
        else 'Shown in search results and browser tabs. "| PickASparky" is added after it.'
    )
    return section(
        "seo",
        "Search & sharing",
        text("title", "SEO title", title, max_length=70, help=title_help),
        paragraph(
            "description",
            "Meta description",
            description,
            # Google shows about 155-160 characters; a little more is allowed so a sentence
            # never has to be cut mid-word, and the Dashboard's counter warns past 160.
            max_length=200,
            rows=3,
            help="The summary under the title in search results. Aim for 120-160 characters.",
        ),
        help="How the page appears in Google and when it is shared.",
    )


# Card/step lists whose icons are part of the design: words are editable, count is fixed.
def fixed_cards(
    key: str,
    label: str,
    item_label: str,
    default: list[dict[str, Any]],
    *,
    title_max: int = 80,
    text_max: int = 300,
    help: str | None = None,
) -> Field:
    return items(
        key,
        label,
        item_label,
        [
            text("title", "Title", "", max_length=title_max),
            paragraph("text", "Text", "", max_length=text_max, rows=2),
        ],
        default,
        fixed=True,
        help=help or "The icons are part of the design; the words are yours.",
    )


def faq_list(key: str, label: str, default: list[dict[str, str]], **options: Any) -> Field:
    return items(
        key,
        label,
        "question",
        [
            text("question", "Question", "", max_length=200),
            paragraph("answer", "Answer", "", max_length=1500, rows=4),
        ],
        default,
        min_items=1,
        max_items=40,
        help=options.pop(
            "help",
            "Shown as an accordion, in this order. Each question also goes into the page's "
            "FAQ structured data for search engines.",
        ),
        **options,
    )


def bullets(key: str, label: str, default: list[str], *, max_length: int = 120) -> Field:
    return items(
        key,
        label,
        "point",
        [text("text", "Text", "", max_length=max_length)],
        [{"text": value} for value in default],
        min_items=1,
        max_items=12,
    )
