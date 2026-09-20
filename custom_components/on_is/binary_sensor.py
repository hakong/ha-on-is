"""Binary sensor platform for ON."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OnIsCoordinator
from .entity import charger_base_name, charger_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Monta charger binary sensors."""
    coordinator: OnIsCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_connectors: set[int | str] = set()

    def add_new_entities() -> None:
        entities: list[BinarySensorEntity] = []
        for connector_id, session in (coordinator.data or {}).items():
            if connector_id in known_connectors:
                continue
            known_connectors.add(connector_id)
            entities.extend(
                (
                    OnIsCableConnectedBinarySensor(
                        coordinator, connector_id, session
                    ),
                    OnIsCloudConnectedBinarySensor(
                        coordinator, connector_id, session
                    ),
                )
            )
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class OnIsBaseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Common ON binary sensor behavior."""

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        self._attr_device_info = charger_device_info(
            connector_id, session, coordinator
        )

    @property
    def session_data(self):
        return (self.coordinator.data or {}).get(self.connector_id)

    @property
    def available(self) -> bool:
        return super().available and self.session_data is not None


class OnIsCableConnectedBinarySensor(OnIsBaseBinarySensor):
    """Whether a vehicle cable is plugged into the charger."""

    _attr_device_class = BinarySensorDeviceClass.PLUG

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{charger_base_name(session)} Cable Connected"
        self._attr_unique_id = f"on_is_{connector_id}_cable_connected"

    @property
    def is_on(self) -> bool | None:
        if not self.session_data:
            return None
        return self.session_data.get("Monta", {}).get("CablePluggedIn")


class OnIsCloudConnectedBinarySensor(OnIsBaseBinarySensor):
    """Whether Monta currently reports the physical charger connected."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator, connector_id, session)
        self._attr_name = f"{charger_base_name(session)} Cloud Connection"
        self._attr_unique_id = f"on_is_{connector_id}_cloud_connected"

    @property
    def is_on(self) -> bool | None:
        if not self.session_data:
            return None
        return self.session_data.get("Monta", {}).get("Connected")
