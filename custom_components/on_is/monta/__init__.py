"""Reusable clients and models for Monta API surfaces.

These modules are intentionally independent from the Home Assistant coordinator.
The Public and Partner clients wrap documented APIs. The app, Hub, and deeplink
clients wrap observed private APIs and must be treated as experimental.
"""

from .app import (
    MontaAppClient,
    MontaAppContext,
    MontaChargeSettings,
    MontaPayingTeam,
)
from .deeplink import MontaDeeplinkClient, MontaGuestContext
from .contracts import (
    APP_SURFACE,
    DEEPLINK_SURFACE,
    HUB_SURFACE,
    MONTA_API_SURFACES,
    PARTNER_SURFACE,
    PUBLIC_SURFACE,
    MontaApiStability,
    MontaApiSurface,
    MontaCapability,
    MontaChargeController,
    MontaNormalizedReader,
)
from .errors import (
    MontaAccessError,
    MontaApiError,
    MontaAuthError,
    MontaNotFoundError,
    MontaRateLimitError,
    MontaResponseError,
)
from .hub import MontaHubClient
from .models import (
    ChargeSession,
    ChargerSnapshot,
    DeeplinkSummary,
    MontaPage,
    MontaToken,
    TelemetryMeasurement,
)
from .partner import MontaPartnerClient
from .public import MontaPublicClient
from .redaction import redact_monta_data, redact_url

__all__ = [
    "APP_SURFACE",
    "ChargeSession",
    "ChargerSnapshot",
    "DEEPLINK_SURFACE",
    "DeeplinkSummary",
    "HUB_SURFACE",
    "MONTA_API_SURFACES",
    "MontaAccessError",
    "MontaAppClient",
    "MontaAppContext",
    "MontaApiError",
    "MontaApiStability",
    "MontaApiSurface",
    "MontaAuthError",
    "MontaDeeplinkClient",
    "MontaCapability",
    "MontaChargeSettings",
    "MontaChargeController",
    "MontaGuestContext",
    "MontaHubClient",
    "MontaNotFoundError",
    "MontaNormalizedReader",
    "MontaPage",
    "MontaPayingTeam",
    "MontaPartnerClient",
    "MontaPublicClient",
    "MontaRateLimitError",
    "MontaResponseError",
    "MontaToken",
    "PARTNER_SURFACE",
    "PUBLIC_SURFACE",
    "TelemetryMeasurement",
    "redact_monta_data",
    "redact_url",
]
