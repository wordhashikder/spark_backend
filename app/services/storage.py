"""Image validation and storage (Cloudinary), behind an interface the tests replace."""

import logging
from dataclasses import dataclass
from functools import partial
from typing import Protocol

import cloudinary.exceptions
import cloudinary.uploader
from anyio import to_thread

from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    PayloadTooLargeError,
    ServiceNotConfiguredError,
    ServiceUnavailableError,
)
from app.core.middleware import MAX_UPLOAD_BYTES

logger = logging.getLogger(__name__)

_UPLOAD_TIMEOUT_SECONDS = 30
_ALLOWED_FORMATS = ["jpg", "png", "webp"]
_WEBP_HEADER_LENGTH = 12


class UnsupportedImageError(AppError):
    status_code = 415
    code = "unsupported_media_type"
    message = "Upload a JPEG, PNG or WebP image."


class UploadFailedError(ServiceUnavailableError):
    code = "upload_failed"
    message = "The image could not be uploaded. Please try again."


class FileTooLargeError(PayloadTooLargeError):
    code = "file_too_large"
    message = "Images must be 5 MB or smaller."


@dataclass(frozen=True, slots=True)
class StoredImage:
    url: str
    public_id: str


class ImageStorage(Protocol):
    async def upload(self, data: bytes, *, folder: str) -> StoredImage: ...

    async def delete(self, public_id: str) -> None: ...


def _is_supported_image(data: bytes) -> bool:
    """Identify JPEG, PNG and WebP by their magic bytes (the client's content type is ignored)."""
    is_jpeg = data.startswith(b"\xff\xd8\xff")
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = (
        len(data) >= _WEBP_HEADER_LENGTH and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    )
    return is_jpeg or is_png or is_webp


def validate_image(data: bytes) -> None:
    """Raise unless `data` is a JPEG, PNG or WebP image of at most 5 MB."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileTooLargeError
    if not _is_supported_image(data):
        raise UnsupportedImageError


class CloudinaryStorage:
    """Cloudinary uploads; the synchronous SDK runs in a worker thread."""

    def __init__(self, settings: Settings) -> None:
        self._folder = settings.cloudinary_folder
        self._credentials = {
            "cloud_name": settings.cloudinary_cloud_name,
            "api_key": settings.cloudinary_api_key,
            "api_secret": settings.cloudinary_api_secret,
        }

    async def upload(self, data: bytes, *, folder: str) -> StoredImage:
        upload = partial(
            cloudinary.uploader.upload,
            data,
            folder=f"{self._folder}/{folder}",
            resource_type="image",
            allowed_formats=_ALLOWED_FORMATS,
            timeout=_UPLOAD_TIMEOUT_SECONDS,
            **self._credentials,
        )
        try:
            result = await to_thread.run_sync(upload)
        except cloudinary.exceptions.Error as exc:
            logger.warning("Cloudinary upload failed: %s", exc)
            raise UploadFailedError from exc
        return StoredImage(url=result["secure_url"], public_id=result["public_id"])

    async def delete(self, public_id: str) -> None:
        await to_thread.run_sync(
            partial(
                cloudinary.uploader.destroy,
                public_id,
                invalidate=True,
                timeout=_UPLOAD_TIMEOUT_SECONDS,
                **self._credentials,
            )
        )


class UnconfiguredStorage:
    """Stands in when Cloudinary credentials are not set."""

    async def upload(self, data: bytes, *, folder: str) -> StoredImage:
        raise ServiceNotConfiguredError

    async def delete(self, public_id: str) -> None:
        raise ServiceNotConfiguredError


async def discard_quietly(storage: ImageStorage, public_id: str | None) -> None:
    """Delete a stored image that is no longer referenced; a failure only leaves an orphan."""
    if not public_id:
        return
    try:
        await storage.delete(public_id)
    except Exception:
        logger.warning("Could not delete stored image %s", public_id, exc_info=True)


def build_storage(settings: Settings) -> ImageStorage:
    return CloudinaryStorage(settings) if settings.cloudinary_configured else UnconfiguredStorage()
