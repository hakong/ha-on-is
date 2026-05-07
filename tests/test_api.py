"""Tests for the ON API client."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


def load_api_module():
    """Load api.py without importing the Home Assistant integration package."""
    aiohttp_stub = types.SimpleNamespace(ClientResponse=object, ClientSession=object)
    sys.modules.setdefault("aiohttp", aiohttp_stub)

    path = Path(__file__).parents[1] / "custom_components" / "on_is" / "api.py"
    spec = importlib.util.spec_from_file_location("on_is_api", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = load_api_module()
OnIsApiError = api.OnIsApiError
OnIsAuthError = api.OnIsAuthError
OnIsClient = api.OnIsClient


class FakeResponse:
    """Minimal async response object for API client tests."""

    def __init__(self, status: int, payload: dict | None = None, text: str = "") -> None:
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class FakeSession:
    """Capture requests made by the client."""

    closed = False

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.last_json = None
        self.last_headers = None

    def post(self, _url, **kwargs):
        self.last_json = kwargs.get("json")
        self.last_headers = kwargs.get("headers")
        return self.response


class OnIsClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_parse_online_data_returns_current_sessions(self):
        client = OnIsClient("user@example.com", "secret", session=object())
        response = FakeResponse(200, {"CurrentSessions": [{"Connector": {"Id": 1}}]})

        self.assertEqual(await client._parse_online_data(response), [{"Connector": {"Id": 1}}])

    async def test_parse_online_data_raises_for_non_success_response(self):
        client = OnIsClient("user@example.com", "secret", session=object())
        response = FakeResponse(500, text="server unavailable")

        with self.assertRaisesRegex(OnIsApiError, "server unavailable"):
            await client._parse_online_data(response)

    async def test_parse_online_data_raises_auth_error_for_unauthorized_response(self):
        client = OnIsClient("user@example.com", "secret", session=object())
        response = FakeResponse(401, text="expired token")

        with self.assertRaises(OnIsAuthError):
            await client._parse_online_data(response)

    async def test_start_charging_sends_expected_payload(self):
        session = FakeSession(FakeResponse(200, {"IsSuccessful": True}))
        client = OnIsClient("user@example.com", "secret", session=session)
        client._access_token = "token"

        self.assertTrue(await client.start_charging("IS*ONP001-1-1", 7))
        self.assertEqual(
            session.last_json,
            {
                "EvseCode": "IS*ONP001-1-1",
                "ConnectorId": 7,
                "EnableLimits": False,
                "SocLimits": False,
            },
        )
        self.assertEqual(session.last_headers["Authorization"], "Bearer token")

    async def test_start_charging_raises_when_api_rejects_command(self):
        session = FakeSession(FakeResponse(200, {"IsSuccessful": False, "ErrorDescription": "busy"}))
        client = OnIsClient("user@example.com", "secret", session=session)
        client._access_token = "token"

        with self.assertRaisesRegex(OnIsApiError, "busy"):
            await client.start_charging("IS*ONP001-1-1", 7)


if __name__ == "__main__":
    unittest.main()
