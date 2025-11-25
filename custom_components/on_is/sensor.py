"""Sensor platform for ON integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OnIsCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ON sensors."""
    coordinator: OnIsCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    
    # 1. Always add a global session counter so the integration never looks "empty"
    entities.append(OnIsSessionCount(coordinator))

    # 2. Add sensors for any active sessions found during setup
    # Note: If the car is unplugged during restart, these might not show up 
    # until the integration is reloaded while plugged in.
    for connector_id, session in coordinator.data.items():
        entities.extend([
            OnIsStatusSensor(coordinator, connector_id, session),
            OnIsPowerSensor(coordinator, connector_id, session),
            OnIsEnergySensor(coordinator, connector_id, session),
        ])

    async_add_entities(entities)


class OnIsBaseSensor(CoordinatorEntity):
    """Base class for ON sensors."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        # Get Location Name
        loc_name = session.get("Location", {}).get("FriendlyName", "Unknown")
        
        # Get specific Charger ID (e.g. "3806") to distinguish neighbors
        cp_code = session.get("ChargePoint", {}).get("FriendlyCode", "")
        
        # New Name Format: "ON Urriðaholtsstræti 30... (3806)"
        if cp_code:
            self._attr_name = f"ON {loc_name} ({cp_code})"
        else:
            self._attr_name = f"ON {loc_name}"

        self._attr_unique_id = f"on_is_{connector_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(connector_id))},
            "name": f"{loc_name} ({cp_code})" if cp_code else loc_name,
            "manufacturer": "Etrel / ON",
            "model": cp_code or "EV Charger",
        }

    @property
    def session_data(self):
        """Helper to get data for this specific connector."""
        return self.coordinator.data.get(self.connector_id)
        
    @property
    def available(self) -> bool:
        """Entity is available only if the session exists in the API response."""
        return super().available and self.session_data is not None


class OnIsStatusSensor(OnIsBaseSensor, SensorEntity):
    """Sensor for the charging status (Preparing, Charging, Suspended)."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Status"
        self._attr_unique_id = f"{super().unique_id}_status"
        self._attr_icon = "mdi:ev-station"

    @property
    def native_value(self):
        if not self.session_data:
            return "Disconnected"
            
        return (
            self.session_data.get("Connector", {})
            .get("Status", {})
            .get("Title", "Unknown")
        )


class OnIsPowerSensor(OnIsBaseSensor, SensorEntity):
    """Sensor for current charging power (kW)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Power"
        self._attr_unique_id = f"{super().unique_id}_power"

    @property
    def native_value(self):
        if not self.session_data:
            return 0.0
        return self.session_data.get("Measurements", {}).get("Power", 0.0)


class OnIsEnergySensor(OnIsBaseSensor, SensorEntity):
    """Sensor for energy added this session (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Energy"
        self._attr_unique_id = f"{super().unique_id}_energy"

    @property
    def native_value(self):
        if not self.session_data:
            return 0.0
        return self.session_data.get("Measurements", {}).get("ActiveEnergyConsumed", 0.0)


class OnIsSessionCount(CoordinatorEntity, SensorEntity):
    """Global sensor to see how many active sessions exist."""
    
    _attr_name = "ON Active Sessions"
    _attr_icon = "mdi:car-electric"
    _attr_unique_id = "on_is_active_sessions"

    def __init__(self, coordinator):
        super().__init__(coordinator)

    @property
    def native_value(self):
        return len(self.coordinator.data)