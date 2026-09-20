"""Exceptions shared by Monta API clients."""
from __future__ import annotations

from typing import Any, Mapping


class MontaApiError(Exception):
    """Base exception raised by a Monta API client."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_code: str | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.payload = payload


class MontaAuthError(MontaApiError):
    """Authentication failed or an access token expired."""


class MontaAccessError(MontaApiError):
    """The authenticated identity cannot access the requested resource."""


class MontaNotFoundError(MontaApiError):
    """The requested Monta resource does not exist."""


class MontaRateLimitError(MontaApiError):
    """A Monta API rate limit was reached."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class MontaResponseError(MontaApiError):
    """A successful response did not contain the expected data shape."""


def error_from_response(
    status: int,
    payload: Any,
    *,
    headers: Mapping[str, str] | None = None,
    action: str = "Monta request",
) -> MontaApiError:
    """Create a typed exception from a Monta error response."""
    details = payload if isinstance(payload, dict) else {}
    error_code = _first_text(details, "errorCode", "error_code", "code")
    reason = _first_text(
        details,
        "readableMessage",
        "readable_message",
        "message",
        "error",
        "status",
    )
    if not reason and isinstance(payload, str):
        reason = payload.strip()
    message = f"{action} failed with HTTP {status}"
    if reason:
        message = f"{message}: {reason}"

    kwargs = {
        "status": status,
        "error_code": error_code,
        "payload": payload,
    }
    if status == 401:
        return MontaAuthError(message, **kwargs)
    if status == 403:
        return MontaAccessError(message, **kwargs)
    if status == 404:
        return MontaNotFoundError(message, **kwargs)
    if status == 429:
        retry_after = _retry_after(headers or {})
        return MontaRateLimitError(message, retry_after=retry_after, **kwargs)
    return MontaApiError(message, **kwargs)


def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _retry_after(headers: Mapping[str, str]) -> float | None:
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
