import unittest

import server


class ServerSourceIntegrationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
