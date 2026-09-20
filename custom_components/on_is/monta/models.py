"""Normalized records shared across Monta API surfaces."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, Mapping, TypeVar

T = TypeVar("T")
JsonObject = dict[str, Any]

TERMINAL_CHARGE_STATES = frozenset(
    {
        "completed",
        "failed",
        "stopped",
        "cancelled",
        "canceled",
        "timeout",
        "released",
    }
)


@dataclass(frozen=True)
class MontaToken:
    """OAuth or guest token data."""

    access_token: str
    refresh_token: str | None = None
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    raw: JsonObject = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MontaToken":
        """Parse Public, Partner, app, or deeplink guest token payloads."""
        token_payload = payload.get("token", payload)
        if not isinstance(token_payload, Mapping):
            raise ValueError("Token response is not an object")
        access_token = _text(token_payload, "accessToken", "access_token")
        if not access_token:
            raise ValueError("Token response is missing accessToken")
        return cls(
            access_token=access_token,
            refresh_token=_text(token_payload, "refreshToken", "refresh_token"),
            access_token_expires_at=parse_datetime(
                _value(
                    token_payload,
                    "accessTokenExpirationDate",
                    "access_token_expiration_date",
                    "expiresAt",
                    "expires_at",
                )
            ),
            refresh_token_expires_at=parse_datetime(
                _value(
                    token_payload,
                    "refreshTokenExpirationDate",
                    "refresh_token_expiration_date",
                )
            ),
            raw=dict(token_payload),
        )

    def access_token_expired(self, *, leeway_seconds: int = 60) -> bool:
        """Return whether the access token is expired or nearly expired."""
        if self.access_token_expires_at is None:
            return False
        now = datetime.now(timezone.utc).timestamp()
        return self.access_token_expires_at.timestamp() <= now + leeway_seconds


@dataclass(frozen=True)
class MontaPage(Generic[T]):
    """Normalized offset or cursor page while retaining the raw response."""

    items: tuple[T, ...]
    page: int | None = None
    per_page: int | None = None
    total: int | None = None
    pages: int | None = None
    after: str | int | None = None
    before: str | int | None = None
    raw: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: Any) -> "MontaPage[Any]":
        """Parse Monta's several list envelope variants."""
        if isinstance(payload, list):
            return cls(items=tuple(payload), total=len(payload), raw=payload)
        if not isinstance(payload, Mapping):
            raise ValueError("Paginated response is not an object or list")

        candidates = ("data", "content", "items", "results")
        items: Any = []
        for key in candidates:
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
        pagination = (
            payload.get("pagination")
            if isinstance(payload.get("pagination"), Mapping)
            else {}
        )
        metadata = {**pagination, **meta}
        return cls(
            items=tuple(items),
            page=_first_not_none(
                _integer(metadata, "page", "currentPage", "current_page"),
                _integer(payload, "page", "pageNumber"),
            ),
            per_page=_first_not_none(
                _integer(metadata, "perPage", "per_page", "size"),
                _integer(payload, "perPage", "per_page", "pageSize"),
            ),
            total=_first_not_none(
                _integer(metadata, "total", "totalCount", "count"),
                _integer(payload, "total", "totalCount", "count"),
            ),
            pages=_first_not_none(
                _integer(metadata, "pages", "totalPages", "last_page"),
                _integer(payload, "pages", "totalPages"),
            ),
            after=_value(metadata, "after", "next", "nextCursor"),
            before=_value(metadata, "before", "previous", "previousCursor"),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class ChargerSnapshot:
    """Backend-neutral snapshot of a Monta charge point."""

    id: str
    name: str | None = None
    identifier: str | None = None
    evse_id: str | None = None
    state: str | None = None
    connected: bool | None = None
    available: bool | None = None
    active: bool | None = None
    cable_plugged_in: bool | None = None
    active_charge_id: str | None = None
    max_kw: float | None = None
    power_kw: float | None = None
    average_kw: float | None = None
    meter_total_kwh: float | None = None
    price_per_kwh: float | None = None
    currency: str | None = None
    last_connected_at: datetime | None = None
    disconnected_at: datetime | None = None
    updated_at: datetime | None = None
    firmware_version: str | None = None
    brand: str | None = None
    model: str | None = None
    team_id: str | None = None
    site_id: str | None = None
    operator_name: str | None = None
    integration_id: str | None = None
    can_start: bool | None = None
    can_start_reason: str | None = None
    raw: JsonObject = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_public(cls, payload: Mapping[str, Any]) -> "ChargerSnapshot":
        """Normalize a Public or Partner API charge point."""
        charger_id = _required_id(payload)
        state = _text(payload, "state", "status")
        active_charge = payload.get("activeCharge") or payload.get("active_charge")
        active_charge_id = _entity_id(active_charge)
        operator = payload.get("operator")
        return cls(
            id=charger_id,
            name=_text(payload, "name"),
            identifier=_text(payload, "identifier", "identity"),
            evse_id=_text(payload, "evseId", "evse_id"),
            state=state,
            connected=False if state == "disconnected" else None,
            available=True if state == "available" else None,
            active=_boolean(payload, "isActive", "active"),
            cable_plugged_in=_boolean(
                payload, "cablePluggedIn", "cable_plugged_in"
            ),
            active_charge_id=active_charge_id,
            max_kw=_number(payload, "maxKw", "maxKW", "max_kw"),
            meter_total_kwh=_number(
                payload, "lastMeterReadingKwh", "last_meter_reading_kwh"
            ),
            last_connected_at=parse_datetime(
                _value(payload, "lastConnectedAt", "last_connected_at")
            ),
            disconnected_at=parse_datetime(
                _value(payload, "disconnectedAt", "disconnected_at")
            ),
            updated_at=parse_datetime(_value(payload, "updatedAt", "updated_at")),
            firmware_version=_text(
                payload, "firmwareVersion", "firmware_version"
            ),
            brand=_text(payload, "brandName", "brand_name"),
            model=_text(payload, "modelName", "model_name"),
            team_id=_opaque_id(_value(payload, "teamId", "team_id")),
            site_id=_opaque_id(_value(payload, "siteId", "site_id")),
            operator_name=_entity_name(operator),
            raw=dict(payload),
        )

    @classmethod
    def from_deeplink(cls, payload: Mapping[str, Any]) -> "ChargerSnapshot":
        """Normalize the private deeplink guest charge-point response."""
        charger_id = _required_id(payload)
        details = payload.get("details")
        details = details if isinstance(details, Mapping) else {}
        active_charge = payload.get("active_charge")
        integration = _mapping(payload.get("integration"))
        pricing = _select_pricing(payload.get("pricings"))
        currency = payload.get("currency")
        integration_state = _text(integration, "state", "status")
        return cls(
            id=charger_id,
            name=_text(payload, "name"),
            identifier=_text(payload, "identifier"),
            state=_text(payload, "state"),
            available=_boolean(payload, "available"),
            active=_boolean(payload, "active"),
            connected=(
                integration_state.lower() == "connected"
                if integration_state
                else None
            ),
            # The nested value remains true on observed unplugged chargers.
            cable_plugged_in=_boolean(payload, "cable_plugged_in"),
            active_charge_id=_entity_id(active_charge),
            max_kw=_number(payload, "max_kw"),
            average_kw=_number(payload, "avg_kw"),
            meter_total_kwh=_number(details, "last_meter_reading_kwh"),
            price_per_kwh=_pricing_amount(pricing),
            currency=_currency_identifier(currency),
            updated_at=parse_datetime(_value(payload, "updated_at")),
            last_connected_at=parse_datetime(
                _value(integration, "last_connected_at", "lastConnectedAt")
            ),
            disconnected_at=parse_datetime(
                _value(integration, "disconnected_at", "disconnectedAt")
            ),
            firmware_version=_text(details, "firmware_version"),
            team_id=_opaque_id(_value(payload, "team_id")),
            operator_name=_text(payload, "operator_name"),
            integration_id=_entity_id(integration),
            can_start=_boolean(details, "can_start"),
            can_start_reason=_text(details, "can_start_reason"),
            raw=dict(payload),
        )

    @classmethod
    def from_app(cls, payload: Mapping[str, Any]) -> "ChargerSnapshot":
        """Normalize a signed-in Android app charge-point response."""
        return cls.from_deeplink(payload)

    @classmethod
    def from_hub(cls, payload: Mapping[str, Any]) -> "ChargerSnapshot":
        """Normalize a Hub gateway charge-point detail or list item."""
        charger_id = _required_id(payload)
        integration = _mapping(payload.get("charge_point_integration"))
        station = _mapping(payload.get("charging_station"))
        station_payload = _mapping(station.get("payload"))
        connectors = station_payload.get("connectors")
        connector = connectors[0] if isinstance(connectors, list) and connectors else {}
        connector = _mapping(connector)
        measurements = _mapping(connector.get("connector_measurements"))

        state = _text(payload, "status", "state") or _text(station, "state")
        connection = _text(payload, "connection") or _text(integration, "state")
        connected = None
        if connection:
            connected = connection.lower() in {"connected", "active", "online"}

        meter_wh = _number(connector, "meter_wh")
        power_w = _number(measurements, "power_import", "powerImport", "power")
        return cls(
            id=charger_id,
            name=_text(payload, "name"),
            identifier=_text(payload, "identifier", "identity"),
            evse_id=_text(payload, "evse_id", "evseId"),
            state=state,
            connected=connected,
            available=True if state and state.lower() == "available" else None,
            active=_boolean(payload, "active", "is_active", "isActive"),
            cable_plugged_in=_boolean(
                connector, "vehicle_plugged", "cable_plugged_in"
            ),
            active_charge_id=_entity_id(
                payload.get("active_charge") or payload.get("activeCharge")
            ),
            max_kw=_number(payload, "max_kw", "maxKw"),
            power_kw=power_w / 1000 if power_w is not None else None,
            meter_total_kwh=meter_wh / 1000 if meter_wh is not None else None,
            last_connected_at=parse_datetime(
                _value(
                    payload,
                    "lastConnectedAt",
                    "last_connected_at",
                )
                or _value(integration, "last_connected_at", "lastConnectedAt")
            ),
            disconnected_at=parse_datetime(
                _value(payload, "disconnectedAt", "disconnected_at")
                or _value(integration, "disconnected_at", "disconnectedAt")
            ),
            updated_at=parse_datetime(
                _value(connector, "updated_at", "updatedAt")
                or _value(station, "updated_at", "updatedAt")
                or _value(payload, "updatedAt", "updated_at")
            ),
            firmware_version=_text(
                integration, "firmware_version", "firmwareVersion"
            ),
            team_id=_opaque_id(_value(payload, "team_id", "teamId")),
            site_id=_opaque_id(_value(payload, "site_id", "siteId")),
            operator_name=_text(payload, "operator_name", "operatorName"),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class ChargeSession:
    """Backend-neutral charging session."""

    id: str
    charge_point_id: str | None = None
    external_charge_id: str | None = None
    state: str | None = None
    created_at: datetime | None = None
    cable_plugged_in_at: datetime | None = None
    started_at: datetime | None = None
    charging_at: datetime | None = None
    starting_at: datetime | None = None
    stopping_at: datetime | None = None
    stopped_at: datetime | None = None
    completed_at: datetime | None = None
    fully_charged_at: datetime | None = None
    failed_at: datetime | None = None
    releasing_at: datetime | None = None
    released_at: datetime | None = None
    timeout_at: datetime | None = None
    consumed_kwh: float | None = None
    power_kw: float | None = None
    price: float | None = None
    cost: float | None = None
    average_price_per_kwh: float | None = None
    currency: str | None = None
    state_of_charge: float | None = None
    start_meter_kwh: float | None = None
    end_meter_kwh: float | None = None
    paying_team_id: str | None = None
    payment_method: str | None = None
    stop_reason: str | None = None
    failure_reason: str | None = None
    can_stop: bool | None = None
    cpi_status: str | None = None
    can_unlock: bool | None = None
    integration_id: str | None = None
    raw: JsonObject = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ChargeSession":
        """Normalize Public, Partner, Hub, or guest charge data."""
        charge_id = _value(payload, "id", "chargeId", "charge_id")
        if charge_id is None:
            raise ValueError("Charge response is missing an id")
        currency = _value(payload, "currency")
        return cls(
            id=str(charge_id),
            charge_point_id=(
                _opaque_id(_value(payload, "chargePointId", "charge_point_id"))
                or _entity_id(payload.get("chargePoint") or payload.get("charge_point"))
                or _entity_id(payload.get("charge_point_info"))
            ),
            external_charge_id=_text(
                payload, "externalChargeId", "external_charge_id", "ocppChargeId"
            ),
            state=_text(payload, "state", "status"),
            created_at=parse_datetime(_value(payload, "createdAt", "created_at")),
            cable_plugged_in_at=parse_datetime(
                _value(payload, "cablePluggedInAt", "cable_plugged_in_at")
            ),
            started_at=parse_datetime(
                _value(payload, "startedAt", "started_at", "startTime")
            ),
            charging_at=parse_datetime(
                _value(payload, "chargingAt", "charging_at")
            ),
            starting_at=parse_datetime(
                _value(payload, "startingAt", "starting_at")
            ),
            stopping_at=parse_datetime(
                _value(payload, "stoppingAt", "stopping_at")
            ),
            stopped_at=parse_datetime(_value(payload, "stoppedAt", "stopped_at")),
            completed_at=parse_datetime(
                _value(payload, "completedAt", "completed_at")
            ),
            fully_charged_at=parse_datetime(
                _value(payload, "fullyChargedAt", "fully_charged_at")
            ),
            failed_at=parse_datetime(_value(payload, "failedAt", "failed_at")),
            releasing_at=parse_datetime(
                _value(payload, "releasingAt", "releasing_at")
            ),
            released_at=parse_datetime(
                _value(payload, "releasedAt", "released_at")
            ),
            timeout_at=parse_datetime(_value(payload, "timeoutAt", "timeout_at")),
            consumed_kwh=_number(
                payload, "consumedKwh", "consumed_kwh", "kwh"
            ),
            power_kw=_power_kw(payload),
            price=_number(payload, "price", "totalPrice", "total_price"),
            cost=_number(payload, "cost", "totalCost", "total_cost"),
            average_price_per_kwh=_number(
                payload, "averagePricePerKwh", "average_price_per_kwh"
            ),
            currency=_currency_identifier(currency),
            state_of_charge=_number(
                payload, "soc", "stateOfCharge", "state_of_charge", "endSoc"
            ),
            start_meter_kwh=_number(
                payload, "startMeterKwh", "start_meter_kwh", "startingKwh"
            ),
            end_meter_kwh=_number(
                payload, "endMeterKwh", "end_meter_kwh", "endingKwh"
            ),
            paying_team_id=(
                _opaque_id(_value(payload, "payingTeamId", "paying_team_id"))
                or _entity_id(payload.get("paying_team"))
            ),
            payment_method=_text(payload, "paymentMethod", "payment_method"),
            stop_reason=_text(payload, "stopReason", "stop_reason"),
            failure_reason=_text(
                payload, "failureReason", "failure_reason", "failedReason"
            ),
            can_stop=_boolean(payload, "canStop", "can_stop"),
            cpi_status=_text(payload, "cpiStatus", "cpi_status"),
            can_unlock=_boolean(_mapping(payload.get("user_actions")), "can_unlock"),
            integration_id=_opaque_id(
                _value(_mapping(payload.get("user_actions")), "integration_id")
            ),
            raw=dict(payload),
        )

    @property
    def is_active(self) -> bool:
        """Return whether this is a non-terminal charge."""
        return bool(
            not self.has_failed
            and self.state
            and self.state.lower() not in TERMINAL_CHARGE_STATES
        )

    @property
    def has_failed(self) -> bool:
        """Return whether Monta attached a failure to this charge.

        Failed starts have been observed with ``state=completed`` while the
        authoritative failure signal lives in ``failed_at`` and ``error``.
        """
        error = self.raw.get("error")
        return bool(
            self.failed_at is not None
            or self.failure_reason
            or (isinstance(error, Mapping) and any(error.values()))
        )

    @property
    def normalized_state(self) -> str | None:
        """Return a state that accounts for Monta's completed failures."""
        return "failed" if self.has_failed else self.state


@dataclass(frozen=True)
class TelemetryMeasurement:
    """One live or historical Monta measurement sample."""

    timestamp: datetime | None
    energy_kwh: float | None = None
    power_kw: float | None = None
    current_a: float | None = None
    voltage_v: float | None = None
    state_of_charge: float | None = None
    phase_currents_a: tuple[float, ...] = ()
    phase_voltages_v: tuple[float, ...] = ()
    phase_powers_kw: tuple[float, ...] = ()
    raw: JsonObject = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TelemetryMeasurement":
        """Normalize a Hub Control or Partner Energy measurement."""
        energy_wh = _number(payload, "energyWattHour", "energy_wh", "meterWh")
        power_w = _number(payload, "powerImport", "power_w", "power")
        return cls(
            timestamp=parse_datetime(
                _value(payload, "timestamp", "measuredAt", "measured_at", "at")
            ),
            energy_kwh=(
                energy_wh / 1000
                if energy_wh is not None
                else _number(payload, "energyKwh", "energy_kwh", "kwh")
            ),
            power_kw=(
                power_w / 1000
                if power_w is not None
                else _number(payload, "powerKw", "power_kw")
            ),
            current_a=_number(payload, "currentImport", "current_a", "current"),
            voltage_v=_number(payload, "voltage", "voltage_v"),
            state_of_charge=_number(payload, "soc", "stateOfCharge"),
            phase_currents_a=_number_tuple(
                payload, "phaseCurrents", "phase_currents_a", "currents"
            ),
            phase_voltages_v=_number_tuple(
                payload, "phaseVoltages", "phase_voltages_v", "voltages"
            ),
            phase_powers_kw=_number_tuple(
                payload, "phasePowersKw", "phase_powers_kw"
            ),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class DeeplinkSummary:
    """Public data rendered by an ON/Monta permanent charger URL."""

    code: str
    title: str | None
    subtitle: str | None
    state_label: str | None
    max_kw: float | None
    price_per_kwh: float | None
    currency: str | None
    price_type: str | None
    charging_enabled: bool | None
    app_link: str | None
    guest_charge_link: str | None
    operator_identifier: str | None
    application_identifier: str | None
    raw: JsonObject = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, code: str, payload: Mapping[str, Any]) -> "DeeplinkSummary":
        data = _mapping(payload.get("data"))
        operator = _mapping(payload.get("operator"))
        price_text = _text(data, "price_text")
        return cls(
            code=code,
            title=_text(data, "title"),
            subtitle=_text(data, "subtitle"),
            state_label=_text(_mapping(data.get("badge")), "text"),
            max_kw=_parse_number(_text(data, "kw")),
            price_per_kwh=_parse_number(price_text),
            currency=_parse_currency(price_text),
            price_type=_text(data, "price_type"),
            charging_enabled=_boolean(data, "charging_enabled"),
            app_link=_text(data, "charge_with_link"),
            guest_charge_link=_text(data, "charge_without_link"),
            operator_identifier=_text(operator, "identifier"),
            application_identifier=_text(operator, "application_identifier"),
            raw=dict(payload),
        )


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _value(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _text(payload: Mapping[str, Any], *keys: str) -> str | None:
    value = _value(payload, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(payload: Mapping[str, Any], *keys: str) -> int | None:
    value = _value(payload, *keys)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(payload: Mapping[str, Any], *keys: str) -> float | None:
    return _parse_number(_value(payload, *keys))


def _parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("\u00a0", " ").split(" ", 1)[0]
        cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _boolean(payload: Mapping[str, Any], *keys: str) -> bool | None:
    value = _value(payload, *keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    return None


def _required_id(payload: Mapping[str, Any]) -> str:
    value = _value(payload, "id", "chargePointId", "charge_point_id")
    if value is None:
        raise ValueError("Charge-point response is missing an id")
    return str(value)


def _entity_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _opaque_id(_value(value, "id", "chargeId", "charge_id"))
    if isinstance(value, (int, str)):
        return str(value)
    return None


def _opaque_id(value: Any) -> str | None:
    """Preserve Monta identifiers as strings to avoid IEEE-754 precision loss."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, str)):
        return str(value)
    return None


def _entity_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _text(value, "name", "displayName", "display_name")
    return str(value) if isinstance(value, str) else None


def _currency_identifier(value: Any) -> str | None:
    if isinstance(value, Mapping):
        identifier = _text(value, "identifier", "code", "currency")
        return identifier.upper() if identifier else None
    if isinstance(value, str):
        return value.upper()
    return None


def _parse_currency(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.replace("\u00a0", " ").split()
    return parts[1] if len(parts) > 1 else None


def _select_pricing(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        for key in ("user", "team", "public"):
            if isinstance(value.get(key), Mapping):
                return value[key]
        return value
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return value[0]
    return {}


def _power_kw(payload: Mapping[str, Any]) -> float | None:
    direct = _number(payload, "powerKw", "power_kw")
    if direct is not None:
        return direct
    watts = _number(payload, "powerW", "power_w", "powerImport")
    if watts is not None:
        return watts / 1000
    measurement = _mapping(payload.get("last_measurement"))
    return _number(measurement, "kw_charge_point", "kw_vehicle")


def _number_tuple(payload: Mapping[str, Any], *keys: str) -> tuple[float, ...]:
    value = _value(payload, *keys)
    if not isinstance(value, list):
        return ()
    numbers = [_parse_number(item) for item in value]
    return tuple(number for number in numbers if number is not None)


def _pricing_amount(pricing: Mapping[str, Any]) -> float | None:
    direct = _number(pricing, "price_per_kwh", "kwh_price", "price", "amount")
    if direct is not None:
        return direct
    master = _mapping(pricing.get("master_pricing"))
    amount = _number(master, "amount", "current_fixed_price")
    if amount is not None:
        return amount
    entries = pricing.get("pricing_entries")
    if isinstance(entries, list):
        for entry in entries:
            entry = _mapping(entry)
            if _text(entry, "type") in {"fixed_kwh", "kwh"}:
                amount = _number(entry, "amount")
                if amount is not None:
                    return amount
    return None


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)
