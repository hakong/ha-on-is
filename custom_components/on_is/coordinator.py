"""Data update coordinator for the ON integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import OnIsClient
from .const import DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

class OnIsCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ON data from the API."""

    def __init__(self, hass: HomeAssistant, client: OnIsClient) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            sessions = await self.client.get_online_data()
            
            # The API returns a list of sessions.
            # We convert this to a Dict keyed by ConnectorId or EvseCode 
            # so we can easily look it up in the sensors.
            # If sessions is [], data is {}.
            
            data_map = {}
            for session in sessions:
                # Use ConnectorId as the unique key for this session
                conn_id = session.get("Connector", {}).get("Id")
                if conn_id:
                    data_map[conn_id] = session
            
            return data_map

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")