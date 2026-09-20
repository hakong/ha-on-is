"""Tests for reusable Monta API clients and normalized models."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).parents[1]
PACKAGE_PATH = ROOT / "custom_components" / "on_is"


def load_monta_modules():
    """Load Monta modules without importing Home Assistant-facing __init__.py."""
    sys.modules.setdefault(
        "aiohttp",
        types.SimpleNamespace(ClientResponse=object, ClientSession=object),
    )
    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = sys.modules.get("custom_components.on_is")
    if package is None:
        package = types.ModuleType("custom_components.on_is")
        package.__path__ = [str(PACKAGE_PATH)]
        sys.modules["custom_components.on_is"] = package

    return {
        name: importlib.import_module(f"custom_components.on_is.monta.{name}")
        for name in (
            "app",
            "base",
            "contracts",
            "deeplink",
            "errors",
            "hub",
            "models",
            "partner",
            "public",
            "redaction",
        )
    }


modules = load_monta_modules()
app = modules["app"]
base = modules["base"]
contracts = modules["contracts"]
deeplink = modules["deeplink"]
errors = modules["errors"]
hub = modules["hub"]
models = modules["models"]
partner = modules["partner"]
public = modules["public"]
redaction = modules["redaction"]


class FakeResponse:
    """Minimal aiohttp response context manager."""

    def __init__(self, status: int, payload=None, *, text: str = "", headers=None):
        self.status = status
        self.payload = payload
        self._text = text
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def text(self):
        return self._text


class FakeSession:
    """Queue responses and retain complete request details."""

    closed = False

    def __init__(self, *responses: FakeResponse):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self.responses.pop(0)


def token_payload(access="access-1", refresh="refresh-1"):
    return {
        "accessToken": access,
        "refreshToken": refresh,
        "accessTokenExpirationDate": "2099-01-01T00:00:00Z",
        "refreshTokenExpirationDate": "2099-02-01T00:00:00Z",
    }


def charge_payload(charge_id=88, state="charging"):
    return {
        "id": charge_id,
        "chargePointId": 6440650,
        "state": state,
        "startedAt": "2026-09-20T16:30:00Z",
        "consumedKwh": 1.25,
        "price": 27.76,
        "averagePricePerKwh": 22.21,
        "currency": {"identifier": "isk"},
    }


class MontaModelTests(unittest.TestCase):
    def test_token_parses_oauth_and_guest_shapes(self):
        oauth = models.MontaToken.from_payload(token_payload())
        guest = models.MontaToken.from_payload(
            {"token": {"access_token": "guest", "refresh_token": "refresh"}}
        )

        self.assertEqual(oauth.access_token, "access-1")
        self.assertEqual(oauth.access_token_expires_at.tzinfo, timezone.utc)
        self.assertEqual(guest.access_token, "guest")
        self.assertEqual(guest.refresh_token, "refresh")

    def test_token_parses_signed_in_app_expiry(self):
        token = models.MontaToken.from_payload(
            {
                "token": {
                    "access_token": "app-access",
                    "refresh_token": "app-refresh",
                    "expires_at": "2099-03-01T00:00:00Z",
                }
            }
        )

        self.assertEqual(token.access_token, "app-access")
        self.assertEqual(token.access_token_expires_at.tzinfo, timezone.utc)

    def test_page_preserves_zero_metadata_and_cursor(self):
        page = models.MontaPage.from_payload(
            {
                "data": [{"id": 1}],
                "meta": {"page": 0, "perPage": 10, "total": 0, "after": "next"},
            }
        )

        self.assertEqual(page.page, 0)
        self.assertEqual(page.total, 0)
        self.assertEqual(page.after, "next")
        self.assertEqual(page.items, ({"id": 1},))

        app_page = models.MontaPage.from_payload(
            {
                "data": [],
                "meta": {
                    "current_page": 2,
                    "last_page": 4,
                    "per_page": 15,
                    "total": 46,
                },
            }
        )
        self.assertEqual(app_page.page, 2)
        self.assertEqual(app_page.pages, 4)
        self.assertEqual(app_page.per_page, 15)

    def test_deeplink_snapshot_keeps_available_and_cable_separate(self):
        snapshot = models.ChargerSnapshot.from_deeplink(
            {
                "id": 6440650,
                "name": "ON 3806-1",
                "state": "available",
                "available": True,
                "active": True,
                "cable_plugged_in": True,
                "active_charge": None,
                "max_kw": 22,
                "currency": {"identifier": "isk"},
                "pricings": {
                    "user": {"master_pricing": {"type": "fixed_kwh", "amount": 22.21}}
                },
                "details": {
                    "last_meter_reading_kwh": 17.402,
                    "firmware_version": "6.3.3.3",
                    "can_start": False,
                    "can_start_reason": "NO_PAYMENT",
                },
            }
        )

        self.assertEqual(snapshot.state, "available")
        self.assertTrue(snapshot.available)
        self.assertTrue(snapshot.cable_plugged_in)
        self.assertEqual(snapshot.price_per_kwh, 22.21)
        self.assertEqual(snapshot.currency, "ISK")
        self.assertEqual(snapshot.meter_total_kwh, 17.402)
        self.assertFalse(snapshot.can_start)

    def test_deeplink_snapshot_ignores_nested_cable_value(self):
        unplugged = models.ChargerSnapshot.from_deeplink(
            {
                "id": 6443017,
                "state": "available",
                "cable_plugged_in": False,
                "details": {"cable_plugged_in": True},
            }
        )
        missing_top_level = models.ChargerSnapshot.from_deeplink(
            {
                "id": 6443017,
                "state": "available",
                "details": {"cable_plugged_in": True},
            }
        )

        self.assertFalse(unplugged.cable_plugged_in)
        self.assertIsNone(missing_top_level.cable_plugged_in)

    def test_hub_snapshot_normalizes_connector_values(self):
        snapshot = models.ChargerSnapshot.from_hub(
            {
                "id": 6440650,
                "name": "ON 3806-1",
                "status": "available",
                "connection": "connected",
                "max_kw": 22,
                "charging_station": {
                    "state": "connected",
                    "payload": {
                        "connectors": [
                            {
                                "vehicle_plugged": True,
                                "meter_wh": 17402,
                                "updated_at": "2026-09-20T16:09:00Z",
                                "connector_measurements": {"power_import": 7400},
                            }
                        ]
                    },
                },
                "charge_point_integration": {
                    "last_connected_at": "2026-09-20T16:08:00Z",
                    "firmware_version": "6.3.3.3",
                },
            }
        )

        self.assertTrue(snapshot.connected)
        self.assertTrue(snapshot.cable_plugged_in)
        self.assertEqual(snapshot.power_kw, 7.4)
        self.assertEqual(snapshot.meter_total_kwh, 17.402)

    def test_charge_and_telemetry_normalization(self):
        session = models.ChargeSession.from_payload(charge_payload())
        measurement = models.TelemetryMeasurement.from_payload(
            {
                "timestamp": "2026-09-20T16:31:00Z",
                "energyWattHour": 1250,
                "powerImport": 7400,
                "currentImport": 10.7,
                "voltage": 230,
                "soc": 54,
            }
        )

        self.assertTrue(session.is_active)
        self.assertEqual(session.currency, "ISK")
        self.assertEqual(measurement.energy_kwh, 1.25)
        self.assertEqual(measurement.power_kw, 7.4)

    def test_app_charge_normalizes_live_measurement_and_transitions(self):
        session = models.ChargeSession.from_payload(
            {
                "id": 889565977676087673,
                "state": "charging",
                "charge_point_info": {"id": 6440650},
                "paying_team": {"id": 42},
                "starting_at": "2026-09-20T17:37:36Z",
                "charging_at": "2026-09-20T17:37:48Z",
                "last_measurement": {
                    "date": "2026-09-20T17:41:48Z",
                    "kw_charge_point": 11.1,
                },
                "user_actions": {"can_unlock": True, "integration_id": 17386972},
                "can_stop": True,
                "cpi_status": "Charging",
            }
        )

        self.assertEqual(session.charge_point_id, "6440650")
        self.assertEqual(session.paying_team_id, "42")
        self.assertEqual(session.power_kw, 11.1)
        self.assertTrue(session.can_unlock)
        self.assertEqual(session.integration_id, "17386972")
        self.assertEqual(session.cpi_status, "Charging")

    def test_failed_start_overrides_completed_state(self):
        session = models.ChargeSession.from_payload(
            {
                "id": 889565977676363587,
                "state": "completed",
                "failed_at": "2026-09-20T21:24:37Z",
                "error": {
                    "description": "Unfortunately, we couldn't charge your car."
                },
            }
        )

        self.assertTrue(session.has_failed)
        self.assertFalse(session.is_active)
        self.assertEqual(session.normalized_state, "failed")

    def test_large_entity_ids_are_exposed_as_opaque_strings(self):
        exact_id = 889559095101176797
        rounded_private_id = 889559095101176800

        session = models.ChargeSession.from_payload(
            {"id": exact_id, "chargePointId": 6440650, "state": "charging"}
        )
        snapshot = models.ChargerSnapshot.from_deeplink(
            {
                "id": 6440650,
                "active_charge": {"id": rounded_private_id},
            }
        )

        self.assertEqual(session.id, "889559095101176797")
        self.assertEqual(session.charge_point_id, "6440650")
        self.assertEqual(snapshot.active_charge_id, "889559095101176800")

    def test_surface_capabilities_distinguish_supported_and_private_apis(self):
        self.assertEqual(
            contracts.PUBLIC_SURFACE.stability,
            contracts.MontaApiStability.DOCUMENTED,
        )
        self.assertTrue(
            contracts.HUB_SURFACE.supports(contracts.MontaCapability.LIVE_TELEMETRY)
        )
        self.assertFalse(
            contracts.PUBLIC_SURFACE.supports(
                contracts.MontaCapability.LIVE_TELEMETRY
            )
        )

    def test_diagnostics_redaction_handles_nested_tokens_and_urls(self):
        result = redaction.redact_monta_data(
            {
                "token": {"access_token": "secret-token"},
                "email": "person@example.com",
                "links": [
                    "https://on.monta.app/identity/recovery?flow=abc&token=secret&safe=yes"
                ],
                "state": "available",
            }
        )

        self.assertEqual(result["token"], "**REDACTED**")
        self.assertEqual(result["email"], "**REDACTED**")
        self.assertIn("token=%2A%2AREDACTED%2A%2A", result["links"][0])
        self.assertEqual(result["state"], "available")
        self.assertEqual(
            redaction.redact_monta_data(
                {"first_name": "Private", "pdf_url": "https://example.test/private"}
            ),
            {"first_name": "**REDACTED**", "pdf_url": "**REDACTED**"},
        )


class MontaTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_error_carries_retry_after(self):
        session = FakeSession(
            FakeResponse(
                429,
                {"message": "slow down", "errorCode": "RATE_LIMIT"},
                headers={"Retry-After": "12"},
            )
        )
        client = base.MontaHttpClient("https://example.test", session=session)

        with self.assertRaises(errors.MontaRateLimitError) as raised:
            await client._request("GET", "/resource")

        self.assertEqual(raised.exception.retry_after, 12)
        self.assertEqual(raised.exception.error_code, "RATE_LIMIT")

    async def test_oauth_refreshes_and_retries_one_unauthorized_request(self):
        session = FakeSession(
            FakeResponse(401, {"message": "expired"}),
            FakeResponse(200, token_payload("access-2", "refresh-2")),
            FakeResponse(200, {"data": []}),
        )
        client = public.MontaPublicClient("client", "secret", session=session)
        client.restore_token(models.MontaToken("access-1", "refresh-1"))

        result = await client.list_charge_points()

        self.assertEqual(result.items, ())
        self.assertEqual([request[1] for request in session.requests], [
            "https://public-api.monta.com/api/v1/charge-points",
            "https://public-api.monta.com/api/v1/auth/refresh",
            "https://public-api.monta.com/api/v1/charge-points",
        ])
        self.assertEqual(
            session.requests[-1][2]["headers"]["Authorization"], "Bearer access-2"
        )


class MontaAppClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_and_charger_snapshot_use_observed_app_contract(self):
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "id": 7,
                    "token": {
                        "access_token": "app-token",
                        "refresh_token": "app-refresh",
                        "expires_at": "2099-03-01T00:00:00Z",
                    },
                },
            ),
            FakeResponse(
                200,
                {
                    "id": 6440650,
                    "state": "available",
                    "available": True,
                    "cable_plugged_in": True,
                    "avg_kw": 13.58,
                    "integration": {
                        "id": 17386972,
                        "state": "connected",
                        "last_connected_at": "2026-09-20T18:00:00Z",
                    },
                },
            ),
        )
        context = app.MontaAppContext(request_uuid="stable-app-id")
        client = app.MontaAppClient(
            "person@example.com", "password", session=session, context=context
        )

        snapshot = await client.get_charger_snapshot(6440650)

        self.assertTrue(snapshot.connected)
        self.assertTrue(snapshot.cable_plugged_in)
        self.assertEqual(snapshot.average_kw, 13.58)
        self.assertIsNone(snapshot.power_kw)
        self.assertEqual(snapshot.integration_id, "17386972")
        self.assertEqual(
            session.requests[0][0:2],
            ("POST", "https://api.monta.app/api/v1/auth/login"),
        )
        self.assertEqual(
            session.requests[0][2]["json"],
            {"email": "person@example.com", "password": "password"},
        )
        self.assertEqual(session.requests[0][2]["headers"]["Uuid"], "stable-app-id")
        self.assertEqual(
            session.requests[1][2]["headers"]["Authorization"], "Bearer app-token"
        )

    async def test_team_discovery_payer_and_charge_controls(self):
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "data": [
                        {"id": "card-1", "type": "site", "data": {"charge_point_id": 6440650}},
                        {"id": "card-2", "type": "site", "data": {"charge_point_id": 6442130}},
                    ]
                },
            ),
            FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": 42,
                            "pre_select": False,
                            "payment": {
                                "title": "Your account",
                                "can_pay_charge_on_charge_point": True,
                            },
                        }
                    ]
                },
            ),
            FakeResponse(200, charge_payload(90, "starting")),
            FakeResponse(
                200,
                {
                    **charge_payload(90, "charging"),
                    "stopping_at": "2026-09-20T17:29:55Z",
                },
            ),
            FakeResponse(200, {"message": "accepted"}),
        )
        client = app.MontaAppClient("person@example.com", "password", session=session)
        client.restore_token(models.MontaToken("app-token"))

        charge_point_ids = await client.list_team_charge_point_ids(11)
        payer = await client.get_default_paying_team(6440650)
        started = await client.start_charge(6440650, payer.id)
        stopping = await client.stop_charge(started.id, 6440650)
        released = await client.release_cable(6440650, 17386972)

        self.assertEqual(charge_point_ids, ("6440650", "6442130"))
        self.assertEqual(payer.id, "42")
        self.assertEqual(started.state, "starting")
        self.assertIsNotNone(stopping.stopping_at)
        self.assertEqual(released, {"message": "accepted"})
        self.assertEqual(
            session.requests[2][0:2],
            ("POST", "https://api.monta.app/api/v1/charges/start"),
        )
        self.assertEqual(
            session.requests[2][2]["json"],
            {
                "amount_type": "full",
                "charge_point_id": "6440650",
                "include": "impact, receipt, error, charge_details, cost_pricing, charts",
                "mode": "instant",
                "paying_team_id": "42",
                "payment_method": "team",
            },
        )
        self.assertEqual(session.requests[3][2]["params"]["charge_point_id"], 6440650)
        self.assertEqual(
            session.requests[4][0:2],
            (
                "GET",
                "https://api.monta.app/api/v1/charge_points/6440650/integrations/17386972/unlock",
            ),
        )

    async def test_charge_settings_preserve_explicit_nulls(self):
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "mode": "instant",
                    "payment": "team",
                    "payment_id": 42,
                    "kwh_mode": "full",
                },
            )
        )
        client = app.MontaAppClient("person@example.com", "password", session=session)
        client.restore_token(models.MontaToken("app-token"))
        settings = app.MontaChargeSettings(payment_id=42, pickup_at="21:15")

        await client.update_charge_point_settings(6440650, settings)

        body = session.requests[0][2]["json"]
        self.assertEqual(body["payment_id"], 42)
        self.assertEqual(body["pickup_at"], "21:15")
        self.assertIn("vehicle_id", body)
        self.assertIsNone(body["vehicle_id"])


class MontaPublicClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_charge_points_authenticates_and_builds_query(self):
        session = FakeSession(
            FakeResponse(200, token_payload()),
            FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": 6440650,
                            "state": "available",
                            "cablePluggedIn": True,
                        }
                    ],
                    "meta": {"page": 0, "perPage": 25, "total": 1},
                },
            ),
        )
        client = public.MontaPublicClient("client", "secret", session=session)

        page = await client.list_charger_snapshots(page=0, per_page=25)

        self.assertEqual(page.items[0].id, "6440650")
        method, url, kwargs = session.requests[-1]
        self.assertEqual(
            (method, url),
            ("GET", "https://public-api.monta.com/api/v1/charge-points"),
        )
        self.assertEqual(kwargs["params"], {"page": 0, "perPage": 25})

    async def test_charge_filters_and_commands_use_public_contract(self):
        session = FakeSession(
            FakeResponse(200, token_payload()),
            FakeResponse(200, {"data": [charge_payload()]}),
            FakeResponse(200, charge_payload(89, "starting")),
            FakeResponse(200, charge_payload(89, "stopping")),
        )
        client = public.MontaPublicClient("client", "secret", session=session)

        sessions = await client.list_charge_sessions(
            charge_point_id=6440650, state="charging", per_page=20
        )
        started = await client.start_charge(6440650)
        stopped = await client.stop_charge(89)

        self.assertEqual(sessions.items[0].price, 27.76)
        self.assertEqual(started.state, "starting")
        self.assertEqual(stopped.state, "stopping")
        self.assertEqual(session.requests[2][0:2], (
            "POST", "https://public-api.monta.com/api/v1/charges"
        ))
        self.assertEqual(session.requests[2][2]["json"], {"chargePointId": 6440650})
        self.assertEqual(session.requests[3][0:2], (
            "POST", "https://public-api.monta.com/api/v1/charges/89/stop"
        ))

    async def test_consumption_period_is_validated_before_request(self):
        client = public.MontaPublicClient("client", "secret", session=FakeSession())
        with self.assertRaises(ValueError):
            await client.get_charge_kwh_consumption(1, period_seconds=60)


class MontaPartnerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_partner_start_requires_explicit_payer_and_builds_limits(self):
        session = FakeSession(
            FakeResponse(200, token_payload()),
            FakeResponse(200, charge_payload(90, "starting")),
        )
        client = partner.MontaPartnerClient("client", "secret", session=session)

        result = await client.start_charge(
            6440650,
            42,
            kwh_limit=25,
            soc_limit=80,
            price_group_id=12,
        )

        self.assertEqual(result.id, "90")
        method, url, kwargs = session.requests[-1]
        self.assertEqual((method, url), ("POST", "https://partner-api.monta.com/api/v1/charges"))
        self.assertEqual(
            kwargs["json"],
            {
                "payingTeamId": 42,
                "chargePointId": 6440650,
                "kwhLimit": 25,
                "socLimit": 80,
                "priceGroupId": 12,
            },
        )

    async def test_partner_stop_uses_documented_get_command(self):
        session = FakeSession(
            FakeResponse(200, token_payload()),
            FakeResponse(200, charge_payload(90, "stopping")),
        )
        client = partner.MontaPartnerClient("client", "secret", session=session)

        await client.stop_charge(90)

        self.assertEqual(session.requests[-1][0:2], (
            "GET", "https://partner-api.monta.com/api/v1/charges/90/stop"
        ))


class MontaDeeplinkClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_summary_does_not_create_guest(self):
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "type": "success",
                    "operator": {"identifier": "on", "application_identifier": "on"},
                    "data": {
                        "title": "ON 3806-1",
                        "badge": {"text": "Available"},
                        "kw": "22 kW",
                        "price_text": "22,21 ISK",
                        "charging_enabled": True,
                        "charge_with_link": "monta://charge_points/6440650",
                    },
                },
            )
        )
        client = deeplink.MontaDeeplinkClient(session=session)

        summary = await client.get_summary(6440650)

        self.assertEqual(summary.state_label, "Available")
        self.assertEqual(summary.price_per_kwh, 22.21)
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(
            session.requests[0][1],
            "https://deeplinks.monta.app/api/deeplink/cp6440650",
        )

    async def test_guest_bootstrap_and_rich_charger_read(self):
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "id": 99,
                    "token": {"access_token": "guest-token", "refresh_token": "guest-refresh"},
                },
            ),
            FakeResponse(
                200,
                {
                    "id": 6440650,
                    "state": "available",
                    "available": True,
                    "cable_plugged_in": True,
                    "details": {"can_start": False, "can_start_reason": "NO_PAYMENT"},
                },
            ),
        )
        context = deeplink.MontaGuestContext(
            guest_id="guest-id", request_uuid="request-id", os="linux", vendor="Linux"
        )
        client = deeplink.MontaDeeplinkClient(session=session, context=context)

        snapshot = await client.get_charger_snapshot(6440650)

        self.assertTrue(snapshot.cable_plugged_in)
        self.assertEqual(snapshot.can_start_reason, "NO_PAYMENT")
        self.assertEqual(
            session.requests[0][2]["json"],
            {
                "charge_point_id": 6440650,
                "guest_id": "guest-id",
                "os": "linux",
                "vendor": "Linux",
            },
        )
        self.assertEqual(
            session.requests[1][2]["headers"]["Authorization"], "Bearer guest-token"
        )
        self.assertEqual(session.requests[1][2]["headers"]["Guest_id"], "guest-id")

    async def test_paid_guest_start_requires_one_payment_reference(self):
        client = deeplink.MontaDeeplinkClient(session=FakeSession())

        with self.assertRaises(ValueError):
            await client.start_paid_charge(6440650)
        with self.assertRaises(ValueError):
            await client.start_paid_charge(
                6440650,
                stripe_payment_intent_id="pi_1",
                adyen_payment_reference="adyen_1",
            )


class MontaHubClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_compact_evse_request_uses_observed_shape(self):
        session = FakeSession(FakeResponse(200, {"data": []}))
        client = hub.MontaHubClient(session=session, access_token="hub-token")

        await client.get_charging_station_evses([6440650], size=10)

        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://hub.monta.app/api/gateway/api/v1/charging-station-evse")
        self.assertEqual(kwargs["params"], {"size": 10})
        self.assertEqual(kwargs["json"], {"filters": {"ids": ["6440650"]}})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer hub-token")

    async def test_hub_start_and_stop_keep_payer_and_force_explicit(self):
        session = FakeSession(FakeResponse(200, {"ok": True}), FakeResponse(200, {"ok": True}))
        client = hub.MontaHubClient(session=session)

        await client.start_charge(6440650, user_id=7, paying_team_id=42)
        await client.stop_charge(6440650)

        self.assertEqual(
            session.requests[0][2]["json"],
            {"userId": 7, "payingTeamId": 42},
        )
        self.assertEqual(session.requests[1][2]["params"], {"force": "false"})
        self.assertEqual(session.requests[1][2]["json"], {})


if __name__ == "__main__":
    unittest.main()
