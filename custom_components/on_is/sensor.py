"""Sensor platform for ON integration."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OnIsCoordinator
from .entity import charger_base_name, charger_device_info
from .helpers import (
    LAST_COMMUNICATION_TIME,
    LAST_COMMUNICATION_TIME_CACHED,
    format_minutes,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ON sensors."""
    coordinator: OnIsCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_connectors: set[int] = set()

    def add_new_entities() -> None:
        entities = []
        for connector_id, session in (coordinator.data or {}).items():
            if connector_id in known_connectors:
                continue
            known_connectors.add(connector_id)
            entities.extend(_build_sensor_entities(coordinator, connector_id, session))

        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


def _build_sensor_entities(coordinator, connector_id, session):
    """Create all sensor entities for a connector."""
    return [
        OnIsStatusSensor(coordinator, connector_id, session),
        OnIsHealthSensor(coordinator, connector_id, session),
        OnIsFirmwareSensor(coordinator, connector_id, session),
        OnIsStabilityScoreSensor(coordinator, connector_id, session),
        OnIsChargeCountSensor(coordinator, connector_id, session),
        OnIsLastConnectedSensor(coordinator, connector_id, session),
        OnIsPowerSensor(coordinator, connector_id, session),
        OnIsEnergySensor(coordinator, connector_id, session),
        OnIsLastCommSensor(coordinator, connector_id, session),
        OnIsSessionStartSensor(coordinator, connector_id, session),
        OnIsPriceSensor(coordinator, connector_id, session),
        OnIsLastSessionCostSensor(coordinator, connector_id, session),
        OnIsLastSessionEnergySensor(coordinator, connector_id, session),
        OnIsLastSessionTimeSensor(coordinator, connector_id, session),
        OnIsLastSessionDurationSensor(coordinator, connector_id, session),
        OnIsLastSessionStateSensor(coordinator, connector_id, session),
        OnIsCurrentSessionDurationSensor(coordinator, connector_id, session),
        OnIsCurrentSessionCostSensor(coordinator, connector_id, session),
        OnIsStateOfChargeSensor(coordinator, connector_id, session),
        OnIsMeterTotalSensor(coordinator, connector_id, session),
        *[
            OnIsPhaseCurrentSensor(coordinator, connector_id, session, phase)
            for phase in (1, 2, 3)
        ],
        *[
            OnIsPhaseVoltageSensor(coordinator, connector_id, session, phase)
            for phase in (1, 2, 3)
        ],
    ]


class OnIsBaseSensor(CoordinatorEntity):
    """Base class for ON sensors."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        base_name = charger_base_name(session)
        self._attr_name = base_name
        self._attr_unique_id = f"on_is_{connector_id}"
        self._attr_device_info = charger_device_info(
            connector_id, session, coordinator
        )

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
        monta = self.session_data.get("Monta", {})
        measurement = self.session_data.get("Measurements", {})
        return {
            "max_power_kw": evse.get("MaxPower"),
            "phases": phases,
            "connector_type": conn.get("Type", {}).get("Title"),
            "evse_id": evse.get("Id"),
            "backend": self.coordinator.backend_name,
            "backend_key": self.coordinator.backend_key,
            "api_family": self.coordinator.api_family,
            "last_successful_update": self.coordinator.last_successful_update,
            "last_update_error": self.coordinator.last_update_error,
            "monta_state": monta.get("State"),
            "cpi_status": monta.get("CpiStatus"),
            "charge_state": monta.get("ChargeState"),
            "failed_at": monta.get("FailedAt"),
            "failure_reason": monta.get("FailureReason"),
            "stop_reason": monta.get("StopReason"),
            "error_title": monta.get("ErrorTitle"),
            "error_description": monta.get("ErrorDescription"),
            "cable_plugged_in": monta.get("CablePluggedIn"),
            "charger_connected": monta.get("Connected"),
            "active_charge_id": monta.get("ActiveChargeId"),
            "can_start": monta.get("CanStart"),
            "can_start_reason": monta.get("CanStartReason"),
            "can_stop": monta.get("CanStop"),
            "can_unlock": monta.get("CanUnlock"),
            "payment_method": monta.get("PaymentMethod"),
            "configured_payment_method": monta.get("ConfiguredPaymentMethod"),
            "payment_method_type": monta.get("PaymentMethodType"),
            "currency": monta.get("Currency"),
            "measurement_time": measurement.get("MeasuredAt"),
            "average_session_power_kw": monta.get("AverageKw"),
            "estimated_kwh": monta.get("EstimatedKwh"),
            "estimated_price": monta.get("EstimatedPrice"),
            "estimated_complete_at": monta.get("EstimatedCompleteAt"),
            "can_smart_charge": monta.get("CanSmartCharge"),
            "auto_charge": monta.get("AutoCharge"),
        }


class OnIsHealthSensor(OnIsBaseSensor, SensorEntity):
    """Summarize charger and integration diagnostics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Health"
        self._attr_unique_id = f"{super().unique_id}_health"

    @property
    def native_value(self):
        if not self.session_data:
            return "unknown"
        monta = self.session_data.get("Monta", {})
        if monta.get("Connected") is False or str(
            monta.get("IntegrationState") or ""
        ).lower() == "disconnected":
            return "disconnected"
        if (
            monta.get("ReconnectRequired") is True
            or _is_error_code(monta.get("ProtocolErrorCode"))
            or _is_error_code(monta.get("ConnectorErrorCode"))
            or _is_unhealthy_state(monta.get("IntegrationState"))
        ):
            return "error"
        if monta.get("Connected") is True or str(
            monta.get("IntegrationState") or ""
        ).lower() == "connected":
            return "healthy"
        return "unknown"

    @property
    def extra_state_attributes(self):
        if not self.session_data:
            return {}
        monta = self.session_data.get("Monta", {})
        return {
            "integration_state": monta.get("IntegrationState"),
            "integration_status": monta.get("IntegrationStatus"),
            "integration_log": monta.get("IntegrationLog"),
            "hub_status": monta.get("HubStatus"),
            "hub_connection": monta.get("HubConnection"),
            "protocol_error_code": monta.get("ProtocolErrorCode"),
            "protocol_error_info": monta.get("ProtocolErrorInfo"),
            "connector_error_code": monta.get("ConnectorErrorCode"),
            "vendor_error_code": monta.get("VendorErrorCode"),
            "connector_status": monta.get("ConnectorStatus"),
            "reconnect_required": monta.get("ReconnectRequired"),
            "meter_accuracy": monta.get("MeterAccuracy"),
            "mid_certified": monta.get("MidCertified"),
            "ocpp": monta.get("Ocpp"),
            "wifi_strength": monta.get("WifiStrength"),
            "cell_strength": monta.get("CellStrength"),
            "connector_updated_at": monta.get("ConnectorUpdatedAt"),
            "hub_updated_at": monta.get("HubUpdatedAt"),
            "hub_data_updated_at": monta.get("HubDataUpdatedAt"),
            "hub_data_error": monta.get("HubDataError"),
            "logs_available": monta.get("LogsAvailable"),
            "logs_error": monta.get("LogsError"),
            "last_log_at": monta.get("LastLogAt"),
            "last_log_type": monta.get("LastLogType"),
        }


class OnIsFirmwareSensor(OnIsBaseSensor, SensorEntity):
    """Installed and available charger firmware."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Firmware"
        self._attr_unique_id = f"{super().unique_id}_firmware"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        return self.session_data.get("Monta", {}).get("FirmwareVersion")

    @property
    def extra_state_attributes(self):
        if not self.session_data:
            return {}
        monta = self.session_data.get("Monta", {})
        return {
            "status": monta.get("FirmwareStatus"),
            "update_available": monta.get("FirmwareUpgradeAvailable"),
            "available_version": monta.get("AvailableFirmwareVersion"),
        }


class OnIsStabilityScoreSensor(OnIsBaseSensor, SensorEntity):
    """Charger or model stability score reported by Monta."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Stability Score"
        self._attr_unique_id = f"{super().unique_id}_stability_score"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        monta = self.session_data.get("Monta", {})
        charger_score = monta.get("ChargerStabilityScore")
        return (
            charger_score
            if charger_score is not None
            else monta.get("ModelStabilityScore")
        )

    @property
    def extra_state_attributes(self):
        if not self.session_data:
            return {}
        monta = self.session_data.get("Monta", {})
        return {
            "scope": (
                "charger"
                if monta.get("ChargerStabilityScore") is not None
                else "model"
            )
        }


class OnIsChargeCountSensor(OnIsBaseSensor, SensorEntity):
    """Lifetime number of charges reported by Hub."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "charges"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Charge Count"
        self._attr_unique_id = f"{super().unique_id}_charge_count"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        return self.session_data.get("Monta", {}).get("ChargeCount")


class OnIsLastConnectedSensor(OnIsBaseSensor, SensorEntity):
    """Latest backend connection timestamp reported by Monta."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-check-outline"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Connected"
        self._attr_unique_id = f"{super().unique_id}_last_connected"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        value = self.session_data.get("Monta", {}).get("LastConnectedAt")
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def extra_state_attributes(self):
        if not self.session_data:
            return {}
        return {
            "disconnected_at": self.session_data.get("Monta", {}).get(
                "DisconnectedAt"
            )
        }


def _is_error_code(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower().replace("_", "") not in {
        "",
        "none",
        "noerror",
        "ok",
    }


def _is_unhealthy_state(value) -> bool:
    return str(value or "").strip().lower() in {
        "error",
        "faulted",
        "failed",
        "unavailable",
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


class OnIsLastCommSensor(OnIsBaseSensor, SensorEntity, RestoreEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC 

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Communication with charger"
        self._attr_unique_id = f"{super().unique_id}_last_comm"
        self._cached_native_value: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last known communication timestamp after HA restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in {"unknown", "unavailable"}:
            return

        self._cached_native_value = self._parse_timestamp(last_state.state)

    @property
    def native_value(self):
        ts = None
        if self.session_data:
            ts = self.session_data.get(LAST_COMMUNICATION_TIME)
        if ts:
            parsed = self._parse_timestamp(ts)
            if parsed:
                self._cached_native_value = parsed
                return parsed
        return self._cached_native_value

    @property
    def available(self) -> bool:
        return super().available or self._cached_native_value is not None

    @property
    def extra_state_attributes(self):
        session = self.session_data
        if not session:
            return {"last_communication_source": "restored"}
        if session.get(LAST_COMMUNICATION_TIME_CACHED):
            return {"last_communication_source": "cached"}
        if session.get(LAST_COMMUNICATION_TIME):
            return {"last_communication_source": "current"}
        if self._cached_native_value is not None:
            return {"last_communication_source": "restored"}
        return {"last_communication_source": "missing"}

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
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
                price = tariffs[0].get("Powers", [])[0].get("Times", [])[0].get("Prices", [])[0].get("PricePerUnit")
                return round(float(price), 2)
        except Exception:
            pass
        return None


# --- LIVE SENSORS ---

class OnIsCurrentSessionDurationSensor(OnIsBaseSensor, SensorEntity):
    """Duration of the current active session."""
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT

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
                now = datetime.now(timezone.utc)
                
                diff = now - start
                return max(0, int(diff.total_seconds() / 60))
            except ValueError:
                pass
        return None

    @property
    def extra_state_attributes(self):
        value = self.native_value
        if value is None:
            return {}
        return {"duration": format_minutes(value)}


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
            session = self.session_data.get("ChargingSession", {})
            if session.get("TotalCosts") is not None:
                return round(float(session["TotalCosts"]), 2)
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


class OnIsStateOfChargeSensor(OnIsBaseSensor, SensorEntity):
    """Vehicle state of charge when the charger supplies it."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Vehicle State of Charge"
        self._attr_unique_id = f"{super().unique_id}_state_of_charge"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        return self.session_data.get("Measurements", {}).get("StateOfCharge")


class OnIsMeterTotalSensor(OnIsBaseSensor, SensorEntity):
    """Lifetime charger meter value when Monta supplies it."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Meter Total"
        self._attr_unique_id = f"{super().unique_id}_meter_total"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        return self.session_data.get("Measurements", {}).get("MeterTotal")


class OnIsPhaseCurrentSensor(OnIsBaseSensor, SensorEntity):
    """Per-phase charging current when available."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, connector_id, session, phase: int):
        super().__init__(coordinator, connector_id, session)
        self.phase = phase
        self._attr_name = f"{super().name} Current L{phase}"
        self._attr_unique_id = f"{super().unique_id}_current_l{phase}"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        return self.session_data.get("Measurements", {}).get(
            f"CurrentL{self.phase}"
        )


class OnIsPhaseVoltageSensor(OnIsBaseSensor, SensorEntity):
    """Per-phase charging voltage when available."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, connector_id, session, phase: int):
        super().__init__(coordinator, connector_id, session)
        self.phase = phase
        self._attr_name = f"{super().name} Voltage L{phase}"
        self._attr_unique_id = f"{super().unique_id}_voltage_l{phase}"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        return self.session_data.get("Measurements", {}).get(
            f"VoltageL{self.phase}"
        )


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

    @property
    def extra_state_attributes(self):
        if not self.session_data:
            return {}
        hist = self.session_data.get("LastSessionData", {})
        return {
            "charge_id": hist.get("Id"),
            "currency": hist.get("Currency"),
            "payment_method": hist.get("PaymentMethod"),
            "state": hist.get("State"),
            "receipt_available": hist.get("ReceiptAvailable"),
            "stop_reason": hist.get("StopReason"),
            "failure_reason": hist.get("FailureReason"),
            "failed_at": hist.get("FailedAt"),
            "error_title": hist.get("ErrorTitle"),
            "error_description": hist.get("ErrorDescription"),
        }


class OnIsLastSessionStateSensor(OnIsBaseSensor, SensorEntity):
    """State and result details for the most recent charging attempt."""

    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{super().name} Last Session State"
        self._attr_unique_id = f"{super().unique_id}_last_state"

    @property
    def native_value(self):
        if not self.session_data:
            return None
        return self.session_data.get("LastSessionData", {}).get("State")

    @property
    def extra_state_attributes(self):
        if not self.session_data:
            return {}
        hist = self.session_data.get("LastSessionData", {})
        return {
            "charge_id": hist.get("Id"),
            "failed_at": hist.get("FailedAt"),
            "failure_reason": hist.get("FailureReason"),
            "stop_reason": hist.get("StopReason"),
            "error_title": hist.get("ErrorTitle"),
            "error_description": hist.get("ErrorDescription"),
        }

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
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT

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
            return max(0, total_minutes)
        return None

    @property
    def extra_state_attributes(self):
        diff = self._get_diff()
        if diff:
            total_minutes = max(0, int(diff.total_seconds() / 60))
            return {
                "duration": format_minutes(total_minutes),
                "total_seconds": int(diff.total_seconds()),
            }
        return {}
