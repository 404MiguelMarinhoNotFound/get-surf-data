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


def _build_week(start_date_iso, days=7, sf_rating=6):
    """Synthesise SF (3-hourly) + OM (hourly) streams across `days` days from 06:00 to 21:00."""
    from datetime import date as _date, timedelta
    base = _date.fromisoformat(start_date_iso)
    sf = []
    om = []
    for day in range(days):
        d = base + timedelta(days=day)
        for h in (6, 9, 12, 15, 18):
            sf.append(_sf_cell(f"{d.isoformat()}T{h:02d}:00:00+00:00", sf_rating))
        for h in range(6, 22):
            om.append(_om_hour(f"{d.isoformat()}T{h:02d}:00:00+00:00"))
    return sf, om


class TopWindowsTests(unittest.TestCase):
    def test_returns_at_most_five(self):
        sf, om = _build_week("2026-05-01", days=7, sf_rating=6)
        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        self.assertIsInstance(out["top_windows"], list)
        self.assertLessEqual(len(out["top_windows"]), 5)

    def test_one_per_halfday_bucket(self):
        # Same morning has overlapping candidate blocks; only one should appear.
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 6),
            _sf_cell("2026-05-01T09:00:00+00:00", 6),
            _sf_cell("2026-05-01T12:00:00+00:00", 6),
        ]
        om = [_om_hour(f"2026-05-01T{h:02d}:00:00+00:00") for h in range(6, 13)]

        out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T05:00:00+00:00")
        windows = out["top_windows"]
        self.assertGreaterEqual(len(windows), 1)
        # All starts on the morning of 2026-05-01 should collapse to one bucket.
        morning_count = sum(
            1 for w in windows if w["starts_at"].startswith("2026-05-01T") and
            int(w["starts_at"][11:13]) < 12  # UTC hour < 12 => Lisbon AM (DST +1)
        )
        self.assertLessEqual(morning_count, 1)

    def test_sorted_by_score_desc(self):
        sf, om = _build_week("2026-05-01", days=7, sf_rating=6)
        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        scores = [w["score"] for w in out["top_windows"] if w.get("score") is not None]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_when_no_decent_hours(self):
        sf = [_sf_cell("2026-05-01T06:00:00+00:00", 0)]
        om = [_om_hour("2026-05-01T06:00:00+00:00", wind_speed=40.0, wind_direction=180.0)]
        out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T05:00:00+00:00")
        self.assertEqual(out["top_windows"], [])
        self.assertIsNone(out["best_window"])

    def test_best_window_alias_matches_top_windows_zero(self):
        sf, om = _build_week("2026-05-01", days=2, sf_rating=6)
        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        if out["top_windows"]:
            self.assertEqual(out["best_window"], out["top_windows"][0])
            self.assertEqual(out["next_decent_window"], out["top_windows"][0])
        else:
            self.assertIsNone(out["best_window"])


class PredictorWindowsTests(unittest.TestCase):
    def test_predictor_includes_low_scores_when_top_windows_are_empty(self):
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 1),
            _sf_cell("2026-05-01T09:00:00+00:00", 1),
        ]

        out = unified.find_next_windows(sf, [], SPOT, "2026-05-01T05:00:00+00:00")

        self.assertEqual(out["top_windows"], [])
        self.assertGreater(len(out["predictor_windows"]), 0)
        self.assertTrue(
            any(window.get("score") is not None and window["score"] < 5.0
                for window in out["predictor_windows"])
        )

    def test_predictor_is_chronological_and_not_capped_at_five(self):
        sf, om = _build_week("2026-05-01", days=2, sf_rating=6)

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        starts = [window["starts_at"] for window in out["predictor_windows"]]

        self.assertGreater(len(out["predictor_windows"]), 5)
        self.assertEqual(starts, sorted(starts))
        self.assertLessEqual(len(out["top_windows"]), 5)

    def test_predictor_uses_fixed_non_overlapping_three_hour_blocks(self):
        om = [
            _om_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
            for hour in range(4, 19)
        ]

        out = unified.find_next_windows([], om, SPOT, "2026-05-01T03:00:00+00:00")
        labels = [window["label"] for window in out["predictor_windows"]]

        self.assertEqual(labels, [
            "Today 05:00-08:00",
            "Today 08:00-11:00",
            "Today 11:00-14:00",
            "Today 14:00-17:00",
            "Today 17:00-20:00",
        ])

    def test_predictor_carries_score_components_for_detail_drawer(self):
        sf, om = _build_week("2026-05-01", days=1, sf_rating=6)

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        window = out["predictor_windows"][0]

        self.assertGreater(len(window["score_components"]), 0)
        self.assertIn("sf_score", window["score_components"][0])
        self.assertIn("om_score", window["score_components"][0])


class RequireSfTimelineTests(unittest.TestCase):
    """SF timeline only covers ~3 days; hours beyond it must not be blocked."""

    def _good_om_hour(self, ts):
        return {
            "timestamp_utc": ts,
            "wave_height": 1.4,
            "wave_period": 13.0,
            "swell_height": 1.3,
            "swell_period": 13.0,
            "swell_direction": 260.0,
            "wind_wave_height": 0.05,
            "wind_speed": 7.0,
            "wind_direction": 10.0,
        }

    def test_post_sf_timeline_hours_appear_in_windows(self):
        # SF cells: day 1-3 only (24 cells at 3h intervals)
        sf = []
        for day in range(3):
            from datetime import date, timedelta
            d = date(2026, 5, 1) + timedelta(days=day)
            for h in (6, 9, 12, 15, 18, 21):
                sf.append(_sf_cell(f"{d.isoformat()}T{h:02d}:00:00+00:00", 4))

        # OM data only for day 6 (well past SF timeline)
        om = [self._good_om_hour(f"2026-05-07T{h:02d}:00:00+00:00") for h in range(6, 20)]

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        starts = [w["starts_at"] for w in out["top_windows"]]
        has_day6 = any(s.startswith("2026-05-07") for s in starts)
        self.assertTrue(has_day6, f"Expected a May-7 window past SF timeline, got: {starts}")

    def test_supplementary_source_gap_does_not_veto_window(self):
        # SF + OM both say good; Surfline rows have no wave data (score will be None).
        # Two consecutive good hours are needed to form a window (min_hours=2).
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 5),
            _sf_cell("2026-05-01T09:00:00+00:00", 5),
        ]
        om = [
            self._good_om_hour("2026-05-01T07:00:00+00:00"),
            self._good_om_hour("2026-05-01T08:00:00+00:00"),
        ]
        # Surfline rows with empty/missing fields — _score_model_row returns None.
        surfline_hourly = [
            {"timestamp_utc": "2026-05-01T07:00:00+00:00"},
            {"timestamp_utc": "2026-05-01T08:00:00+00:00"},
        ]

        out = unified.find_next_windows(
            sf, om, SPOT, "2026-05-01T05:00:00+00:00",
            surfline_hourly=surfline_hourly,
        )
        self.assertGreater(len(out["top_windows"]), 0,
                           "Window should not be vetoed by Surfline rows with no score")


if __name__ == "__main__":
    unittest.main()
