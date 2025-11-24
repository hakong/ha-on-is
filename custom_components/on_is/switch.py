"""Switch platform for ON integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OnIsCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ON switches."""
    coordinator: OnIsCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for connector_id, session in coordinator.data.items():
        entities.append(OnIsChargerSwitch(coordinator, connector_id, session))

    async_add_entities(entities)


class OnIsChargerSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to Start/Stop charging."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        loc_name = session.get("Location", {}).get("FriendlyName", "Unknown")
        self._attr_name = f"ON {loc_name} Control"
        self._attr_unique_id = f"on_is_{connector_id}_switch"
        self._attr_icon = "mdi:ev-plug-type2"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(connector_id))},
            "name": loc_name,
        }

    @property
    def session_data(self):
        return self.coordinator.data.get(self.connector_id)

    @property
    def available(self) -> bool:
        """Switch is only available if car is plugged in."""
        return self.session_data is not None

    @property
    def is_on(self) -> bool:
        """Return true if charging."""
        if not self.session_data:
            return False
        
        status = self.session_data.get("Connector", {}).get("Status", {}).get("Title", "").lower()
        # 'charging' is obviously on. 'occupied' usually means plugged in but idle.
        # 'suspended evse' or 'suspended ev' means stopped.
        return status == "charging"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start charging."""
        if not self.session_data:
            _LOGGER.error("Cannot start charging: No active session data found")
            return

        evse_code = self._get_evse_code()
        conn_id = self.connector_id
        
        _LOGGER.debug(f"Sending Start Command: EvseCode={evse_code}, ConnectorId={conn_id}")
        
        await self.coordinator.client.start_charging(evse_code, conn_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop charging."""
        if not self.session_data:
            return

        evse_code = self._get_evse_code()
        cp_id = self.session_data.get("ChargePoint", {}).get("Id")
        conn_id = self.connector_id

        _LOGGER.debug(f"Sending Stop Command: EvseCode={evse_code}, CP={cp_id}, Conn={conn_id}")

        await self.coordinator.client.stop_charging(evse_code, cp_id, conn_id)
        await self.coordinator.async_request_refresh()

    def _get_evse_code(self) -> str:
        """Constructs the EvseCode required for commands."""
        # Formula based on logs: ChargePointCode-EvseFriendlyCode-ConnectorCode
        # Example: IS*ONP00281-3806-1-1
        
        cp_code = self.session_data.get("ChargePoint", {}).get("FriendlyCode")
        evse_code = self.session_data.get("Evse", {}).get("FriendlyCode")
        conn_code = self.session_data.get("Connector", {}).get("Code")
        
        return f"{cp_code}-{evse_code}-{conn_code}"