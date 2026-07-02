"""Backend selection for the ON integration."""
from __future__ import annotations

from typing import Any, Protocol

import aiohttp

from .const import BACKEND_OCEAN, DEFAULT_BACKEND

BACKEND_METADATA = {
    BACKEND_OCEAN: {
        "key": BACKEND_OCEAN,
        "name": "Etrel OCEAN",
        "api_family": "Etrel OCEAN / DuskyWebApi",
        "base_url": "https://app.on.is/DuskyWebApi",
    },
}


class OnIsBackendClient(Protocol):
    """Protocol shared by the current and future ON backend clients."""

    backend_key: str
    backend_name: str
    api_family: str
    base_url: str

    async def close(self) -> None:
        """Close client resources owned by the backend."""

    async def login(self) -> str:
        """Validate credentials and prepare the backend client."""

    async def get_online_data(self) -> list[dict[str, Any]]:
        """Return current charger sessions."""

    async def start_charging(self, evse_code: str, connector_id: int) -> bool:
        """Start charging for a connector."""

    async def stop_charging(
        self, evse_code: str, charge_point_id: int, connector_id: int
    ) -> bool:
        """Stop charging for a connector."""

    async def get_location_status(self, location_id: int) -> dict[int, dict[str, Any]]:
        """Return passive charger status for a location."""

    async def resolve_evse_code(self, evse_code: str) -> int | None:
        """Resolve an EVSE code to a location id."""

    async def get_charging_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent charging history."""


def get_backend_metadata(backend_key: str | None = None) -> dict[str, str]:
    """Return metadata for a supported backend."""
    key = backend_key or DEFAULT_BACKEND
    if key not in BACKEND_METADATA:
        raise ValueError(f"Unsupported ON backend: {key}")
    return dict(BACKEND_METADATA[key])


def create_backend_client(
    email: str,
    password: str,
    session: aiohttp.ClientSession,
    backend_key: str | None = None,
) -> OnIsBackendClient:
    """Create the configured backend client.

    ON has announced a move to Monta for its new app. Keeping backend creation in
    one place makes that future client an additive change instead of a rewrite of
    config flow, coordinator, sensors, and switches.
    """
    key = backend_key or DEFAULT_BACKEND
    if key != BACKEND_OCEAN:
        raise ValueError(f"Unsupported ON backend: {key}")

    from .api import OnIsClient

    return OnIsClient(email=email, password=password, session=session)
