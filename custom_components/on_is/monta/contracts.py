"""Protocols and capability metadata for composing Monta API clients."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .models import ChargeSession, ChargerSnapshot, MontaPage


class MontaApiStability(str, Enum):
    """Support level of a Monta API surface."""

    DOCUMENTED = "documented"
    PRIVATE = "private"


class MontaCapability(str, Enum):
    """Feature units exposed by one or more Monta API surfaces."""

    AUTH_APPLICATION = "auth_application"
    AUTH_GUEST = "auth_guest"
    AUTH_USER = "auth_user"
    CHARGER_READ = "charger_read"
    CHARGE_HISTORY = "charge_history"
    CHARGE_CONTROL = "charge_control"
    CABLE_RELEASE = "cable_release"
    CABLE_STATE = "cable_state"
    LIVE_TELEMETRY = "live_telemetry"
    WALLET = "wallet"
    PRICING = "pricing"
    RECEIPTS = "receipts"
    STATISTICS = "statistics"
    WEBHOOKS = "webhooks"


@dataclass(frozen=True)
class MontaApiSurface:
    """Static metadata used by setup flows and diagnostics."""

    key: str
    name: str
    base_url: str
    stability: MontaApiStability
    capabilities: frozenset[MontaCapability]
    notes: str

    def supports(self, capability: MontaCapability) -> bool:
        return capability in self.capabilities


PUBLIC_SURFACE = MontaApiSurface(
    key="monta_public",
    name="Monta Public API",
    base_url="https://public-api.monta.com/api/v1",
    stability=MontaApiStability.DOCUMENTED,
    capabilities=frozenset(
        {
            MontaCapability.AUTH_APPLICATION,
            MontaCapability.CHARGER_READ,
            MontaCapability.CHARGE_HISTORY,
            MontaCapability.CHARGE_CONTROL,
            MontaCapability.CABLE_STATE,
            MontaCapability.WALLET,
            MontaCapability.PRICING,
        }
    ),
    notes="User-scoped; ON-managed charge-point access is currently forbidden.",
)

PARTNER_SURFACE = MontaApiSurface(
    key="monta_partner",
    name="Monta Partner API",
    base_url="https://partner-api.monta.com/api/v1",
    stability=MontaApiStability.DOCUMENTED,
    capabilities=frozenset(MontaCapability),
    notes="Requires a separately provisioned operator consumer.",
)

HUB_SURFACE = MontaApiSurface(
    key="monta_hub",
    name="Monta Hub private API",
    base_url="https://hub.monta.app",
    stability=MontaApiStability.PRIVATE,
    capabilities=frozenset(
        {
            MontaCapability.CHARGER_READ,
            MontaCapability.CHARGE_HISTORY,
            MontaCapability.CHARGE_CONTROL,
            MontaCapability.CABLE_STATE,
            MontaCapability.LIVE_TELEMETRY,
            MontaCapability.WALLET,
            MontaCapability.PRICING,
            MontaCapability.STATISTICS,
        }
    ),
    notes="Requires an externally authenticated Hub browser session.",
)

DEEPLINK_SURFACE = MontaApiSurface(
    key="monta_deeplink",
    name="Monta deeplink guest API",
    base_url="https://deeplinks.monta.app",
    stability=MontaApiStability.PRIVATE,
    capabilities=frozenset(
        {
            MontaCapability.AUTH_GUEST,
            MontaCapability.CHARGER_READ,
            MontaCapability.CHARGE_HISTORY,
            MontaCapability.CHARGE_CONTROL,
            MontaCapability.CABLE_STATE,
            MontaCapability.PRICING,
        }
    ),
    notes="Anonymous ad-hoc payment identity; never equivalent to ON monthly billing.",
)

APP_SURFACE = MontaApiSurface(
    key="monta_app",
    name="Monta signed-in app private API",
    base_url="https://api.monta.app",
    stability=MontaApiStability.PRIVATE,
    capabilities=frozenset(
        {
            MontaCapability.AUTH_USER,
            MontaCapability.CHARGER_READ,
            MontaCapability.CHARGE_HISTORY,
            MontaCapability.CHARGE_CONTROL,
            MontaCapability.CABLE_RELEASE,
            MontaCapability.CABLE_STATE,
            MontaCapability.LIVE_TELEMETRY,
            MontaCapability.WALLET,
            MontaCapability.PRICING,
            MontaCapability.RECEIPTS,
        }
    ),
    notes="Undocumented Android API; provides ON account-credit payer context.",
)

MONTA_API_SURFACES = {
    surface.key: surface
    for surface in (
        PUBLIC_SURFACE,
        PARTNER_SURFACE,
        HUB_SURFACE,
        DEEPLINK_SURFACE,
        APP_SURFACE,
    )
}


@runtime_checkable
class MontaNormalizedReader(Protocol):
    """Minimum normalized read contract for a future coordinator."""

    async def get_charger_snapshot(self, charge_point_id: int) -> ChargerSnapshot:
        """Return the current charge-point snapshot."""

    async def get_active_charge(
        self, charge_point_id: int
    ) -> ChargeSession | None:
        """Return the active session, if one is visible."""

    async def list_charge_sessions(
        self, **filters: Any
    ) -> MontaPage[ChargeSession]:
        """Return normalized current or historical sessions."""


@runtime_checkable
class MontaChargeController(Protocol):
    """Conceptual start/stop contract; concrete payer arguments differ by API."""

    async def start_charge(self, charge_point_id: int, **kwargs: Any) -> Any:
        """Start charging with surface-specific explicit payer arguments."""

    async def stop_charge(self, resource_id: int, **kwargs: Any) -> Any:
        """Stop charging using the ID required by the concrete surface."""
