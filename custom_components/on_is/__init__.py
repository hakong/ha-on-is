"""The ON (Orka náttúrunnar) integration."""
from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .backends import create_backend_client
from .coordinator import OnIsCoordinator
from .const import (
    BACKEND_MONTA_APP,
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_BACKEND,
    CONF_CHARGE_POINT_ID,
    CONF_CONNECTOR_ID,
    CONF_DEVICE_UUID,
    CONF_EVSE_CODE,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_TOKEN_EXPIRES_AT,
    CONF_TEAM_ID,
    DEFAULT_BACKEND,
    DOMAIN,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

ENTRY_VERSION = 3
_LEGACY_UNIQUE_ID = re.compile(
    r"^on_is_(?P<connector>.+)_(?:status|power|energy|last_comm|session_start|"
    r"price|last_cost|last_energy|last_end|last_duration|current_duration|"
    r"current_cost|switch)$"
)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older ON config entries."""
    data = dict(entry.data)
    if entry.version == 1:
        data.setdefault(CONF_BACKEND, DEFAULT_BACKEND)

    if entry.version < ENTRY_VERSION:
        # OCEAN was retired by ON. Keep the old connector identifier so HA's
        # entity registry continues to address the same entities after moving
        # all network calls to Monta.
        data[CONF_BACKEND] = BACKEND_MONTA_APP
        data.setdefault(CONF_CONNECTOR_ID, _legacy_connector_id(hass, entry))
        if data.get(CONF_CONNECTOR_ID) is None:
            data.pop(CONF_CONNECTOR_ID, None)

    hass.config_entries.async_update_entry(entry, data=data, version=ENTRY_VERSION)
    return True


def _legacy_connector_id(hass: HomeAssistant, entry: ConfigEntry) -> int | str | None:
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        match = _LEGACY_UNIQUE_ID.match(entity.unique_id)
        if not match:
            continue
        value = match.group("connector")
        try:
            return int(value)
        except ValueError:
            return value
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ON from a config entry."""
    session = async_get_clientsession(hass)
    client = create_backend_client(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        session=session,
        backend_key=entry.data.get(CONF_BACKEND, DEFAULT_BACKEND),
        charge_point_id=entry.data.get(CONF_CHARGE_POINT_ID),
        team_id=entry.data.get(CONF_TEAM_ID),
        evse_code=entry.data.get(CONF_EVSE_CODE),
        connector_id=entry.data.get(CONF_CONNECTOR_ID),
        device_uuid=entry.data.get(CONF_DEVICE_UUID),
        access_token=entry.data.get(CONF_ACCESS_TOKEN),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        access_token_expires_at=entry.data.get(CONF_ACCESS_TOKEN_EXPIRES_AT),
        refresh_token_expires_at=entry.data.get(CONF_REFRESH_TOKEN_EXPIRES_AT),
    )

    coordinator = OnIsCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    resolved_data = dict(entry.data)
    for key, value in (
        (CONF_CHARGE_POINT_ID, getattr(client, "charge_point_id", None)),
        (CONF_TEAM_ID, getattr(client, "team_id", None)),
        (CONF_CONNECTOR_ID, getattr(client, "connector_id", None)),
    ):
        if value is not None:
            resolved_data[key] = value
    if resolved_data != dict(entry.data):
        hass.config_entries.async_update_entry(entry, data=resolved_data)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: OnIsCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.close()
    return unload_ok
