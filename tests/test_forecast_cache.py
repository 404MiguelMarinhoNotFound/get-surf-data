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


class ForecastCacheReadTests(unittest.TestCase):
    def test_empty_snapshot_error_shape_is_explicit(self):
        from forecast_cache import empty_cache_payload

        payload = empty_cache_payload("carcavelos", "improver")
        self.assertEqual(payload["code"], "forecast_cache_empty")
        self.assertIn("scripts/db_backfill.py", payload["error"])
        self.assertEqual(payload["spot_id"], "carcavelos")
        self.assertEqual(payload["level"], "improver")


if __name__ == "__main__":
    unittest.main()
