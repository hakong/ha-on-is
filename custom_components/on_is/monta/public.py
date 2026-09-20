"""Client for Monta's documented user-facing Public API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

import aiohttp

from .base import MontaOAuthClient, compact_dict, iso_value
from .errors import MontaResponseError
from .models import ChargeSession, ChargerSnapshot, MontaPage

PUBLIC_API_BASE_URL = "https://public-api.monta.com/api/v1"
CHARGE_STATES = frozenset(
    {
        "reserved",
        "starting",
        "charging",
        "stopping",
        "paused",
        "scheduled",
        "stopped",
        "completed",
    }
)
CONSUMPTION_PERIODS = frozenset({300, 600, 900, 1800, 3600})


class MontaPublicClient(MontaOAuthClient):
    """Supported Monta Public API client.

    The API is rate limited across all applications belonging to one user.
    Callers should cache static/history responses and avoid using this client as
    a high-frequency telemetry stream.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        session: aiohttp.ClientSession | None = None,
        base_url: str = PUBLIC_API_BASE_URL,
    ) -> None:
        super().__init__(base_url, client_id, client_secret, session=session)

    async def list_charge_points(
        self, *, page: int = 0, per_page: int = 10
    ) -> MontaPage[dict[str, Any]]:
        """List charge points owned or administered by the user."""
        _validate_page(page, per_page)
        payload = await self._authorized_request(
            "GET",
            "/charge-points",
            params={"page": page, "perPage": per_page},
        )
        return MontaPage.from_payload(payload)

    async def list_charger_snapshots(
        self, *, page: int = 0, per_page: int = 10
    ) -> MontaPage[ChargerSnapshot]:
        """List charge points as backend-neutral snapshots."""
        result = await self.list_charge_points(page=page, per_page=per_page)
        return _map_page(result, ChargerSnapshot.from_public)

    async def get_charge_point(self, charge_point_id: int) -> dict[str, Any]:
        payload = await self._authorized_request(
            "GET", f"/charge-points/{charge_point_id}"
        )
        return _require_mapping(payload, "charge point")

    async def get_charger_snapshot(self, charge_point_id: int) -> ChargerSnapshot:
        return ChargerSnapshot.from_public(await self.get_charge_point(charge_point_id))

    async def list_charges(
        self,
        *,
        charge_point_id: int | None = None,
        state: str | None = None,
        from_date: str | date | datetime | None = None,
        to_date: str | date | datetime | None = None,
        page: int = 0,
        per_page: int = 10,
    ) -> MontaPage[dict[str, Any]]:
        """List user charges with supported Public API filters."""
        _validate_page(page, per_page)
        if state is not None and state not in CHARGE_STATES:
            raise ValueError(f"Unsupported Monta charge state: {state}")
        payload = await self._authorized_request(
            "GET",
            "/charges",
            params=compact_dict(
                {
                    "chargePointId": charge_point_id,
                    "state": state,
                    "fromDate": iso_value(from_date),
                    "toDate": iso_value(to_date),
                    "page": page,
                    "perPage": per_page,
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def list_charge_sessions(self, **filters: Any) -> MontaPage[ChargeSession]:
        """List charges as normalized sessions."""
        result = await self.list_charges(**filters)
        return _map_page(result, ChargeSession.from_payload)

    async def get_charge(self, charge_id: int) -> dict[str, Any]:
        payload = await self._authorized_request("GET", f"/charges/{charge_id}")
        return _require_mapping(payload, "charge")

    async def get_charge_session(self, charge_id: int) -> ChargeSession:
        return ChargeSession.from_payload(await self.get_charge(charge_id))

    async def get_active_charge(
        self, charge_point_id: int | None = None
    ) -> ChargeSession | None:
        """Find the newest non-terminal session visible to the application."""
        sessions = await self.list_charge_sessions(
            charge_point_id=charge_point_id,
            page=0,
            per_page=100,
        )
        return next((session for session in sessions.items if session.is_active), None)

    async def get_charge_kwh_consumption(
        self,
        charge_id: int,
        *,
        period_seconds: int = 3600,
    ) -> Any:
        """Retrieve interval energy for one OCPP-connected charge."""
        if period_seconds not in CONSUMPTION_PERIODS:
            raise ValueError(
                "consumption period must be one of 300, 600, 900, 1800, or 3600 seconds"
            )
        return await self._authorized_request(
            "GET",
            f"/charges/{charge_id}/kwh-consumption",
            params={"consumptionPeriodSizeInSeconds": period_seconds},
        )

    async def start_charge(self, charge_point_id: int) -> ChargeSession:
        """Start charging using the user's authorized Public API identity."""
        payload = await self._authorized_request(
            "POST",
            "/charges",
            json_body={"chargePointId": charge_point_id},
            action="Starting Monta charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "started charge"))

    async def stop_charge(self, charge_id: int) -> ChargeSession:
        """Stop an active charge."""
        payload = await self._authorized_request(
            "POST",
            f"/charges/{charge_id}/stop",
            action="Stopping Monta charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "stopped charge"))

    async def get_personal_wallet(self) -> dict[str, Any]:
        payload = await self._authorized_request("GET", "/wallets/personal")
        return _require_mapping(payload, "personal wallet")

    async def list_wallet_transactions(
        self,
        *,
        state: str | None = "complete",
        from_date: str | date | datetime | None = None,
        to_date: str | date | datetime | None = None,
        page: int = 0,
        per_page: int = 10,
    ) -> MontaPage[dict[str, Any]]:
        _validate_page(page, per_page)
        payload = await self._authorized_request(
            "GET",
            "/wallet-transactions",
            params=compact_dict(
                {
                    "state": state,
                    "fromDate": iso_value(from_date),
                    "toDate": iso_value(to_date),
                    "page": page,
                    "perPage": per_page,
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def get_wallet_transaction(self, transaction_id: int) -> dict[str, Any]:
        payload = await self._authorized_request(
            "GET", f"/wallet-transactions/{transaction_id}"
        )
        return _require_mapping(payload, "wallet transaction")

    async def list_afir_charge_points(
        self, country: str, *, page: int = 1, per_page: int = 100
    ) -> Any:
        """Return AFIR DATEX II charge-point metadata."""
        if not country or len(country.strip()) != 2:
            raise ValueError("country must be an ISO 3166-1 alpha-2 code")
        if page < 1 or not 1 <= per_page <= 100:
            raise ValueError("AFIR page must be >= 1 and per_page between 1 and 100")
        return await self._authorized_request(
            "GET",
            "/afir/charge-points",
            params={"country": country.upper(), "page": page, "perPage": per_page},
        )

    async def get_afir_evse_status(self, evse_id: str) -> Any:
        """Return current AFIR availability and ad-hoc price for one EVSE."""
        return await self._authorized_request(
            "GET", f"/afir/charge-points/{evse_id}/status"
        )

    async def list_afir_status_changes(
        self,
        country: str,
        *,
        since: str | None = None,
        cursor: str | None = None,
        per_page: int = 100,
    ) -> Any:
        """Return cursor-based AFIR availability/price changes."""
        if not country or len(country.strip()) != 2:
            raise ValueError("country must be an ISO 3166-1 alpha-2 code")
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        return await self._authorized_request(
            "GET",
            "/afir/charge-points/status",
            params=compact_dict(
                {
                    "country": country.upper(),
                    "since": since,
                    "cursor": cursor,
                    "perPage": per_page,
                }
            ),
        )


def _validate_page(page: int, per_page: int) -> None:
    if page < 0:
        raise ValueError("page must be zero or greater")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100")


def _require_mapping(payload: Any, description: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MontaResponseError(
            f"Monta {description} response is not an object", payload=payload
        )
    return dict(payload)


def _map_page(page: MontaPage[Any], parser: Any) -> MontaPage[Any]:
    return MontaPage(
        items=tuple(parser(item) for item in page.items),
        page=page.page,
        per_page=page.per_page,
        total=page.total,
        pages=page.pages,
        after=page.after,
        before=page.before,
        raw=page.raw,
    )
