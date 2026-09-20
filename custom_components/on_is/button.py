"""Button platform for ON."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    """Set up ON action buttons."""
    coordinator: OnIsCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_connectors: set[int | str] = set()

    def add_new_entities() -> None:
        entities: list[ButtonEntity] = []
        for connector_id, session in (coordinator.data or {}).items():
            if connector_id in known_connectors:
                continue
            known_connectors.add(connector_id)
            entities.append(OnIsReleaseCableButton(coordinator, connector_id, session))
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class OnIsReleaseCableButton(CoordinatorEntity, ButtonEntity):
    """Request that the charger unlock its cable."""

    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator, connector_id, session):
        super().__init__(coordinator)
        self.connector_id = connector_id
        self._attr_name = f"{charger_base_name(session)} Release Cable"
        self._attr_unique_id = f"on_is_{connector_id}_release_cable"
        self._attr_device_info = charger_device_info(
            connector_id, session, coordinator
        )

    @property
    def session_data(self):
        return (self.coordinator.data or {}).get(self.connector_id)

    @property
    def available(self) -> bool:
        if not super().available or not self.session_data:
            return False
        return self.session_data.get("Monta", {}).get("CanUnlock") is True

    async def async_press(self) -> None:
        """Release the connector after an explicit user action."""
        try:
            await self.coordinator.async_release_cable()
        except Exception as err:
            raise HomeAssistantError(f"Could not release ON cable: {err}") from err
