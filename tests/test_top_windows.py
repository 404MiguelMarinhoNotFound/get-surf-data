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
    def test_returns_at_most_ten(self):
        sf, om = _build_week("2026-05-01", days=7, sf_rating=6)
        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        self.assertIsInstance(out["top_windows"], list)
        self.assertLessEqual(len(out["top_windows"]), 10)

    def test_top_windows_can_include_multiple_fixed_blocks_same_halfday(self):
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 6),
            _sf_cell("2026-05-01T09:00:00+00:00", 6),
            _sf_cell("2026-05-01T12:00:00+00:00", 6),
        ]
        om = [_om_hour(f"2026-05-01T{h:02d}:00:00+00:00") for h in range(4, 13)]

        out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T03:00:00+00:00")
        starts = [window["starts_at"] for window in out["top_windows"]]

        self.assertIn("2026-05-01T07:00:00+00:00", starts)  # local 08:00
        self.assertIn("2026-05-01T10:00:00+00:00", starts)  # local 11:00

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

    def test_top_windows_are_fixed_three_hour_blocks(self):
        sf, om = _build_week("2026-05-01", days=2, sf_rating=6)
        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")

        self.assertGreater(len(out["top_windows"]), 0)
        for window in out["top_windows"]:
            start = datetime.fromisoformat(window["starts_at"])
            end = datetime.fromisoformat(window["ends_at"])
            self.assertEqual((end - start).total_seconds() / 3600, 3)

    def test_top_windows_are_subset_of_predictor_windows_by_start_time(self):
        sf, om = _build_week("2026-05-01", days=3, sf_rating=6)
        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")

        predictor_starts = {window["starts_at"] for window in out["predictor_windows"]}
        for window in out["top_windows"]:
            self.assertIn(window["starts_at"], predictor_starts)

    def test_top_windows_rank_by_window_score_not_each_hour_threshold(self):
        scored = []
        for hour, score in ((7, 4.8), (8, 8.0), (9, 8.0), (10, 5.4), (11, 5.4), (12, 5.4)):
            scored.append({
                "dt": datetime.fromisoformat(f"2026-05-01T{hour:02d}:00:00+00:00"),
                "decider_score": score,
                "tier": unified.TIER_GREEN,
                "has_hard_gate": False,
                "window_eligible": True,
                "blocked_by": [],
                "step_hours": 1,
            })

        blocks = unified._top_windows(scored, unified._hour_is_decent, datetime.fromisoformat("2026-05-01T05:00:00+00:00"), SPOT)

        self.assertEqual(blocks[0][0]["dt"].isoformat(), "2026-05-01T07:00:00+00:00")

    def test_top_windows_follow_visible_window_score_with_source_gate_context(self):
        scored = []
        for hour, score, source in (
            (7, 6.0, "gfs_shape"),
            (8, 6.1, None),
            (9, 6.2, None),
            (10, 5.4, None),
            (11, 5.4, None),
            (12, 5.4, None),
        ):
            scored.append({
                "dt": datetime.fromisoformat(f"2026-05-01T{hour:02d}:00:00+00:00"),
                "decider_score": score,
                "tier": unified.TIER_RED if source else unified.TIER_GREEN,
                "has_hard_gate": bool(source),
                "hard_gate": {"blocked": bool(source), "reason": "shape", "source": source},
                "window_eligible": True,
                "blocked_by": [source] if source else [],
                "step_hours": 1,
            })

        blocks = unified._top_windows(scored, unified._hour_is_decent, datetime.fromisoformat("2026-05-01T05:00:00+00:00"), SPOT)

        self.assertEqual(blocks[0][0]["dt"].isoformat(), "2026-05-01T07:00:00+00:00")


class PredictorWindowsTests(unittest.TestCase):
    def test_predictor_includes_low_scores_when_top_windows_are_empty(self):
        sf = [
            _sf_cell("2026-05-01T04:00:00+00:00", 1),
        ]

        out = unified.find_next_windows(sf, [], SPOT, "2026-05-01T03:00:00+00:00")

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
        self.assertLessEqual(len(out["top_windows"]), 10)

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

    def test_windows_include_practical_payload(self):
        sf, om = _build_week("2026-05-01", days=1, sf_rating=6)

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        window = out["predictor_windows"][0]
        practical = window["window_practical"]

        self.assertIsNone(practical["unavailable_reason"])
        self.assertIn("summary", practical)
        self.assertEqual(
            [indicator["id"] for indicator in practical["indicators"]],
            ["wave_fit", "energy", "wind", "shape", "direction", "tide"],
        )

    def test_practical_payload_has_no_source_breakdown(self):
        sf, om = _build_week("2026-05-01", days=1, sf_rating=6)

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        practical = out["predictor_windows"][0]["window_practical"]
        forbidden_keys = {
            "sf", "surfline", "windguru", "om", "gfs", "ibi",
            "sf_score", "surfline_score", "windguru_score", "om_score",
            "gfs_score", "ibi_score", "source_scores", "factor_scores",
        }

        def walk_keys(value):
            if isinstance(value, dict):
                for key, nested in value.items():
                    yield key
                    yield from walk_keys(nested)
            elif isinstance(value, list):
                for item in value:
                    yield from walk_keys(item)

        self.assertTrue(forbidden_keys.isdisjoint(set(walk_keys(practical))))

    def test_practical_payload_marks_unavailable_without_factor_data(self):
        block = [{
            "dt": datetime.fromisoformat("2026-05-01T07:00:00+00:00"),
            "decider_score": 6.5,
            "tier": unified.TIER_GREEN,
            "confidence": "high",
            "confidence_detail": {"source_count": 1, "source_score_spread": 0.0, "missing_sources": []},
            "blocked_by": [],
            "step_hours": 1,
        }]

        window = unified._window_payload(
            block,
            datetime.fromisoformat("2026-05-01T05:00:00+00:00"),
            SPOT,
            level="improver",
        )

        self.assertEqual(window["window_practical"]["unavailable_reason"], "no_weighted_factor_scores")
        self.assertEqual(window["window_practical"]["indicators"], [])

    def test_practical_indicators_use_weighted_model_factors(self):
        block = [{
            "dt": datetime.fromisoformat("2026-05-01T07:00:00+00:00"),
            "decider_score": 6.5,
            "tier": unified.TIER_GREEN,
            "confidence": "high",
            "confidence_detail": {"source_count": 2, "source_score_spread": 0.0, "missing_sources": []},
            "factor_scores": {
                "om": {"height": 1.0, "power": 1.0, "period": 1.0, "wind": 1.0, "chop": 1.0, "direction": 1.0},
                "gfs": {"height": 0.0, "power": 0.0, "period": 0.0, "wind": 0.0, "chop": 0.0, "direction": 0.0},
                "tide": 1.0,
            },
            "weights": {"om": 0.75, "gfs": 0.25},
            "blocked_by": [],
            "step_hours": 1,
        }]

        window = unified._window_payload(
            block,
            datetime.fromisoformat("2026-05-01T05:00:00+00:00"),
            SPOT,
            level="improver",
        )
        indicators = {item["id"]: item for item in window["window_practical"]["indicators"]}

        self.assertAlmostEqual(indicators["wave_fit"]["score_0_1"], 0.75)
        self.assertEqual(indicators["wave_fit"]["status"], "Good fit")
        self.assertAlmostEqual(indicators["energy"]["score_0_1"], 0.75)

    def test_windows_include_selected_window_technical_payload(self):
        sf, om = _build_week("2026-05-01", days=1, sf_rating=6)

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        windows = [out["best_window"], *out["top_windows"], *out["predictor_windows"]]

        for window in [item for item in windows if item]:
            technical = window["window_technical"]
            self.assertEqual(technical["version"], "selected_window_technical_v1")
            self.assertIsNone(technical["unavailable_reason"])
            self.assertIsInstance(technical["aggregate"], dict)
            self.assertGreater(len(technical["hours"]), 0)
            self.assertIn("score_components", window)
            self.assertIn("window_practical", window)

    def test_technical_payload_has_validation_indicators(self):
        sf, om = _build_week("2026-05-01", days=1, sf_rating=6)

        out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
        technical = out["predictor_windows"][0]["window_technical"]

        self.assertEqual(
            [indicator["label"] for indicator in technical["indicators"]],
            ["Wave fit", "Energy", "Wind", "Shape", "Direction", "Tide"],
        )
        for indicator in technical["indicators"]:
            self.assertIn("factor_score_0_1", indicator)
            self.assertIn("fields", indicator)
            self.assertGreater(len(indicator["fields"]), 0)
            self.assertNotIn("explanation", indicator)

    def test_technical_payload_uses_weighted_raw_values(self):
        block = [{
            "dt": datetime.fromisoformat("2026-05-01T07:00:00+00:00"),
            "decider_score": 6.5,
            "tier": unified.TIER_GREEN,
            "confidence": "high",
            "confidence_detail": {"source_count": 2, "source_score_spread": 0.0, "missing_sources": []},
            "om_row": {
                "wave_height": 2.0,
                "wave_period": 10.0,
                "swell_height": 2.0,
                "swell_period": 10.0,
                "swell_direction": 260.0,
                "wind_speed": 8.0,
                "wind_direction": 10.0,
                "wind_wave_height": 0.10,
            },
            "gfs_row": {
                "wave_height": 1.0,
                "wave_period": 14.0,
                "swell_height": 1.0,
                "swell_period": 14.0,
                "swell_direction": 220.0,
                "wind_speed": 20.0,
                "wind_direction": 190.0,
                "wind_wave_height": 0.50,
            },
            "factor_scores": {
                "om": {"height": 1.0, "power": 1.0, "period": 1.0, "wind": 1.0, "chop": 1.0, "direction": 1.0},
                "gfs": {"height": 0.0, "power": 0.0, "period": 0.0, "wind": 0.0, "chop": 0.0, "direction": 0.0},
                "tide": 1.0,
            },
            "weights": {"om": 0.75, "gfs": 0.25},
            "tide": {"color": "green", "state": "rising", "height_m": 1.2},
            "blocked_by": [],
            "step_hours": 1,
        }]

        window = unified._window_payload(
            block,
            datetime.fromisoformat("2026-05-01T05:00:00+00:00"),
            SPOT,
            level="improver",
        )
        values = window["window_technical"]["aggregate"]["values"]
        self.assertAlmostEqual(values["height_m"], 1.75)
        self.assertAlmostEqual(values["period_s"], 11.0)
        self.assertAlmostEqual(values["wind_speed_kmh"], 11.0)

        block[0]["weights"] = {"om": 0.25, "gfs": 0.75}
        reweighted = unified._window_payload(
            block,
            datetime.fromisoformat("2026-05-01T05:00:00+00:00"),
            SPOT,
            level="improver",
        )
        reweighted_values = reweighted["window_technical"]["aggregate"]["values"]
        self.assertAlmostEqual(reweighted_values["height_m"], 1.25)
        self.assertAlmostEqual(reweighted_values["period_s"], 13.0)
        self.assertAlmostEqual(reweighted_values["wind_speed_kmh"], 17.0)

    def test_technical_payload_marks_unavailable_without_raw_or_factor_data(self):
        block = [{
            "dt": datetime.fromisoformat("2026-05-01T07:00:00+00:00"),
            "decider_score": 6.5,
            "tier": unified.TIER_GREEN,
            "confidence": "high",
            "confidence_detail": {"source_count": 1, "source_score_spread": 0.0, "missing_sources": []},
            "blocked_by": [],
            "step_hours": 1,
        }]

        window = unified._window_payload(
            block,
            datetime.fromisoformat("2026-05-01T05:00:00+00:00"),
            SPOT,
            level="improver",
        )

        self.assertEqual(
            window["window_technical"]["unavailable_reason"],
            "no_selected_window_technical_data",
        )
        self.assertIsNone(window["window_technical"]["aggregate"])
        self.assertEqual(window["window_technical"]["indicators"], [])
        self.assertEqual(window["window_technical"]["hours"], [])

    def test_predictor_carries_ibi_scores_when_hourly_rows_exist(self):
        sf, om = _build_week("2026-05-01", days=1, sf_rating=6)
        ibi_hourly = [
            {
                **_om_hour(f"2026-05-01T{hour:02d}:00:00+00:00"),
                "wind_speed": None,
                "wind_direction": None,
            }
            for hour in range(6, 21)
        ]

        out = unified.find_next_windows(
            sf,
            om,
            SPOT,
            "2026-04-30T23:00:00+00:00",
            ibi_hourly=ibi_hourly,
        )
        components = out["predictor_windows"][0]["score_components"]

        self.assertTrue(any(component["ibi_score"] is not None for component in components))
        self.assertNotIn("ibi", out["predictor_windows"][0]["confidence_detail"]["missing_sources"])


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
        # A complete fixed 3-hour block is needed to form a top window.
        sf = [
            _sf_cell("2026-05-01T06:00:00+00:00", 5),
            _sf_cell("2026-05-01T09:00:00+00:00", 5),
        ]
        om = [
            self._good_om_hour("2026-05-01T07:00:00+00:00"),
            self._good_om_hour("2026-05-01T08:00:00+00:00"),
            self._good_om_hour("2026-05-01T09:00:00+00:00"),
        ]
        # Surfline rows with empty/missing fields — _score_model_row returns None.
        surfline_hourly = [
            {"timestamp_utc": "2026-05-01T07:00:00+00:00"},
            {"timestamp_utc": "2026-05-01T08:00:00+00:00"},
            {"timestamp_utc": "2026-05-01T09:00:00+00:00"},
        ]

        out = unified.find_next_windows(
            sf, om, SPOT, "2026-05-01T05:00:00+00:00",
            surfline_hourly=surfline_hourly,
        )
        self.assertGreater(len(out["top_windows"]), 0,
                           "Window should not be vetoed by Surfline rows with no score")


if __name__ == "__main__":
    unittest.main()
