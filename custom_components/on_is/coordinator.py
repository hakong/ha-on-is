"""Data update coordinator for the ON integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .backends import OnIsBackendClient
from .const import (
    BACKEND_MONTA_APP,
    CONF_EVSE_CODE,
    CONF_LOCATION_ID,
    DOMAIN,
    SCAN_INTERVAL_SECONDS,
)
from .helpers import (
    apply_cached_last_communication,
    evse_codes_match,
    extract_evse_code,
    rate_limit_backoff_seconds,
)
from .monta.errors import MontaApiError, MontaAuthError, MontaRateLimitError

_LOGGER = logging.getLogger(__name__)

class OnIsCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ON data from the API."""

    def __init__(self, hass: HomeAssistant, client: OnIsBackendClient, entry: ConfigEntry) -> None:
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
        self._rate_limit_failures = 0
        self._normal_update_interval = timedelta(seconds=SCAN_INTERVAL_SECONDS)
        self._cached_history = {}
        self._cached_last_communication: dict[int, str] = {}
        self.backend_key = client.backend_key
        self.backend_name = client.backend_name
        self.api_family = client.api_family
        self.base_url = client.base_url
        self.last_successful_update: str | None = None
        self.last_update_error: str | None = None
        self.last_start_attempt_at: str | None = None
        self.last_start_result: str | None = None
        self.last_start_error: str | None = None

    async def async_start_charging(self, evse_code: str, connector_id: int | str) -> None:
        """Send an explicit start request and retain its outcome for the UI."""
        self.last_start_attempt_at = datetime.now(timezone.utc).isoformat()
        self.last_start_result = "requesting"
        self.last_start_error = None
        self.async_update_listeners()
        try:
            await self.client.start_charging(evse_code, connector_id)
        except Exception as err:
            self.last_start_result = "rejected"
            self.last_start_error = _start_error_message(err)
            self.async_update_listeners()
            raise
        self.last_start_result = "accepted"
        self.async_update_listeners()

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

            # 2. Fetch & Merge Passive Status (Home Location)
            # We now do this ALWAYS if a location is configured, to get Price/Tariffs
            config_id = self.entry.data.get(CONF_LOCATION_ID)
            if config_id and self.backend_key != BACKEND_MONTA_APP:
                try:
                    await self._merge_specific_location(int(config_id), data_map)
                except Exception as e:
                    _LOGGER.warning(f"Error checking home location {config_id}: {e}")

            # 3. Update History Cache (Every 10th poll)
            if self._poll_count % 10 == 0:
                await self._refresh_history_cache()
            
            self._poll_count += 1

            # 4. Inject History
            for conn_id, session in data_map.items():
                latest_session = session.get("LastSessionData")
                if latest_session:
                    self._cached_history[conn_id] = latest_session
                elif conn_id in self._cached_history:
                    session["LastSessionData"] = self._cached_history[conn_id]
                apply_cached_last_communication(
                    conn_id,
                    session,
                    self._cached_last_communication,
                )

            # 5. Filter Results
            self.last_successful_update = datetime.now(timezone.utc).isoformat()
            self.last_update_error = None
            self._rate_limit_failures = 0
            self.update_interval = self._normal_update_interval
            self._persist_client_config()
            target_code = self.entry.data.get(CONF_EVSE_CODE)
            if target_code and data_map:
                filtered_map = {}
                for conn_id, session in data_map.items():
                    if evse_codes_match(extract_evse_code(session), target_code):
                        filtered_map[conn_id] = session
                return filtered_map
            
            return data_map

        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            if isinstance(err, MontaAuthError):
                raise ConfigEntryAuthFailed("ON account authentication failed") from err
            if isinstance(err, MontaRateLimitError):
                self._rate_limit_failures += 1
                delay = rate_limit_backoff_seconds(
                    self._rate_limit_failures,
                    err.retry_after,
                )
                self.update_interval = timedelta(seconds=delay)
                self.last_update_error = (
                    f"Monta API rate limit reached; retrying in {delay:g} seconds"
                )
                raise UpdateFailed(self.last_update_error) from err
            self.last_update_error = str(err)
            raise UpdateFailed(f"Error communicating with API: {err}")

    def _persist_client_config(self) -> None:
        """Persist reusable app identity and rotating auth state."""
        get_data = getattr(self.client, "persisted_config_data", None)
        if get_data is None:
            return
        backend_data = get_data()
        data = dict(self.entry.data)
        changed = False
        for key, value in backend_data.items():
            if data.get(key) != value:
                data[key] = value
                changed = True
        if changed:
            self.hass.config_entries.async_update_entry(self.entry, data=data)

    async def async_release_cable(self) -> None:
        """Release the cable through a backend that supports connector unlock."""
        release = getattr(self.client, "release_cable", None)
        if release is None:
            raise ValueError("The configured ON backend cannot release the cable")
        await release()
        await asyncio.sleep(3)
        await self.async_request_refresh()

    async def async_refresh_after_control(self) -> None:
        """Give Monta time to resolve an asynchronous command, then refresh."""
        await asyncio.sleep(3)
        await self.async_request_refresh()

    async def _refresh_history_cache(self):
        """Fetch history and update the cache."""
        try:
            history = await self.client.get_charging_history(limit=10)
            seen_connectors = set()
            for item in history:
                h_conn_id = item.get("Connector", {}).get("Id")
                if h_conn_id and h_conn_id not in seen_connectors:
                    self._cached_history[h_conn_id] = item
                    seen_connectors.add(h_conn_id)
        except (MontaAuthError, MontaRateLimitError):
            raise
        except Exception as e:
            _LOGGER.warning(f"Failed to update history: {e}")

    async def _merge_specific_location(self, loc_id: int, data_map: dict):
        """Fetch static location data and merge it into the active sessions."""
        passive_data = await self.client.get_location_status(loc_id)
        
        target_code = self.entry.data.get(CONF_EVSE_CODE)
        
        for conn_id, passive_session in passive_data.items():
            
            # CASE A: This charger is currently Active (in data_map)
            # We need to inject the Tariff/Price info from the passive data
            if conn_id in data_map:
                active_session = data_map[conn_id]
                
                # Merge Connector data (Tariffs usually live here)
                if "Connector" in passive_session:
                    p_conn = passive_session["Connector"]
                    a_conn = active_session.setdefault("Connector", {})
                    
                    # Copy Tariffs if missing in Active
                    if "Tariffs" in p_conn and "Tariffs" not in a_conn:
                        a_conn["Tariffs"] = p_conn["Tariffs"]
                        
                    # Copy Phases if Active reports 0
                    p_phases = p_conn.get("NumberOfPhases")
                    a_phases = a_conn.get("NumberOfPhases")
                    if p_phases and (not a_phases or a_phases == 0):
                        a_conn["NumberOfPhases"] = p_phases

            # CASE B: This charger is Idle (not in data_map)
            # We add it if it matches our target or is Occupied/Preparing
            else:
                should_add = False
                if target_code:
                    if evse_codes_match(extract_evse_code(passive_session), target_code):
                        should_add = True
                else:
                    status = passive_session.get("Connector", {}).get("Status", {}).get("Title", "").lower()
                    if status in ["occupied", "preparing", "suspended ev", "suspended evse", "charging"]:
                        should_add = True
                
                if should_add:
                    data_map[conn_id] = passive_session


def _start_error_message(err: Exception) -> str:
    """Keep the server's reason visible without storing its full response."""
    reason = " ".join(str(err).split()) or type(err).__name__
    if isinstance(err, MontaApiError) and err.error_code:
        reason = f"{err.error_code}: {reason}"
    return reason[:300]
