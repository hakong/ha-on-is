"""Config flow for ON (Orka náttúrunnar) integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OnIsApiError, OnIsAuthError, OnIsClient
from .const import DOMAIN, CONF_LOCATION_ID, CONF_EVSE_CODE

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_EVSE_CODE): str, 
    }
)

class OnIsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ON."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            evse_input = user_input.get(CONF_EVSE_CODE)
            if evse_input:
                evse_input = evse_input.strip()

            requested_evse = (evse_input or "").lower()
            for existing_entry in self._async_current_entries():
                existing_email = existing_entry.data.get(CONF_EMAIL, "").strip().lower()
                existing_evse = existing_entry.data.get(CONF_EVSE_CODE, "")
                existing_evse = existing_evse.strip().lower() if existing_evse else ""
                if existing_email == email.lower() and existing_evse == requested_evse:
                    return self.async_abort(reason="already_configured")

            unique_id = email.lower()
            if evse_input:
                unique_id = f"{unique_id}:{requested_evse}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = OnIsClient(
                email=email,
                password=user_input[CONF_PASSWORD],
                session=session,
            )

            try:
                await client.login()

                # 2. (Optional) Resolve Home Charger QR Code
                location_id = None
                
                if evse_input:
                    location_id = await client.resolve_evse_code(evse_input)
                    if not location_id:
                        errors["base"] = "invalid_evse_code"
                
                if not errors:
                    data = {
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                    if location_id:
                        data[CONF_LOCATION_ID] = location_id
                    
                    # --- CHANGE: SAVE THE SPECIFIC CODE ---
                    if evse_input:
                        data[CONF_EVSE_CODE] = evse_input
                    # --------------------------------------

                    return self.async_create_entry(
                        title=email,
                        data=data
                    )

            except OnIsAuthError:
                errors["base"] = "invalid_auth"
            except OnIsApiError:
                _LOGGER.exception("API exception during setup")
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during setup")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", 
            data_schema=STEP_USER_DATA_SCHEMA, 
            errors=errors, 
            description_placeholders={
                "code_example": "IS*ONP00281-3806-1-1"
            }
        )
