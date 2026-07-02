"""Diagnostics support for the ON integration."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import OnIsCoordinator

TO_REDACT = {CONF_PASSWORD}


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
        diagnostics["connector_ids"] = sorted((coordinator.data or {}).keys())

    return diagnostics
