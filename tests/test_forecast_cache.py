import unittest
from datetime import datetime, timezone


class ForecastCacheTimeTests(unittest.TestCase):
    def test_latest_lisbon_slot_uses_winter_midnight_and_noon(self):
        from forecast_cache import latest_lisbon_slot

        one_am_utc = datetime(2026, 1, 10, 1, 0, tzinfo=timezone.utc)
        slot = latest_lisbon_slot(one_am_utc)
        self.assertEqual(slot.isoformat(), "2026-01-10T00:00:00+00:00")

        afternoon_utc = datetime(2026, 1, 10, 13, 0, tzinfo=timezone.utc)
        slot = latest_lisbon_slot(afternoon_utc)
        self.assertEqual(slot.isoformat(), "2026-01-10T12:00:00+00:00")

    def test_latest_lisbon_slot_uses_summer_local_time(self):
        from forecast_cache import latest_lisbon_slot

        summer_midnight_lisbon = datetime(2026, 7, 9, 23, 30, tzinfo=timezone.utc)
        slot = latest_lisbon_slot(summer_midnight_lisbon)
        self.assertEqual(slot.isoformat(), "2026-07-10T00:00:00+01:00")

        summer_noon_lisbon = datetime(2026, 7, 10, 11, 30, tzinfo=timezone.utc)
        slot = latest_lisbon_slot(summer_noon_lisbon)
        self.assertEqual(slot.isoformat(), "2026-07-10T12:00:00+01:00")

    def test_is_stale_compares_against_latest_due_slot(self):
        from forecast_cache import is_stale, latest_lisbon_slot

        now_utc = datetime(2026, 5, 7, 12, 5, tzinfo=timezone.utc)
        current_slot = latest_lisbon_slot(now_utc)
        old_slot = datetime(2026, 5, 7, 0, 0, tzinfo=current_slot.tzinfo)

        self.assertTrue(is_stale(now_utc, {"last_success_slot_local": old_slot}))
        self.assertFalse(is_stale(now_utc, {"last_success_slot_local": current_slot}))
        self.assertTrue(is_stale(now_utc, {}))

    def test_refreshing_state_is_abandoned_after_timeout_window(self):
        from datetime import timedelta
        from forecast_cache import refresh_is_abandoned

        now_utc = datetime(2026, 5, 7, 12, 20, tzinfo=timezone.utc)

        self.assertTrue(
            refresh_is_abandoned(
                {
                    "status": "refreshing",
                    "last_started_at": now_utc - timedelta(minutes=11),
                },
                now_utc,
            )
        )
        self.assertFalse(
            refresh_is_abandoned(
                {
                    "status": "refreshing",
                    "last_started_at": now_utc - timedelta(minutes=2),
                },
                now_utc,
            )
        )
        self.assertFalse(refresh_is_abandoned({"status": "success"}, now_utc))


class ForecastCacheMappingTests(unittest.TestCase):
    def test_hourly_row_mapping_accepts_source_variants(self):
        from forecast_cache import hourly_db_row

        row = hourly_db_row(
            spot_id="carcavelos",
            source="surfline",
            run_id="00000000-0000-0000-0000-000000000001",
            row={
                "timestamp_utc": "2026-05-07T09:00:00+00:00",
                "wave_height": 1.23,
                "wave_period": 10.5,
                "wave_direction": 275,
                "swell_height": 1.1,
                "swell_period": 11,
                "swell_direction": 270,
                "wind_speed": 8.5,
                "wind_direction": 15,
                "wind_gusts": 14.0,
                "tide_height_m": 2.1,
                "air_temp": 21.5,
            },
        )

        self.assertEqual(row["spot_id"], "carcavelos")
        self.assertEqual(row["source"], "surfline")
        self.assertEqual(row["timestamp_utc"], "2026-05-07T09:00:00+00:00")
        self.assertEqual(row["wind_speed_kmh"], 8.5)
        self.assertEqual(row["wind_direction_deg"], 15)
        self.assertEqual(row["wind_gusts_kmh"], 14.0)
        self.assertEqual(row["air_temp_c"], 21.5)
        self.assertEqual(row["raw"]["wave_height"], 1.23)

    def test_source_hourly_rows_include_windguru_ecmwf(self):
        from forecast_cache import _source_hourly_rows

        rows = _source_hourly_rows(
            spot_id="carcavelos",
            run_id="00000000-0000-0000-0000-000000000001",
            sources={
                "windguru_ecmwf": {
                    "data": {
                        "hourly": [
                            {
                                "timestamp_utc": "2026-05-07T09:00:00+00:00",
                                "wave_height": 1.2,
                                "wave_period": 11,
                                "wind_speed_kmh": 8,
                            }
                        ]
                    }
                }
            },
            payload={},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "windguru_ecmwf")
        self.assertEqual(rows[0]["wave_height"], 1.2)


class ForecastCacheWriteTests(unittest.TestCase):
    def test_replace_source_rows_streams_copy_inserts(self):
        import forecast_cache

        class FakeCopy:
            def __init__(self):
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def write_row(self, row):
                self.rows.append(row)

        class FakeCursor:
            def __init__(self):
                self.executes = []
                self.copy_calls = []

            def execute(self, sql, params=None):
                self.executes.append((sql, params))

            def copy(self, sql):
                copy = FakeCopy()
                self.copy_calls.append((sql, copy))
                return copy

        original_rows = forecast_cache._source_hourly_rows
        original_jsonb = forecast_cache.db.jsonb
        forecast_cache._source_hourly_rows = lambda *_args, **_kwargs: [
            {
                "spot_id": "carcavelos",
                "source": "om",
                "raw": {"n": 1},
                "timestamp_utc": "2026-05-07T09:00:00+00:00",
            },
            {
                "spot_id": "carcavelos",
                "source": "om",
                "raw": {"n": 2},
                "timestamp_utc": "2026-05-07T10:00:00+00:00",
            },
        ]
        forecast_cache.db.jsonb = lambda value: value
        try:
            cur = FakeCursor()
            forecast_cache._replace_source_rows(cur, "carcavelos", "run-1", {}, {})
        finally:
            forecast_cache._source_hourly_rows = original_rows
            forecast_cache.db.jsonb = original_jsonb

        self.assertEqual(len(cur.executes), 1)
        self.assertEqual(len(cur.copy_calls), 1)
        self.assertEqual(len(cur.copy_calls[0][1].rows), 2)

    def test_replace_window_rows_streams_copy_inserts(self):
        import forecast_cache

        class FakeCopy:
            def __init__(self):
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def write_row(self, row):
                self.rows.append(row)

        class FakeCursor:
            def __init__(self):
                self.executes = []
                self.copy_calls = []

            def execute(self, sql, params=None):
                self.executes.append((sql, params))

            def copy(self, sql):
                copy = FakeCopy()
                self.copy_calls.append((sql, copy))
                return copy

        original_rows = forecast_cache._window_rows
        original_jsonb = forecast_cache.db.jsonb
        forecast_cache._window_rows = lambda *_args, **_kwargs: [
            {
                "spot_id": "carcavelos",
                "level": "improver",
                "window_type": "top_windows",
                "payload": {"rank": 1},
                "rank": 1,
            },
            {
                "spot_id": "carcavelos",
                "level": "improver",
                "window_type": "top_windows",
                "payload": {"rank": 2},
                "rank": 2,
            },
        ]
        forecast_cache.db.jsonb = lambda value: value
        try:
            cur = FakeCursor()
            forecast_cache._replace_window_rows(cur, "carcavelos", "improver", "run-1", {})
        finally:
            forecast_cache._window_rows = original_rows
            forecast_cache.db.jsonb = original_jsonb

        self.assertEqual(len(cur.executes), 1)
        self.assertEqual(len(cur.copy_calls), 1)
        self.assertEqual(len(cur.copy_calls[0][1].rows), 2)

    def test_replace_source_snapshots_streams_copy_inserts(self):
        import forecast_cache

        class FakeCopy:
            def __init__(self):
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def write_row(self, row):
                self.rows.append(row)

        class FakeCursor:
            def __init__(self):
                self.executes = []
                self.copy_calls = []

            def execute(self, sql, params=None):
                self.executes.append((sql, params))

            def copy(self, sql):
                copy = FakeCopy()
                self.copy_calls.append((sql, copy))
                return copy

        original_rows = forecast_cache._source_snapshot_rows
        original_jsonb = forecast_cache.db.jsonb
        forecast_cache._source_snapshot_rows = lambda *_args, **_kwargs: [
            {
                "spot_id": "carcavelos",
                "source": "om",
                "current_payload": {"ok": True},
                "analysis_payload": {"score": 1},
            },
            {
                "spot_id": "carcavelos",
                "source": "gfs",
                "current_payload": {"ok": True},
                "analysis_payload": {"score": 2},
            },
        ]
        forecast_cache.db.jsonb = lambda value: value
        try:
            cur = FakeCursor()
            forecast_cache._replace_source_snapshots(cur, "carcavelos", "run-1", {}, {})
        finally:
            forecast_cache._source_snapshot_rows = original_rows
            forecast_cache.db.jsonb = original_jsonb

        self.assertEqual(len(cur.executes), 1)
        self.assertEqual(len(cur.copy_calls), 1)
        self.assertEqual(len(cur.copy_calls[0][1].rows), 2)


class ForecastCacheReadTests(unittest.TestCase):
    def test_empty_snapshot_error_shape_is_explicit(self):
        from forecast_cache import empty_cache_payload

        payload = empty_cache_payload("carcavelos", "improver")
        self.assertEqual(payload["code"], "forecast_cache_empty")
        self.assertIn("scripts/db_backfill.py", payload["error"])
        self.assertEqual(payload["spot_id"], "carcavelos")
        self.assertEqual(payload["level"], "improver")

    def test_refresh_diagnostics_expose_safe_state_without_traceback(self):
        from forecast_cache import refresh_diagnostics

        now_utc = datetime(2026, 5, 7, 13, 5, tzinfo=timezone.utc)
        state = {
            "status": "failed",
            "last_success_at": datetime(2026, 5, 7, 0, 10, tzinfo=timezone.utc),
            "last_success_slot_local": datetime(2026, 5, 6, 23, 0, tzinfo=timezone.utc),
            "last_started_at": datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
            "last_error": {
                "type": "RuntimeError",
                "message": "surfline fetch timed out",
                "traceback": "secret internals",
            },
        }

        diagnostics = refresh_diagnostics(state, now_utc)

        self.assertEqual(diagnostics["refresh_status"], "failed")
        self.assertTrue(diagnostics["refresh_stale"])
        self.assertEqual(
            diagnostics["refresh_last_success_at"],
            "2026-05-07T00:10:00+00:00",
        )
        self.assertEqual(
            diagnostics["refresh_last_success_slot_local"],
            "2026-05-07T00:00:00+01:00",
        )
        self.assertEqual(
            diagnostics["refresh_last_started_at"],
            "2026-05-07T12:00:00+00:00",
        )
        self.assertEqual(
            diagnostics["refresh_last_error"],
            {"type": "RuntimeError", "message": "surfline fetch timed out"},
        )

    def test_read_cached_payload_includes_refresh_diagnostics(self):
        import forecast_cache

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchone(self):
                return {
                    "payload": {"spot_id": "carcavelos", "unified": {}},
                    "updated_at": datetime(2026, 5, 7, 12, 20, tzinfo=timezone.utc),
                }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class FakeConn:
            def cursor(self):
                return FakeCursor()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        original_connect = forecast_cache.db.connect
        original_state = forecast_cache.get_refresh_state
        forecast_cache.db.connect = lambda: FakeConn()
        forecast_cache.get_refresh_state = lambda _conn: {
            "status": "success",
            "last_success_at": datetime(2026, 5, 7, 12, 10, tzinfo=timezone.utc),
            "last_success_slot_local": datetime(2026, 5, 7, 11, 0, tzinfo=timezone.utc),
            "last_started_at": datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
            "last_error": None,
        }
        try:
            payload = forecast_cache.read_cached_payload("carcavelos", "improver")
        finally:
            forecast_cache.db.connect = original_connect
            forecast_cache.get_refresh_state = original_state

        self.assertEqual(payload["refresh_status"], "success")
        self.assertIn("refresh_last_success_at", payload)
        self.assertIn("refresh_last_success_slot_local", payload)
        self.assertIn("refresh_last_started_at", payload)
        self.assertIn("refresh_stale", payload)
        self.assertEqual(payload["cache_status"], payload["refresh_status"])
        self.assertEqual(payload["cache_stale"], payload["refresh_stale"])

    def test_sanitizes_legacy_missing_tide_window_payload(self):
        from forecast_cache import sanitize_cached_payload

        window = {
            "window_practical": {
                "indicators": [{"id": "wave_fit"}, {"id": "tide"}],
            },
            "window_technical": {
                "aggregate": {
                    "values": {"height_m": 1.2},
                    "factor_scores": {"height": 0.8, "tide": 1.0},
                },
                "indicators": [{"id": "wave_fit"}, {"id": "tide"}],
                "hours": [
                    {
                        "values": {"height_m": 1.2},
                        "factor_scores": {"height": 0.8, "tide": 1.0},
                    }
                ],
            },
            "score_components": [
                {
                    "tide": None,
                    "factor_scores": {
                        "om": {"height": 0.8, "tide": 1.0},
                        "tide": 1.0,
                    },
                }
            ],
        }
        payload = {"unified": {"predictor_windows": [window]}}

        sanitize_cached_payload(payload)

        self.assertEqual(
            [item["id"] for item in window["window_practical"]["indicators"]],
            ["wave_fit"],
        )
        self.assertEqual(
            [item["id"] for item in window["window_technical"]["indicators"]],
            ["wave_fit"],
        )
        self.assertNotIn("tide", window["window_technical"]["aggregate"]["factor_scores"])
        self.assertNotIn("tide", window["window_technical"]["hours"][0]["factor_scores"])
        self.assertIsNone(window["score_components"][0]["factor_scores"]["tide"])
        self.assertNotIn("tide", window["score_components"][0]["factor_scores"]["om"])


if __name__ == "__main__":
    unittest.main()
