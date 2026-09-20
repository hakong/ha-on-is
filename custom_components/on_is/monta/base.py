"""HTTP and OAuth building blocks for Monta clients."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any, Mapping

import aiohttp

from .errors import MontaAuthError, MontaResponseError, error_from_response
from .models import MontaToken

JsonObject = dict[str, Any]


def compact_dict(values: Mapping[str, Any]) -> dict[str, Any]:
    """Drop unset query/body values while preserving false and zero."""
    return {key: value for key, value in values.items() if value is not None}


def csv_value(value: str | list[Any] | tuple[Any, ...] | set[Any] | None) -> str | None:
    """Normalize a scalar or collection for comma-separated API filters."""
    if value is None or isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def iso_value(value: str | date | datetime | None) -> str | None:
    """Serialize date-like query values while preserving opaque strings."""
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


class MontaHttpClient:
    """Small async JSON transport shared by all Monta API surfaces."""

    def __init__(
        self,
        base_url: str,
        *,
        session: aiohttp.ClientSession | None = None,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._default_headers = {
            "Accept": "application/json",
            **dict(default_headers or {}),
        }

    async def close(self) -> None:
        """Close the HTTP session if this client created it."""
        if self._owns_session and not self._session.closed:
            await self._session.close()

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        action: str | None = None,
    ) -> Any:
        """Perform one JSON request and map HTTP failures to typed errors."""
        request_headers = {**self._default_headers, **dict(headers or {})}
        kwargs: dict[str, Any] = {"headers": request_headers}
        if params:
            kwargs["params"] = compact_dict(params)
        if json_body is not None:
            kwargs["json"] = json_body

        async with self._session.request(method, self._url(path), **kwargs) as response:
            payload = await _read_payload(response)
            if not 200 <= response.status < 300:
                raise error_from_response(
                    response.status,
                    payload,
                    headers=getattr(response, "headers", None),
                    action=action or f"{method.upper()} {path}",
                )
            return payload


class MontaOAuthClient(MontaHttpClient):
    """Shared client-credential and refresh-token behavior."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        session: aiohttp.ClientSession | None = None,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            base_url,
            session=session,
            default_headers=default_headers,
        )
        self.client_id = client_id
        self._client_secret = client_secret
        self.token: MontaToken | None = None
        self._auth_lock = asyncio.Lock()

    @property
    def access_token(self) -> str | None:
        """Return the current access token without exposing the client secret."""
        return self.token.access_token if self.token else None

    def restore_token(self, token: MontaToken) -> None:
        """Restore a previously persisted token record."""
        self.token = token

    async def authenticate(self, *, force: bool = False) -> MontaToken:
        """Exchange client credentials for an access/refresh token pair."""
        async with self._auth_lock:
            if (
                not force
                and self.token is not None
                and not self.token.access_token_expired()
            ):
                return self.token
            payload = await self._request(
                "POST",
                "/auth/token",
                json_body={
                    "clientId": self.client_id,
                    "clientSecret": self._client_secret,
                },
                action="Monta authentication",
            )
            self.token = _parse_token(payload)
            return self.token

    async def refresh_access_token(self) -> MontaToken:
        """Refresh the access token, falling back to client credentials."""
        async with self._auth_lock:
            if not self.token or not self.token.refresh_token:
                payload = await self._request(
                    "POST",
                    "/auth/token",
                    json_body={
                        "clientId": self.client_id,
                        "clientSecret": self._client_secret,
                    },
                    action="Monta authentication",
                )
            else:
                try:
                    payload = await self._request(
                        "POST",
                        "/auth/refresh",
                        json_body={"refreshToken": self.token.refresh_token},
                        action="Monta token refresh",
                    )
                except MontaAuthError:
                    payload = await self._request(
                        "POST",
                        "/auth/token",
                        json_body={
                            "clientId": self.client_id,
                            "clientSecret": self._client_secret,
                        },
                        action="Monta authentication",
                    )
            self.token = _parse_token(payload)
            return self.token

    async def auth_info(self, path: str = "/auth/me") -> JsonObject:
        """Return current application/consumer details."""
        payload = await self._authorized_request("GET", path)
        return _require_object(payload, "Monta auth information")

    async def _authorized_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        action: str | None = None,
        retry_auth: bool = True,
    ) -> Any:
        token = await self.authenticate()
        request_headers = {
            **dict(headers or {}),
            "Authorization": f"Bearer {token.access_token}",
        }
        try:
            return await self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=request_headers,
                action=action,
            )
        except MontaAuthError:
            if not retry_auth:
                raise
            token = await self.refresh_access_token()
            request_headers["Authorization"] = f"Bearer {token.access_token}"
            return await self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=request_headers,
                action=action,
            )


async def _read_payload(response: aiohttp.ClientResponse) -> Any:
    if response.status == 204:
        return None
    try:
        return await response.json(content_type=None)
    except (ValueError, json.JSONDecodeError, TypeError):
        text = await response.text()
        if not text.strip():
            return None
        return text


def _parse_token(payload: Any) -> MontaToken:
    if not isinstance(payload, Mapping):
        raise MontaResponseError("Monta token response is not an object", payload=payload)
    try:
        return MontaToken.from_payload(payload)
    except ValueError as err:
        raise MontaResponseError(str(err), payload=payload) from err


def _require_object(payload: Any, description: str) -> JsonObject:
    if not isinstance(payload, Mapping):
        raise MontaResponseError(
            f"{description} response is not an object",
            payload=payload,
        )
    return dict(payload)
