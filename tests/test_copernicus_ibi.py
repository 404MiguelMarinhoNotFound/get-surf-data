import os
import unittest
from datetime import datetime, timezone

import copernicus_ibi
import copernicus_ibi_explainer


class ExtractValueTests(unittest.TestCase):
    def test_parses_geojson_response(self):
        # Copernicus WMTS GFI returns a FeatureCollection with `value` in properties.
        body = '{"type":"FeatureCollection","features":[{"properties":{"lat":38.7,"lon":-9.3,"value":1.42,"units":"m"}}]}'
        self.assertAlmostEqual(copernicus_ibi._extract_value(body), 1.42)

    def test_parses_geojson_null_value_returns_none(self):
        body = '{"features":[{"properties":{"lat":38.7,"lon":-9.3,"value":null}}]}'
        self.assertIsNone(copernicus_ibi._extract_value(body))

    def test_parses_value_payload(self):
        body = '{"value": 2.7}'
        self.assertAlmostEqual(copernicus_ibi._extract_value(body), 2.7)

    def test_falls_back_to_regex(self):
        body = "<Result><Value>1.85</Value></Result>"
        self.assertAlmostEqual(copernicus_ibi._extract_value(body), 1.85)

    def test_treats_9999_as_no_data(self):
        body = '{"features":[{"properties":{"value":9999.0}}]}'
        self.assertIsNone(copernicus_ibi._extract_value(body))

    def test_returns_none_for_empty(self):
        self.assertIsNone(copernicus_ibi._extract_value(""))


class AuthHeaderTests(unittest.TestCase):
    def test_returns_none_when_creds_missing(self):
        old_user = os.environ.pop("COPERNICUS_USER", None)
        old_pass = os.environ.pop("COPERNICUS_PASS", None)
        try:
            self.assertIsNone(copernicus_ibi._auth_header())
        finally:
            if old_user is not None:
                os.environ["COPERNICUS_USER"] = old_user
            if old_pass is not None:
                os.environ["COPERNICUS_PASS"] = old_pass

    def test_builds_basic_auth_when_creds_present(self):
        os.environ["COPERNICUS_USER"] = "alice"
        os.environ["COPERNICUS_PASS"] = "wonder"
        try:
            h = copernicus_ibi._auth_header()
            self.assertIn("Authorization", h)
            self.assertTrue(h["Authorization"].startswith("Basic "))
        finally:
            del os.environ["COPERNICUS_USER"]
            del os.environ["COPERNICUS_PASS"]


class FetchSoftFailureTests(unittest.TestCase):
    def test_fetch_returns_none_when_creds_missing(self):
        old_user = os.environ.pop("COPERNICUS_USER", None)
        old_pass = os.environ.pop("COPERNICUS_PASS", None)
        try:
            self.assertIsNone(copernicus_ibi.fetch(38.7, -9.3))
        finally:
            if old_user is not None:
                os.environ["COPERNICUS_USER"] = old_user
            if old_pass is not None:
                os.environ["COPERNICUS_PASS"] = old_pass

    def test_fetch_returns_hourly_rows_when_layers_are_available(self):
        original_auth = copernicus_ibi._auth_header
        original_fetch = copernicus_ibi._fetch_layers_for_time
        calls = []

        def fake_fetch(_lat, _lon, when_iso, _headers):
            calls.append(when_iso)
            return {
                "wave_height": 1.0,
                "wave_peak_period": 12.0,
                "wave_direction": 260.0,
                "swell_height": 0.9,
                "swell_period": 12.0,
                "swell_direction": 260.0,
                "wind_wave_height": 0.1,
            }

        try:
            copernicus_ibi._auth_header = lambda: {"Authorization": "Basic test"}
            copernicus_ibi._fetch_layers_for_time = fake_fetch
            out = copernicus_ibi.fetch(
                38.7,
                -9.3,
                when=datetime(2026, 5, 1, 6, tzinfo=timezone.utc),
                days=0.125,
            )
        finally:
            copernicus_ibi._auth_header = original_auth
            copernicus_ibi._fetch_layers_for_time = original_fetch

        self.assertIsNotNone(out)
        self.assertEqual(len(out["hourly"]), 3)
        self.assertEqual(out["hourly"][0]["timestamp_utc"], "2026-05-01T06:00:00.000Z")
        self.assertEqual(out["hourly"][0]["wave_period"], 12.0)
        self.assertIsNone(out["hourly"][0]["wind_speed"])
        self.assertEqual(len(calls), 3)

    def test_layer_fetch_uses_one_shared_join_deadline(self):
        original_layers = copernicus_ibi._LAYERS
        original_thread = copernicus_ibi.threading.Thread
        original_timeout = copernicus_ibi._TIMEOUT_S
        original_monotonic = copernicus_ibi.time.monotonic
        join_timeouts = []
        clock = {"now": 100.0}

        class FakeThread:
            def __init__(self, target, args):
                self.target = target
                self.args = args

            def start(self):
                return None

            def join(self, timeout=None):
                join_timeouts.append(timeout)
                clock["now"] += timeout or 0

        try:
            copernicus_ibi._LAYERS = {"a": "A", "b": "B", "c": "C"}
            copernicus_ibi.threading.Thread = FakeThread
            copernicus_ibi._TIMEOUT_S = 12
            copernicus_ibi.time.monotonic = lambda: clock["now"]

            copernicus_ibi._fetch_layers_for_time(38.7, -9.3, "2026-05-08T12:00:00Z", {})

            self.assertEqual(len(join_timeouts), 3)
            self.assertLessEqual(sum(join_timeouts), 14.5)
        finally:
            copernicus_ibi._LAYERS = original_layers
            copernicus_ibi.threading.Thread = original_thread
            copernicus_ibi._TIMEOUT_S = original_timeout
            copernicus_ibi.time.monotonic = original_monotonic


class ExplainerTests(unittest.TestCase):
    def test_interpret_all_handles_typical_payload(self):
        current = {
            "timestamp_utc":     "2026-04-29T10:00:00Z",
            "wave_height":       1.2,
            "wave_period":       11.0,
            "swell_height":      1.0,
            "swell_period":      11.0,
            "swell_direction":   265.0,
            "wind_wave_height":  0.2,
        }
        out = copernicus_ibi_explainer.interpret_all(
            current=current,
            optimal_bearing=260,
            offshore_bearing=10,
            optimal_label="W-SW",
            level="improver",
        )
        self.assertIn("ibi_verdict", out)
        self.assertIn("ibi_details", out)
        # Verdict text uses the IBI label, not the OM one.
        self.assertNotIn("Open-Meteo", out["ibi_verdict_text"] or "")


if __name__ == "__main__":
    unittest.main()
