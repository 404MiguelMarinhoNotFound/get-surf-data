import os
import unittest

from scripts.check_latest_surf_data import check_all_spots


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_SURF_TESTS") == "1",
    "set RUN_LIVE_SURF_TESTS=1 to hit surf-forecast.com",
)
class LiveLatestSurfDataTests(unittest.TestCase):
    def test_live_spots_are_complete_plausible_and_fresh(self):
        max_age_hours = float(os.environ.get("SURF_MAX_UPSTREAM_AGE_HOURS", "8"))
        report = check_all_spots(max_age_hours=max_age_hours)

        failures = []
        for result in report["results"]:
            for error in result["errors"]:
                failures.append(f"{result['spot_id']}: {error}")

        if failures:
            self.fail("\n".join(failures))


if __name__ == "__main__":
    unittest.main()
