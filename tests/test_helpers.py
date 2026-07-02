"""Tests for small ON data helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def load_helpers_module():
    """Load helpers.py without importing the Home Assistant integration package."""
    path = Path(__file__).parents[1] / "custom_components" / "on_is" / "helpers.py"
    spec = importlib.util.spec_from_file_location("on_is_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = load_helpers_module()
apply_cached_last_communication = helpers.apply_cached_last_communication
evse_codes_match = helpers.evse_codes_match
extract_evse_code = helpers.extract_evse_code
format_minutes = helpers.format_minutes
LAST_COMMUNICATION_TIME = helpers.LAST_COMMUNICATION_TIME
LAST_COMMUNICATION_TIME_CACHED = helpers.LAST_COMMUNICATION_TIME_CACHED


class HelperTests(unittest.TestCase):
    def test_extract_evse_code_prefers_connector_evse_code(self):
        session = {"Connector": {"EvseCode": "IS*ONP001-1-1"}}

        self.assertEqual(extract_evse_code(session), "IS*ONP001-1-1")

    def test_extract_evse_code_builds_code_from_parts(self):
        session = {
            "ChargePoint": {"FriendlyCode": "IS*ONP001"},
            "Evse": {"FriendlyCode": "2"},
            "Connector": {"Code": "1"},
        }

        self.assertEqual(extract_evse_code(session), "IS*ONP001-2-1")

    def test_extract_evse_code_returns_unknown_for_missing_parts(self):
        self.assertEqual(extract_evse_code({"Connector": {}}), "unknown")

    def test_evse_codes_match_ignores_whitespace_and_case(self):
        self.assertTrue(evse_codes_match(" is*onp001-1-1 ", "IS*ONP001-1-1"))

    def test_format_minutes(self):
        self.assertEqual(format_minutes(12), "12m")
        self.assertEqual(format_minutes(80), "1h 20m")

    def test_apply_cached_last_communication_stores_current_timestamp(self):
        cache = {}
        session = {LAST_COMMUNICATION_TIME: "2026-07-02T09:13:02Z"}

        apply_cached_last_communication(3806, session, cache)

        self.assertEqual(cache[3806], "2026-07-02T09:13:02Z")
        self.assertFalse(session[LAST_COMMUNICATION_TIME_CACHED])

    def test_apply_cached_last_communication_restores_missing_timestamp(self):
        cache = {3806: "2026-07-02T09:13:02Z"}
        session = {}

        apply_cached_last_communication(3806, session, cache)

        self.assertEqual(session[LAST_COMMUNICATION_TIME], "2026-07-02T09:13:02Z")
        self.assertTrue(session[LAST_COMMUNICATION_TIME_CACHED])

    def test_apply_cached_last_communication_marks_missing_without_cache(self):
        session = {}

        apply_cached_last_communication(3806, session, {})

        self.assertFalse(session[LAST_COMMUNICATION_TIME_CACHED])
        self.assertNotIn(LAST_COMMUNICATION_TIME, session)


if __name__ == "__main__":
    unittest.main()
