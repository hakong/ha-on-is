"""Small data helpers for the ON integration."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

LAST_COMMUNICATION_TIME = "LastCommunicationTime"
LAST_COMMUNICATION_TIME_CACHED = "LastCommunicationTimeCached"

START_REASON_LABELS = {
    "PAYMENT_NOT_ALLOWED": "Payment not allowed for this account",
    "NO_ELIGIBLE_PAYER": "No eligible ON billing account",
    "PAYER_LOOKUP_FAILED": "Could not check ON billing account",
    "NOT_AVAILABLE": "Charger unavailable",
    "NO_PAYMENT": "No payment method available",
}


def elapsed_minutes_since(
    timestamp: datetime | None, now: datetime | None = None
) -> int | None:
    """Return nonnegative whole minutes since a successful update."""
    if timestamp is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - timestamp).total_seconds() // 60))


def start_readiness(monta: Mapping[str, Any]) -> str:
    """Describe Monta's current start eligibility in plain language."""
    if monta.get("ActiveChargeId"):
        return "Charge in progress"
    if monta.get("ActiveChargePresent"):
        if monta.get("ActiveChargeSummaryState") == "paused":
            return "Occupied (paused): session not visible to this account"
        return "Occupied: session not visible to this account"
    if monta.get("Connected") is False:
        return "Charger offline"
    if monta.get("CanStart") is True:
        return "Ready to start"
    reason = monta.get("CanStartReason")
    if reason:
        return START_REASON_LABELS.get(str(reason), str(reason).replace("_", " ").title())
    if monta.get("CanStart") is False:
        return "Monta says start unavailable"
    return "Start availability unknown"


def extract_evse_code(session: dict) -> str:
    """Return the ON EVSE code for a session-like API object."""
    connector = session.get("Connector", {})
    if connector.get("EvseCode"):
        return connector["EvseCode"]

    try:
        cp_code = session.get("ChargePoint", {}).get("FriendlyCode")
        evse_code = session.get("Evse", {}).get("FriendlyCode")
        conn_code = connector.get("Code")
    except AttributeError:
        return "unknown"

    if not cp_code or not evse_code or not conn_code:
        return "unknown"

    return f"{cp_code}-{evse_code}-{conn_code}"


def evse_codes_match(left: str | None, right: str | None) -> bool:
    """Compare EVSE codes while ignoring accidental casing and whitespace."""
    if not left or not right:
        return False
    return left.strip().casefold() == right.strip().casefold()


def format_minutes(total_minutes: int) -> str:
    """Return a compact human-readable duration."""
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"


def rate_limit_backoff_seconds(
    failures: int,
    retry_after: float | None = None,
) -> float:
    """Honor Retry-After or return bounded exponential backoff."""
    if retry_after is not None:
        return max(60, retry_after)
    return min(900, 60 * (2 ** max(0, failures - 1)))


def apply_cached_last_communication(
    connector_id: int,
    session: dict,
    cache: dict[int, str],
) -> None:
    """Keep last communication timestamps stable when passive data omits them."""
    timestamp = session.get(LAST_COMMUNICATION_TIME)
    if timestamp:
        cache[connector_id] = timestamp
        session[LAST_COMMUNICATION_TIME_CACHED] = False
        return

    cached_timestamp = cache.get(connector_id)
    if cached_timestamp:
        session[LAST_COMMUNICATION_TIME] = cached_timestamp
        session[LAST_COMMUNICATION_TIME_CACHED] = True
        return

    session[LAST_COMMUNICATION_TIME_CACHED] = False
