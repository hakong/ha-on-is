"""Privacy-safe diagnostics helpers for raw Monta payloads."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "**REDACTED**"
SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "accesstoken",
        "authorization",
        "address",
        "address1",
        "address2",
        "address3",
        "city",
        "client_secret",
        "clientsecret",
        "cookie",
        "email",
        "display_name",
        "first_name",
        "guest_id",
        "guestid",
        "jwt",
        "last_name",
        "legal_email",
        "national_id",
        "password",
        "pdf_url",
        "phone",
        "profile_image_url",
        "push_alias",
        "refresh_token",
        "refreshtoken",
        "secret",
        "signed_data_url",
        "token",
        "zendesk_jwt",
        "web_url",
        "zip",
    }
)
SENSITIVE_QUERY_KEYS = frozenset(
    {"access_token", "authorization", "code", "flow", "secret", "token"}
)


def redact_monta_data(value: Any) -> Any:
    """Recursively redact credentials and direct personal identifiers."""
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            compact = normalized.replace("_", "")
            if normalized in SENSITIVE_KEYS or compact in SENSITIVE_KEYS:
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_monta_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_monta_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_monta_data(item) for item in value)
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return redact_url(value)
    return value


def redact_url(url: str) -> str:
    """Redact auth-related query parameters without destroying the URL shape."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    query = [
        (key, REDACTED if key.lower() in SENSITIVE_QUERY_KEYS else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )
