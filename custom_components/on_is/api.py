import logging
from typing import Any, Dict, List

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Headers mimic the Android App to avoid WAF blocking
HEADERS = {
    "User-Agent": "is.on.charge.android v.2025.7.5 == Android-16;Pixel 7 Pro;SDK:36",
    "Accept": "application/json",
}

BASE_URL = "https://app.on.is/DuskyWebApi"


class OnIsApiError(Exception):
    """Base exception for ON API errors."""


class OnIsAuthError(OnIsApiError):
    """Raised when ON rejects the configured credentials."""


class OnIsClient:
    def __init__(self, email: str, password: str, session: aiohttp.ClientSession = None):
        self._email = email
        self._password = password
        self._owns_session = session is None
        self._session = session if session else aiohttp.ClientSession()
        self._access_token = None
        self._token_expires = None

    async def close(self):
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def _response_error(self, resp: aiohttp.ClientResponse, action: str) -> OnIsApiError:
        """Build a useful exception from a failed API response."""
        text = await resp.text()
        message = f"{action} failed: {resp.status}"
        if text:
            message = f"{message} - {text}"
        if resp.status in (401, 403):
            return OnIsAuthError(message)
        return OnIsApiError(message)

    async def login(self):
        """Exchanges credentials for a Bearer token."""
        url = f"{BASE_URL}/login"
        
        # Note: The logs show Content-Type is x-www-form-urlencoded
        payload = {
            "email": self._email,
            "password": self._password,
            "grant_type": "password"
        }
        
        async with self._session.post(url, data=payload, headers=HEADERS) as resp:
            if resp.status != 200:
                raise await self._response_error(resp, "Login")
            
            data = await resp.json()
            self._access_token = data.get("access_token")
            if not self._access_token:
                raise OnIsAuthError("Login response did not include an access token")
            return self._access_token

    async def _get_headers(self):
        if not self._access_token:
            await self.login()
        return {
            **HEADERS,
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }

    async def get_online_data(self) -> List[Dict[str, Any]]:
        """
        The main polling endpoint. 
        Returns [] if disconnected.
        Returns a list of sessions if plugged in/charging.
        """
        url = f"{BASE_URL}/api/onlineData"
        headers = await self._get_headers()
        
        async with self._session.get(url, headers=headers) as resp:
            if resp.status == 401:
                # Token expired, retry once
                await self.login()
                headers = await self._get_headers()
                async with self._session.get(url, headers=headers) as resp_retry:
                    return await self._parse_online_data(resp_retry)
            
            return await self._parse_online_data(resp)

    async def _parse_online_data(self, resp) -> List[Dict[str, Any]]:
        if resp.status != 200:
            raise await self._response_error(resp, "Fetching online data")
        
        data = await resp.json()
        # The relevant data is inside the 'CurrentSessions' list
        return data.get("CurrentSessions", [])

    async def start_charging(self, evse_code: str, connector_id: int):
        """Sends the remoteStartTransaction command."""
        url = f"{BASE_URL}/api/commands/remoteStartTransaction"
        headers = await self._get_headers()
        
        payload = {
            "EvseCode": evse_code,
            "ConnectorId": connector_id,
            "EnableLimits": False,
            "SocLimits": False
        }
        
        async with self._session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                raise await self._response_error(resp, "Start charging")
            data = await resp.json()
            # ResultCode 1 means success
            if data.get("IsSuccessful") is True:
                return True
            raise OnIsApiError(f"Start failed: {data.get('ErrorDescription')}")

    async def stop_charging(self, evse_code: str, charge_point_id: int, connector_id: int):
        """Sends the remoteStopTransaction command."""
        url = f"{BASE_URL}/api/commands/remoteStopTransaction"
        headers = await self._get_headers()
        
        payload = {
            "EvseCode": evse_code,
            "ChargePointId": charge_point_id,
            "ConnectorId": connector_id,
            "SocLimits": False
        }
        
        async with self._session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                raise await self._response_error(resp, "Stop charging")
            data = await resp.json()
            if data.get("IsSuccessful") is True:
                return True
            raise OnIsApiError(f"Stop failed: {data.get('ErrorDescription')}")

    async def get_location_status(self, location_id: int):
        """Fetches infrastructure status (for when session is not active)."""
        url = f"{BASE_URL}/api/locations/{location_id}?uiCulture=en-GB"
        headers = await self._get_headers()

        async with self._session.get(url, headers=headers) as resp:
            if resp.status != 200:
                raise await self._response_error(resp, f"Fetching location {location_id}")

            data = await resp.json()
            results = {}

            for cp in data.get("ChargePoints", []):
                for evse in cp.get("Evses", []):
                    for conn in evse.get("Connectors", []):
                        c_id = conn.get("Id")
                        if c_id:
                            results[c_id] = {
                                "Location": data,
                                "ChargePoint": cp,
                                "Evse": evse,
                                "Connector": conn,
                                "Measurements": {"Power": 0, "ActiveEnergyConsumed": 0},
                                "IsPassive": True,
                            }
            return results

    async def resolve_evse_code(self, evse_code: str) -> int | None:
        """Resolves a QR code (IS*ONP...) to a Location ID."""
        # Ensure clean input (trim whitespace)
        code = evse_code.strip()
        url = f"{BASE_URL}/api/connectors/{code}/chargingData"
        headers = await self._get_headers()

        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("LocationId")
                if resp.status == 404:
                    _LOGGER.warning("Failed to resolve EVSE code %s: %s", code, resp.status)
                    return None
                raise await self._response_error(resp, f"Resolving EVSE code {code}")
        except OnIsApiError:
            raise
        except Exception as e:
            raise OnIsApiError(f"Error resolving EVSE code: {e}") from e
        
        return None

    async def get_charging_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent charging sessions."""
        # Fetching page 1 with a small size is enough to find the recent one
        url = f"{BASE_URL}/api/chargingSessions?pageSize={limit}&pageNumber=1"
        headers = await self._get_headers()

        async with self._session.get(url, headers=headers) as resp:
            if resp.status != 200:
                raise await self._response_error(resp, "Fetching charging history")
            data = await resp.json()
            return data.get("Content", [])
