import unittest

import scraper


class ScraperParseTests(unittest.TestCase):
    def test_parse_summary_complete_sentence(self):
        text = (
            "48hr Weather and Surf, issued 6 pm Monday 27 Apr 2026 WEST. "
            "Carcavelos surf forecast is: 1.1m 7s primary swell from a "
            "North-northwest direction and 0.5m 10s secondary swell from a "
            "West direction. The wind direction is predicted to be cross-offshore. "
            "The swell rating is 11. Today's sea temperature is 16.6 C."
        )

        out = scraper.parse_summary(text)

        self.assertEqual(out["height_m"], 1.1)
        self.assertEqual(out["period_s"], 7)
        self.assertEqual(out["swell_direction"], "NNW")
        self.assertEqual(out["wind_state"], "cross-offshore")
        self.assertEqual(out["rating"], 11)
        self.assertEqual(out["sea_temp_c"], 16.6)

    def test_parse_summary_empty_on_unrelated_html(self):
        self.assertEqual(scraper.parse_summary("<html>hello</html>"), {})

    def test_primary_swell_regex_is_atomic(self):
        text = "Carcavelos surf forecast is: 1.5m primary swell from a West direction."

        out = scraper.parse_summary(text)

        self.assertNotIn("height_m", out)
        self.assertNotIn("period_s", out)
        self.assertNotIn("swell_direction", out)

    def test_wording_drift_drops_primary_swell_fields(self):
        text = (
            "Carcavelos surf forecast is: 1.1m 7s main swell from a "
            "North-northwest direction. The wind direction is predicted to be offshore."
        )

        out = scraper.parse_summary(text)

        self.assertNotIn("height_m", out)
        self.assertNotIn("period_s", out)
        self.assertNotIn("swell_direction", out)
        self.assertEqual(out["wind_state"], "offshore")

    def test_parse_upstream_issued_at(self):
        text = "48hr Weather and Surf, issued 6 pm Monday 27 Apr 2026 WEST"

        self.assertEqual(
            scraper.parse_upstream_issued_at(text),
            "2026-04-27T18:00:00+01:00",
        )

    def test_parse_upstream_issued_at_midnight(self):
        text = "48hr Weather and Surf, issued 12 am Monday 27 Apr 2026 WET"

        self.assertEqual(
            scraper.parse_upstream_issued_at(text),
            "2026-04-27T00:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
