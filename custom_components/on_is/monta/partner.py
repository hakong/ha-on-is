"""Client for Monta's documented operator-facing Partner API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

import aiohttp

from .base import MontaOAuthClient, compact_dict, csv_value, iso_value
from .errors import MontaResponseError
from .models import ChargeSession, ChargerSnapshot, MontaPage, TelemetryMeasurement

PARTNER_API_BASE_URL = "https://partner-api.monta.com/api/v1"


class MontaPartnerClient(MontaOAuthClient):
    """Documented Partner API client for provisioned operator consumers."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        session: aiohttp.ClientSession | None = None,
        base_url: str = PARTNER_API_BASE_URL,
    ) -> None:
        super().__init__(base_url, client_id, client_secret, session=session)

    async def consumer_info(self) -> dict[str, Any]:
        """Return consumer scopes, organizations, and rate-limit policy."""
        return await self.auth_info("/consumers/me")

    async def list_charge_points(
        self,
        *,
        page: int = 0,
        per_page: int = 100,
        site_id: int | None = None,
        team_id: int | None = None,
        operator_id: int | None = None,
        state: str | list[str] | None = None,
        from_updated_date: str | date | datetime | None = None,
        include_deleted: bool | None = None,
        partner_external_id: str | None = None,
        sort_by_location: bool | None = None,
    ) -> MontaPage[dict[str, Any]]:
        _validate_page(page, per_page)
        payload = await self._authorized_request(
            "GET",
            "/charge-points",
            params=compact_dict(
                {
                    "page": page,
                    "perPage": per_page,
                    "siteId": site_id,
                    "teamId": team_id,
                    "operatorId": operator_id,
                    "state": csv_value(state),
                    "fromUpdatedDate": iso_value(from_updated_date),
                    "includeDeleted": include_deleted,
                    "partnerExternalId": partner_external_id,
                    "sortByLocation": sort_by_location,
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def list_charger_snapshots(self, **filters: Any) -> MontaPage[ChargerSnapshot]:
        result = await self.list_charge_points(**filters)
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
        page: int = 0,
        per_page: int = 100,
        team_id: int | None = None,
        operator_id: int | None = None,
        charge_point_id: int | None = None,
        site_id: int | None = None,
        state: str | list[str] | None = None,
        from_date: str | date | datetime | None = None,
        to_date: str | date | datetime | None = None,
        from_updated_date: str | date | datetime | None = None,
        from_completed_date: str | date | datetime | None = None,
        to_completed_date: str | date | datetime | None = None,
        charge_auth_type: str | None = None,
        charge_auth_id: int | None = None,
        partner_external_id: str | None = None,
        operator_role: str | None = None,
    ) -> MontaPage[dict[str, Any]]:
        _validate_page(page, per_page)
        payload = await self._authorized_request(
            "GET",
            "/charges",
            params=compact_dict(
                {
                    "page": page,
                    "perPage": per_page,
                    "teamId": team_id,
                    "operatorId": operator_id,
                    "chargePointId": charge_point_id,
                    "siteId": site_id,
                    "state": csv_value(state),
                    "fromDate": iso_value(from_date),
                    "toDate": iso_value(to_date),
                    "fromUpdatedDate": iso_value(from_updated_date),
                    "fromCompletedDate": iso_value(from_completed_date),
                    "toCompletedDate": iso_value(to_completed_date),
                    "chargeAuthType": charge_auth_type,
                    "chargeAuthId": charge_auth_id,
                    "partnerExternalId": partner_external_id,
                    "operatorRole": operator_role,
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def list_charge_sessions(self, **filters: Any) -> MontaPage[ChargeSession]:
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
        """Find the newest non-terminal charge visible to the consumer."""
        sessions = await self.list_charge_sessions(
            charge_point_id=charge_point_id,
            page=0,
            per_page=100,
        )
        return next((session for session in sessions.items if session.is_active), None)

    async def get_charge_breakdown(self, charge_id: int) -> dict[str, Any]:
        payload = await self._authorized_request(
            "GET", f"/charges/{charge_id}/breakdown"
        )
        return _require_mapping(payload, "charge breakdown")

    async def get_charge_kwh_consumption(
        self, charge_id: int, *, period_seconds: int = 3600
    ) -> Any:
        if period_seconds <= 0:
            raise ValueError("period_seconds must be greater than zero")
        return await self._authorized_request(
            "GET",
            f"/charges/{charge_id}/kwh-consumption",
            params={"consumptionPeriodSizeInSeconds": period_seconds},
        )

    async def start_charge(
        self,
        charge_point_id: int,
        paying_team_id: int,
        *,
        reserve_charge: bool | None = None,
        kwh_limit: float | None = None,
        soc_limit: float | None = None,
        price_limit: float | None = None,
        price_group_id: int | None = None,
        partner_external_id: str | None = None,
        partner_custom_payload: Mapping[str, Any] | None = None,
    ) -> ChargeSession:
        """Start or reserve a charge against an explicitly selected payer."""
        if kwh_limit is not None and not 1 <= kwh_limit <= 500:
            raise ValueError("kwh_limit must be between 1 and 500")
        if soc_limit is not None and not 1 <= soc_limit <= 100:
            raise ValueError("soc_limit must be between 1 and 100")
        if price_limit is not None and price_limit < 1:
            raise ValueError("price_limit must be at least 1")
        payload = await self._authorized_request(
            "POST",
            "/charges",
            json_body=compact_dict(
                {
                    "payingTeamId": paying_team_id,
                    "chargePointId": charge_point_id,
                    "reserveCharge": reserve_charge,
                    "kwhLimit": kwh_limit,
                    "socLimit": soc_limit,
                    "priceLimit": price_limit,
                    "priceGroupId": price_group_id,
                    "partnerExternalId": partner_external_id,
                    "partnerCustomPayload": dict(partner_custom_payload)
                    if partner_custom_payload is not None
                    else None,
                }
            ),
            action="Starting Monta Partner charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "started charge"))

    async def stop_charge(self, charge_id: int) -> ChargeSession:
        """Stop a charge using the Partner API's documented GET command."""
        payload = await self._authorized_request(
            "GET",
            f"/charges/{charge_id}/stop",
            action="Stopping Monta Partner charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "stopped charge"))

    async def restart_charge(self, charge_id: int) -> ChargeSession:
        payload = await self._authorized_request(
            "GET",
            f"/charges/{charge_id}/restart",
            action="Restarting Monta Partner charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "restarted charge"))

    async def get_charge_point_statistics(
        self,
        charge_point_id: int,
        *,
        from_date: str | date | datetime,
        to_date: str | date | datetime,
    ) -> dict[str, Any]:
        payload = await self._authorized_request(
            "GET",
            "/charge-point-statistics/by-charge-point",
            params={
                "chargePointId": charge_point_id,
                "fromDate": iso_value(from_date),
                "toDate": iso_value(to_date),
            },
        )
        return _require_mapping(payload, "charge-point statistics")

    async def get_charge_point_logs(
        self,
        charge_point_id: int,
        *,
        page: int = 0,
        per_page: int = 100,
        from_date: str | date | datetime | None = None,
        to_date: str | date | datetime | None = None,
        pagination_type: str | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._authorized_request(
            "GET",
            f"/charge-points/{charge_point_id}/logs",
            params=compact_dict(
                {
                    "page": page,
                    "perPage": per_page,
                    "fromDate": iso_value(from_date),
                    "toDate": iso_value(to_date),
                    "paginationType": pagination_type,
                    "before": before,
                    "after": after,
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def get_evse_meter_values(
        self,
        site_id: int,
        charge_point_identity: str,
        connector_id: int,
        *,
        from_date: str | date | datetime,
        to_date: str | date | datetime,
    ) -> tuple[TelemetryMeasurement, ...]:
        payload = await self._authorized_request(
            "GET",
            f"/energy/sites/{site_id}/evses/{charge_point_identity}/{connector_id}/meter-values",
            params={"from": iso_value(from_date), "to": iso_value(to_date)},
        )
        page = MontaPage.from_payload(payload)
        return tuple(TelemetryMeasurement.from_payload(item) for item in page.items)

    async def get_evse_state_history(
        self,
        site_id: int,
        node_id: int,
        *,
        start_at: str | date | datetime,
        end_at: str | date | datetime,
    ) -> Any:
        return await self._authorized_request(
            "GET",
            f"/energy/sites/{site_id}/nodes/{node_id}/evse-states",
            params={"startAt": iso_value(start_at), "endAt": iso_value(end_at)},
        )

    async def get_price_group(self, price_group_id: int) -> dict[str, Any]:
        payload = await self._authorized_request(
            "GET", f"/price-groups/{price_group_id}"
        )
        return _require_mapping(payload, "price group")

    async def get_price_forecast(
        self,
        *,
        charge_point_id: int | None = None,
        price_group_id: int | None = None,
        team_member_id: int | None = None,
    ) -> Any:
        if not any((charge_point_id, price_group_id, team_member_id)):
            raise ValueError("at least one price forecast target is required")
        return await self._authorized_request(
            "GET",
            "/prices/forecast",
            params=compact_dict(
                {
                    "chargePointId": charge_point_id,
                    "priceGroupId": price_group_id,
                    "teamMemberId": team_member_id,
                }
            ),
        )

    async def get_webhook_config(self) -> dict[str, Any]:
        payload = await self._authorized_request("GET", "/webhooks/config")
        return _require_mapping(payload, "webhook config")

    async def set_webhook_config(
        self,
        webhook_url: str,
        webhook_secret: str,
        event_types: list[str],
        *,
        custom_headers: Mapping[str, str] | None = None,
        team_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        payload = await self._authorized_request(
            "PUT",
            "/webhooks/config",
            json_body=compact_dict(
                {
                    "webhookUrl": webhook_url,
                    "webhookSecret": webhook_secret,
                    "eventTypes": event_types,
                    "customHeaders": {"headers": dict(custom_headers)}
                    if custom_headers
                    else None,
                    "teamIds": team_ids,
                }
            ),
        )
        return _require_mapping(payload, "webhook config")

    async def delete_webhook_config(self) -> None:
        await self._authorized_request("DELETE", "/webhooks/config")

    async def list_webhook_entries(
        self,
        *,
        page: int = 0,
        per_page: int = 100,
        status: str | None = None,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._authorized_request(
            "GET",
            "/webhooks/entries",
            params=compact_dict(
                {"page": page, "perPage": per_page, "status": status}
            ),
        )
        return MontaPage.from_payload(payload)


def _validate_page(page: int, per_page: int) -> None:
    if page < 0 or not 1 <= per_page <= 100:
        raise ValueError("page must be >= 0 and per_page between 1 and 100")


def _require_mapping(payload: Any, description: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MontaResponseError(
            f"Monta Partner {description} response is not an object",
            payload=payload,
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
