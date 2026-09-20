"""Client for the private API used by the signed-in Monta Android app."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import uuid

import aiohttp

from .base import MontaHttpClient, compact_dict, csv_value
from .errors import MontaAuthError, MontaResponseError
from .models import ChargeSession, ChargerSnapshot, MontaPage, MontaToken

APP_API_BASE_URL = "https://api.monta.app"
APP_CHARGE_POINT_INCLUDES = (
    "country",
    "has_active_charging_rule",
    "integration",
    "model",
    "cost",
    "user_actions",
)
APP_CHARGE_DETAIL_INCLUDES = (
    "charge_point_info",
    "timeout_guidance",
    "last_measurement",
    "impact",
    "receipt",
    "error",
    "charge_details",
    "charts",
    "cpi_status",
    "user_actions",
    "pre_auth",
)
APP_CHARGE_LIST_EXCLUDES = (
    "vehicle",
    "paying_team",
    "source",
    "payment",
    "user",
    "rating",
    "pricing",
    "charge_point",
)
APP_START_INCLUDES = (
    "impact",
    "receipt",
    "error",
    "charge_details",
    "cost_pricing",
    "charts",
)


@dataclass
class MontaAppContext:
    """Stable app identity headers observed in the ON Android client."""

    operator: str = "on"
    application: str = "on"
    country: str = "is"
    timezone: str = "Atlantic/Reykjavik"
    language: str = "en_US"
    app_version: str = "2026.96.0"
    android_api: str = "android37"
    device: str = "googlePixel%207%20Pro"
    request_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    def headers(self) -> dict[str, str]:
        """Return the request context sent by the captured Flutter app."""
        return {
            "User-Agent": "Dart/3.12 (dart:io)",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "Uuid": self.request_uuid,
            "Meta": ";".join(
                (
                    "android",
                    "production",
                    self.app_version,
                    self.android_api,
                    self.device,
                )
            ),
            "Operator": self.operator,
            "Country": self.country,
            "timezone": self.timezone,
            "Accept-Language": self.language,
            "Application": self.application,
        }


@dataclass(frozen=True)
class MontaPayingTeam:
    """One signed-in payer option returned for a charge point."""

    id: str
    can_pay: bool
    pre_select: bool
    payment_title: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MontaPayingTeam":
        team_id = payload.get("id")
        if team_id is None:
            raise ValueError("Paying-team response is missing an id")
        payment = payload.get("payment")
        payment = payment if isinstance(payment, Mapping) else {}
        return cls(
            id=str(team_id),
            can_pay=payment.get("can_pay_charge_on_charge_point") is True,
            pre_select=payload.get("pre_select") is True,
            payment_title=(
                str(payment["title"]).strip() if payment.get("title") else None
            ),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class MontaChargeSettings:
    """Saved charge preferences written by the app immediately after start."""

    payment_id: int | str
    mode: str = "instant"
    payment: str = "team"
    kwh_mode: str = "full"
    pickup_at: str = "09:00"
    pickup_days_ahead: int = 0
    kwh_fixed: float | None = None
    kwh_percentage_now: float | None = None
    kwh_percentage_stop: float | None = None
    start_at: str | None = None
    vehicle_id: int | str | None = None

    def as_payload(self, charge_point_id: int | str) -> dict[str, Any]:
        return {
            "charge_point_id": charge_point_id,
            "kwh_fixed": self.kwh_fixed,
            "kwh_mode": self.kwh_mode,
            "kwh_percentage_now": self.kwh_percentage_now,
            "kwh_percentage_stop": self.kwh_percentage_stop,
            "mode": self.mode,
            "payment": self.payment,
            "payment_id": self.payment_id,
            "pickup_at": self.pickup_at,
            "pickup_days_ahead": self.pickup_days_ahead,
            "start_at": self.start_at,
            "vehicle_id": self.vehicle_id,
        }


class MontaAppClient(MontaHttpClient):
    """Authenticated ON app client reconstructed from the Android capture.

    This is an undocumented private API. Callers must keep charge control and
    cable release behind explicit user actions.
    """

    def __init__(
        self,
        email: str,
        password: str,
        *,
        session: aiohttp.ClientSession | None = None,
        context: MontaAppContext | None = None,
        base_url: str = APP_API_BASE_URL,
    ) -> None:
        self.email = email
        self._password = password
        self.context = context or MontaAppContext()
        self.token: MontaToken | None = None
        self.profile: dict[str, Any] | None = None
        self._auth_lock = asyncio.Lock()
        super().__init__(
            base_url,
            session=session,
            default_headers=self.context.headers(),
        )

    def restore_token(self, token: MontaToken) -> None:
        """Restore a token obtained by an earlier app login."""
        self.token = token

    async def login(self, *, force: bool = False) -> dict[str, Any]:
        """Authenticate with the ON app account and retain its bearer token."""
        async with self._auth_lock:
            if (
                not force
                and self.token is not None
                and not self.token.access_token_expired()
                and self.profile is not None
            ):
                return self.profile
            payload = await self._request(
                "POST",
                "/api/v1/auth/login",
                json_body={"email": self.email, "password": self._password},
                action="Monta app login",
            )
            profile = _require_mapping(payload, "app login")
            try:
                self.token = MontaToken.from_payload(profile)
            except ValueError as err:
                raise MontaResponseError(str(err), payload=payload) from err
            self.profile = profile
            return profile

    async def get_current_user(
        self, *, includes: str | Sequence[str] | None = None
    ) -> dict[str, Any]:
        payload = await self._app_request(
            "GET",
            "/api/v1/users/me",
            params=compact_dict({"include": csv_value(includes)}),
        )
        return _require_mapping(payload, "current user")

    async def list_teams(
        self, *, team_type: str | None = None
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._app_request(
            "GET", "/api/v1/teams", params=compact_dict({"type": team_type})
        )
        return MontaPage.from_payload(payload)

    async def get_personal_team(self) -> dict[str, Any]:
        payload = await self._app_request("GET", "/api/v1/teams/personal")
        return _require_mapping(payload, "personal team")

    async def get_team(self, team_id: int | str) -> dict[str, Any]:
        payload = await self._app_request("GET", f"/api/v1/teams/{team_id}")
        return _require_mapping(payload, "team")

    async def list_team_charger_cards(
        self, team_id: int | str, *, page: int = 1
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._app_request(
            "GET",
            "/api/app/bff/cards/chargers/team",
            params={"id": team_id, "page": page},
        )
        return MontaPage.from_payload(payload)

    async def list_team_charge_point_ids(
        self, team_id: int | str, *, page: int = 1
    ) -> tuple[str, ...]:
        cards = await self.list_team_charger_cards(team_id, page=page)
        result: list[str] = []
        for card in cards.items:
            data = card.get("data") if isinstance(card, Mapping) else None
            charge_point_id = data.get("charge_point_id") if isinstance(data, Mapping) else None
            if charge_point_id is not None:
                result.append(str(charge_point_id))
        return tuple(result)

    async def list_charge_points(
        self,
        *,
        team_id: int | str | None = None,
        team_types: str | Sequence[str] | None = None,
        admin: bool | None = None,
        includes: str | Sequence[str] | None = None,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._app_request(
            "GET",
            "/api/v1/charge_points",
            params=compact_dict(
                {
                    "team_id": team_id,
                    "team_types": csv_value(team_types),
                    "admin": _query_bool(admin),
                    "include": csv_value(includes),
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def get_charge_point(
        self,
        charge_point_id: int | str,
        *,
        team_id: int | str | None = None,
        mode: str | None = None,
        amount_type: str | None = None,
        estimated_kwh: float | None = None,
        payment_method: str | None = None,
        planned_pickup_at: str | None = None,
        includes: str | Sequence[str] | None = None,
    ) -> dict[str, Any]:
        payload = await self._app_request(
            "GET",
            f"/api/v1/charge_points/{charge_point_id}",
            params=compact_dict(
                {
                    "include": csv_value(includes),
                    "mode": mode,
                    "amount_type": amount_type,
                    "estimated_kwh": estimated_kwh,
                    "payment_method": payment_method,
                    "team_id": team_id,
                    "planned_pickup_at": planned_pickup_at,
                }
            ),
        )
        return _require_mapping(payload, "app charge point")

    async def get_charger_snapshot(
        self, charge_point_id: int | str, **options: Any
    ) -> ChargerSnapshot:
        return ChargerSnapshot.from_app(
            await self.get_charge_point(charge_point_id, **options)
        )

    async def list_paying_teams(
        self, charge_point_id: int | str
    ) -> MontaPage[MontaPayingTeam]:
        payload = await self._app_request(
            "GET",
            "/api/v1/teams/pay-charge",
            params={"charge_point_id": charge_point_id},
        )
        page = MontaPage.from_payload(payload)
        return _map_page(page, MontaPayingTeam.from_payload)

    async def get_default_paying_team(
        self, charge_point_id: int | str
    ) -> MontaPayingTeam | None:
        teams = await self.list_paying_teams(charge_point_id)
        eligible = [team for team in teams.items if team.can_pay]
        return next((team for team in eligible if team.pre_select), None) or (
            eligible[0] if eligible else None
        )

    async def list_charges(
        self,
        *,
        page: int | None = None,
        per_page: int = 10,
        show_active: bool | None = None,
        includes: str | Sequence[str] | None = ("charge_point_info",),
        excludes: str | Sequence[str] | None = APP_CHARGE_LIST_EXCLUDES,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._app_request(
            "GET",
            "/api/v1/charges",
            params=compact_dict(
                {
                    "page": page,
                    "per_page": per_page,
                    "show_active": _query_bool(show_active),
                    "include": csv_value(includes),
                    "exclude": csv_value(excludes),
                }
            ),
        )
        return MontaPage.from_payload(payload)

    async def list_charge_sessions(self, **filters: Any) -> MontaPage[ChargeSession]:
        return _map_page(await self.list_charges(**filters), ChargeSession.from_payload)

    async def get_active_charge(
        self, charge_point_id: int | str
    ) -> ChargeSession | None:
        page = await self.list_charge_sessions(show_active=True, per_page=10)
        target = str(charge_point_id)
        return next(
            (
                charge
                for charge in page.items
                if charge.charge_point_id == target and charge.is_active
            ),
            None,
        )

    async def get_charge(
        self,
        charge_id: int | str,
        *,
        includes: str | Sequence[str] | None = APP_CHARGE_DETAIL_INCLUDES,
        excludes: str | Sequence[str] | None = None,
    ) -> ChargeSession:
        payload = await self._app_request(
            "GET",
            f"/api/v1/charges/{charge_id}",
            params=compact_dict(
                {"include": csv_value(includes), "exclude": csv_value(excludes)}
            ),
        )
        return ChargeSession.from_payload(_require_mapping(payload, "app charge"))

    async def start_charge(
        self,
        charge_point_id: int | str,
        paying_team_id: int | str,
        *,
        payment_method: str = "team",
        mode: str = "instant",
        amount_type: str = "full",
        includes: str | Sequence[str] = APP_START_INCLUDES,
    ) -> ChargeSession:
        payload = await self._app_request(
            "POST",
            "/api/v1/charges/start",
            json_body={
                "amount_type": amount_type,
                "charge_point_id": str(charge_point_id),
                "include": _spaced_csv(includes),
                "mode": mode,
                "paying_team_id": str(paying_team_id),
                "payment_method": payment_method,
            },
            action="Starting Monta app charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "started app charge"))

    async def stop_charge(
        self,
        charge_id: int | str,
        charge_point_id: int | str,
        *,
        includes: str | Sequence[str] = APP_CHARGE_DETAIL_INCLUDES,
        excludes: str | Sequence[str] | None = ("charge_point",),
    ) -> ChargeSession:
        payload = await self._app_request(
            "POST",
            f"/api/v1/charges/{charge_id}/stop",
            params=compact_dict(
                {
                    "charge_point_id": charge_point_id,
                    "include": csv_value(includes),
                    "exclude": csv_value(excludes),
                }
            ),
            action="Stopping Monta app charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "stopped app charge"))

    async def update_charge_point_settings(
        self, charge_point_id: int | str, settings: MontaChargeSettings
    ) -> dict[str, Any]:
        payload = await self._app_request(
            "PUT",
            "/api/v1/users/charge_point_settings",
            json_body=settings.as_payload(charge_point_id),
            action="Updating Monta charge-point settings",
        )
        return _require_mapping(payload, "charge-point settings")

    async def release_cable(
        self, charge_point_id: int | str, integration_id: int | str
    ) -> dict[str, Any]:
        payload = await self._app_request(
            "GET",
            f"/api/v1/charge_points/{charge_point_id}/integrations/{integration_id}/unlock",
            action="Releasing Monta charge cable",
        )
        return _require_mapping(payload, "cable release")

    async def get_receipt(
        self, charge_id: int | str, *, email: str | None = None
    ) -> dict[str, Any]:
        payload = await self._app_request(
            "GET",
            f"/api/v1/wallet/receipts/charges/{charge_id}",
            params=compact_dict({"email": email}),
        )
        return _require_mapping(payload, "charge receipt")

    async def list_subscriptions(self, *, page: int = 1) -> MontaPage[dict[str, Any]]:
        payload = await self._app_request(
            "GET", "/api/app/bff/me/subscriptions", params={"page": page}
        )
        return MontaPage.from_payload(payload)

    async def list_vehicles(
        self, *, force: bool | None = None, includes: str | Sequence[str] | None = None
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._app_request(
            "GET",
            "/api/v1/vehicles",
            params=compact_dict(
                {"force": _query_bool(force), "include": csv_value(includes)}
            ),
        )
        return MontaPage.from_payload(payload)

    async def list_team_transactions(
        self, team_id: int | str
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._app_request(
            "GET", f"/api/v1/transactions/teams/{team_id}"
        )
        return MontaPage.from_payload(payload)

    async def _app_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        action: str | None = None,
        retry_auth: bool = True,
    ) -> Any:
        if self.token is None or self.token.access_token_expired():
            await self.login(force=self.token is not None)
        assert self.token is not None
        headers = {"Authorization": f"Bearer {self.token.access_token}"}
        try:
            return await self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=headers,
                action=action,
            )
        except MontaAuthError:
            if not retry_auth:
                raise
            await self.login(force=True)
            assert self.token is not None
            return await self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers={"Authorization": f"Bearer {self.token.access_token}"},
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


def _query_bool(value: bool | None) -> str | None:
    if value is None:
        return None
    return "1" if value else "0"


def _spaced_csv(value: str | Sequence[str]) -> str:
    return value if isinstance(value, str) else ", ".join(str(item) for item in value)
