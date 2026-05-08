import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import windguru


WIND_HTML = """
<pre>
Portugal - Carcavelos,  lat: 38.6757, lon: -9.3243, alt: 7, SST: 17 C
GFS 13 km (init: 2026-05-03 12 UTC)
        Date    WSPD   WDIRN    WDEG    GUST     TMP
     (UTC+1)   knots    dir.    deg.   knots       C
  Sun 3. 13h       8     WSW     252       7      17
  Sun 3. 14h       9       W     262       9      17
</pre>
"""

WAVE_HTML = """
<pre>
Portugal - Carcavelos,  lat: 38.6757, lon: -9.3243, alt: 7, SST: 17 C
GFS-Wave 16 km (init: 2026-05-03 12 UTC)
        Date   HTSGW  WADIRN   WADEG   PERPW  SWELL1 SWDIRN1  SWDEG1  SWPER1  SWELL2 SWDIRN2  SWDEG2  SWPER2   WVHGT  WVDIRN   WVDEG   WVPER
     (UTC+1)       m    dir.    deg.     sec       m    dir.    deg.     sec       m    dir.    deg.     sec       m    dir.    deg.     sec
  Sun 3. 13h       1      NW     318      11     0.7      NW     322      11     0.7       W     260       8       -       -       -       -
  Sun 3. 14h     1.1      NW     319      10     0.8      NW     323      10     0.6       W     261       7     0.4      NW     314       3
</pre>
"""


class WindguruParserTests(unittest.TestCase):
    def test_parse_wind_and_wave_rows(self):
        parsed = windguru.parse(
            WIND_HTML,
            WAVE_HTML,
            now_utc=datetime(2026, 5, 3, 12, 15, tzinfo=timezone.utc),
        )

        self.assertEqual(parsed["model_init_utc"], "2026-05-03T12:00:00+00:00")
        self.assertEqual(parsed["sst_c"], 17.0)
        self.assertEqual(len(parsed["hourly"]), 2)

        first = parsed["hourly"][0]
        self.assertEqual(first["timestamp_utc"], "2026-05-03T12:00:00+00:00")
        self.assertAlmostEqual(first["wind_speed_kmh"], 14.82, places=2)
        self.assertEqual(first["wind_direction_deg"], 252.0)
        self.assertEqual(first["wave_height"], 1.0)
        self.assertEqual(first["swell_period"], 11.0)
        self.assertEqual(first["swell2_direction"], 260.0)
        self.assertNotIn("wind_wave_height", first)

        current = parsed["current"]
        self.assertEqual(current["timestamp_utc"], "2026-05-03T12:00:00+00:00")
        self.assertEqual(current["windguru_fetched_at"], "2026-05-03T12:15:00+00:00")

    def test_model_url_helpers_preserve_gfs_defaults(self):
        self.assertEqual(
            windguru._wind_url(1060),
            "https://micro.windguru.cz/?s=1060&m=gfs&v=WSPD,WDIRN,WDEG,GUST,TMP",
        )
        self.assertIn("m=gfswh", windguru._wave_url(1060))
        self.assertIn("HTSGW,WADIRN,WADEG,PERPW", windguru._wave_url(1060))

    def test_fetch_accepts_ecmwf_models_and_source_name(self):
        now = datetime(2026, 5, 3, 12, 15, tzinfo=timezone.utc)
        with patch.object(windguru, "fetch_text", side_effect=[WIND_HTML, WAVE_HTML]) as fetch_text:
            parsed = windguru.fetch(
                1060,
                now_utc=now,
                wind_model="ifs",
                wave_model="ifsw",
                source_name="windguru_ecmwf",
            )

        self.assertEqual(fetch_text.call_args_list[0].args[0], windguru._wind_url(1060, "ifs"))
        self.assertEqual(fetch_text.call_args_list[1].args[0], windguru._wave_url(1060, "ifsw"))
        self.assertEqual(parsed["source"], "windguru_ecmwf")
        self.assertEqual(parsed["model"], {"wind": "ifs", "wave": "ifsw"})
        self.assertEqual(parsed["current"]["timestamp_utc"], "2026-05-03T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
