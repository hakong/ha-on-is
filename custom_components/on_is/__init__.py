"""The ON (Orka náttúrunnar) integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .backends import create_backend_client
from .coordinator import OnIsCoordinator
from .const import CONF_BACKEND, DEFAULT_BACKEND, DOMAIN

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older ON config entries."""
    if entry.version == 1:
        data = dict(entry.data)
        data.setdefault(CONF_BACKEND, DEFAULT_BACKEND)
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            version=2,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ON from a config entry."""
    session = async_get_clientsession(hass)
    client = create_backend_client(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        session=session,
        backend_key=entry.data.get(CONF_BACKEND, DEFAULT_BACKEND),
    )

    # Pass 'entry' to the coordinator
    coordinator = OnIsCoordinator(hass, client, entry)
    
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
