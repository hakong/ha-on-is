"""Diagnostics support for the ON integration."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_UUID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .coordinator import OnIsCoordinator

TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_UUID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return redacted diagnostics for an ON config entry."""
    coordinator: OnIsCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    diagnostics = {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
    }

    if coordinator is not None:
        diagnostics["backend"] = {
            "key": coordinator.backend_key,
            "name": coordinator.backend_name,
            "api_family": coordinator.api_family,
            "base_url": coordinator.base_url,
        }
        diagnostics["last_successful_update"] = coordinator.last_successful_update
        diagnostics["last_update_error"] = coordinator.last_update_error
        diagnostics["poll_interval_seconds"] = (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        )
        diagnostics["connector_ids"] = sorted((coordinator.data or {}).keys())
        diagnostics["charger"] = async_redact_data(
            {
                str(connector_id): {
                    "status": data.get("Connector", {}).get("Status", {}).get("Title"),
                    "evse_code": data.get("Connector", {}).get("EvseCode"),
                    "monta": data.get("Monta", {}),
                }
                for connector_id, data in (coordinator.data or {}).items()
            },
            {"evse_code", "ActiveChargeId", "IntegrationId"},
        )

    return diagnostics
