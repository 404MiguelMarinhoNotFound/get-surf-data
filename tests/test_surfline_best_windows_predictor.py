import unittest
import json

import unified_explainer as unified


SPOT = {
    "tz": "Europe/Lisbon",
    "offshore_bearing": 10,
    "optimal_swell_bearing": 260,
    "tide_window": "any",
}


def _clean_hour(ts):
    return {
        "timestamp_utc": ts,
        "wave_height": 1.0,
        "wave_period": 12.0,
        "swell_height": 1.0,
        "swell_period": 12.0,
        "swell_direction": 260.0,
        "wind_wave_height": 0.02,
        "wind_speed_kmh": 6.0,
        "wind_direction_deg": 10.0,
    }


def _rca_trace(name, sources, predictor):
    payload = {
        "case": name,
        "data_sources_say": sources,
        "predictor_says": {
            "sources_used": predictor.get("sources_used"),
            "source_scores": predictor.get("source_scores"),
            "weights": predictor.get("weights"),
            "decision": predictor.get("decision"),
            "tier": predictor.get("tier"),
            "score": predictor.get("score"),
            "best_window": predictor.get("best_window"),
            "top_windows": predictor.get("top_windows"),
        },
    }
    print("\nRCA_TRACE " + json.dumps(payload, indent=2, sort_keys=True))


def _window_rca_trace(name, sources, windows):
    payload = {
        "case": name,
        "data_sources_say": sources,
        "predictor_says": {
            "best_window": windows.get("best_window"),
            "top_windows": windows.get("top_windows"),
            "next_gold_window": windows.get("next_gold_window"),
            "gold_count_7d": windows.get("gold_count_7d"),
            "now_tier": windows.get("now_tier"),
        },
    }
    print("\nRCA_TRACE " + json.dumps(payload, indent=2, sort_keys=True))


class SurflineBestWindowPredictorTests(unittest.TestCase):
    def test_surfline_hourly_alone_populates_best_window(self):
        surfline_hourly = [
            _clean_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(7, 12)
        ]

        out = unified.find_next_windows(
            rating_timeline=[],
            om_hourly=[],
            spot=SPOT,
            sf_now_utc="2026-05-01T07:00:00+00:00",
            surfline_hourly=surfline_hourly,
        )

        _window_rca_trace(
            "surfline_only_best_window",
            {
                "surfline_hourly": surfline_hourly,
                "surf_forecast_rating_timeline": [],
                "open_meteo_hourly": [],
            },
            out,
        )

        self.assertIsNotNone(out["best_window"])
        self.assertEqual(out["best_window"], out["top_windows"][0])
        self.assertEqual(out["best_window"]["confidence"], "surfline_only")
        self.assertGreater(len(out["best_window"]["score_components"]), 0)
        self.assertTrue(
            all(c["surfline_score"] is not None for c in out["best_window"]["score_components"])
        )
        self.assertTrue(
            all(c["om_score"] is None for c in out["best_window"]["score_components"])
        )

    def test_surfline_is_blended_into_best_window_components_with_om(self):
        surfline_hourly = [
            _clean_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(7, 12)
        ]
        om_hourly = [
            _clean_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(7, 12)
        ]

        out = unified.find_next_windows(
            rating_timeline=[],
            om_hourly=om_hourly,
            spot=SPOT,
            sf_now_utc="2026-05-01T07:00:00+00:00",
            surfline_hourly=surfline_hourly,
        )

        _window_rca_trace(
            "surfline_and_om_blended_best_window",
            {
                "surfline_hourly": surfline_hourly,
                "open_meteo_hourly": om_hourly,
                "surf_forecast_rating_timeline": [],
            },
            out,
        )

        components = out["best_window"]["score_components"]
        self.assertIsNotNone(out["best_window"])
        self.assertTrue(any(c["surfline_score"] is not None for c in components))
        self.assertTrue(any(c["om_score"] is not None for c in components))
        self.assertIn("surfline", components[0]["factor_scores"])
        self.assertGreaterEqual(components[0]["confidence_detail"]["source_count"], 2)

    def test_unify_exposes_surfline_source_score_and_best_window_component(self):
        sf_data = {
            "rating": 6,
            "verdict": "go",
            "details": [],
            "rating_timeline": [],
            "now_utc": "2026-05-01T07:00:00+00:00",
            "fetched_at": "2026-05-01T07:00:00+00:00",
            "tide": None,
            "height_m": 1.0,
            "period_s": 12,
        }
        surfline_analysis = _clean_hour("2026-05-01T07:00:00+00:00")
        surfline_hourly = [
            _clean_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(7, 12)
        ]
        om_analysis = _clean_hour("2026-05-01T07:00:00+00:00")
        om_hourly = [
            _clean_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(7, 12)
        ]

        out = unified.unify(
            sf_data=sf_data,
            om_analysis=om_analysis,
            om_hourly=om_hourly,
            spot=SPOT,
            level="improver",
            surfline_analysis=surfline_analysis,
            surfline_hourly=surfline_hourly,
        )

        _rca_trace(
            "unified_predictor_with_surfline_best_window",
            {
                "surf_forecast_current": sf_data,
                "surfline_current": surfline_analysis,
                "surfline_hourly": surfline_hourly,
                "open_meteo_current": om_analysis,
                "open_meteo_hourly": om_hourly,
            },
            out,
        )

        self.assertIn("surfline", out["sources_used"])
        self.assertIsNotNone(out["source_scores"]["surfline"])
        self.assertIsNotNone(out["best_window"])
        self.assertTrue(
            any(
                component["surfline_score"] is not None
                for component in out["best_window"]["score_components"]
            )
        )


if __name__ == "__main__":
    unittest.main()
