"""Experimental client for private Monta Hub browser APIs."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import aiohttp

from .base import MontaHttpClient, compact_dict, csv_value, iso_value
from .errors import MontaResponseError
from .models import ChargeSession, ChargerSnapshot, MontaPage, TelemetryMeasurement

HUB_BASE_URL = "https://hub.monta.app"


class MontaHubClient(MontaHttpClient):
    """Wrapper around the observed Hub gateway, BFF, and Control routes.

    Authentication is intentionally external. The signed-in ON app bearer is
    accepted by the observed Hub read endpoints, so the ON adapter reuses that
    persisted token instead of creating a second browser identity session.
    """

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession | None = None,
        access_token: str | None = None,
        base_url: str = HUB_BASE_URL,
    ) -> None:
        super().__init__(base_url, session=session)
        self.access_token = access_token

    def set_access_token(self, access_token: str | None) -> None:
        self.access_token = access_token

    async def get_current_user(self) -> dict[str, Any]:
        payload = await self._hub_request("GET", "/api/gateway/api/v1/users/me")
        return _require_mapping(payload, "Hub user")

    async def list_charge_points(
        self,
        *,
        page: int = 0,
        per_page: int = 50,
        team_id: int | None = None,
        site_id: int | None = None,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET",
            "/api/gateway/api/v1/charge-points",
            params=compact_dict(
                {
                    "page": page,
                    "perPage": per_page,
                    "teamId": team_id,
                    "siteId": site_id,
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def search_charge_points(
        self,
        *,
        size: int = 50,
        sort: str | Sequence[str] | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> MontaPage[dict[str, Any]]:
        params = {"size": size, "sort": csv_value(sort)}
        if filters:
            params.update(filters)
        payload = await self._hub_request(
            "GET",
            "/api/gateway/api/v1/charge-points/search",
            params=compact_dict(params),
        )
        return MontaPage.from_payload(payload)

    async def count_charge_points(
        self, *, filters: Mapping[str, Any] | None = None
    ) -> Any:
        return await self._hub_request(
            "GET",
            "/api/gateway/api/v1/charge-points/search/count",
            params=dict(filters or {}),
        )

    async def get_charge_point(self, charge_point_id: int) -> dict[str, Any]:
        payload = await self._hub_request(
            "GET", f"/api/gateway/api/v1/charge-points/{charge_point_id}"
        )
        return _require_mapping(payload, "Hub charge point")

    async def get_charger_snapshot(self, charge_point_id: int) -> ChargerSnapshot:
        return ChargerSnapshot.from_hub(await self.get_charge_point(charge_point_id))

    async def get_charging_station_evses(
        self, charge_point_ids: Sequence[int | str], *, size: int | None = None
    ) -> MontaPage[dict[str, Any]]:
        """Return compact EVSE state for selected charge-point IDs."""
        if not charge_point_ids:
            raise ValueError("at least one charge_point_id is required")
        payload = await self._hub_request(
            "POST",
            "/api/gateway/api/v1/charging-station-evse",
            params=compact_dict({"size": size}),
            json_body={"filters": {"ids": [str(item) for item in charge_point_ids]}},
        )
        return MontaPage.from_payload(payload)

    async def get_team_status_monitor(
        self, team_id: int, *, page: int = 0, per_page: int = 50
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET",
            f"/api/bff/api/v1/teams/{team_id}/charge-points/status-monitor",
            params={"page": page, "perPage": per_page},
        )
        return MontaPage.from_payload(payload)

    async def search_teams(
        self,
        *,
        size: int = 50,
        member_user_ids: Sequence[int] | None = None,
        include: str | Sequence[str] | None = None,
        exclude: str | Sequence[str] | None = None,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET",
            "/api/gateway/api/v1/hub/teams/search",
            params=compact_dict(
                {
                    "size": size,
                    "memberUserIds": csv_value(member_user_ids),
                    "include": csv_value(include),
                    "exclude": csv_value(exclude),
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def search_sites(
        self, *, team_id: int | None = None, size: int = 50
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET",
            "/api/gateway/api/v1/hub/sites/search",
            params=compact_dict({"teamId": team_id, "size": size}),
        )
        return MontaPage.from_payload(payload)

    async def get_team_wallets(self, team_id: int) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET", f"/api/gateway/api/v1/teams/{team_id}/wallets"
        )
        return MontaPage.from_payload(payload)

    async def get_team_charge_keys(
        self, team_id: int, *, page: int = 0, per_page: int = 50
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET",
            f"/api/bff/api/v1/teams/{team_id}/charge-keys",
            params={"page": page, "perPage": per_page},
        )
        return MontaPage.from_payload(payload)

    async def list_charges(
        self,
        *,
        page: int = 0,
        per_page: int = 50,
        state: str | Sequence[str] | None = None,
        site_id: int | None = None,
        team_id: int | None = None,
        paying_team_id: int | None = None,
        charge_point_id: int | None = None,
        charging_station_id: int | None = None,
        charge_key_id: int | None = None,
        vehicle_id: int | None = None,
        payment_method: str | None = None,
        from_date: str | date | datetime | None = None,
        to_date: str | date | datetime | None = None,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET",
            "/api/gateway/api/v1/charges",
            params=compact_dict(
                {
                    "page": page,
                    "perPage": per_page,
                    "state": csv_value(state),
                    "site_id": site_id,
                    "team_id": team_id,
                    "paying_team_id": paying_team_id,
                    "charge_point_id": charge_point_id,
                    "charging_station_id": charging_station_id,
                    "charge_key_id": charge_key_id,
                    "vehicle_id": vehicle_id,
                    "payment_method": payment_method,
                    "from_date": iso_value(from_date),
                    "to_date": iso_value(to_date),
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def list_charge_sessions(self, **filters: Any) -> MontaPage[ChargeSession]:
        page = await self.list_charges(**filters)
        return _map_page(page, ChargeSession.from_payload)

    async def get_active_charge(self, charge_point_id: int) -> ChargeSession | None:
        sessions = await self.list_charge_sessions(
            charge_point_id=charge_point_id,
            page=0,
            per_page=100,
        )
        return next((session for session in sessions.items if session.is_active), None)

    async def get_charge(self, charge_id: int) -> dict[str, Any]:
        payload = await self._hub_request(
            "GET", f"/api/gateway/api/v1/charges/{charge_id}"
        )
        return _require_mapping(payload, "Hub charge")

    async def get_charge_breakdown(self, charge_id: int) -> Any:
        return await self._hub_request(
            "GET", f"/api/bff/api/v1/charges/{charge_id}/breakdowns"
        )

    async def get_charge_receipt(self, charge_id: int) -> Any:
        return await self._hub_request(
            "GET", f"/api/gateway/api/v1/charges/{charge_id}/receipt"
        )

    async def get_charge_measurements(
        self, external_charge_id: str
    ) -> tuple[TelemetryMeasurement, ...]:
        payload = await self._hub_request(
            "GET",
            f"/api/control/v1/charges/{quote(external_charge_id, safe='')}/measurements",
        )
        page = MontaPage.from_payload(payload)
        return tuple(TelemetryMeasurement.from_payload(item) for item in page.items)

    async def get_charging_station_logs(
        self, station_identity: str, *, params: Mapping[str, Any] | None = None
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._hub_request(
            "GET",
            f"/api/control/v2/charging-stations/{quote(station_identity, safe='')}/logs",
            params=params,
        )
        return MontaPage.from_payload(payload)

    async def start_charge(
        self,
        charge_point_id: int,
        *,
        user_id: int,
        paying_team_id: int | None = None,
        price_group_id: int | None = None,
    ) -> Any:
        """Invoke the observed Hub start command with an explicit user/payer."""
        return await self._hub_request(
            "POST",
            f"/api/bff/api/v1/charge-points/{charge_point_id}/start",
            json_body=compact_dict(
                {
                    "userId": user_id,
                    "payingTeamId": paying_team_id,
                    "priceGroupId": price_group_id,
                }
            ),
            action="Starting charge through Monta Hub",
        )

    async def stop_charge(self, charge_point_id: int, *, force: bool = False) -> Any:
        return await self._hub_request(
            "POST",
            f"/api/bff/api/v1/charge-points/{charge_point_id}/stop",
            params={"force": str(force).lower()},
            json_body={},
            action="Stopping charge through Monta Hub",
        )

    async def _hub_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        action: str | None = None,
    ) -> Any:
        headers = (
            {"Authorization": f"Bearer {self.access_token}"}
            if self.access_token
            else None
        )
        return await self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            headers=headers,
            action=action,
        )


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
