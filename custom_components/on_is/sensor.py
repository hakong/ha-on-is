"""Sensor platform for ON integration."""
from __future__ import annotations

import logging
import re
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

    for connector_id, session in coordinator.data.items():
        entities.extend([
            OnIsStatusSensor(coordinator, connector_id, session),
            OnIsPowerSensor(coordinator, connector_id, session),
            OnIsEnergySensor(coordinator, connector_id, session),
            OnIsLastCommSensor(coordinator, connector_id, session),
            OnIsSessionStartSensor(coordinator, connector_id, session),
            OnIsPriceSensor(coordinator, connector_id, session),
            OnIsLastSessionCostSensor(coordinator, connector_id, session),
            OnIsLastSessionEnergySensor(coordinator, connector_id, session),
            OnIsLastSessionTimeSensor(coordinator, connector_id, session),
            OnIsLastSessionDurationSensor(coordinator, connector_id, session),
        ])

    async_add_entities(entities)


class OnIsBaseSensor(CoordinatorEntity):
    """Base class for ON sensors."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        cp_code = session.get("ChargePoint", {}).get("FriendlyCode", "")
        if cp_code:
            base_name = f"ON Charger {cp_code}"
        else:
            loc_name = session.get("Location", {}).get("FriendlyName", "Unknown")
            base_name = f"ON {loc_name}"

        self._attr_name = base_name
        self._attr_unique_id = f"on_is_{connector_id}"
        
        # REMOVED attributes from here to clean up other sensors.
        # They are now only in OnIsStatusSensor.

        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(connector_id))},
            "name": base_name,
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

    @property
    def extra_state_attributes(self):
        """Return technical details only on the Status sensor."""
        if not self.session_data:
            return {}

        # Logic to find phases in either Active or Passive data
        phases = self.session_data.get("Connector", {}).get("NumberOfPhases")
        if not phases or phases == 0:
            phases = self.session_data.get("Evse", {}).get("NumberOfPhases")
            
        evse = self.session_data.get("Evse", {})
        conn = self.session_data.get("Connector", {})
        
        return {
            "max_power_kw": evse.get("MaxPower"),
            "phases": phases,
            "connector_type": conn.get("Type", {}).get("Title"),
            "evse_id": evse.get("Id"),
        }


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
        return super().available and self.native_value is not None


class OnIsPriceSensor(OnIsBaseSensor, SensorEntity):
    """Price per kWh."""
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
            tariffs = self.session_data.get("Connector", {}).get("Tariffs", [])
            if tariffs:
                return tariffs[0].get("Powers", [])[0].get("Times", [])[0].get("Prices", [])[0].get("PricePerUnit")
        except Exception:
            pass
        return None


class OnIsLastSessionCostSensor(OnIsBaseSensor, SensorEntity):
    """Cost of the last completed session."""
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "ISK"
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session Cost"
        self._attr_unique_id = f"{super().unique_id}_last_cost"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        hist = self.session_data.get("LastSessionData", {})
        return hist.get("TotalCosts")


class OnIsLastSessionEnergySensor(OnIsBaseSensor, SensorEntity):
    """Energy delivered in the last completed session."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session Energy"
        self._attr_unique_id = f"{super().unique_id}_last_energy"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        hist = self.session_data.get("LastSessionData", {})
        return hist.get("ActiveEnergyConsumption")


class OnIsLastSessionTimeSensor(OnIsBaseSensor, SensorEntity):
    """End time of the last completed session."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session End"
        self._attr_unique_id = f"{super().unique_id}_last_end"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        hist = self.session_data.get("LastSessionData", {})
        ts = hist.get("ChargingTo") or hist.get("ConnectedTo")
        if ts:
             try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
             except ValueError:
                return None
        return None


class OnIsLastSessionDurationSensor(OnIsBaseSensor, SensorEntity):
    """Duration of the last completed session."""
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session Duration"
        self._attr_unique_id = f"{super().unique_id}_last_duration"

    def _get_diff(self):
        if not self.session_data:
            return None
        hist = self.session_data.get("LastSessionData", {})
        start_str = hist.get("ConnectedFrom")
        end_str = hist.get("ConnectedTo")
        if start_str and end_str:
            try:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                return end - start
            except ValueError:
                pass
        return None

    @property
    def native_value(self):
        diff = self._get_diff()
        if diff:
            total_minutes = int(diff.total_seconds() / 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            return f"{hours}h {minutes}m"
        return None

    @property
    def extra_state_attributes(self):
        """Return raw numbers for automation/templating."""
        diff = self._get_diff()
        if diff:
            return {
                "total_seconds": int(diff.total_seconds()),
                "total_minutes": int(diff.total_seconds() / 60),
                "total_hours": round(diff.total_seconds() / 3600, 2)
            }
        return {}
