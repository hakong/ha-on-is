"""ON backend adapter for the private signed-in Monta app API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import re
import time
from typing import Any, Mapping

import aiohttp

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_EXPIRES_AT,
    CONF_DEVICE_UUID,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_TOKEN_EXPIRES_AT,
)
from .monta.app import (
    APP_CHARGE_POINT_INCLUDES,
    MontaAppClient,
    MontaAppContext,
    MontaPayingTeam,
)
from .monta.errors import (
    MontaAccessError,
    MontaApiError,
    MontaAuthError,
    MontaRateLimitError,
)
from .monta.hub import MontaHubClient
from .monta.models import (
    ChargeSession,
    ChargerSnapshot,
    MontaToken,
    TERMINAL_CHARGE_STATES,
    parse_datetime,
)

CHARGER_NUMBER_PATTERNS = (
    re.compile(r"\*E(?P<number>\d+)(?:\*|$)", re.IGNORECASE),
    re.compile(r"-(?P<number>\d+)-\d+-\d+$"),
    re.compile(r"\bON\s+(?P<number>\d+)-\d+\b", re.IGNORECASE),
)

FAILED_CHARGE_VISIBILITY = timedelta(minutes=10)
HUB_HEALTH_REFRESH_SECONDS = 300
PAYING_TEAM_REFRESH_SECONDS = 3600

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MontaChargerCandidate:
    """One charger assigned to a signed-in ON team."""

    charge_point_id: str
    team_id: str
    title: str
    subtitle: str | None = None
    state_label: str | None = None

    @property
    def charger_number(self) -> str | None:
        return extract_charger_number(self.title)


class MontaOnIsClient:
    """Adapt signed-in Monta records to the integration's stable data contract."""

    backend_key = "monta_app"
    backend_name = "Monta (ON app)"
    api_family = "Monta signed-in app private API"
    base_url = "https://api.monta.app"

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        *,
        charge_point_id: int | str | None = None,
        team_id: int | str | None = None,
        evse_code: str | None = None,
        connector_id: int | str | None = None,
        device_uuid: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        access_token_expires_at: str | None = None,
        refresh_token_expires_at: str | None = None,
        app_client: MontaAppClient | None = None,
        hub_client: MontaHubClient | None = None,
    ) -> None:
        self._app = app_client or MontaAppClient(
            email=email,
            password=password,
            session=session,
            context=MontaAppContext(request_uuid=device_uuid) if device_uuid else None,
        )
        if access_token and app_client is None:
            self._app.restore_token(
                MontaToken(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    access_token_expires_at=parse_datetime(
                        access_token_expires_at
                    ),
                    refresh_token_expires_at=parse_datetime(
                        refresh_token_expires_at
                    ),
                )
            )
        self._hub = hub_client or (
            MontaHubClient(session=session) if app_client is None else None
        )
        self.charge_point_id = (
            str(charge_point_id) if charge_point_id is not None else None
        )
        self.team_id = str(team_id) if team_id is not None else None
        self.evse_code = evse_code.strip() if evse_code else None
        self.connector_id = str(connector_id) if connector_id is not None else None
        self._candidate: MontaChargerCandidate | None = None
        self._last_data: dict[int | str, dict[str, Any]] = {}
        self._last_snapshot: ChargerSnapshot | None = None
        self._active_charge: ChargeSession | None = None
        self._paying_team_id: str | None = None
        self._paying_team_last_attempt: float | None = None
        self._paying_team_error: str | None = None
        self._hub_detail: dict[str, Any] = {}
        self._hub_last_attempt: float | None = None
        self._hub_updated_at: str | None = None
        self._hub_error: str | None = None
        self._hub_logs_access_checked = False
        self._hub_logs_available: bool | None = None
        self._hub_logs_error: str | None = None
        self._hub_last_log: dict[str, Any] = {}

        if self.charge_point_id and self.team_id:
            if self.connector_id is None:
                self.connector_id = self.charge_point_id
            number = extract_charger_number(self.evse_code)
            title = f"ON {number}-1" if number else f"ON {self.charge_point_id}"
            self._candidate = MontaChargerCandidate(
                charge_point_id=self.charge_point_id,
                team_id=self.team_id,
                title=title,
            )

    def persisted_config_data(self) -> dict[str, str]:
        """Return reusable app identity and token values for HA storage."""
        data = {CONF_DEVICE_UUID: self._app.context.request_uuid}
        token = self._app.token
        if token is None:
            return data
        data[CONF_ACCESS_TOKEN] = token.access_token
        if token.refresh_token:
            data[CONF_REFRESH_TOKEN] = token.refresh_token
        if token.access_token_expires_at:
            data[CONF_ACCESS_TOKEN_EXPIRES_AT] = (
                token.access_token_expires_at.isoformat()
            )
        if token.refresh_token_expires_at:
            data[CONF_REFRESH_TOKEN_EXPIRES_AT] = (
                token.refresh_token_expires_at.isoformat()
            )
        return data

    async def close(self) -> None:
        await self._app.close()
        if self._hub is not None:
            await self._hub.close()

    async def login(self) -> str:
        await self._app.login()
        return self._app.token.access_token if self._app.token else "authenticated"

    async def discover_charge_points(self) -> tuple[MontaChargerCandidate, ...]:
        """Return charge points exposed through all signed-in team cards."""
        teams = await self._app.list_teams(team_type="any")
        candidates: dict[str, MontaChargerCandidate] = {}
        for team in teams.items:
            team_id = team.get("id") if isinstance(team, Mapping) else None
            if team_id is None:
                continue
            page_number = 1
            while True:
                cards = await self._app.list_team_charger_cards(
                    team_id, page=page_number
                )
                for card in cards.items:
                    data = card.get("data") if isinstance(card, Mapping) else None
                    if not isinstance(data, Mapping):
                        continue
                    charge_point_id = data.get("charge_point_id")
                    if charge_point_id is None:
                        continue
                    title = str(data.get("title") or f"ON charger {charge_point_id}")
                    badge = data.get("badge")
                    state_label = (
                        str(badge.get("text"))
                        if isinstance(badge, Mapping) and badge.get("text")
                        else None
                    )
                    candidates[str(charge_point_id)] = MontaChargerCandidate(
                        charge_point_id=str(charge_point_id),
                        team_id=str(team_id),
                        title=title,
                        subtitle=(
                            str(data["subtitle"]) if data.get("subtitle") else None
                        ),
                        state_label=state_label,
                    )
                if not cards.pages or page_number >= cards.pages:
                    break
                page_number += 1
        return tuple(candidates.values())

    async def get_online_data(self) -> list[dict[str, Any]]:
        await self._ensure_target()
        assert self.charge_point_id is not None
        paying_team_id = await self._get_paying_team_id()
        raw = await self._app.get_charge_point(
            self.charge_point_id,
            team_id=paying_team_id or self.team_id,
            mode="instant",
            amount_type="full",
            payment_method="team",
            includes=APP_CHARGE_POINT_INCLUDES,
        )
        snapshot = ChargerSnapshot.from_app(raw)
        active_charge = await self._get_relevant_charge(raw, snapshot)
        hub_detail = await self._get_hub_detail()
        self._last_snapshot = snapshot
        self._active_charge = active_charge

        connector_key = self._connector_key()
        data = self._to_legacy_data(
            raw,
            snapshot,
            active_charge,
            connector_key,
            hub_detail,
        )
        self._last_data = {connector_key: data}
        return [data]

    async def _get_paying_team_id(self) -> str | None:
        """Cache the ON billing team used by the app's eligibility check."""
        assert self.charge_point_id is not None
        now = time.monotonic()
        if (
            self._paying_team_last_attempt is not None
            and now - self._paying_team_last_attempt < PAYING_TEAM_REFRESH_SECONDS
        ):
            return self._paying_team_id
        self._paying_team_last_attempt = now
        try:
            payer = await self._app.get_default_paying_team(self.charge_point_id)
        except (MontaAuthError, MontaRateLimitError):
            raise
        except (MontaApiError, aiohttp.ClientError, TimeoutError) as err:
            self._paying_team_error = type(err).__name__
            _LOGGER.debug("Optional Monta payer refresh failed: %s", err)
            return self._paying_team_id
        self._paying_team_id = payer.id if payer else None
        self._paying_team_error = None
        return self._paying_team_id

    async def _get_hub_detail(self) -> Mapping[str, Any]:
        """Refresh slow-changing Hub health data without affecting core polling."""
        if self._hub is None or self.charge_point_id is None:
            return self._hub_detail
        token = self._app.token
        if token is None:
            return self._hub_detail
        now = time.monotonic()
        if (
            self._hub_last_attempt is not None
            and now - self._hub_last_attempt < HUB_HEALTH_REFRESH_SECONDS
        ):
            return self._hub_detail
        self._hub_last_attempt = now
        self._hub.set_access_token(token.access_token)
        try:
            detail = await self._hub.get_charge_point(int(self.charge_point_id))
        except (MontaApiError, aiohttp.ClientError, TimeoutError, ValueError) as err:
            self._hub_error = type(err).__name__
            _LOGGER.debug("Optional Monta Hub health refresh failed: %s", err)
            return self._hub_detail

        self._hub_detail = detail
        self._hub_updated_at = datetime.now(timezone.utc).isoformat()
        self._hub_error = None
        await self._refresh_hub_logs(detail)
        return self._hub_detail

    async def _refresh_hub_logs(self, detail: Mapping[str, Any]) -> None:
        """Probe logs once when forbidden, or refresh them with Hub health."""
        if self._hub is None or (
            self._hub_logs_access_checked and self._hub_logs_available is False
        ):
            return
        station = _mapping(detail.get("charging_station"))
        identity = station.get("identifier")
        if not identity:
            return
        try:
            logs = await self._hub.get_charging_station_logs(
                str(identity), params={"page": 0, "perPage": 10}
            )
        except MontaAccessError:
            self._hub_logs_access_checked = True
            self._hub_logs_available = False
            self._hub_logs_error = "access_denied"
            return
        except (MontaApiError, aiohttp.ClientError, TimeoutError, ValueError) as err:
            self._hub_logs_error = type(err).__name__
            _LOGGER.debug("Optional Monta station-log refresh failed: %s", err)
            return

        self._hub_logs_access_checked = True
        self._hub_logs_available = True
        self._hub_logs_error = None
        self._hub_last_log = _safe_log_summary(logs.items[0] if logs.items else {})

    async def _get_relevant_charge(
        self,
        raw: Mapping[str, Any],
        snapshot: ChargerSnapshot,
    ) -> ChargeSession | None:
        """Fetch rich detail using an exact charge ID from a list response."""
        active_summary = raw.get("active_charge")
        if isinstance(active_summary, Mapping) and active_summary.get("id") is not None:
            # Observed charge IDs exceed JavaScript's exact-integer range.
            # Do not trust the potentially rounded nested ID.
            listed = await self._app.get_active_charge(self.charge_point_id)
            if listed is not None:
                return await self._app.get_charge(listed.id)
            # The charger may be occupied by a session this account cannot read.
            # An old charge must not be mistaken for that active session.
            return None

        candidate = self._active_charge
        if candidate is None:
            if snapshot.cable_plugged_in is not True:
                return None
            recent = await self._app.list_charge_sessions(page=1, per_page=10)
            candidate = next(
                (
                    charge
                    for charge in recent.items
                    if charge.charge_point_id == self.charge_point_id
                ),
                None,
            )
        if candidate is None:
            return None
        detail = await self._app.get_charge(candidate.id)
        return (
            detail
            if detail.is_active
            or (snapshot.cable_plugged_in is True and detail.can_unlock)
            or _is_recent_failure(detail)
            else None
        )

    async def get_location_status(
        self, _location_id: int
    ) -> dict[int | str, dict[str, Any]]:
        """Return the latest snapshot; Monta has no OCEAN location equivalent."""
        if not self._last_data:
            await self.get_online_data()
        return dict(self._last_data)

    async def resolve_evse_code(self, evse_code: str) -> int | None:
        candidates = await self.discover_charge_points()
        candidate = _match_candidate(candidates, None, evse_code)
        return int(candidate.charge_point_id) if candidate else None

    async def get_charging_history(self, limit: int = 10) -> list[dict[str, Any]]:
        await self._ensure_target()
        assert self.charge_point_id is not None
        page = await self._app.list_charge_sessions(page=1, per_page=limit)
        history = []
        for charge in page.items:
            if charge.charge_point_id != self.charge_point_id:
                continue
            if charge.state and charge.state.lower() not in TERMINAL_CHARGE_STATES:
                continue
            history.append(self._history_to_legacy(charge))
        return history[:limit]

    async def start_charging(self, _evse_code: str, _connector_id: int) -> bool:
        await self._ensure_target()
        assert self.charge_point_id is not None
        payer = await self._app.get_default_paying_team(self.charge_point_id)
        if payer is None:
            raise ValueError("No eligible ON account payer is available")
        self._paying_team_id = payer.id
        self._paying_team_last_attempt = time.monotonic()
        self._paying_team_error = None
        self._active_charge = await self._app.start_charge(
            self.charge_point_id,
            payer.id,
        )
        return True

    async def stop_charging(
        self, _evse_code: str, _charge_point_id: int, _connector_id: int
    ) -> bool:
        await self._ensure_target()
        assert self.charge_point_id is not None
        charge = (
            self._active_charge
            if self._active_charge and self._active_charge.is_active
            else None
        )
        if charge is None:
            charge = await self._app.get_active_charge(self.charge_point_id)
        if charge is None:
            raise ValueError("No active ON charge is available to stop")
        self._active_charge = await self._app.stop_charge(
            charge.id,
            self.charge_point_id,
        )
        return True

    async def release_cable(self) -> bool:
        """Explicitly request connector unlock for the configured charger."""
        await self._ensure_target()
        if self._last_snapshot is None or self._last_snapshot.integration_id is None:
            await self.get_online_data()
        assert self.charge_point_id is not None
        if self._last_snapshot is None or self._last_snapshot.integration_id is None:
            raise ValueError("Monta did not provide a charger integration ID")
        await self._app.release_cable(
            self.charge_point_id,
            self._last_snapshot.integration_id,
        )
        return True

    async def get_receipt(self, charge_id: int | str) -> dict[str, Any]:
        return await self._app.get_receipt(charge_id)

    async def get_paying_team(self) -> MontaPayingTeam | None:
        await self._ensure_target()
        assert self.charge_point_id is not None
        return await self._app.get_default_paying_team(self.charge_point_id)

    async def _ensure_target(self) -> None:
        if self._candidate is not None:
            return
        candidates = await self.discover_charge_points()
        candidate = _match_candidate(
            candidates,
            self.charge_point_id,
            self.evse_code,
        )
        if candidate is None:
            if not candidates:
                raise ValueError("The ON account has no assigned Monta chargers")
            raise ValueError("Configured ON charger was not found in this account")
        self._candidate = candidate
        self.charge_point_id = candidate.charge_point_id
        self.team_id = candidate.team_id
        if self.connector_id is None:
            self.connector_id = candidate.charge_point_id

    def _connector_key(self) -> int | str:
        assert self.connector_id is not None
        try:
            return int(self.connector_id)
        except ValueError:
            return self.connector_id

    def _to_legacy_data(
        self,
        raw: Mapping[str, Any],
        snapshot: ChargerSnapshot,
        charge: ChargeSession | None,
        connector_key: int | str,
        hub_detail: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        connector = _first_mapping(raw.get("connectors"))
        model = raw.get("model") if isinstance(raw.get("model"), Mapping) else {}
        details = raw.get("details") if isinstance(raw.get("details"), Mapping) else {}
        integration = _mapping(raw.get("integration"))
        hub = _mapping(hub_detail)
        hub_integration = _mapping(hub.get("charge_point_integration"))
        station = _mapping(hub.get("charging_station"))
        station_payload = _mapping(station.get("payload"))
        hub_connector = _first_mapping(station_payload.get("connectors"))
        number = (
            self._candidate.charger_number
            if self._candidate is not None
            else extract_charger_number(snapshot.name or "")
        )
        evse_code = self.evse_code or (
            f"IS*ONP*E{number}*1*1" if number else str(snapshot.identifier or "unknown")
        )
        status = _friendly_status(snapshot, charge)
        price = snapshot.price_per_kwh
        tariffs = []
        if price is not None:
            tariffs = [
                {
                    "Powers": [
                        {"Times": [{"Prices": [{"PricePerUnit": price}]}]}
                    ]
                }
            ]
        live_charge = charge if charge is not None and charge.is_active else None
        measurement = (
            live_charge.raw.get("last_measurement")
            if live_charge is not None
            and isinstance(live_charge.raw.get("last_measurement"), Mapping)
            else {}
        )
        charging_session = _charge_to_legacy_session(live_charge)
        active_summary = _mapping(raw.get("active_charge"))
        active_charge_present = bool(active_summary.get("id")) or live_charge is not None
        last_connected_at = _first_value(
            hub_integration.get("last_connected_at"),
            integration.get("last_connected_at"),
            _iso(snapshot.last_connected_at),
        )
        last_communication = (
            str(measurement["date"])
            if measurement.get("date")
            else _first_value(
                _iso(snapshot.updated_at),
                last_connected_at,
                hub_connector.get("updated_at"),
            )
        )
        status_changed = _first_timestamp(
            charge.stopping_at if charge and charge.is_active else None,
            charge.charging_at if charge and charge.is_active else None,
            charge.starting_at if charge and charge.is_active else None,
            snapshot.last_connected_at,
        )
        result = {
            "Location": {
                "FriendlyName": snapshot.name or "ON charger",
            },
            "ChargePoint": {
                "Id": int(snapshot.id) if snapshot.id.isdigit() else snapshot.id,
                "FriendlyCode": number or snapshot.name or snapshot.id,
            },
            "Evse": {
                "Id": int(snapshot.id) if snapshot.id.isdigit() else snapshot.id,
                "FriendlyCode": "1",
                "MaxPower": snapshot.max_kw,
                "NumberOfPhases": None,
            },
            "Connector": {
                "Id": connector_key,
                "Code": "1",
                "EvseCode": evse_code,
                "Status": {"Title": status},
                "Type": {"Title": connector.get("name") or connector.get("identifier")},
                "NumberOfPhases": None,
                "Tariffs": tariffs,
            },
            "Measurements": {
                "Power": (
                    live_charge.power_kw
                    if live_charge and live_charge.power_kw is not None
                    else 0.0
                ),
                "ActiveEnergyConsumed": (
                    live_charge.consumed_kwh
                    if live_charge and live_charge.consumed_kwh is not None
                    else 0.0
                ),
                "CurrentL1": measurement.get("current_l1"),
                "CurrentL2": measurement.get("current_l2"),
                "CurrentL3": measurement.get("current_l3"),
                "VoltageL1": measurement.get("voltage_l1"),
                "VoltageL2": measurement.get("voltage_l2"),
                "VoltageL3": measurement.get("voltage_l3"),
                "MeasuredAt": measurement.get("date"),
                "StateOfCharge": (
                    live_charge.state_of_charge if live_charge else None
                ),
                "MeterTotal": _first_value(
                    hub.get("total_kwh"),
                    _wh_to_kwh(hub_connector.get("meter_wh")),
                ),
            },
            "ChargingSession": charging_session,
            "LastCommunicationTime": last_communication,
            "LastStatusChangeTime": status_changed,
            "IsPassive": live_charge is None,
            "Monta": {
                "State": snapshot.state,
                "Connected": snapshot.connected,
                "Available": snapshot.available,
                "Active": snapshot.active,
                "CablePluggedIn": snapshot.cable_plugged_in,
                "ActiveChargeId": live_charge.id if live_charge else None,
                "ActiveChargePresent": active_charge_present,
                "ActiveChargeAccessible": live_charge is not None,
                "ActiveChargeSummaryState": active_summary.get("state"),
                "AverageKw": snapshot.average_kw,
                "CanStart": snapshot.can_start if self._paying_team_id else False,
                "CanStartReason": (
                    snapshot.can_start_reason
                    if self._paying_team_id
                    else (
                        "PAYER_LOOKUP_FAILED"
                        if self._paying_team_error
                        else "NO_ELIGIBLE_PAYER"
                    )
                ),
                "PayingTeamAvailable": self._paying_team_id is not None,
                "PayerLookupError": self._paying_team_error,
                "CanStop": live_charge.can_stop if live_charge else False,
                "CanUnlock": charge.can_unlock if charge else False,
                "CpiStatus": charge.cpi_status if charge else None,
                "ChargeState": charge.normalized_state if charge else None,
                "FailedAt": _iso(charge.failed_at) if charge else None,
                "FailureReason": _charge_failure_reason(charge),
                "StopReason": charge.stop_reason if charge else None,
                "ErrorTitle": _charge_error_text(charge, "title"),
                "ErrorDescription": _charge_error_text(
                    charge, "description", "message"
                ),
                "IntegrationId": snapshot.integration_id,
                "IntegrationState": _first_value(
                    hub_integration.get("state"), integration.get("state")
                ),
                "IntegrationStatus": _first_value(
                    hub_integration.get("status"), integration.get("status")
                ),
                "IntegrationLog": integration.get("log"),
                "LastConnectedAt": last_connected_at,
                "DisconnectedAt": _first_value(
                    hub_integration.get("disconnected_at"),
                    integration.get("disconnected_at"),
                ),
                "ReconnectRequired": _first_value(
                    hub_integration.get("reconnect_required"),
                    integration.get("reconnect_required"),
                ),
                "FirmwareVersion": _first_value(
                    station.get("firmware_version"), snapshot.firmware_version
                ),
                "AvailableFirmwareVersion": station.get(
                    "available_firmware_version"
                ),
                "FirmwareStatus": station_payload.get("firmware_status"),
                "FirmwareUpgradeAvailable": _first_value(
                    hub.get("firmware_upgrade_available"),
                    station.get("has_available_firmware_upgrade"),
                ),
                "Brand": _model_brand(model),
                "Model": model.get("name") or model.get("model_name"),
                "SerialNumber": _first_value(
                    hub_integration.get("serial_number"),
                    raw.get("serial_number"),
                    integration.get("external_id"),
                ),
                "ProtocolErrorCode": hub_integration.get(
                    "protocol_error_code"
                ),
                "ProtocolErrorInfo": _safe_error_info(
                    hub_integration.get("protocol_error_code_info")
                ),
                "VendorErrorCode": _first_value(
                    hub_connector.get("vendor_error_code"),
                    hub_integration.get("protocol_vendor_error_code"),
                ),
                "ConnectorErrorCode": hub_connector.get("error_code"),
                "ConnectorStatus": hub_connector.get("status"),
                "ConnectorUpdatedAt": hub_connector.get("updated_at"),
                "MeterAccuracy": _first_value(
                    station_payload.get("meter_accuracy"),
                    hub_integration.get("meter_accuracy"),
                    integration.get("meter_accuracy"),
                ),
                "MidCertified": station_payload.get("mid"),
                "Ocpp": station_payload.get("ocpp"),
                "WifiStrength": _first_value(
                    station_payload.get("wifi_strength"),
                    hub_integration.get("wifi_strength"),
                    integration.get("wifi_strength"),
                ),
                "CellStrength": _first_value(
                    station_payload.get("cell_strength"),
                    hub_integration.get("cell_strength"),
                    integration.get("cell_strength"),
                ),
                "ChargerStabilityScore": hub.get("stability_score"),
                "ModelStabilityScore": model.get("stability_score"),
                "LifetimeKwh": hub.get("total_kwh"),
                "ChargeCount": hub.get("charge_count"),
                "HubStatus": hub.get("status"),
                "HubConnection": hub.get("connection"),
                "HubUpdatedAt": hub.get("updated_at"),
                "HubDataUpdatedAt": self._hub_updated_at,
                "HubDataError": self._hub_error,
                "LogsAvailable": self._hub_logs_available,
                "LogsError": self._hub_logs_error,
                "LastLogAt": self._hub_last_log.get("timestamp"),
                "LastLogType": self._hub_last_log.get("type"),
                "PaymentMethod": charge.payment_method if charge else None,
                "ConfiguredPaymentMethod": details.get("payment_method"),
                "PaymentMethodType": details.get("payment_method_type"),
                "HasPayment": details.get("has_payment"),
                "Currency": charge.currency if charge else snapshot.currency,
                "ReceiptAvailable": bool(charge and charge.raw.get("has_receipt")),
                "LastMeterReadingKwh": details.get("last_meter_reading_kwh"),
                "EstimatedKwh": details.get("estimated_kwh"),
                "EstimatedPrice": details.get("estimated_price"),
                "EstimatedCompleteAt": details.get("estimated_complete_at"),
                "CanSmartCharge": details.get("can_smart_charge"),
                "AutoCharge": raw.get("auto_charge"),
            },
        }
        if charge is not None and not charge.is_active:
            result["LastSessionData"] = self._history_to_legacy(charge)
        return result

    def _history_to_legacy(self, charge: ChargeSession) -> dict[str, Any]:
        connector_key = self._connector_key()
        return {
            "Id": charge.id,
            "Connector": {"Id": connector_key},
            "TotalCosts": charge.price,
            "ActiveEnergyConsumption": charge.consumed_kwh,
            "ConnectedFrom": _iso(
                charge.cable_plugged_in_at or charge.starting_at or charge.started_at
            ),
            "ConnectedTo": _iso(
                charge.released_at
                or charge.completed_at
                or charge.stopped_at
            ),
            "ChargingFrom": _iso(charge.charging_at or charge.started_at),
            "ChargingTo": _iso(charge.stopped_at or charge.completed_at),
            "PaymentMethod": charge.payment_method,
            "State": charge.normalized_state,
            "ReceiptAvailable": bool(charge.raw.get("has_receipt")),
            "Currency": charge.currency,
            "StopReason": charge.stop_reason,
            "FailureReason": _charge_failure_reason(charge),
            "FailedAt": _iso(charge.failed_at),
            "ErrorTitle": _charge_error_text(charge, "title"),
            "ErrorDescription": _charge_error_text(
                charge, "description", "message"
            ),
        }


def extract_charger_number(value: str | None) -> str | None:
    """Extract the user-facing charger number from old/new ON identifiers."""
    if not value:
        return None
    text = value.strip()
    for pattern in CHARGER_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("number")
    return None


def _match_candidate(
    candidates: tuple[MontaChargerCandidate, ...],
    charge_point_id: str | None,
    evse_code: str | None,
) -> MontaChargerCandidate | None:
    if charge_point_id is not None:
        target_id = str(charge_point_id)
        direct = next(
            (item for item in candidates if item.charge_point_id == target_id),
            None,
        )
        if direct is not None:
            return direct
    target_number = extract_charger_number(evse_code)
    if target_number:
        matched = next(
            (item for item in candidates if item.charger_number == target_number),
            None,
        )
        if matched is not None:
            return matched
    return candidates[0] if len(candidates) == 1 else None


def _friendly_status(
    snapshot: ChargerSnapshot, charge: ChargeSession | None
) -> str:
    if snapshot.connected is False or snapshot.state == "disconnected":
        return "Disconnected"
    if charge is not None:
        if charge.has_failed and _is_recent_failure(charge):
            return "Failed"
        if charge.is_active:
            state = (charge.state or "").lower()
            if charge.stopping_at is not None or state == "stopping":
                return "Stopping"
            if state == "charging":
                return "Charging"
            if state == "paused":
                return "Suspended EV"
            if state in {"starting", "reserved", "scheduled"}:
                return state.replace("_", " ").title()
            if state:
                return state.replace("_", " ").title()
    if snapshot.state == "busy-charging":
        return "Charging"
    if snapshot.state == "busy-non-charging":
        active = _mapping(snapshot.raw.get("active_charge"))
        return "Busy (paused)" if active.get("state") == "paused" else "Busy (not charging)"
    if snapshot.cable_plugged_in is True:
        return "Preparing"
    if snapshot.state:
        return snapshot.state.replace("-", " ").replace("_", " ").title()
    return "Unknown"


def _is_recent_failure(charge: ChargeSession) -> bool:
    """Keep an asynchronous failure visible long enough for HA to observe it."""
    if not charge.has_failed:
        return False
    failed_at = charge.failed_at or charge.completed_at or charge.stopped_at
    if failed_at is None:
        return True
    if failed_at.tzinfo is None:
        failed_at = failed_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - failed_at <= FAILED_CHARGE_VISIBILITY


def _charge_error_text(
    charge: ChargeSession | None, *keys: str
) -> str | None:
    """Extract display-safe text from Monta's structured charge error."""
    if charge is None:
        return None
    error = charge.raw.get("error")
    if not isinstance(error, Mapping):
        return None
    for key in keys:
        value = error.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _charge_failure_reason(charge: ChargeSession | None) -> str | None:
    """Return Monta's explicit reason or its human-readable fallback."""
    if charge is None or not charge.has_failed:
        return None
    return charge.failure_reason or _charge_error_text(
        charge, "description", "message", "title"
    )


def _charge_to_legacy_session(charge: ChargeSession | None) -> dict[str, Any]:
    if charge is None:
        return {}
    return {
        "Id": charge.id,
        "ConnectedFrom": _iso(
            charge.cable_plugged_in_at or charge.starting_at or charge.started_at
        ),
        "ChargingFrom": _iso(charge.charging_at or charge.started_at),
        "ChargingTo": _iso(charge.stopped_at),
        "TotalCosts": charge.price,
        "State": charge.state,
        "PaymentMethod": charge.payment_method,
        "PayingTeamId": charge.paying_team_id,
    }


def _first_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return value[0]
    return {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_value(*values: Any) -> Any:
    """Return the first non-null value while preserving false and zero."""
    return next((value for value in values if value is not None), None)


def _wh_to_kwh(value: Any) -> float | None:
    try:
        return float(value) / 1000 if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error_info(value: Any) -> str | None:
    """Return only concise display text from optional Hub error details."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        for key in ("message", "description", "title", "code"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def _safe_log_summary(value: Any) -> dict[str, Any]:
    """Retain non-sensitive station-log metadata only."""
    if not isinstance(value, Mapping):
        return {}
    return {
        "timestamp": _first_value(
            value.get("timestamp"), value.get("created_at"), value.get("createdAt")
        ),
        "type": _first_value(
            value.get("type"),
            value.get("event"),
            value.get("action"),
            value.get("status"),
        ),
    }


def _model_brand(model: Mapping[str, Any]) -> str | None:
    brand = model.get("brand") or model.get("brand_name")
    if brand:
        return str(brand)
    identifier = str(model.get("identifier") or "")
    if "_" in identifier:
        return identifier.split("_", 1)[0].title()
    return None


def _first_timestamp(*values: datetime | None) -> str | None:
    return next((_iso(value) for value in values if value is not None), None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
