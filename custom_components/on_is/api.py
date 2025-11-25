import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any, List

_LOGGER = logging.getLogger(__name__)

# Clean, descriptive headers
HEADERS = {
    "User-Agent": "HomeAssistant-OnIsIntegration",
    "Accept": "application/json",
}

BASE_URL = "https://app.on.is/DuskyWebApi"

class OnIsClient:
    def __init__(self, email: str, password: str, session: aiohttp.ClientSession = None):
        self._email = email
        self._password = password
        self._session = session if session else aiohttp.ClientSession()
        self._access_token = None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def login(self):
        """Exchanges credentials for a Bearer token."""
        url = f"{BASE_URL}/login"
        
        # aiohttp automatically sets Content-Type: application/x-www-form-urlencoded 
        # when passing a dict to 'data'
        payload = {
            "email": self._email,
            "password": self._password,
            "grant_type": "password"
        }
        
        try:
            async with self._session.post(url, data=payload, headers=HEADERS) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    _LOGGER.error(f"Login failed: {resp.status} - {text}")
                    raise Exception(f"Login failed: {resp.status}")
                
                data = await resp.json()
                self._access_token = data.get("access_token")
                return self._access_token
        except Exception as e:
            _LOGGER.error(f"Error connecting to ON API: {e}")
            raise

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
                _LOGGER.info("Token expired, refreshing...")
                await self.login()
                headers = await self._get_headers()
                async with self._session.get(url, headers=headers) as resp_retry:
                    return await self._parse_online_data(resp_retry)
            
            return await self._parse_online_data(resp)

    async def _parse_online_data(self, resp) -> List[Dict[str, Any]]:
        if resp.status != 200:
            _LOGGER.warning(f"Failed to fetch online data: {resp.status}")
            return []
        
        data = await resp.json()
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
            data = await resp.json()
            if data.get("IsSuccessful") is True:
                return True
            raise Exception(f"Start failed: {data.get('ErrorDescription')}")

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
            data = await resp.json()
            if data.get("IsSuccessful") is True:
                return True
            raise Exception(f"Stop failed: {data.get('ErrorDescription')}")