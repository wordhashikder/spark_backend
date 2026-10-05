"""Application errors and the handlers that render the uniform error envelope."""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


class AppError(Exception):
    """Base class for errors that map directly onto an HTTP error response."""

    status_code: int = 400
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        fields: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.fields = dict(fields) if fields else None
        self.headers = dict(headers) if headers else None
        super().__init__(self.message)


class BadRequestError(AppError):
    pass


class InvalidTokenError(AppError):
    code = "invalid_token"
    message = "This link is invalid or has expired."


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Authentication is required."

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        super().__init__(message, code=code, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to do this."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "The request body is too large."


class FieldValidationError(AppError):
    """A 422 carrying per-field messages, raised for checks that need I/O (e.g. geocoding)."""

    status_code = 422
    code = "validation_error"
    message = "Please check the highlighted fields."

    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__(fields=fields)


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please try again later."

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(headers={"Retry-After": str(max(1, retry_after_seconds))})


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "The service is temporarily unavailable. Please try again shortly."


class ServiceNotConfiguredError(ServiceUnavailableError):
    code = "service_not_configured"
    message = "This feature is not available at the moment."


class FieldValueError(ValueError):
    """Raised inside a Pydantic model validator to pin a cross-field error on one field."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if fields is not None:
        error["fields"] = dict(fields)
    return JSONResponse({"error": error}, status_code=status_code, headers=headers)


def _friendly_message(error: Mapping[str, Any]) -> str:
    """Turn one Pydantic error into a sentence fit to show beside a form field."""
    kind = str(error.get("type", ""))
    context = error.get("ctx") or {}
    match kind:
        case "missing":
            return "This field is required."
        case "string_too_short":
            minimum = context.get("min_length", 1)
            if minimum == 1:
                return "This field is required."
            return f"Must be at least {minimum} characters."
        case "string_too_long":
            return f"Must be at most {context.get('max_length')} characters."
        case "too_long":
            return f"Must have at most {context.get('max_length')} items."
        case "too_short":
            return f"Must have at least {context.get('min_length')} items."
        case "greater_than_equal":
            return f"Must be at least {context.get('ge')}."
        case "less_than_equal":
            return f"Must be at most {context.get('le')}."
        case "enum" | "literal_error":
            return "Choose one of the available options."
        case "json_invalid":
            return "The request body is not valid JSON."
        case "value_error" if "error" in context:
            return str(context["error"])
        case "value_error" if "reason" in context:
            # Raised by Pydantic's email validation, which explains itself in `reason`.
            return "Enter a valid email address."
    if kind.startswith(("int_", "float_", "bool_", "string_type", "uuid_")):
        return "This value is not valid."
    message = str(error.get("msg", "This value is not valid."))
    return message[:1].upper() + message[1:]


def _field_name(error: Mapping[str, Any]) -> str:
    original = (error.get("ctx") or {}).get("error")
    if isinstance(original, FieldValueError):
        return original.field
    location = [part for part in error.get("loc", ()) if isinstance(part, str)]
    return location[-1] if location else "body"


def _validation_fields(errors: list[Mapping[str, Any]]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for error in errors:
        fields.setdefault(_field_name(error), _friendly_message(error))
    return fields


async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(
        exc.status_code, exc.code, exc.message, fields=exc.fields, headers=exc.headers
    )


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        FieldValidationError.status_code,
        FieldValidationError.code,
        FieldValidationError.message,
        fields=_validation_fields(list(exc.errors())),
    )


async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    message = HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, code, message, headers=exc.headers)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
