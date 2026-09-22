"""Switch platform for ON integration."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BACKEND_MONTA_APP, DOMAIN
from .coordinator import OnIsCoordinator
from .entity import charger_base_name, charger_device_info
from .helpers import extract_evse_code, start_readiness

_LOGGER = logging.getLogger(__name__)

OPTIMISTIC_TIMEOUT = 30

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ON switches."""
    coordinator: OnIsCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_connectors: set[int] = set()

    def add_new_entities() -> None:
        entities = []
        for connector_id, session in (coordinator.data or {}).items():
            if connector_id in known_connectors:
                continue
            known_connectors.add(connector_id)
            entities.append(OnIsChargerSwitch(coordinator, connector_id, session))

        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class OnIsChargerSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to start or stop charging with brief optimistic state."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        
        self._override_state = None
        self._override_timestamp = 0
        
        base_name = charger_base_name(session)

        self._attr_name = f"{base_name} Charging"
        self._attr_unique_id = f"on_is_{connector_id}_switch"
        self._attr_icon = "mdi:ev-plug-type2"
        self._attr_device_info = charger_device_info(
            connector_id, session, coordinator
        )

    @property
    def session_data(self):
        return self.coordinator.data.get(self.connector_id)

    @property
    def available(self) -> bool:
        return super().available and self.session_data is not None

    @property
    def is_on(self) -> bool:
        """Return true if a charging session is active (authorized)."""
        actual_state = self._authoritative_is_on()
        if self._override_state is not None:
            if self._command_failed() or actual_state == self._override_state:
                self._override_state = None
                return actual_state
            if time.time() - self._override_timestamp < OPTIMISTIC_TIMEOUT:
                return self._override_state
            self._override_state = None
        return actual_state

    @property
    def assumed_state(self) -> bool:
        """Mark the switch as assumed only while Monta confirms a command."""
        return self._override_state is not None

    def _authoritative_is_on(self) -> bool:
        """Reflect a controllable charge, not another account's occupancy."""
        if not self.session_data:
            return False

        session_info = self.session_data.get("ChargingSession", {})
        if self.coordinator.backend_key == BACKEND_MONTA_APP:
            return bool(session_info.get("Id"))
        if session_info.get("Id"):
            return True

        status_raw = (
            self.session_data.get("Connector", {})
            .get("Status", {})
            .get("Title", "")
        )
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

    @property
    def extra_state_attributes(self):
        if not self.session_data or self.coordinator.backend_key != BACKEND_MONTA_APP:
            return {}
        monta = self.session_data.get("Monta", {})
        return {
            "active_charge_present": monta.get("ActiveChargePresent"),
            "active_charge_accessible": monta.get("ActiveChargeAccessible"),
            "charger_state": monta.get("State"),
        }

    def _command_failed(self) -> bool:
        if not self.session_data:
            return False
        monta = self.session_data.get("Monta", {})
        return bool(monta.get("FailedAt") or monta.get("FailureReason"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start charging."""
        if not self.session_data:
            raise HomeAssistantError("Cannot start charging without charger data")
        if self._authoritative_is_on():
            return

        evse_code = self._get_evse_code()
        conn_id = self.connector_id
        monta = self.session_data.get("Monta", {})
        notification_id = f"on_is_start_{conn_id}"

        try:
            await self.coordinator.async_start_charging(evse_code, conn_id)
        except Exception as err:
            reason = self.coordinator.last_start_error or str(err)
            advisory = start_readiness(monta)
            persistent_notification.async_create(
                self.hass,
                f"Charging did not start. Monta's prior readiness check said: "
                f"**{advisory}**. The start request failed with: **{reason}**. "
                "Check the charger's Start Readiness and Status entities before retrying.",
                title=f"{self.name}: start failed",
                notification_id=notification_id,
            )
            raise HomeAssistantError(f"Could not start ON charging: {reason}") from err

        persistent_notification.async_dismiss(self.hass, notification_id)

        self._override_state = True
        self._override_timestamp = time.time()
        self.async_write_ha_state()
        await self.coordinator.async_refresh_after_control()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop charging."""
        if not self.session_data:
            raise HomeAssistantError("Cannot stop charging without charger data")

        evse_code = self._get_evse_code()
        cp_id = self.session_data.get("ChargePoint", {}).get("Id")
        conn_id = self.connector_id

        try:
            await self.coordinator.client.stop_charging(evse_code, cp_id, conn_id)
        except Exception as err:
            raise HomeAssistantError(f"Could not stop ON charging: {err}") from err

        self._override_state = False
        self._override_timestamp = time.time()
        self.async_write_ha_state()
        await self.coordinator.async_refresh_after_control()

    def _get_evse_code(self) -> str:
        return extract_evse_code(self.session_data)
