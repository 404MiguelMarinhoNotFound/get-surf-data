import unittest
from datetime import datetime, timedelta, timezone

import scraper


def _cell(day, time, rating, ts=None):
    c = {"day": day, "time": time, "rating": rating}
    if ts:
        c["timestamp_utc"] = ts
    return c


class PickBestWindowTests(unittest.TestCase):
    def test_returns_none_for_empty(self):
        self.assertIsNone(scraper.pick_best_window([]))

    def test_returns_none_when_below_min_rating(self):
        cells = [_cell("Tue 28", "7AM", 1), _cell("Tue 28", "10AM", 1)]
        self.assertIsNone(scraper.pick_best_window(cells))

    def test_falls_back_to_global_max_when_untimestamped(self):
        cells = [_cell("Tue 28", "7AM", 5), _cell("Tue 28", "1PM", 8)]
        out = scraper.pick_best_window(cells)
        self.assertIn("1PM", out)
        self.assertIn("8/10", out)

    def test_skips_past_slots_when_timestamped(self):
        # Now is 4 PM UTC. Morning peak (rating 9 at 7 AM UTC) should be skipped
        # in favor of the next-best upcoming slot.
        now = datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc)
        cells = [
            _cell("Tue 28", "7AM", 9, ts="2026-04-28T07:00:00+00:00"),
            _cell("Tue 28", "1PM", 4, ts="2026-04-28T13:00:00+00:00"),
            _cell("Tue 28", "7PM", 6, ts="2026-04-28T19:00:00+00:00"),
        ]
        out = scraper.pick_best_window(cells, now_utc=now)
        self.assertIn("7PM", out)
        self.assertIn("6/10", out)

    def test_keeps_in_progress_slot(self):
        # Slot at 4PM is 30 min in the past — still considered "in progress".
        now = datetime(2026, 4, 28, 16, 30, tzinfo=timezone.utc)
        cells = [
            _cell("Tue 28", "4PM", 7, ts="2026-04-28T16:00:00+00:00"),
            _cell("Tue 28", "7PM", 5, ts="2026-04-28T19:00:00+00:00"),
        ]
        out = scraper.pick_best_window(cells, now_utc=now)
        self.assertIn("4PM", out)
        self.assertIn("7/10", out)

    def test_all_past_falls_back_to_recent_window(self):
        # Whole timeline is in the past — pick the highest of the last cells.
        now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        cells = [
            _cell("Tue 28", "7AM", 9, ts="2026-04-28T07:00:00+00:00"),
            _cell("Tue 28", "7PM", 4, ts="2026-04-28T19:00:00+00:00"),
        ]
        out = scraper.pick_best_window(cells, now_utc=now)
        self.assertIsNotNone(out)


class ParseRatingTimelineTzTests(unittest.TestCase):
    GRID = (
        "Tue 28 Wed 29 "
        "1PM 4PM 7PM 1AM 4AM 7AM 10AM 1PM 4PM 7PM "
        "Rating (10 max) 3 5 6 1 1 2 4 7 8 5"
    )

    def test_parses_without_tz(self):
        out = scraper.parse_rating_timeline(self.GRID)
        self.assertIsNotNone(out)
        self.assertEqual(len(out["labeled"]), 10)
        self.assertNotIn("timestamp_utc", out["labeled"][0])

    def test_attaches_timestamp_when_tz_given(self):
        now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
        out = scraper.parse_rating_timeline(self.GRID, now_utc=now, tz_name="Europe/Lisbon")
        self.assertIsNotNone(out)
        cells = out["labeled"]
        self.assertIn("timestamp_utc", cells[0])
        # First cell is "Tue 28 1PM" Lisbon time. In late April Lisbon is UTC+1.
        first = datetime.fromisoformat(cells[0]["timestamp_utc"])
        self.assertEqual(first, datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc))
        # Day rolls over at the boundary into Wed 29.
        wed_first = next(c for c in cells if c["day"].startswith("Wed"))
        self.assertTrue(wed_first["timestamp_utc"].startswith("2026-04-29"))

    def test_forward_thinking_best_window_skips_morning(self):
        # 6 PM UTC on the 28th: morning peaks already past; next-best upcoming wins.
        now = datetime(2026, 4, 28, 18, 0, tzinfo=timezone.utc)
        out = scraper.parse_rating_timeline(self.GRID, now_utc=now, tz_name="Europe/Lisbon")
        # Highest-rated upcoming cell is Wed 29 4PM (rating 8).
        self.assertIn("4PM", out["best_window"])
        self.assertIn("8/10", out["best_window"])
        self.assertIn("Wed", out["best_window"])


if __name__ == "__main__":
    unittest.main()
