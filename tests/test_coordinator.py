"""Coordinator persistence tests, run when Home Assistant is installed."""
from __future__ import annotations

from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

try:
    from homeassistant.core import HomeAssistant
except ImportError:
    HomeAssistant = None


@unittest.skipIf(HomeAssistant is None, "Home Assistant runtime required")
class HistoryPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_monta import models  # Establish the integration package loader.
        from custom_components.on_is.coordinator import OnIsCoordinator

        self.tmp = TemporaryDirectory()
        self.hass = HomeAssistant(self.tmp.name)
        self.entry = SimpleNamespace(entry_id="test-entry", data={}, async_on_unload=Mock())
        self.client = SimpleNamespace(
            backend_key="monta_app", backend_name="Monta", api_family="app",
            base_url="https://api.monta.app",
            get_online_data=AsyncMock(return_value=[{"Connector": {"Id": 3806}}]),
            get_charging_history=AsyncMock(return_value=[]),
        )
        with patch("custom_components.on_is.coordinator.Store") as store:
            self.store = store.return_value
            self.store.async_load = AsyncMock(return_value={})
            self.store.async_save = AsyncMock()
            self.coordinator = OnIsCoordinator(self.hass, self.client, self.entry)

    async def asyncTearDown(self):
        await self.hass.async_stop()
        self.tmp.cleanup()

    async def test_restart_then_summary_refresh_preserves_rich_failure(self):
        rich = {"Id": "failed", "Connector": {"Id": 3806}, "State": "failed",
                "FailureCode": "StartTransactionTimeout", "ErrorTitle": "Timeout"}
        self.store.async_load.return_value = {"3806": rich}
        await self.coordinator.async_load_history()
        self.client.get_charging_history.return_value = [{
            "Id": "failed", "Connector": {"Id": 3806}, "State": "failed",
            "FailureCode": None, "ErrorTitle": None,
        }]
        result = await self.coordinator._async_update_data()
        self.assertEqual(result[3806]["LastSessionData"]["ErrorTitle"], "Timeout")
        self.assertEqual(result[3806]["LastSessionData"]["FailureCode"],
                         "StartTransactionTimeout")
        self.store.async_save.assert_not_awaited()

    async def test_new_session_clears_failure_and_is_saved_once(self):
        self.coordinator._cache_history(3806, {
            "Id": "old", "Connector": {"Id": 3806}, "ErrorTitle": "Timeout",
        })
        self.client.get_charging_history.return_value = [{
            "Id": "new", "Connector": {"Id": 3806}, "State": "completed",
        }]
        result = await self.coordinator._async_update_data()
        self.assertNotIn("ErrorTitle", result[3806]["LastSessionData"])
        self.store.async_save.assert_awaited_once()
        await self.coordinator._async_update_data()
        self.store.async_save.assert_awaited_once()
