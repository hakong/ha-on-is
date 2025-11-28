"""Sensor platform for ON integration."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

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
import homeassistant.util.dt as dt_util

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
            
            OnIsCurrentSessionDurationSensor(coordinator, connector_id, session),
            OnIsCurrentSessionCostSensor(coordinator, connector_id, session),
        ])

    async_add_entities(entities)


class OnIsBaseSensor(CoordinatorEntity):
    """Base class for ON sensors."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        cp_code = session.get("ChargePoint", {}).get("FriendlyCode", "")
        # Fix for Active API returning long code
        if cp_code and "-" in cp_code:
            cp_code = cp_code.split("-")[-1]

        if cp_code:
            base_name = f"ON Charger {cp_code}"
        else:
            loc_name = session.get("Location", {}).get("FriendlyName", "Unknown")
            base_name = f"ON {loc_name}"

        self._attr_name = base_name
        self._attr_unique_id = f"on_is_{connector_id}"
        
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
        if not self.session_data:
            return {}
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
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Current Session Energy"
        self._attr_unique_id = f"{super().unique_id}_energy"

    @property
    def native_value(self):
        if not self.session_data:
            return 0.0
        return self.session_data.get("Measurements", {}).get("ActiveEnergyConsumed", 0.0)


class OnIsLastCommSensor(OnIsBaseSensor, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC 

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Communication with charger"
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
    """Timestamp of when the session/charging started."""
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    
    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Session Start"
        self._attr_unique_id = f"{super().unique_id}_session_start"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        
        # Priority 1: Official Billing Session Start
        session = self.session_data.get("ChargingSession", {})
        ts = session.get("ChargingFrom") or session.get("ConnectedFrom")
        
        # Priority 2: Fallback to Last Status Change (e.g. "Preparing" -> "Occupied")
        if not ts:
            ts = self.session_data.get("LastStatusChangeTime")
            # Only use this fallback if we are actually occupied/charging
            status = self.session_data.get("Connector", {}).get("Status", {}).get("Title", "").lower()
            if status not in ["occupied", "charging", "suspended ev", "suspended evse"]:
                return None

        if ts:
             try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
             except ValueError:
                return None
        return None


class OnIsPriceSensor(OnIsBaseSensor, SensorEntity):
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


# --- LIVE SENSORS ---

class OnIsCurrentSessionDurationSensor(OnIsBaseSensor, SensorEntity):
    """Duration of the current active session."""
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Current Session Duration"
        self._attr_unique_id = f"{super().unique_id}_current_duration"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        
        # Priority 1: Official Billing Session
        session = self.session_data.get("ChargingSession", {})
        start_str = session.get("ChargingFrom") or session.get("ConnectedFrom")
        
        # Priority 2: Fallback to Status Change
        if not start_str:
            status = self.session_data.get("Connector", {}).get("Status", {}).get("Title", "").lower()
            if status in ["occupied", "charging", "suspended ev"]:
                start_str = self.session_data.get("LastStatusChangeTime")
        
        if start_str:
            try:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                now = dt_util.utcnow()
                
                diff = now - start
                total_minutes = int(diff.total_seconds() / 60)
                
                if total_minutes < 60:
                    return f"{total_minutes}m"
                
                hours = total_minutes // 60
                minutes = total_minutes % 60
                return f"{hours}h {minutes}m"
            except ValueError:
                pass
        return None


class OnIsCurrentSessionCostSensor(OnIsBaseSensor, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "ISK"
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Current Session Cost"
        self._attr_unique_id = f"{super().unique_id}_current_cost"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        try:
            energy = self.session_data.get("Measurements", {}).get("ActiveEnergyConsumed", 0.0)
            tariffs = self.session_data.get("Connector", {}).get("Tariffs", [])
            price = 0.0
            if tariffs:
                price = tariffs[0].get("Powers", [])[0].get("Times", [])[0].get("Prices", [])[0].get("PricePerUnit", 0.0)
            if energy and price:
                return round(float(energy) * float(price), 2)
        except Exception:
            pass
        return 0.0


# --- HISTORY SENSORS ---

class OnIsLastSessionCostSensor(OnIsBaseSensor, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "ISK"
    _attr_icon = "mdi:cash"
    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session Cost"
        self._attr_unique_id = f"{super().unique_id}_last_cost"
    @property
    def native_value(self):
        if not self.session_data: return None
        hist = self.session_data.get("LastSessionData", {})
        return hist.get("TotalCosts")

class OnIsLastSessionEnergySensor(OnIsBaseSensor, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL
    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session Energy"
        self._attr_unique_id = f"{super().unique_id}_last_energy"
    @property
    def native_value(self):
        if not self.session_data: return None
        hist = self.session_data.get("LastSessionData", {})
        return hist.get("ActiveEnergyConsumption")

class OnIsLastSessionTimeSensor(OnIsBaseSensor, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session End"
        self._attr_unique_id = f"{super().unique_id}_last_end"
    @property
    def native_value(self):
        if not self.session_data: return None
        hist = self.session_data.get("LastSessionData", {})
        ts = hist.get("ChargingTo") or hist.get("ConnectedTo")
        if ts:
             try: return datetime.fromisoformat(ts.replace("Z", "+00:00"))
             except ValueError: return None
        return None

class OnIsLastSessionDurationSensor(OnIsBaseSensor, SensorEntity):
    _attr_icon = "mdi:timer-outline"
    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session Duration"
        self._attr_unique_id = f"{super().unique_id}_last_duration"
    def _get_diff(self):
        if not self.session_data: return None
        hist = self.session_data.get("LastSessionData", {})
        start_str = hist.get("ConnectedFrom")
        end_str = hist.get("ConnectedTo")
        if start_str and end_str:
            try:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                return end - start
            except ValueError: pass
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
        diff = self._get_diff()
        if diff:
            return {"total_seconds": int(diff.total_seconds()), "total_minutes": int(diff.total_seconds() / 60)}
        return {}