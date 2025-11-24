"""The ON (Orka náttúrunnar) integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OnIsClient
from .coordinator import OnIsCoordinator
from .const import DOMAIN

# Platforms to load (Sensor = Read only, Switch = Start/Stop)
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ON from a config entry."""
    
    # 1. Create the API Client
    session = async_get_clientsession(hass)
    client = OnIsClient(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    # 2. Create the Coordinator (Polls API)
    coordinator = OnIsCoordinator(hass, client)
    
    # 3. Fetch initial data so we don't wait 30s for entities to appear
    await coordinator.async_config_entry_first_refresh()

    # 4. Store them in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # 5. Load the platforms (sensor.py, switch.py)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok