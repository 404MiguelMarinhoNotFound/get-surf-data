import os
from pathlib import Path
import unittest
import urllib.error

import api.sync as api_sync
import server


def _sf_payload(now="2026-05-03T05:00:00+00:00"):
    return {
        "url": "https://example.test/sf",
        "fetched_at": now,
        "now_utc": now,
        "height_m": 1.0,
        "period_s": 11,
        "swell_direction": "W",
        "wind_state": "offshore",
        "wind_speed_kmh": 8,
        "rating": 6,
        "details": [],
        "rating_timeline": [],
        "tide": None,
    }


def _model_hour(ts):
    return {
        "timestamp_utc": ts,
        "wave_height": 1.0,
        "wave_period": 11,
        "swell_height": 1.0,
        "swell_period": 11,
        "swell_direction": 260,
        "wind_wave_height": 0.1,
        "wind_speed_kmh": 8,
        "wind_direction_deg": 10,
    }


def _ibi_hour(ts):
    row = _model_hour(ts)
    row["wind_speed_kmh"] = None
    row["wind_direction_deg"] = None
    return row


class ServerSourceIntegrationTests(unittest.TestCase):
    def test_load_env_file_sets_missing_keys_without_overriding_existing(self):
        original_missing = os.environ.pop("SURF_TEST_MISSING_ENV", None)
        original_existing = os.environ.get("SURF_TEST_EXISTING_ENV")
        os.environ["SURF_TEST_EXISTING_ENV"] = "runtime"
        env_path = Path(__file__).parent / "tmp.env.local"
        env_path.write_text(
            "SURF_TEST_MISSING_ENV=from-file\n"
            "SURF_TEST_EXISTING_ENV=from-file\n",
            encoding="utf-8",
        )
        try:
            server._load_env_file(env_path)
            self.assertEqual(os.environ.get("SURF_TEST_MISSING_ENV"), "from-file")
            self.assertEqual(os.environ.get("SURF_TEST_EXISTING_ENV"), "runtime")
        finally:
            env_path.unlink(missing_ok=True)
            os.environ.pop("SURF_TEST_MISSING_ENV", None)
            if original_missing is not None:
                os.environ["SURF_TEST_MISSING_ENV"] = original_missing
            if original_existing is None:
                os.environ.pop("SURF_TEST_EXISTING_ENV", None)
            else:
                os.environ["SURF_TEST_EXISTING_ENV"] = original_existing

    def test_sync_spot_returns_surfline_and_windguru_source_scores(self):
        original = {
            "scraper": server.scraper.scrape,
            "open_meteo": server.open_meteo.fetch,
            "noaa_gfs": server.noaa_gfs.fetch,
            "copernicus": server.copernicus_ibi.fetch,
            "surfline": server.surfline.fetch,
            "windguru": server.windguru.fetch,
            "cache": dict(server.CACHE),
        }
        server.CACHE.clear()

        def sf(*_args, **_kwargs):
            return {
                "url": "https://example.test/sf",
                "fetched_at": "2026-05-03T12:00:00+00:00",
                "now_utc": "2026-05-03T12:00:00+00:00",
                "height_m": 1.0,
                "period_s": 11,
                "swell_direction": "W",
                "wind_state": "offshore",
                "wind_speed_kmh": 8,
                "rating": 6,
                "details": [],
                "rating_timeline": [],
                "tide": None,
            }

        model_current = {
            "wave_height": 1.0,
            "wave_period": 11,
            "swell_height": 1.0,
            "swell_period": 11,
            "swell_direction": 260,
            "wind_wave_height": 0.1,
            "wind_speed_kmh": 8,
            "wind_direction_deg": 10,
        }

        def model(*_args, **_kwargs):
            return {"current": dict(model_current), "today_hours": [], "hourly": []}

        def surfline_fetch(*_args, **_kwargs):
            current = dict(model_current)
            current["condition_rating"] = "FAIR"
            return {"current": current, "hourly": []}

        def windguru_fetch(*_args, **_kwargs):
            current = dict(model_current)
            current["windguru_fetched_at"] = "2026-05-03T12:00:00+00:00"
            return {"current": current, "hourly": [], "sst_c": 17.0}

        try:
            server.scraper.scrape = sf
            server.open_meteo.fetch = model
            server.noaa_gfs.fetch = model
            server.copernicus_ibi.fetch = lambda *_args, **_kwargs: None
            server.surfline.fetch = surfline_fetch
            server.windguru.fetch = windguru_fetch

            data = server.sync_spot("carcavelos", force=True)
        finally:
            server.scraper.scrape = original["scraper"]
            server.open_meteo.fetch = original["open_meteo"]
            server.noaa_gfs.fetch = original["noaa_gfs"]
            server.copernicus_ibi.fetch = original["copernicus"]
            server.surfline.fetch = original["surfline"]
            server.windguru.fetch = original["windguru"]
            server.CACHE.clear()
            server.CACHE.update(original["cache"])

        self.assertIsNotNone(data["surfline_analysis"])
        self.assertIsNotNone(data["windguru_analysis"])
        self.assertIsNone(data["surfline_error"])
        self.assertIsNone(data["windguru_error"])
        self.assertIn("surfline", data["unified"]["source_scores"])
        self.assertIn("windguru", data["unified"]["source_scores"])

    def test_sync_spot_passes_ibi_hourly_into_predictor(self):
        original = {
            "scraper": server.scraper.scrape,
            "open_meteo": server.open_meteo.fetch,
            "noaa_gfs": server.noaa_gfs.fetch,
            "copernicus": server.copernicus_ibi.fetch,
            "surfline": server.surfline.fetch,
            "windguru": server.windguru.fetch,
            "cache": dict(server.CACHE),
        }
        server.CACHE.clear()

        hourly = [_model_hour(f"2026-05-03T{hour:02d}:00:00+00:00") for hour in range(4, 7)]
        ibi_hourly = [_ibi_hour(f"2026-05-03T{hour:02d}:00:00+00:00") for hour in range(4, 7)]

        try:
            server.scraper.scrape = lambda *_args, **_kwargs: _sf_payload("2026-05-03T03:00:00+00:00")
            server.open_meteo.fetch = lambda *_args, **_kwargs: {
                "current": _model_hour("2026-05-03T03:00:00+00:00"),
                "today_hours": [],
                "hourly": hourly,
            }
            server.noaa_gfs.fetch = lambda *_args, **_kwargs: {
                "current": _model_hour("2026-05-03T03:00:00+00:00"),
                "today_hours": [],
                "hourly": [],
            }
            server.copernicus_ibi.fetch = lambda *_args, **_kwargs: {
                "current": _ibi_hour("2026-05-03T03:00:00+00:00"),
                "today_hours": [],
                "hourly": ibi_hourly,
            }
            server.surfline.fetch = lambda *_args, **_kwargs: {"current": None, "hourly": []}
            server.windguru.fetch = lambda *_args, **_kwargs: {"current": None, "hourly": []}

            data = server.sync_spot("carcavelos", force=True)
        finally:
            server.scraper.scrape = original["scraper"]
            server.open_meteo.fetch = original["open_meteo"]
            server.noaa_gfs.fetch = original["noaa_gfs"]
            server.copernicus_ibi.fetch = original["copernicus"]
            server.surfline.fetch = original["surfline"]
            server.windguru.fetch = original["windguru"]
            server.CACHE.clear()
            server.CACHE.update(original["cache"])

        self.assertEqual(len(data["ibi_hourly"]), 3)
        components = data["unified"]["predictor_windows"][0]["score_components"]
        self.assertTrue(any(component["ibi_score"] is not None for component in components))

    def test_api_sync_passes_ibi_hourly_into_predictor(self):
        original = {
            "scraper": api_sync.scraper.scrape,
            "open_meteo": api_sync.open_meteo.fetch,
            "noaa_gfs": api_sync.noaa_gfs.fetch,
            "copernicus": api_sync.copernicus_ibi.fetch,
            "surfline": api_sync.surfline.fetch,
            "windguru": api_sync.windguru.fetch,
        }
        hourly = [_model_hour(f"2026-05-03T{hour:02d}:00:00+00:00") for hour in range(4, 7)]
        ibi_hourly = [_ibi_hour(f"2026-05-03T{hour:02d}:00:00+00:00") for hour in range(4, 7)]

        try:
            api_sync.scraper.scrape = lambda *_args, **_kwargs: _sf_payload("2026-05-03T03:00:00+00:00")
            api_sync.open_meteo.fetch = lambda *_args, **_kwargs: {
                "current": _model_hour("2026-05-03T03:00:00+00:00"),
                "today_hours": [],
                "hourly": hourly,
            }
            api_sync.noaa_gfs.fetch = lambda *_args, **_kwargs: {
                "current": _model_hour("2026-05-03T03:00:00+00:00"),
                "today_hours": [],
                "hourly": [],
            }
            api_sync.copernicus_ibi.fetch = lambda *_args, **_kwargs: {
                "current": _ibi_hour("2026-05-03T03:00:00+00:00"),
                "today_hours": [],
                "hourly": ibi_hourly,
            }
            api_sync.surfline.fetch = lambda *_args, **_kwargs: {"current": None, "hourly": []}
            api_sync.windguru.fetch = lambda *_args, **_kwargs: {"current": None, "hourly": []}

            data = api_sync._sync_spot("carcavelos")
        finally:
            api_sync.scraper.scrape = original["scraper"]
            api_sync.open_meteo.fetch = original["open_meteo"]
            api_sync.noaa_gfs.fetch = original["noaa_gfs"]
            api_sync.copernicus_ibi.fetch = original["copernicus"]
            api_sync.surfline.fetch = original["surfline"]
            api_sync.windguru.fetch = original["windguru"]

        self.assertEqual(len(data["ibi_hourly"]), 3)
        components = data["unified"]["predictor_windows"][0]["score_components"]
        self.assertTrue(any(component["ibi_score"] is not None for component in components))

    def test_surfline_403_is_preserved_as_source_error(self):
        original = {
            "scraper": server.scraper.scrape,
            "open_meteo": server.open_meteo.fetch,
            "noaa_gfs": server.noaa_gfs.fetch,
            "copernicus": server.copernicus_ibi.fetch,
            "surfline": server.surfline.fetch,
            "windguru": server.windguru.fetch,
            "cache": dict(server.CACHE),
        }
        server.CACHE.clear()

        def blocked(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                url="https://services.surfline.com/",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=None,
            )

        try:
            server.scraper.scrape = lambda *_args, **_kwargs: _sf_payload()
            server.open_meteo.fetch = lambda *_args, **_kwargs: {
                "current": _model_hour("2026-05-03T05:00:00+00:00"),
                "today_hours": [],
                "hourly": [_model_hour(f"2026-05-03T{hour:02d}:00:00+00:00") for hour in range(6, 9)],
            }
            server.noaa_gfs.fetch = lambda *_args, **_kwargs: None
            server.copernicus_ibi.fetch = lambda *_args, **_kwargs: None
            server.surfline.fetch = blocked
            server.windguru.fetch = lambda *_args, **_kwargs: None

            data = server.sync_spot("carcavelos", force=True)
        finally:
            server.scraper.scrape = original["scraper"]
            server.open_meteo.fetch = original["open_meteo"]
            server.noaa_gfs.fetch = original["noaa_gfs"]
            server.copernicus_ibi.fetch = original["copernicus"]
            server.surfline.fetch = original["surfline"]
            server.windguru.fetch = original["windguru"]
            server.CACHE.clear()
            server.CACHE.update(original["cache"])

        self.assertIn("HTTP Error 403", data["surfline_error"])
        self.assertEqual(data["surfline_hourly"], [])


if __name__ == "__main__":
    unittest.main()
