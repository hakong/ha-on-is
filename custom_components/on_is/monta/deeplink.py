"""Experimental client for Monta's permanent-link and guest APIs."""
from __future__ import annotations

from dataclasses import dataclass, field
import platform
from typing import Any, Mapping
from urllib.parse import quote
import uuid

import aiohttp

from .base import MontaHttpClient, compact_dict
from .errors import MontaAuthError, MontaResponseError
from .models import (
    ChargeSession,
    ChargerSnapshot,
    DeeplinkSummary,
    MontaPage,
    MontaToken,
)

DEEPLINK_API_BASE_URL = "https://deeplinks.monta.app"
DEFAULT_CHARGE_INCLUDES = (
    "charge_point",
    "charge_point.charts",
    "payment",
    "last_measurement",
    "user_actions",
    "error",
    "pre_auth",
    "help_center",
)


@dataclass
class MontaGuestContext:
    """Stable browser-like identity used by the anonymous guest API."""

    operator: str = "on"
    application: str = "on"
    timezone: str = "Atlantic/Reykjavik"
    guest_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    os: str = field(default_factory=lambda: platform.system().lower() or "unknown")
    vendor: str = field(default_factory=lambda: platform.system() or "unknown")

    def headers(self) -> dict[str, str]:
        """Return the identity headers observed in the deployed web client."""
        return {
            "Application": self.application,
            "Operator": self.operator,
            "timezone": self.timezone,
            "Guest_id": self.guest_id,
            "Uuid": self.request_uuid,
            "Meta": "web;production;1.0.0;browser;home-assistant",
        }


class MontaDeeplinkClient(MontaHttpClient):
    """Read permanent-link state and operate an explicitly paid guest charge.

    This is an undocumented API. Guest payment/start methods are exposed as
    primitives for research, but no Home Assistant code calls them.
    """

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession | None = None,
        context: MontaGuestContext | None = None,
        base_url: str = DEEPLINK_API_BASE_URL,
    ) -> None:
        self.context = context or MontaGuestContext()
        super().__init__(
            base_url,
            session=session,
            default_headers=self.context.headers(),
        )
        self.token: MontaToken | None = None
        self.guest_profile: dict[str, Any] | None = None
        self.charge_point_id: int | None = None

    def restore_guest_token(self, token: MontaToken, charge_point_id: int) -> None:
        """Restore a guest token associated with one charge point."""
        self.token = token
        self.charge_point_id = charge_point_id

    async def get_summary(self, code: str | int) -> DeeplinkSummary:
        """Read public permanent-link data without creating a guest."""
        normalized = normalize_deeplink_code(code)
        payload = await self._request("GET", f"/api/deeplink/{normalized}")
        data = _require_mapping(payload, "deeplink summary")
        operator = data.get("operator")
        if isinstance(operator, Mapping):
            self.context.operator = str(
                operator.get("identifier") or self.context.operator
            )
            self.context.application = str(
                operator.get("application_identifier") or self.context.application
            )
            self._default_headers.update(self.context.headers())
        return DeeplinkSummary.from_payload(normalized, data)

    async def create_guest(self, charge_point_id: int) -> dict[str, Any]:
        """Create/renew an anonymous guest scoped to a charge point."""
        payload = await self._request(
            "POST",
            "/api/v1/auth/guest",
            json_body={
                "charge_point_id": charge_point_id,
                "guest_id": self.context.guest_id,
                "os": self.context.os,
                "vendor": self.context.vendor,
            },
            action="Creating Monta guest",
        )
        profile = _require_mapping(payload, "guest authentication")
        try:
            self.token = MontaToken.from_payload(profile)
        except ValueError as err:
            raise MontaResponseError(str(err), payload=payload) from err
        self.charge_point_id = charge_point_id
        self.guest_profile = profile
        return profile

    async def get_current_user(self, charge_point_id: int | None = None) -> dict[str, Any]:
        payload = await self._guest_request(
            "GET", "/api/v1/users/me", charge_point_id=charge_point_id
        )
        return _require_mapping(payload, "guest user")

    async def get_charge_point(self, charge_point_id: int) -> dict[str, Any]:
        payload = await self._guest_request(
            "GET",
            f"/api/v1/charge_points/{charge_point_id}",
            charge_point_id=charge_point_id,
        )
        return _require_mapping(payload, "guest charge point")

    async def get_charger_snapshot(self, charge_point_id: int) -> ChargerSnapshot:
        return ChargerSnapshot.from_deeplink(
            await self.get_charge_point(charge_point_id)
        )

    async def list_charges(
        self,
        charge_point_id: int,
        *,
        per_page: int = 5,
        includes: tuple[str, ...] = DEFAULT_CHARGE_INCLUDES,
    ) -> MontaPage[dict[str, Any]]:
        payload = await self._guest_request(
            "GET",
            "/api/v1/charges",
            charge_point_id=charge_point_id,
            params={
                "pagination": "simple",
                "per_page": per_page,
                "include": ",".join(includes),
            },
        )
        return MontaPage.from_payload(payload)

    async def get_active_charge(self, charge_point_id: int) -> ChargeSession | None:
        sessions = await self.list_charge_sessions(charge_point_id)
        return next((session for session in sessions.items if session.is_active), None)

    async def list_charge_sessions(
        self,
        charge_point_id: int,
        *,
        per_page: int = 5,
        includes: tuple[str, ...] = DEFAULT_CHARGE_INCLUDES,
        **_: Any,
    ) -> MontaPage[ChargeSession]:
        page = await self.list_charges(
            charge_point_id,
            per_page=per_page,
            includes=includes,
        )
        return _map_page(page, ChargeSession.from_payload)

    async def get_charge(
        self,
        charge_point_id: int,
        charge_id: int,
        *,
        includes: tuple[str, ...] = DEFAULT_CHARGE_INCLUDES,
    ) -> ChargeSession:
        payload = await self._guest_request(
            "GET",
            f"/api/v1/charges/{charge_id}",
            charge_point_id=charge_point_id,
            params={"include": ",".join(includes)},
        )
        return ChargeSession.from_payload(_require_mapping(payload, "guest charge"))

    async def create_stripe_charge_payment_intent(
        self, charge_point_id: int
    ) -> dict[str, Any]:
        """Create the ad-hoc card/Google Pay hold used by the guest page."""
        payload = await self._guest_request(
            "POST",
            "/api/v1/wallet/stripe/payment_intents/charge",
            charge_point_id=charge_point_id,
            json_body={"charge_point_id": charge_point_id},
        )
        return _require_mapping(payload, "Stripe payment intent")

    async def create_adyen_charge_payment(
        self,
        charge_point_id: int,
        *,
        payment_method: Mapping[str, Any],
        redirect_url: str,
    ) -> dict[str, Any]:
        payload = await self._guest_request(
            "POST",
            "/api/v1/wallet/adyen/payments/charge",
            charge_point_id=charge_point_id,
            json_body={
                "charge_point_id": charge_point_id,
                "payment_method": dict(payment_method),
                "redirect_url": redirect_url,
            },
        )
        return _require_mapping(payload, "Adyen payment")

    async def confirm_adyen_charge_payment(
        self, charge_point_id: int, redirect_result: str
    ) -> dict[str, Any]:
        payload = await self._guest_request(
            "GET",
            f"/api/v1/wallet/adyen/payments/details/{quote(redirect_result, safe='')}",
            charge_point_id=charge_point_id,
        )
        return _require_mapping(payload, "Adyen payment confirmation")

    async def start_paid_charge(
        self,
        charge_point_id: int,
        *,
        email: str | None = None,
        stripe_payment_intent_id: str | None = None,
        adyen_payment_reference: str | None = None,
        payment_method: str | None = None,
    ) -> ChargeSession:
        """Start an anonymous charge after an external payment succeeds."""
        if bool(stripe_payment_intent_id) == bool(adyen_payment_reference):
            raise ValueError(
                "provide exactly one Stripe payment intent or Adyen payment reference"
            )
        body = compact_dict(
            {
                "charge_point_id": charge_point_id,
                "email": email,
                "payment_intent_id": stripe_payment_intent_id,
                "payment_id": adyen_payment_reference,
                "payment_method": payment_method,
            }
        )
        payload = await self._guest_request(
            "POST",
            "/api/v1/charges/start",
            charge_point_id=charge_point_id,
            params={"include": ",".join(DEFAULT_CHARGE_INCLUDES)},
            json_body=body,
            action="Starting paid Monta guest charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "guest charge"))

    async def stop_charge(
        self, charge_point_id: int, charge_id: int
    ) -> ChargeSession:
        payload = await self._guest_request(
            "POST",
            f"/api/v1/charges/{charge_id}/stop",
            charge_point_id=charge_point_id,
            action="Stopping Monta guest charge",
        )
        return ChargeSession.from_payload(_require_mapping(payload, "guest charge"))

    async def get_receipt(self, charge_point_id: int, charge_id: int) -> dict[str, Any]:
        payload = await self._guest_request(
            "GET",
            f"/api/v1/wallet/receipts/charges/{charge_id}",
            charge_point_id=charge_point_id,
        )
        return _require_mapping(payload, "guest receipt")

    async def _guest_request(
        self,
        method: str,
        path: str,
        *,
        charge_point_id: int | None,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        action: str | None = None,
        retry_auth: bool = True,
    ) -> Any:
        target_id = charge_point_id or self.charge_point_id
        if target_id is None:
            raise ValueError("charge_point_id is required to create a guest")
        if self.token is None or self.charge_point_id != target_id:
            await self.create_guest(target_id)
        assert self.token is not None
        try:
            return await self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers={"Authorization": f"Bearer {self.token.access_token}"},
                action=action,
            )
        except MontaAuthError:
            if not retry_auth:
                raise
            await self.create_guest(target_id)
            assert self.token is not None
            return await self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers={"Authorization": f"Bearer {self.token.access_token}"},
                action=action,
            )


def normalize_deeplink_code(code: str | int) -> str:
    """Normalize an integer or cp-prefixed permanent-link code."""
    text = str(code).strip()
    if text.lower().startswith("cp"):
        text = text[2:]
    if not text.isdigit():
        raise ValueError("deeplink code must be a numeric charge-point id")
    return f"cp{text}"


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
