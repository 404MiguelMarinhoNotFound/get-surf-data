import os
import time
import unittest

import forecast_sync


def _sf_payload():
    return {
        "url": "https://example.test/sf",
        "fetched_at": "2026-05-08T06:00:00+00:00",
        "now_utc": "2026-05-08T06:00:00+00:00",
        "height_m": 1.0,
        "period_s": 10,
        "swell_direction": "W",
        "wind_state": "offshore",
        "wind_speed_kmh": 8,
        "rating": 5,
        "details": [],
        "rating_timeline": [],
        "tide": None,
    }


def _model_hour(ts):
    return {
        "timestamp_utc": ts,
        "wave_height": 1.0,
        "wave_period": 10,
        "swell_height": 0.9,
        "swell_period": 10,
        "swell_direction": 260,
        "wind_wave_height": 0.1,
        "wind_speed_kmh": 8,
        "wind_direction_deg": 20,
    }


class BuildPayloadHealthRowsTests(unittest.TestCase):
    def test_build_payload_exposes_open_meteo_and_gfs_hourly_rows(self):
        om_hourly = [_model_hour("2026-05-08T06:00:00+00:00")]
        gfs_hourly = [_model_hour("2026-05-08T07:00:00+00:00")]
        spot = {
            "id": "carcavelos",
            "name": "Carcavelos",
            "url": "https://example.test/sf",
            "lat": 38.68,
            "lon": -9.34,
            "offshore_bearing": 10,
            "optimal_swell_bearing": 260,
            "optimal_swell_label": "W",
        }
        sources = {
            "sf": {"data": _sf_payload(), "error": None},
            "om": {"data": {"current": om_hourly[0], "today_hours": om_hourly, "hourly": om_hourly}, "error": None},
            "gfs": {"data": {"current": gfs_hourly[0], "today_hours": gfs_hourly, "hourly": gfs_hourly}, "error": None},
            "ibi": {"data": None, "error": "disabled"},
            "surfline": {"data": None, "error": "disabled"},
            "windguru": {"data": None, "error": "disabled"},
            "windguru_ecmwf": {"data": None, "error": "disabled"},
        }

        payload = forecast_sync.build_payload(spot, sources)

        self.assertEqual(payload["om_hourly"], om_hourly)
        self.assertEqual(payload["gfs_hourly"], gfs_hourly)

    def test_build_payload_preserves_model_rows_when_surf_forecast_fails(self):
        om_hourly = [_model_hour("2026-05-08T06:00:00+00:00")]
        gfs_hourly = [_model_hour("2026-05-08T07:00:00+00:00")]
        spot = {
            "id": "carcavelos",
            "name": "Carcavelos",
            "url": "https://example.test/sf",
            "lat": 38.68,
            "lon": -9.34,
            "offshore_bearing": 10,
            "optimal_swell_bearing": 260,
            "optimal_swell_label": "W",
        }
        sources = {
            "sf": {"data": None, "error": "sf fetch timed out after 35s"},
            "om": {"data": {"current": om_hourly[0], "today_hours": om_hourly, "hourly": om_hourly}, "error": None},
            "gfs": {"data": {"current": gfs_hourly[0], "today_hours": gfs_hourly, "hourly": gfs_hourly}, "error": None},
            "ibi": {"data": None, "error": "Copernicus no data returned"},
            "surfline": {"data": None, "error": "disabled"},
            "windguru": {"data": None, "error": "disabled"},
            "windguru_ecmwf": {"data": None, "error": "disabled"},
        }

        payload = forecast_sync.build_payload(spot, sources)

        self.assertEqual(payload["error"], "Couldn't fetch forecast: sf fetch timed out after 35s")
        self.assertEqual(payload["om_hourly"], om_hourly)
        self.assertEqual(payload["gfs_hourly"], gfs_hourly)
        self.assertIsNone(payload["om_error"])
        self.assertIsNone(payload["gfs_error"])
        self.assertIn("unified", payload)
        self.assertIn("om", payload["unified"]["sources_used"])


class WindguruEcmwfValidationTests(unittest.TestCase):
    def _complete_row(self):
        return {
            "timestamp_utc": "2026-05-07T06:00:00+00:00",
            "wave_height": 0.7,
            "wave_period": 6.0,
            "wave_direction": 311.0,
            "swell_height": 0.6,
            "swell_period": 5.0,
            "swell_direction": 308.0,
            "swell2_height": 0.1,
            "swell2_period": 13.0,
            "swell2_direction": 268.0,
            "wind_wave_height": 0.3,
            "wind_wave_period": 2.0,
            "wind_wave_direction": 336.0,
            "wind_speed_kmh": 12.96,
            "wind_direction_deg": 333.0,
            "wind_gusts_kmh": 20.37,
        }

    def test_windguru_ecmwf_validation_accepts_complete_rows(self):
        payload = {"hourly": [self._complete_row()]}

        self.assertIs(forecast_sync._validate_windguru_ecmwf_payload(payload), payload)

    def test_windguru_ecmwf_validation_rejects_empty_rows(self):
        with self.assertRaisesRegex(ValueError, "no hourly rows"):
            forecast_sync._validate_windguru_ecmwf_payload({"hourly": []})

    def test_windguru_ecmwf_validation_rejects_incomplete_rows(self):
        row = self._complete_row()
        row.pop("wave_height")

        with self.assertRaisesRegex(ValueError, "no complete ifs/ifsw"):
            forecast_sync._validate_windguru_ecmwf_payload({"hourly": [row]})


class SourceFetchBudgetTests(unittest.TestCase):
    def test_default_source_fetch_budget_leaves_time_for_cache_writes(self):
        old_value = os.environ.get("SOURCE_FETCH_BUDGET_SECONDS")
        os.environ.pop("SOURCE_FETCH_BUDGET_SECONDS", None)
        try:
            self.assertLessEqual(forecast_sync._source_fetch_budget_seconds(), 30.0)
        finally:
            if old_value is not None:
                os.environ["SOURCE_FETCH_BUDGET_SECONDS"] = old_value

    def test_source_fetch_budget_uses_env_override(self):
        old_value = os.environ.get("SOURCE_FETCH_BUDGET_SECONDS")
        os.environ["SOURCE_FETCH_BUDGET_SECONDS"] = "12.5"
        try:
            self.assertEqual(forecast_sync._source_fetch_budget_seconds(), 12.5)
        finally:
            if old_value is None:
                os.environ.pop("SOURCE_FETCH_BUDGET_SECONDS", None)
            else:
                os.environ["SOURCE_FETCH_BUDGET_SECONDS"] = old_value

    def test_default_ibi_timeout_is_shorter_than_global_budget(self):
        old_budget = os.environ.get("SOURCE_FETCH_BUDGET_SECONDS")
        old_ibi = os.environ.get("SOURCE_FETCH_TIMEOUT_IBI_SECONDS")
        os.environ.pop("SOURCE_FETCH_BUDGET_SECONDS", None)
        os.environ.pop("SOURCE_FETCH_TIMEOUT_IBI_SECONDS", None)
        try:
            self.assertLess(
                forecast_sync._source_timeout_seconds("ibi"),
                forecast_sync._source_fetch_budget_seconds(),
            )
        finally:
            if old_budget is not None:
                os.environ["SOURCE_FETCH_BUDGET_SECONDS"] = old_budget
            if old_ibi is not None:
                os.environ["SOURCE_FETCH_TIMEOUT_IBI_SECONDS"] = old_ibi

    def test_slow_ibi_does_not_consume_global_source_budget(self):
        old_budget = os.environ.get("SOURCE_FETCH_BUDGET_SECONDS")
        old_ibi = os.environ.get("SOURCE_FETCH_TIMEOUT_IBI_SECONDS")
        os.environ["SOURCE_FETCH_BUDGET_SECONDS"] = "1"
        os.environ["SOURCE_FETCH_TIMEOUT_IBI_SECONDS"] = "0.05"
        originals = {
            "scrape": forecast_sync.scraper.scrape,
            "surfline": forecast_sync.surfline.fetch,
            "windguru": forecast_sync.windguru.fetch,
            "open_meteo": forecast_sync.open_meteo.fetch,
            "noaa_gfs": forecast_sync.noaa_gfs.fetch,
            "credentials": forecast_sync.copernicus_ibi.credentials_configured,
            "ibi": forecast_sync.copernicus_ibi.fetch,
        }
        try:
            forecast_sync.scraper.scrape = lambda *_args, **_kwargs: _sf_payload()
            forecast_sync.surfline.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
            forecast_sync.windguru.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
            forecast_sync.open_meteo.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
            forecast_sync.noaa_gfs.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
            forecast_sync.copernicus_ibi.credentials_configured = lambda: True

            def slow_ibi(*_args, **_kwargs):
                time.sleep(0.5)
                return {"current": {}, "hourly": []}

            forecast_sync.copernicus_ibi.fetch = slow_ibi

            started = time.perf_counter()
            spot = {
                "id": "carcavelos",
                "name": "Carcavelos",
                "url": "https://example.test/sf",
                "lat": 38.68,
                "lon": -9.34,
                "offshore_bearing": 10,
                "surfline_spot_id": "abc",
                "windguru_spot_id": "123",
            }
            sources = forecast_sync.fetch_sources_for_spot(spot)
            elapsed = time.perf_counter() - started

            self.assertLess(elapsed, 0.35)
            self.assertEqual(sources["ibi"]["error"], "ibi fetch timed out after 0.05s")
        finally:
            forecast_sync.scraper.scrape = originals["scrape"]
            forecast_sync.surfline.fetch = originals["surfline"]
            forecast_sync.windguru.fetch = originals["windguru"]
            forecast_sync.open_meteo.fetch = originals["open_meteo"]
            forecast_sync.noaa_gfs.fetch = originals["noaa_gfs"]
            forecast_sync.copernicus_ibi.credentials_configured = originals["credentials"]
            forecast_sync.copernicus_ibi.fetch = originals["ibi"]
            if old_budget is None:
                os.environ.pop("SOURCE_FETCH_BUDGET_SECONDS", None)
            else:
                os.environ["SOURCE_FETCH_BUDGET_SECONDS"] = old_budget
            if old_ibi is None:
                os.environ.pop("SOURCE_FETCH_TIMEOUT_IBI_SECONDS", None)
            else:
                os.environ["SOURCE_FETCH_TIMEOUT_IBI_SECONDS"] = old_ibi


class CopernicusDiagnosticsTests(unittest.TestCase):
    def _spot(self):
        return {
            "id": "carcavelos",
            "name": "Carcavelos",
            "url": "https://example.test/sf",
            "lat": 38.68,
            "lon": -9.34,
            "offshore_bearing": 10,
            "surfline_spot_id": "abc",
            "windguru_spot_id": "123",
        }

    def _with_fast_optional_sources(self):
        originals = {
            "scrape": forecast_sync.scraper.scrape,
            "surfline": forecast_sync.surfline.fetch,
            "windguru": forecast_sync.windguru.fetch,
            "open_meteo": forecast_sync.open_meteo.fetch,
            "noaa_gfs": forecast_sync.noaa_gfs.fetch,
            "credentials": forecast_sync.copernicus_ibi.credentials_configured,
            "ibi": forecast_sync.copernicus_ibi.fetch,
        }
        forecast_sync.scraper.scrape = lambda *_args, **_kwargs: _sf_payload()
        forecast_sync.surfline.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
        forecast_sync.windguru.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
        forecast_sync.open_meteo.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
        forecast_sync.noaa_gfs.fetch = lambda *_args, **_kwargs: {"current": {}, "hourly": []}
        return originals

    def _restore(self, originals):
        forecast_sync.scraper.scrape = originals["scrape"]
        forecast_sync.surfline.fetch = originals["surfline"]
        forecast_sync.windguru.fetch = originals["windguru"]
        forecast_sync.open_meteo.fetch = originals["open_meteo"]
        forecast_sync.noaa_gfs.fetch = originals["noaa_gfs"]
        forecast_sync.copernicus_ibi.credentials_configured = originals["credentials"]
        forecast_sync.copernicus_ibi.fetch = originals["ibi"]

    def test_fetch_sources_reports_missing_copernicus_credentials(self):
        originals = self._with_fast_optional_sources()
        try:
            forecast_sync.copernicus_ibi.credentials_configured = lambda: False
            forecast_sync.copernicus_ibi.fetch = lambda *_args, **_kwargs: self.fail("fetch should not run")

            sources = forecast_sync.fetch_sources_for_spot(self._spot())

            self.assertEqual(sources["ibi"]["error"], "Copernicus credentials missing")
        finally:
            self._restore(originals)

    def test_fetch_sources_reports_copernicus_no_data_separately(self):
        originals = self._with_fast_optional_sources()
        try:
            forecast_sync.copernicus_ibi.credentials_configured = lambda: True
            forecast_sync.copernicus_ibi.fetch = lambda *_args, **_kwargs: None

            sources = forecast_sync.fetch_sources_for_spot(self._spot())

            self.assertEqual(sources["ibi"]["error"], "Copernicus no data returned")
        finally:
            self._restore(originals)


if __name__ == "__main__":
    unittest.main()
