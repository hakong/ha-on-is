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

            # 2. Fetch Passive Status (ONLY for the configured Home Location)
            config_id = self.entry.data.get(CONF_LOCATION_ID)
            if config_id:
                try:
                    await self._check_specific_location(int(config_id), data_map)
                except Exception as e:
                    _LOGGER.warning(f"Error checking home location {config_id}: {e}")

            # 3. Filter Results
            target_code = self.entry.data.get(CONF_EVSE_CODE)
            
            if target_code and data_map:
                filtered_map = {}
                for conn_id, session in data_map.items():
                    current_code = self._extract_evse_code(session)
                    
                    if current_code == target_code:
                        filtered_map[conn_id] = session
                    else:
                        _LOGGER.debug(f"Ignoring device {current_code} (Not {target_code})")
                
                return filtered_map
            
            return data_map

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def _check_specific_location(self, loc_id: int, data_map: dict):
        """Fetch status for a specific location ID and merge into data_map."""
        passive_data = await self.client.get_location_status(loc_id)
        
        # Get the target code if configured
        target_code = self.entry.data.get(CONF_EVSE_CODE)
        
        for conn_id, fake_session in passive_data.items():
            should_add = False
            
            # Check if this connector matches our configured QR Code
            # If so, we ALWAYS add it, even if 'available'
            if target_code:
                current_code = self._extract_evse_code(fake_session)
                if current_code == target_code:
                    should_add = True
            
            # If we don't have a target code, or it didn't match, use the old logic
            # (only add if active/occupied)
            if not should_add:
                status = fake_session.get("Connector", {}).get("Status", {}).get("Title", "").lower()
                if status in ["occupied", "preparing", "suspended ev", "suspended evse", "charging"]:
                    should_add = True
            
            # Only add if not already present from the Active Session list
            if should_add:
                if conn_id not in data_map:
                    data_map[conn_id] = fake_session

    def _extract_evse_code(self, session: dict) -> str:
        """Find the EVSE Code from either Active or Passive data."""
        # Method 1: Passive data usually has it directly
        if "EvseCode" in session.get("Connector", {}):
            return session["Connector"]["EvseCode"]
            
        # Method 2: Active data requires reconstruction
        try:
            cp_code = session.get("ChargePoint", {}).get("FriendlyCode")
            evse_code = session.get("Evse", {}).get("FriendlyCode")
            conn_code = session.get("Connector", {}).get("Code")
            return f"{cp_code}-{evse_code}-{conn_code}"
        except Exception:
            return "unknown"