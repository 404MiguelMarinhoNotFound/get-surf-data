import unittest
from datetime import datetime, timezone

import unified_explainer as unified


SPOT = {
    "tz": "Europe/Lisbon",
    "offshore_bearing": 10,
    "optimal_swell_bearing": 260,
    "tide_window": "mid-to-high",
}


def _sf_cell(ts, rating):
    dt = datetime.fromisoformat(ts)
    return {
        "day": dt.strftime("%a %d"),
        "time": dt.strftime("%I%p").lstrip("0"),
        "rating": rating,
        "timestamp_utc": ts,
    }


def _om_hour(ts, wind_speed=6.0, wind_direction=10.0):
    return {
        "timestamp_utc": ts,
        "wave_height": 0.9,
        "wave_period": 12.0,
        "swell_height": 0.9,
        "swell_period": 12.0,
        "swell_direction": 260.0,
        "wind_wave_height": 0.02,
        "wind_speed": wind_speed,
        "wind_direction": wind_direction,
    }


class UnifiedWindowScoringTests(unittest.TestCase):
    def test_sf_rating_two_passes_when_model_strongly_corroborates(self):
        # Under doctrine V2 SF gold-star awareness (CLAUDE.md 2026-05): a low SF
        # cell no longer hard-vetoes a window when OM strongly disagrees. The
        # gate now needs SF<=2 AND non-gold AND OM<5.5 — clean offshore swell
        # here makes OM>=5.5 so the window is allowed through.
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 2),
            _sf_cell("2026-05-01T09:00:00+00:00", 2),
        ]
        om = [
            _om_hour("2026-05-01T06:00:00+00:00"),
            _om_hour("2026-05-01T07:00:00+00:00"),
            _om_hour("2026-05-01T08:00:00+00:00"),
            _om_hour("2026-05-01T09:00:00+00:00"),
        ]

        out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T05:30:00+00:00")

        self.assertIsNotNone(out["best_window"])

    def test_sf_rating_two_still_gates_when_model_also_weak(self):
        # Companion to the test above: flat swell + bad wind drives OM<5.5,
        # so the softened gate still fires and the window is suppressed.
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 2),
            _sf_cell("2026-05-01T09:00:00+00:00", 2),
        ]
        flat = lambda ts: {
            "timestamp_utc": ts,
            "wave_height": 0.15,
            "wave_period": 5.0,
            "swell_height": 0.15,
            "swell_period": 5.0,
            "swell_direction": 260.0,
            "wind_wave_height": 0.1,
            "wind_speed": 25.0,
            "wind_direction": 190.0,
        }
        om = [
            flat("2026-05-01T06:00:00+00:00"),
            flat("2026-05-01T07:00:00+00:00"),
            flat("2026-05-01T08:00:00+00:00"),
            flat("2026-05-01T09:00:00+00:00"),
        ]

        out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T05:30:00+00:00")

        self.assertIsNone(out["best_window"])

    def test_corrected_carcavelos_evening_zero_ratings_hide_hero_window(self):
        sf = [
            _sf_cell("2026-04-29T18:00:00+00:00", 0),
            _sf_cell("2026-04-29T21:00:00+00:00", 0),
        ]
        om = [
            _om_hour("2026-04-29T18:00:00+00:00", wind_speed=14.9, wind_direction=250.0),
            _om_hour("2026-04-29T19:00:00+00:00", wind_speed=13.0, wind_direction=251.0),
            _om_hour("2026-04-29T20:00:00+00:00", wind_speed=10.1, wind_direction=253.0),
            _om_hour("2026-04-29T21:00:00+00:00", wind_speed=8.0, wind_direction=252.0),
            _om_hour("2026-04-29T22:00:00+00:00", wind_speed=7.6, wind_direction=251.0),
        ]

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-29T17:37:00+00:00")

        self.assertIsNone(out["best_window"])

    def test_sf_timeline_gap_does_not_create_om_only_hero_window(self):
        sf = [
            _sf_cell("2026-04-29T09:00:00+00:00", 1),
            _sf_cell("2026-04-29T12:00:00+00:00", 0),
            _sf_cell("2026-04-29T15:00:00+00:00", 0),
        ]
        om = [
            _om_hour("2026-04-29T18:00:00+00:00"),
            _om_hour("2026-04-29T19:00:00+00:00"),
            _om_hour("2026-04-29T20:00:00+00:00"),
            _om_hour("2026-04-29T21:00:00+00:00"),
        ]

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-29T17:30:00+00:00")

        self.assertIsNone(out["best_window"])

    def test_short_sf_timeline_suppresses_later_model_windows(self):
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 6),
            _sf_cell("2026-05-01T09:00:00+00:00", 6),
        ]
        om = [
            _om_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(18, 22)
        ]

        out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T05:00:00+00:00")

        self.assertIsNone(out["best_window"])
        self.assertEqual(out["top_windows"], [])

    def test_model_only_windows_appear_when_no_sf_timeline_exists(self):
        om = [
            _om_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(7, 12)
        ]

        out = unified.find_next_windows([], om, SPOT, "2026-05-01T05:00:00+00:00")

        self.assertIsNotNone(out["best_window"])
        self.assertGreaterEqual(len(out["top_windows"]), 1)

    def test_red_tide_blocks_otherwise_good_future_window(self):
        sf = [
            _sf_cell("2026-04-29T18:00:00+00:00", 6),
            _sf_cell("2026-04-29T21:00:00+00:00", 6),
        ]
        om = [
            _om_hour("2026-04-29T18:00:00+00:00"),
            _om_hour("2026-04-29T19:00:00+00:00"),
            _om_hour("2026-04-29T20:00:00+00:00"),
        ]
        tide = {
            "events": [
                {"type": "high", "time": "2026-04-29T13:00:00+00:00", "height_m": 2.6},
                {"type": "low", "time": "2026-04-29T19:00:00+00:00", "height_m": 0.3},
                {"type": "high", "time": "2026-04-30T01:00:00+00:00", "height_m": 2.7},
            ]
        }

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-29T18:30:00+00:00", tide=tide)

        self.assertIsNone(out["best_window"])
        self.assertEqual(out["now_tier"], "red")

    def test_long_good_run_uses_fixed_three_hour_window(self):
        sf = [
            _sf_cell("2026-05-01T08:00:00+00:00", 6),
            _sf_cell("2026-05-01T11:00:00+00:00", 6),
            _sf_cell("2026-05-01T14:00:00+00:00", 6),
            _sf_cell("2026-05-01T17:00:00+00:00", 6),
        ]
        om = [
            _om_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(4, 19)
        ]

        out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T03:00:00+00:00")
        window = out["best_window"]
        start = datetime.fromisoformat(window["starts_at"])
        end = datetime.fromisoformat(window["ends_at"])

        self.assertEqual((end - start).total_seconds() / 3600, 3)
        self.assertRegex(window["label"], r"(Today|Tomorrow|Fri) \d{2}:00-\d{2}:00")

    def test_overnight_label_uses_24h_clock_and_end_day(self):
        label = unified._label_window(
            datetime(2026, 5, 1, 16, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc),
            SPOT,
        )

        self.assertEqual(label, "Tomorrow 17:00-Sat 10:00")


if __name__ == "__main__":
    unittest.main()
