"""Switch platform for ON integration."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OnIsCoordinator

_LOGGER = logging.getLogger(__name__)

STICKY_TIMEOUT = 30 

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
    """Switch to Start/Stop charging with Optimistic State."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        self._override_state = None
        self._override_timestamp = 0
        
        cp_code = session.get("ChargePoint", {}).get("FriendlyCode", "")
        
        if cp_code:
            base_name = f"ON Charger {cp_code}"
        else:
            loc_name = session.get("Location", {}).get("FriendlyName", "Unknown")
            base_name = f"ON {loc_name}"

        self._attr_name = f"{base_name} Charging"
        self._attr_unique_id = f"on_is_{connector_id}_switch"
        self._attr_icon = "mdi:ev-plug-type2"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(connector_id))},
            "name": base_name,
        }

    @property
    def session_data(self):
        return self.coordinator.data.get(self.connector_id)

    @property
    def available(self) -> bool:
        return self.session_data is not None

    @property
    def is_on(self) -> bool:
        """Return true if a charging session is active (authorized)."""
        if self._override_state is not None:
            if time.time() - self._override_timestamp < STICKY_TIMEOUT:
                return self._override_state
            else:
                self._override_state = None
        
        if not self.session_data:
            return False
        
        # Check for Active Session ID
        session_info = self.session_data.get("ChargingSession", {})
        if session_info.get("Id"):
            return True
            
        # Fallback Logic
        status_raw = self.session_data.get("Connector", {}).get("Status", {}).get("Title", "")
        status = str(status_raw).lower().strip()
        
        if status == "charging":
            return True

        measurements = self.session_data.get("Measurements", {})
        power_raw = measurements.get("Power", 0)
        try:
            if float(power_raw) > 0.01:
                return True
        except (ValueError, TypeError):
            pass
            
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start charging."""
        if not self.session_data:
            _LOGGER.error("Cannot start charging: No active session data found")
            return

        evse_code = self._get_evse_code()
        conn_id = self.connector_id
        
        await self.coordinator.client.start_charging(evse_code, conn_id)
        
        self._override_state = True
        self._override_timestamp = time.time()
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop charging."""
        if not self.session_data:
            return

        evse_code = self._get_evse_code()
        cp_id = self.session_data.get("ChargePoint", {}).get("Id")
        conn_id = self.connector_id

        await self.coordinator.client.stop_charging(evse_code, cp_id, conn_id)

        self._override_state = False
        self._override_timestamp = time.time()
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    def _get_evse_code(self) -> str:
        if "EvseCode" in self.session_data.get("Connector", {}):
            return self.session_data["Connector"]["EvseCode"]

        cp_code = self.session_data.get("ChargePoint", {}).get("FriendlyCode")
        evse_code = self.session_data.get("Evse", {}).get("FriendlyCode")
        conn_code = self.session_data.get("Connector", {}).get("Code")
        
        return f"{cp_code}-{evse_code}-{conn_code}"