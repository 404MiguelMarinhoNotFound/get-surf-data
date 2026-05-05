import unittest
from unittest.mock import patch

import surfline


class SurflineParserTests(unittest.TestCase):
    def test_parse_payloads_extracts_current_report_and_forecast_fields(self):
        report = {
            "associated": {
                "href": "https://www.surfline.com/surf-report/example",
                "advertising": {"conditionsBasedAdUnits": {"pub_meta_9": "POOR TO FAIR"}},
            },
            "data": {
                "conditions": {
                    "waterTemp": {"min": 16, "max": 17},
                    "waveHeight": {"min": 0.3, "max": 0.6, "humanRelation": "Knee to thigh"},
                    "weather": {"temperature": 15},
                    "wetsuit": {"thickness": "3/2mm", "type": "Fullsuit"},
                    "wind": {"speed": 9, "direction": 321, "directionType": "Cross-shore", "gust": 12},
                }
            },
        }
        wave = {
            "associated": {"runInitializationTimestamp": 1777788000},
            "data": {
                "wave": [{
                    "timestamp": 1777795200,
                    "surf": {"min": 0.4, "max": 0.7, "humanRelation": "Thigh to waist", "optimalScore": 2},
                    "power": 130,
                    "swells": [
                        {"height": 0.9, "period": 10, "direction": 244, "directionMin": 235, "power": 130, "impact": 1},
                        {"height": 0.4, "period": 8, "direction": 260, "directionMin": 255, "power": 20, "impact": 0.5},
                        {"height": 0.2, "period": 14, "direction": 310, "directionMin": 300, "power": 10, "impact": 0.2},
                    ],
                }]
            },
        }
        wind = {"data": {"wind": [{"timestamp": 1777795200, "speed": 9, "direction": 321, "directionType": "Cross-shore", "gust": 12}]}}
        tide = {"data": {"tides": [{"timestamp": 1777795200, "height": 1.7}]}}
        weather = {"data": {"weather": [{"timestamp": 1777795200, "temperature": 15.5}]}}

        parsed = surfline.parse_payloads(report, wave, wind, tide, weather)
        current = parsed["current"]

        self.assertEqual(current["condition_rating"], "POOR TO FAIR")
        self.assertEqual(current["surf_height_min_m"], 0.4)
        self.assertEqual(current["surf_height_max_m"], 0.7)
        self.assertEqual(current["primary_swell_height_m"], 0.9)
        self.assertEqual(current["secondary_swell_period_s"], 8.0)
        self.assertEqual(current["tertiary_swell_direction_deg"], 310.0)
        self.assertAlmostEqual(current["wind_speed_kmh"], 16.67, places=2)
        self.assertEqual(current["wind_state"], "cross-shore")
        self.assertEqual(current["tide_height_m"], 1.7)
        self.assertEqual(current["air_temp_c"], 15.5)
        self.assertEqual(current["water_temp_c"], 17.0)
        self.assertEqual(current["wetsuit_hint"], "3/2mm Fullsuit")
        self.assertEqual(len(parsed["hourly"]), 1)
        hourly = parsed["hourly"][0]
        self.assertEqual(hourly["timestamp_utc"], "2026-05-03T08:00:00+00:00")
        self.assertEqual(hourly["swell_period"], 10.0)
        self.assertEqual(hourly["swell_direction"], 244.0)
        self.assertAlmostEqual(hourly["wind_speed"], 16.67, places=2)
        self.assertEqual(hourly["surfline_optimal_score"], 2)

    def test_get_json_uses_browser_like_headers(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"ok": true}'

        captured = {}

        def fake_urlopen(req, timeout):
            captured["headers"] = dict(req.header_items())
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(surfline._get_json("https://example.test"), {"ok": True})

        self.assertIn("User-agent", captured["headers"])
        self.assertIn("Accept", captured["headers"])
        self.assertIn("Origin", captured["headers"])
        self.assertIn("Referer", captured["headers"])


class SurflineTierAndAttributionTests(unittest.TestCase):
    def _make_report_with_condition(self, value):
        return {"condition": {"value": value}, "data": {}, "associated": {}}

    def _make_report_with_optimal_score(self, score):
        return {"data": {}, "associated": {}}

    def _make_wave_with_score(self, score):
        return {"data": {"wave": [{"timestamp": 1777795200, "surf": {"optimalScore": score}, "swells": []}]}}

    def test_optimal_score_4_yields_fair_to_good(self):
        wave = self._make_wave_with_score(4)
        report = self._make_report_with_optimal_score(4)
        rating = surfline._condition_rating(report, {"surf": {"optimalScore": 4}})
        self.assertEqual(rating, "FAIR TO GOOD")

    def test_optimal_score_5_yields_good_not_epic(self):
        rating = surfline._condition_rating({}, {"surf": {"optimalScore": 5}})
        self.assertEqual(rating, "GOOD")

    def test_condition_value_epic_survives_untouched(self):
        report = self._make_report_with_condition("EPIC")
        rating = surfline._condition_rating(report)
        self.assertEqual(rating, "EPIC")

    def test_condition_value_good_is_forecaster(self):
        source = surfline._rating_source(
            self._make_report_with_condition("GOOD"), "GOOD"
        )
        self.assertEqual(source, "forecaster")

    def test_condition_value_epic_is_forecaster(self):
        source = surfline._rating_source(
            self._make_report_with_condition("EPIC"), "EPIC"
        )
        self.assertEqual(source, "forecaster")

    def test_optimal_score_fallback_is_model(self):
        source = surfline._rating_source({}, "FAIR TO GOOD")
        self.assertEqual(source, "model")

    def test_condition_value_fair_without_attribution_is_model(self):
        report = self._make_report_with_condition("FAIR")
        source = surfline._rating_source(report, "FAIR")
        self.assertEqual(source, "model")

    def test_surfline_rating_source_in_normalized_current(self):
        report = {"condition": {"value": "GOOD"}, "data": {}, "associated": {}}
        wave = {"associated": {}, "data": {"wave": []}}
        wind = {"data": {"wind": []}}
        tide = {"data": {"tides": []}}
        weather = {"data": {"weather": []}}
        parsed = surfline.parse_payloads(report, wave, wind, tide, weather)
        self.assertEqual(parsed["current"].get("condition_rating"), "GOOD")
        self.assertEqual(parsed["current"].get("surfline_rating_source"), "forecaster")

    def test_surfline_rating_source_model_for_poor_to_fair(self):
        report = {"condition": {"value": "POOR_TO_FAIR"}, "data": {}, "associated": {}}
        wave = {"associated": {}, "data": {"wave": []}}
        wind = {"data": {"wind": []}}
        tide = {"data": {"tides": []}}
        weather = {"data": {"weather": []}}
        parsed = surfline.parse_payloads(report, wave, wind, tide, weather)
        self.assertEqual(parsed["current"].get("surfline_rating_source"), "model")


if __name__ == "__main__":
    unittest.main()
