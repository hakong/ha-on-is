"""Small data helpers for the ON integration."""
from __future__ import annotations


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
