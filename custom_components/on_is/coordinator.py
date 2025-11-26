"""Data update coordinator for the ON integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import OnIsClient
from .const import DOMAIN, SCAN_INTERVAL_SECONDS, CONF_LOCATION_ID, CONF_EVSE_CODE

_LOGGER = logging.getLogger(__name__)

class OnIsCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ON data from the API."""

    def __init__(self, hass: HomeAssistant, client: OnIsClient, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.entry = entry
        self._poll_count = 0 
        # Cache for history data {connector_id: history_dict}
        self._cached_history = {}

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            # 1. Fetch Active Sessions (Global)
            active_sessions = await self.client.get_online_data()
            
            data_map = {}
            for session in active_sessions:
                conn_id = session.get("Connector", {}).get("Id")
                if conn_id:
                    data_map[conn_id] = session

            # 2. Fetch Passive Status (Home Location)
            config_id = self.entry.data.get(CONF_LOCATION_ID)
            if config_id:
                try:
                    await self._check_specific_location(int(config_id), data_map)
                except Exception as e:
                    _LOGGER.warning(f"Error checking home location {config_id}: {e}")

            # 3. Update History Cache (Every 10th poll, or approx 5 mins)
            if self._poll_count % 10 == 0:
                await self._refresh_history_cache()
            
            self._poll_count += 1

            # 4. Inject Cached History into Current Session Data
            # We do this EVERY poll so the sensors don't go 'Unknown'
            for conn_id, session in data_map.items():
                if conn_id in self._cached_history:
                    session["LastSessionData"] = self._cached_history[conn_id]

            # 5. Filter Results
            target_code = self.entry.data.get(CONF_EVSE_CODE)
            if target_code and data_map:
                filtered_map = {}
                for conn_id, session in data_map.items():
                    current_code = self._extract_evse_code(session)
                    if current_code == target_code:
                        filtered_map[conn_id] = session
                return filtered_map
            
            return data_map

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def _refresh_history_cache(self):
        """Fetch history and update the cache."""
        try:
            history = await self.client.get_charging_history(limit=10)
            
            # Process history items and map them to Connector IDs
            for item in history:
                h_conn_id = item.get("Connector", {}).get("Id")
                
                # Only store the most recent session for each connector
                # Since the API returns sorted by date desc, the first one we see is the newest
                if h_conn_id and h_conn_id not in self._cached_history:
                    self._cached_history[h_conn_id] = item
                    # If we want to be smarter, we could check timestamps, 
                    # but the list order is usually reliable.
            
            # Clear cache for IDs that weren't found? 
            # No, better to keep old history than show nothing if API fails temporarily.

        except Exception as e:
            _LOGGER.warning(f"Failed to update history: {e}")

    async def _check_specific_location(self, loc_id: int, data_map: dict):
        passive_data = await self.client.get_location_status(loc_id)
        target_code = self.entry.data.get(CONF_EVSE_CODE)
        
        for conn_id, fake_session in passive_data.items():
            should_add = False
            if target_code:
                if self._extract_evse_code(fake_session) == target_code:
                    should_add = True
            
            if not should_add:
                status = fake_session.get("Connector", {}).get("Status", {}).get("Title", "").lower()
                if status in ["occupied", "preparing", "suspended ev", "suspended evse", "charging"]:
                    should_add = True
            
            if should_add and conn_id not in data_map:
                data_map[conn_id] = fake_session

    def _extract_evse_code(self, session: dict) -> str:
        if "EvseCode" in session.get("Connector", {}):
            return session["Connector"]["EvseCode"]
        try:
            cp_code = session.get("ChargePoint", {}).get("FriendlyCode")
            evse_code = session.get("Evse", {}).get("FriendlyCode")
            conn_code = session.get("Connector", {}).get("Code")
            return f"{cp_code}-{evse_code}-{conn_code}"
        except Exception:
            return "unknown"