"""Shared entity helpers for the ON integration."""
from __future__ import annotations

from typing import Any, Mapping

from .const import DOMAIN


def charger_base_name(session: Mapping[str, Any]) -> str:
    """Return a stable user-facing charger name."""
    cp_code = str(session.get("ChargePoint", {}).get("FriendlyCode") or "")
    if cp_code and "-" in cp_code:
        cp_code = cp_code.split("-")[-1]
    if cp_code:
        return f"ON Charger {cp_code}"
    location = session.get("Location", {}).get("FriendlyName", "Unknown")
    return f"ON {location}"


def charger_device_info(
    connector_id: int | str,
    session: Mapping[str, Any],
    coordinator: Any,
) -> dict[str, Any]:
    """Build common Home Assistant device metadata."""
    monta = session.get("Monta", {})
    model = monta.get("Model") or session.get("ChargePoint", {}).get("FriendlyCode")
    device_info = {
        "identifiers": {(DOMAIN, str(connector_id))},
        "name": charger_base_name(session),
        "manufacturer": monta.get("Brand") or "ON",
        "model": model or "EV Charger",
        "sw_version": monta.get("FirmwareVersion") or coordinator.backend_name,
    }
    if monta.get("SerialNumber"):
        device_info["serial_number"] = monta["SerialNumber"]
    return device_info
