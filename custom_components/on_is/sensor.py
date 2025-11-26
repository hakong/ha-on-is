"""Sensor platform for ON integration."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower, EntityCategory
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
    """Set up ON sensors."""
    coordinator: OnIsCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    # 1. Global Session Count
    entities.append(OnIsSessionCount(coordinator))

    # 2. Per-Charger Sensors
    for connector_id, session in coordinator.data.items():
        entities.extend([
            OnIsStatusSensor(coordinator, connector_id, session),
            OnIsPowerSensor(coordinator, connector_id, session),
            OnIsEnergySensor(coordinator, connector_id, session),
            OnIsLastCommSensor(coordinator, connector_id, session),
            OnIsSessionStartSensor(coordinator, connector_id, session),
            OnIsPriceSensor(coordinator, connector_id, session),
        ])

    async_add_entities(entities)


class OnIsBaseSensor(CoordinatorEntity):
    """Base class for ON sensors."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        loc_name = session.get("Location", {}).get("FriendlyName", "Unknown")
        cp_code = session.get("ChargePoint", {}).get("FriendlyCode", "")

        # Naming
        if cp_code:
            self._attr_name = f"ON {loc_name} ({cp_code})"
        else:
            self._attr_name = f"ON {loc_name}"

        self._attr_unique_id = f"on_is_{connector_id}"
        
        # Technical Attributes
        evse = session.get("Evse", {})
        conn = session.get("Connector", {})
        
        self._attr_extra_state_attributes = {
            "max_power_kw": evse.get("MaxPower"),
            "phases": evse.get("NumberOfPhases"),
            "connector_type": conn.get("Type", {}).get("Title"),
            "evse_id": evse.get("Id"),
        }

        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(connector_id))},
            "name": f"{loc_name} ({cp_code})" if cp_code else loc_name,
            "manufacturer": "Etrel / ON",
            "model": cp_code or "EV Charger",
            "sw_version": "Ocean API",
        }

    @property
    def session_data(self):
        return self.coordinator.data.get(self.connector_id)

    @property
    def available(self) -> bool:
        return super().available and self.session_data is not None


class OnIsStatusSensor(OnIsBaseSensor, SensorEntity):
    """Charging status."""
    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Status"
        self._attr_unique_id = f"{super().unique_id}_status"
        self._attr_icon = "mdi:ev-station"

    @property
    def native_value(self):
        if not self.session_data:
            return "Disconnected"
        return self.session_data.get("Connector", {}).get("Status", {}).get("Title", "Unknown")


class OnIsPowerSensor(OnIsBaseSensor, SensorEntity):
    """Current Power (kW)."""
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
    """Energy Added (kWh)."""
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


class OnIsLastCommSensor(OnIsBaseSensor, SensorEntity):
    """Timestamp of last communication with the charger."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC 

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Communication"
        self._attr_unique_id = f"{super().unique_id}_last_comm"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        # Format: "2025-11-24T11:51:41.16Z"
        ts = self.session_data.get("LastCommunicationTime")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None


class OnIsSessionStartSensor(OnIsBaseSensor, SensorEntity):
    """Timestamp of when the car was plugged in."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    
    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Session Start"
        self._attr_unique_id = f"{super().unique_id}_session_start"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        
        # Try ChargingSession (Active)
        session = self.session_data.get("ChargingSession", {})
        ts = session.get("ConnectedFrom") or session.get("ChargingFrom")
        
        if ts:
             try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
             except ValueError:
                return None
        return None
        
    @property
    def available(self) -> bool:
        # Only available if plugged in and we have a timestamp
        return super().available and self.native_value is not None


class OnIsPriceSensor(OnIsBaseSensor, SensorEntity):
    """Price per kWh extracted from Tariff structure."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "ISK/kWh"
    _attr_icon = "mdi:currency-kzt"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Price"
        self._attr_unique_id = f"{super().unique_id}_price"

    @property
    def native_value(self):
        if not self.session_data:
            return None
            
        try:
            # Navigate deep into the tariff structure
            # Connector -> Tariffs[0] -> Powers[0] -> Times[0] -> Prices[0] -> PricePerUnit
            tariffs = self.session_data.get("Connector", {}).get("Tariffs", [])
            if not tariffs:
                return None
            
            powers = tariffs[0].get("Powers", [])
            if not powers:
                return None
                
            times = powers[0].get("Times", [])
            if not times:
                return None
                
            prices = times[0].get("Prices", [])
            if not prices:
                return None
                
            return prices[0].get("PricePerUnit")
            
        except Exception:
            pass
            
        return None


class OnIsSessionCount(CoordinatorEntity, SensorEntity):
    """Global active session counter."""
    _attr_name = "ON Active Sessions"
    _attr_icon = "mdi:car-electric"
    _attr_unique_id = "on_is_active_sessions"

    def __init__(self, coordinator):
        super().__init__(coordinator)

    @property
    def native_value(self):
        return len(self.coordinator.data)