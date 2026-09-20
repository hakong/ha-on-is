"""Config flow for ON (Orka natturunnar)."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .backends import create_backend_client
from .const import (
    BACKEND_MONTA_APP,
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_BACKEND,
    CONF_CHARGE_POINT_ID,
    CONF_CONNECTOR_ID,
    CONF_DEVICE_UUID,
    CONF_EVSE_CODE,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_TOKEN_EXPIRES_AT,
    CONF_TEAM_ID,
    DOMAIN,
)
from .monta.errors import MontaApiError, MontaAuthError
from .monta_backend import MontaChargerCandidate, MontaOnIsClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class OnIsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ON."""

    VERSION = 3

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._candidates: dict[str, MontaChargerCandidate] = {}
        self._backend_data: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Authenticate and discover chargers available to the account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            reusable = next(
                (
                    dict(entry.data)
                    for entry in self._async_current_entries()
                    if entry.data.get(CONF_EMAIL, "").strip().lower()
                    == email.lower()
                    and entry.data.get(CONF_PASSWORD) == password
                ),
                None,
            )
            client = self._new_client(email, password, reusable)
            try:
                if reusable is None:
                    await client.login()
                candidates = await client.discover_charge_points()
                self._backend_data = client.persisted_config_data()
                if not candidates:
                    errors["base"] = "no_chargers"
                else:
                    self._credentials = {
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                    }
                    self._candidates = {
                        candidate.charge_point_id: candidate
                        for candidate in candidates
                    }
                    if len(candidates) == 1:
                        return await self._create_for_candidate(candidates[0])
                    return await self.async_step_charger()
            except MontaAuthError:
                errors["base"] = "invalid_auth"
            except MontaApiError:
                _LOGGER.exception("Monta API exception during setup")
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during setup")
                errors["base"] = "cannot_connect"
            finally:
                await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_charger(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose one of the chargers exposed by Monta team cards."""
        if user_input is not None:
            return await self._create_for_candidate(
                self._candidates[user_input[CONF_CHARGE_POINT_ID]]
            )

        choices = {
            candidate.charge_point_id: _candidate_label(candidate)
            for candidate in self._candidates.values()
        }
        return self.async_show_form(
            step_id="charger",
            data_schema=vol.Schema(
                {vol.Required(CONF_CHARGE_POINT_ID): vol.In(choices)}
            ),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Start credential repair for an existing entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate and save a replacement password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            client = self._new_client(
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                dict(entry.data),
            )
            try:
                await client.login()
            except MontaAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Monta API exception during reauthentication")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        **client.persisted_config_data(),
                    },
                )
            finally:
                await client.close()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )

    async def _create_for_candidate(
        self, candidate: MontaChargerCandidate
    ) -> FlowResult:
        email = self._credentials[CONF_EMAIL]
        await self.async_set_unique_id(
            f"{email.lower()}:{candidate.charge_point_id}"
        )
        self._abort_if_unique_id_configured()

        charger_number = candidate.charger_number
        evse_code = (
            f"IS*ONP*E{charger_number}*1*1"
            if charger_number
            else candidate.title
        )
        return self.async_create_entry(
            title=candidate.title,
            data={
                CONF_BACKEND: BACKEND_MONTA_APP,
                **self._credentials,
                **self._backend_data,
                CONF_CHARGE_POINT_ID: candidate.charge_point_id,
                CONF_TEAM_ID: candidate.team_id,
                CONF_CONNECTOR_ID: candidate.charge_point_id,
                CONF_EVSE_CODE: evse_code,
            },
        )

    def _new_client(
        self,
        email: str,
        password: str,
        data: dict[str, Any] | None = None,
    ) -> MontaOnIsClient:
        options = data or {}
        return create_backend_client(
            email=email,
            password=password,
            session=async_get_clientsession(self.hass),
            backend_key=BACKEND_MONTA_APP,
            charge_point_id=options.get(CONF_CHARGE_POINT_ID),
            team_id=options.get(CONF_TEAM_ID),
            evse_code=options.get(CONF_EVSE_CODE),
            connector_id=options.get(CONF_CONNECTOR_ID),
            device_uuid=options.get(CONF_DEVICE_UUID),
            access_token=options.get(CONF_ACCESS_TOKEN),
            refresh_token=options.get(CONF_REFRESH_TOKEN),
            access_token_expires_at=options.get(CONF_ACCESS_TOKEN_EXPIRES_AT),
            refresh_token_expires_at=options.get(CONF_REFRESH_TOKEN_EXPIRES_AT),
        )


def _candidate_label(candidate: MontaChargerCandidate) -> str:
    details = [candidate.title]
    if candidate.subtitle:
        details.append(candidate.subtitle)
    if candidate.state_label:
        details.append(candidate.state_label)
    return " - ".join(details)
