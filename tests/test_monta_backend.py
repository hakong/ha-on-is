"""Tests for the Home Assistant-facing Monta backend adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_monta import models

from custom_components.on_is.monta.app import MontaPayingTeam
from custom_components.on_is.monta.errors import MontaAccessError
from custom_components.on_is.monta_backend import MontaOnIsClient


def _charge(charge_id="889565977676087673", state="charging"):
    return models.ChargeSession.from_payload(
        {
            "id": charge_id,
            "state": state,
            "charge_point_info": {"id": 6440650},
            "paying_team": {"id": 42},
            "starting_at": "2026-09-20T17:37:36Z",
            "charging_at": "2026-09-20T17:37:48Z",
            "consumed_kwh": 5.182,
            "price": 115.09,
            "currency": {"identifier": "isk"},
            "payment_method": "team",
            "last_measurement": {
                "date": "2026-09-20T17:41:48Z",
                "kw_charge_point": 11.112,
                "current_l1": 16.1,
                "voltage_l1": 230.4,
            },
            "user_actions": {"can_unlock": True, "integration_id": 17386972},
            "can_stop": True,
            "cpi_status": "Charging",
            "has_receipt": True,
        }
    )


class FakeAppClient:
    """Small signed-in app client double."""

    def __init__(self):
        self.token = models.MontaToken(
            access_token="token",
            refresh_token="refresh",
        )
        self.context = SimpleNamespace(request_uuid="device-1")
        self.active = _charge()
        self.calls = []

    async def close(self):
        self.calls.append(("close",))

    async def login(self):
        self.calls.append(("login",))

    async def list_teams(self, *, team_type=None):
        self.calls.append(("teams", team_type))
        return models.MontaPage(items=({"id": 42},))

    async def list_team_charger_cards(self, team_id, *, page=1):
        return models.MontaPage(
            items=(
                {
                    "data": {
                        "charge_point_id": 6440650,
                        "title": "ON 3806-1",
                        "subtitle": "Urriðaholtsstræti 30",
                        "badge": {"text": "Available"},
                    }
                },
                {
                    "data": {
                        "charge_point_id": 6442130,
                        "title": "ON 4763-1",
                    }
                },
            ),
            page=1,
            pages=1,
        )

    async def get_charge_point(self, charge_point_id, **kwargs):
        self.calls.append(("detail", str(charge_point_id), kwargs))
        point = {
            "id": 6440650,
            "name": "ON 3806-1",
            "state": "busy-charging",
            "available": False,
            "active": True,
            "cable_plugged_in": True,
            "active_charge": {"id": 889565977676087700},
            "max_kw": 22,
            "avg_kw": 7.2,
            "currency": {"identifier": "isk"},
            "pricings": {
                "user": {
                    "master_pricing": {"type": "fixed_kwh", "amount": 22.21}
                }
            },
            "details": {
                "can_start": False,
                "last_meter_reading_kwh": 1702.5,
                "firmware_version": "6.3.3.3",
            },
            "integration": {
                "id": 17386972,
                "state": "connected",
                "last_connected_at": "2026-09-20T17:41:47Z",
            },
            "model": {"brand": "Zaptec", "name": "Zaptec Pro"},
            "connectors": [{"name": "Type 2"}],
        }
        if self.active is None or not self.active.is_active:
            point.update({"state": "available", "available": True,
                          "active": False, "active_charge": None})
        return point

    async def get_active_charge(self, charge_point_id):
        self.calls.append(("active", str(charge_point_id)))
        return self.active if self.active and self.active.is_active else None

    async def get_charge(self, charge_id):
        self.calls.append(("charge_detail", str(charge_id)))
        return self.active

    async def list_charge_sessions(self, **kwargs):
        completed = _charge("889565977676087600", "completed")
        return models.MontaPage(items=(completed,))

    async def get_default_paying_team(self, charge_point_id):
        self.calls.append(("payer", str(charge_point_id)))
        return MontaPayingTeam(id="42", can_pay=True, pre_select=True)

    async def start_charge(self, charge_point_id, paying_team_id):
        self.calls.append(("start", str(charge_point_id), str(paying_team_id)))
        return self.active

    async def stop_charge(self, charge_id, charge_point_id):
        self.calls.append(("stop", str(charge_id), str(charge_point_id)))
        self.active = _charge(charge_id, "completed")
        return self.active

    async def release_cable(self, charge_point_id, integration_id):
        self.calls.append(
            ("release", str(charge_point_id), str(integration_id))
        )
        return {"success": True}

    async def get_receipt(self, charge_id):
        return {"charge_id": str(charge_id)}


class FakeHubClient:
    """Hub health client double using the app bearer."""

    def __init__(self):
        self.access_token = None
        self.calls = []

    def set_access_token(self, access_token):
        self.access_token = access_token

    async def close(self):
        self.calls.append(("close",))

    async def get_charge_point(self, charge_point_id):
        self.calls.append(("hub_detail", str(charge_point_id)))
        return {
            "status": "busy-charging",
            "connection": "connected",
            "updated_at": "2026-09-20T21:49:34Z",
            "total_kwh": 66.282,
            "charge_count": 5,
            "stability_score": None,
            "firmware_upgrade_available": False,
            "charge_point_integration": {
                "state": "connected",
                "status": "Charging",
                "last_connected_at": "2026-09-20T22:08:45Z",
                "serial_number": "ZPR103825",
                "protocol_error_code": "NoError",
                "meter_accuracy": "ClassB",
            },
            "charging_station": {
                "identifier": "station-1",
                "firmware_version": "6.3.3.3",
                "available_firmware_version": None,
                "payload": {
                    "firmware_status": "Idle",
                    "meter_accuracy": "ClassB",
                    "mid": True,
                    "ocpp": True,
                    "connectors": [
                        {
                            "status": "Charging",
                            "meter_wh": 66282,
                            "error_code": "NoError",
                            "updated_at": "2026-09-20T21:49:19Z",
                        }
                    ],
                },
            },
        }

    async def get_charging_station_logs(self, station_identity, *, params=None):
        self.calls.append(("logs", station_identity, params))
        raise MontaAccessError("Hub logs forbidden", status=403)


class MontaBackendTests(unittest.IsolatedAsyncioTestCase):
    def test_restores_persisted_app_identity_and_token(self):
        client = MontaOnIsClient(
            "user@example.com",
            "secret",
            session=object(),
            device_uuid="stable-device",
            access_token="saved-access",
            refresh_token="saved-refresh",
            access_token_expires_at="3026-09-20T17:28:05+00:00",
        )

        self.assertEqual(client._app.context.request_uuid, "stable-device")
        self.assertEqual(client._app.token.access_token, "saved-access")
        self.assertEqual(client._app.token.refresh_token, "saved-refresh")
        self.assertFalse(client._app.token.access_token_expired())

    async def test_maps_charger_and_preserves_legacy_connector_id(self):
        app = FakeAppClient()
        client = MontaOnIsClient(
            "user@example.com",
            "secret",
            app_client=app,
            evse_code="IS*ONP00281-3806-1-1",
            connector_id=8350522,
        )

        data = (await client.get_online_data())[0]

        self.assertEqual(client.charge_point_id, "6440650")
        self.assertEqual(data["Connector"]["Id"], 8350522)
        self.assertEqual(data["Connector"]["Status"]["Title"], "Charging")
        self.assertEqual(data["Measurements"]["Power"], 11.112)
        self.assertEqual(data["Measurements"]["ActiveEnergyConsumed"], 5.182)
        self.assertEqual(data["ChargingSession"]["TotalCosts"], 115.09)
        self.assertTrue(data["Monta"]["CablePluggedIn"])
        self.assertTrue(data["Monta"]["Connected"])
        self.assertTrue(data["Monta"]["CanUnlock"])
        self.assertIsNone(data["Measurements"]["MeterTotal"])
        self.assertIn(("active", "6440650"), app.calls)
        self.assertIn(
            ("charge_detail", "889565977676087673"), app.calls
        )

    async def test_history_and_account_credit_controls(self):
        app = FakeAppClient()
        client = MontaOnIsClient(
            "user@example.com",
            "secret",
            app_client=app,
            charge_point_id=6440650,
        )
        await client.get_online_data()

        history = await client.get_charging_history()
        await client.start_charging("ignored", 1)
        await client.stop_charging("ignored", 1, 1)
        await client.release_cable()

        self.assertEqual(history[0]["Id"], "889565977676087600")
        self.assertTrue(history[0]["ReceiptAvailable"])
        self.assertIn(("start", "6440650", "42"), app.calls)
        self.assertIn(
            ("stop", "889565977676087673", "6440650"), app.calls
        )
        self.assertIn(("release", "6440650", "17386972"), app.calls)

    async def test_release_waits_for_charge_to_finish_before_unlocking(self):
        class DelayedStopApp(FakeAppClient):
            def __init__(self):
                super().__init__()
                self.polls = 0

            async def stop_charge(self, charge_id, charge_point_id):
                self.calls.append(("stop", str(charge_id), str(charge_point_id)))
                return _charge(charge_id, "charging")

            async def get_charge(self, charge_id):
                self.calls.append(("charge_detail", str(charge_id)))
                self.polls += 1
                return _charge(charge_id, "completed" if self.polls == 2 else "charging")

        app = DelayedStopApp()
        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=app, charge_point_id=6440650,
        )
        with patch("custom_components.on_is.monta_backend.asyncio.sleep") as sleep:
            await client.release_cable()

        self.assertEqual(sleep.await_count, 2)
        self.assertEqual(
            [call[0] for call in app.calls],
            ["teams", "detail", "active", "stop", "charge_detail",
             "charge_detail", "release"],
        )

    async def test_release_idle_charger_ignores_unlock_preview(self):
        app = FakeAppClient()
        app.active = None
        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=app, charge_point_id=6440650,
        )

        await client.release_cable()

        self.assertFalse(any(call[0] == "stop" for call in app.calls))
        self.assertIn(("release", "6440650", "17386972"), app.calls)

    async def test_release_cannot_stop_another_accounts_charge(self):
        class OccupiedApp(FakeAppClient):
            async def get_active_charge(self, charge_point_id):
                self.calls.append(("active", str(charge_point_id)))
                return None

        app = OccupiedApp()
        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=app, charge_point_id=6440650,
        )

        with self.assertRaisesRegex(ValueError, "this account cannot stop"):
            await client.release_cable()

        self.assertFalse(any(call[0] in {"stop", "release"} for call in app.calls))

    async def test_release_does_not_unlock_when_stop_remains_pending(self):
        class PendingStopApp(FakeAppClient):
            async def stop_charge(self, charge_id, charge_point_id):
                self.calls.append(("stop", str(charge_id), str(charge_point_id)))
                return _charge(charge_id, "charging")

        app = PendingStopApp()
        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=app, charge_point_id=6440650,
        )
        with patch("custom_components.on_is.monta_backend.asyncio.sleep"):
            with self.assertRaisesRegex(TimeoutError, "was not released"):
                await client.release_cable()

        self.assertFalse(any(call[0] == "release" for call in app.calls))

    def test_exports_reusable_login_session(self):
        client = MontaOnIsClient(
            "user@example.com",
            "secret",
            app_client=FakeAppClient(),
        )

        self.assertEqual(
            client.persisted_config_data(),
            {
                "device_uuid": "device-1",
                "access_token": "token",
                "refresh_token": "refresh",
            },
        )

    async def test_known_charge_point_skips_team_discovery(self):
        app = FakeAppClient()
        client = MontaOnIsClient(
            "user@example.com",
            "secret",
            app_client=app,
            charge_point_id=6440650,
            team_id=42,
        )

        await client.get_online_data()

        self.assertFalse(any(call[0] == "teams" for call in app.calls))

    async def test_start_eligibility_uses_billing_team_and_caches_lookup(self):
        class BillingContextApp(FakeAppClient):
            async def get_charge_point(self, charge_point_id, **kwargs):
                point = await super().get_charge_point(charge_point_id, **kwargs)
                point["details"]["can_start"] = kwargs.get("team_id") == "42"
                point["details"]["can_start_reason"] = (
                    None if point["details"]["can_start"] else "PAYMENT_NOT_ALLOWED"
                )
                return point

        app = BillingContextApp()
        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=app,
            charge_point_id=6440650, team_id=99,
        )

        first = (await client.get_online_data())[0]
        await client.get_online_data()

        self.assertTrue(first["Monta"]["CanStart"])
        self.assertEqual(first["Monta"]["CanStartReason"], None)
        self.assertEqual([call[0] for call in app.calls].count("payer"), 1)
        details = [call for call in app.calls if call[0] == "detail"]
        self.assertTrue(all(call[2]["team_id"] == "42" for call in details))

    async def test_missing_billing_team_is_visible(self):
        class NoPayerApp(FakeAppClient):
            async def get_default_paying_team(self, charge_point_id):
                return None

        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=NoPayerApp(),
            charge_point_id=6440650, team_id=99,
        )
        data = (await client.get_online_data())[0]

        self.assertFalse(data["Monta"]["CanStart"])
        self.assertEqual(data["Monta"]["CanStartReason"], "NO_ELIGIBLE_PAYER")
        self.assertFalse(data["Monta"]["PayingTeamAvailable"])

    async def test_enriches_and_caches_hub_health_with_app_bearer(self):
        app = FakeAppClient()
        app_point = await app.get_charge_point(6440650)
        app_point["model"]["stability_score"] = 84

        async def get_charge_point(charge_point_id, **kwargs):
            app.calls.append(("detail", str(charge_point_id), kwargs))
            return app_point

        app.get_charge_point = get_charge_point
        hub = FakeHubClient()
        client = MontaOnIsClient(
            "user@example.com",
            "secret",
            app_client=app,
            hub_client=hub,
            charge_point_id=6440650,
            team_id=42,
        )

        clock = SimpleNamespace(now=42.0)
        with patch(
            "custom_components.on_is.monta_backend.time",
            SimpleNamespace(monotonic=lambda: clock.now),
        ):
            data = (await client.get_online_data())[0]
            await client.get_online_data()
            self.assertEqual(
                [call[0] for call in hub.calls].count("hub_detail"), 1
            )
            clock.now += 301
            await client.get_online_data()

        self.assertEqual(hub.access_token, "token")
        self.assertEqual(data["Measurements"]["MeterTotal"], 66.282)
        self.assertEqual(data["Monta"]["LifetimeKwh"], 66.282)
        self.assertEqual(data["Monta"]["ChargeCount"], 5)
        self.assertEqual(data["Monta"]["ProtocolErrorCode"], "NoError")
        self.assertEqual(data["Monta"]["ModelStabilityScore"], 84)
        self.assertEqual(data["Monta"]["SerialNumber"], "ZPR103825")
        self.assertTrue(data["Monta"]["MidCertified"])
        self.assertTrue(data["Monta"]["Ocpp"])
        self.assertFalse(data["Monta"]["LogsAvailable"])
        self.assertEqual(data["Monta"]["LogsError"], "access_denied")
        self.assertEqual(
            [call[0] for call in hub.calls].count("hub_detail"), 2
        )

    async def test_old_completed_charge_does_not_override_plugged_in_status(self):
        class PluggedInApp(FakeAppClient):
            async def get_charge_point(self, charge_point_id, **kwargs):
                point = await super().get_charge_point(charge_point_id, **kwargs)
                point.update({"state": "available", "available": True,
                              "active": False, "active_charge": None})
                return point

            async def get_charge(self, charge_id):
                self.calls.append(("charge_detail", str(charge_id)))
                return self.active

            async def list_charge_sessions(self, **kwargs):
                return models.MontaPage(items=(self.active,))

        app = PluggedInApp()
        app.active = models.ChargeSession.from_payload({
            "id": "old-completed-charge", "state": "completed",
            "charge_point_info": {"id": 6440650},
            "stopping_at": "2026-09-20T11:43:00Z",
            "completed_at": "2026-09-20T11:44:00Z",
            "user_actions": {"can_unlock": True},
        })
        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=app,
            charge_point_id=6440650, team_id=42,
        )

        data = (await client.get_online_data())[0]

        self.assertEqual(data["Connector"]["Status"]["Title"], "Preparing")
        self.assertEqual(data["ChargingSession"], {})
        self.assertEqual(data["LastSessionData"]["State"], "completed")

    async def test_unreadable_active_charge_is_occupied_not_preparing(self):
        class OtherSessionApp(FakeAppClient):
            async def get_charge_point(self, charge_point_id, **kwargs):
                point = await super().get_charge_point(charge_point_id, **kwargs)
                point["state"] = "busy-non-charging"
                point["active_charge"] = {
                    "id": 889989849962903685,
                    "state": "paused",
                }
                point["details"].update({
                    "can_start": False,
                    "can_start_reason": "NOT_AVAILABLE",
                })
                return point

            async def get_active_charge(self, charge_point_id):
                self.calls.append(("active", str(charge_point_id)))
                return None

        app = OtherSessionApp()
        client = MontaOnIsClient(
            "user@example.com", "secret", app_client=app,
            charge_point_id=6440650, team_id=42,
        )

        data = (await client.get_online_data())[0]

        self.assertEqual(data["Connector"]["Status"]["Title"], "Busy (paused)")
        self.assertEqual(data["ChargingSession"], {})
        self.assertTrue(data["Monta"]["ActiveChargePresent"])
        self.assertFalse(data["Monta"]["ActiveChargeAccessible"])
        self.assertEqual(data["Monta"]["ActiveChargeSummaryState"], "paused")
        self.assertFalse(data["Monta"]["CanUnlock"])
        self.assertFalse(any(call[0] == "charge_detail" for call in app.calls))

        app.active = _charge("old-completed", "completed")
        second = (await client.get_online_data())[0]
        self.assertEqual(second["Connector"]["Status"]["Title"], "Busy (paused)")
        self.assertEqual(second["ChargingSession"], {})

        original_get_charge_point = app.get_charge_point

        async def charging_point(charge_point_id, **kwargs):
            point = await original_get_charge_point(charge_point_id, **kwargs)
            point["state"] = "busy-charging"
            point["active_charge"]["state"] = "charging"
            return point

        app.get_charge_point = charging_point
        third = (await client.get_online_data())[0]
        self.assertEqual(third["Connector"]["Status"]["Title"], "Charging")
        self.assertEqual(third["ChargingSession"], {})

    async def test_completed_charge_with_failed_at_is_reported_as_failed(self):
        class FailedAppClient(FakeAppClient):
            async def get_charge_point(self, charge_point_id, **kwargs):
                point = await super().get_charge_point(charge_point_id, **kwargs)
                point.update(
                    {
                        "state": "available",
                        "available": True,
                        "active": False,
                        "active_charge": None,
                    }
                )
                point["details"].update(
                    {
                        "can_start": False,
                        "can_start_reason": "PAYMENT_NOT_ALLOWED",
                    }
                )
                return point

            async def list_charge_sessions(self, **kwargs):
                return models.MontaPage(items=(self.active,))

        app = FailedAppClient()
        app.active = models.ChargeSession.from_payload(
            {
                "id": "889565977676363587",
                "state": "completed",
                "charge_point_info": {"id": 6440650},
                "starting_at": "2026-09-20T21:24:35Z",
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": "2026-09-20T21:24:37Z",
                "cpi_status": "Finishing",
                "user_actions": {"can_unlock": False},
                "error": {
                    "description": "Unfortunately, we couldn't charge your car."
                },
            }
        )
        client = MontaOnIsClient(
            "user@example.com",
            "secret",
            app_client=app,
            charge_point_id=6440650,
            team_id=42,
        )

        data = (await client.get_online_data())[0]

        self.assertEqual(data["Connector"]["Status"]["Title"], "Failed")
        self.assertEqual(data["ChargingSession"], {})
        self.assertEqual(data["Monta"]["ChargeState"], "failed")
        self.assertEqual(
            data["Monta"]["ErrorDescription"],
            "Unfortunately, we couldn't charge your car.",
        )
        self.assertEqual(data["LastSessionData"]["State"], "failed")
        self.assertIsNotNone(data["LastSessionData"]["FailedAt"])


if __name__ == "__main__":
    unittest.main()
